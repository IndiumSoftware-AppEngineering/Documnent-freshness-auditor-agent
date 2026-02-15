import os
import ast
import re
import yaml
import subprocess
import difflib
import locale
import sys
from datetime import datetime
from typing import Dict, List, Set,Optional
from crewai.tools import BaseTool
from pathlib import Path


def _safe_read_text(path: str) -> str:
    """Read a file robustly: try UTF-8 (and BOM), then cp1252, then fallback.

    This prevents the Windows 'charmap' codec can't decode byte errors by
    decoding bytes explicitly and using a replacement strategy as a last resort.
    """
    with open(path, "rb") as bf:
        data = bf.read()

    # build a prioritized list of encodings to try
    encodings = ["utf-8", "utf-8-sig"]

    # include the system preferred encoding if it isn't already present
    try:
        pref = locale.getpreferredencoding(False) or ""
    except Exception:
        pref = ""
    if pref and pref.lower() not in (e.lower() for e in encodings):
        encodings.append(pref)

    # on Windows, try the 'mbcs' codec which maps to the ANSI code page
    if sys.platform.startswith("win") and "mbcs" not in encodings:
        encodings.append("mbcs")

    # common Windows fallback
    if "cp1252" not in encodings:
        encodings.append("cp1252")

    # latin-1 will never fail (direct byte->unicode mapping)
    if "latin-1" not in encodings:
        encodings.append("latin-1")

    for enc in encodings:
        try:
            return data.decode(enc)
        except Exception:
            continue

    # final fallback: decode as utf-8 with replacement to avoid exceptions
    return data.decode("utf-8", errors="replace")

class DocstringSignatureTool(BaseTool):
    name: str = "Docstring Signature Auditor"
    description: str = "Checks one .py file for docstring vs function signature mismatches."

    def _run(self, file_path: str) -> Dict:
            if not os.path.isfile(file_path) or not file_path.endswith(".py"):
                return {"status": "error", "message": "Invalid or missing .py file"}

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=file_path)
            except Exception as e:
                return {"status": "error", "message": f"Parse error: {str(e)}"}

            issues = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    issue = self._check_function(node)
                    if issue:
                        issues.append(issue)

            return {
                "status": "ok" if not issues else "issues_found",
                "file": file_path,
                "issues": issues
            }

    def _check_function(self, node: ast.FunctionDef) -> Dict or None:
        name = node.name
        line = node.lineno

        # Get signature params (skip self/cls)
        params = [arg.arg for arg in node.args.args]
        if params and params[0] in ("self", "cls"):
            params = params[1:]

        doc = ast.get_docstring(node) or ""
        if not doc.strip():
            return {"function": name, "line": line, "message": "Missing docstring"}

        # Basic param extraction from docstring
        documented = set()
        for match in re.findall(r':param\s+(\w+)', doc):
            documented.add(match)
        for line in doc.splitlines():
            m = re.match(r'^\s*(\w+)\s*:', line.strip())
            if m:
                documented.add(m.group(1))

        missing = [p for p in params if p not in documented]
        stale = [p for p in documented if p not in params]

        if not missing and not stale:
            return None

        msg = []
        if missing:
            msg.append(f"Missing params in doc: {', '.join(missing)}")
        if stale:
            msg.append(f"Stale params in doc: {', '.join(stale)}")

        return {"function": name, "line": line, "message": "; ".join(msg)}

class ReadmeStructureTool(BaseTool):
    name: str = "README Structure Auditor"
    description: str = "Checks one README.md for mentioned files/dirs that don't exist."

    def _run(self, readme_path: str, project_root: str) -> Dict:
        if not os.path.isfile(readme_path) or not readme_path.endswith(".md"):
            return {"status": "error", "message": "Invalid or missing README.md"}

        if not os.path.isdir(project_root):
            return {"status": "error", "message": "Invalid project root"}

        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return {"status": "error", "message": f"Read error: {str(e)}"}

        issues = self._find_issues(content, project_root)

        return {
            "status": "ok" if not issues else "issues_found",
            "file": readme_path,
            "issues": issues
        }

    def _find_issues(self, content: str, root: str) -> List[Dict]:
        issues = []

        # Simple file/dir mention extraction
        mentions = set(re.findall(r'\b([\w/-]+\.(py|md|txt|yaml|json|toml))\b', content))
        mentions.update(re.findall(r'\b(src|tests|docs|lib|config)/?\b', content))

        # Get real relative paths
        real_paths = set()
        root_path = Path(root)
        for path in root_path.rglob("*"):
            if path.is_file() or path.is_dir():
                real_paths.add(str(path.relative_to(root_path)))

        # Check mentioned but missing
        for mention in mentions:
            if mention not in real_paths:
                issues.append({
                    "type": "missing_mention",
                    "message": f"Mentioned '{mention}' does not exist in project"
                })

        return issues

class ApiImplementationTool(BaseTool):
    name: str = "API Implementation Auditor"
    description: str = "Compares OpenAPI/Swagger spec against API implementation code."

    def _run(self, spec_path: str, impl_path: str) -> Dict:
        if not os.path.isfile(spec_path):
            return {"status": "error", "message": f"OpenAPI spec not found: {spec_path}"}
        if not os.path.isfile(impl_path):
            return {"status": "error", "message": f"Implementation file not found: {impl_path}"}

        # Read spec
        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                if spec_path.endswith(".yaml") or spec_path.endswith(".yml"):
                    spec = yaml.safe_load(f)
                else:
                    spec = json.load(f)
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse spec: {str(e)}"}

        # Read implementation code
        try:
            with open(impl_path, "r", encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            return {"status": "error", "message": f"Failed to read code: {str(e)}"}

        # Extract endpoints from spec
        spec_endpoints = set(spec.get("paths", {}).keys())

        # Extract routes from code (FastAPI/Flask)
        patterns = [
            r'@(?:app|router|api)\.(get|post|put|delete|patch)\("([^"]+)"\)',
            r"@(?:app|router|api)\.(get|post|put|delete|patch)\(\'([^']+)\'\)"
        ]
        code_routes = set()
        for pat in patterns:
            matches = re.findall(pat, code)
            for method, path in matches:
                code_routes.add(path)

        issues = []

        # In spec but missing in code
        for path in spec_endpoints - code_routes:
            issues.append({
                "type": "missing_implementation",
                "message": f"Endpoint {path} in spec but not in code"
            })

        # In code but missing in spec
        for path in code_routes - spec_endpoints:
            issues.append({
                "type": "undocumented_endpoint",
                "message": f"Endpoint {path} in code but not in spec"
            })

        return {
            "status": "ok" if not issues else "issues_found",
            "spec_file": spec_path,
            "impl_file": impl_path,
            "issues": issues
        }



class CodeCommentTool(BaseTool):
    name: str = "Code Comment Auditor"
    description: str = "Extracts inline comments and surrounding code for LLM-based verification of correctness."

    def _run(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."

        content = _safe_read_text(file_path)
        lines = content.splitlines(keepends=True)

        comments_with_context = []

        # Line comments: Python (#) and C/JS (//)
        for i, line in enumerate(lines):
            if re.search(r"(^|\s)#", line) or re.search(r"(^|\s)//", line):
                context = lines[max(0, i-2):min(len(lines), i+3)]
                comments_with_context.append({
                    "line_number": i + 1,
                    "comment": line.strip(),
                    "context": "".join(context)
                })

        # Block comments: /* ... */
        in_block = False
        block_start = 0
        block_lines = []
        for i, line in enumerate(lines):
            if not in_block and "/*" in line:
                in_block = True
                block_start = i
                block_lines = [line]
                if "*/" in line:
                    in_block = False
                    context = lines[max(0, block_start-2):min(len(lines), i+3)]
                    comments_with_context.append({
                        "line_range": f"{block_start + 1}-{i + 1}",
                        "comment": "".join(block_lines).strip(),
                        "context": "".join(context)
                    })
                continue

            if in_block:
                block_lines.append(line)
                if "*/" in line:
                    in_block = False
                    context = lines[max(0, block_start-2):min(len(lines), i+3)]
                    comments_with_context.append({
                        "line_range": f"{block_start + 1}-{i + 1}",
                        "comment": "".join(block_lines).strip(),
                        "context": "".join(context)
                    })

        return str(comments_with_context) if comments_with_context else "No inline comments found."

class ListFilesTool(BaseTool):
    name: str = "list_files"
    description: str = "Recursively lists all files in a given directory to help identify which files need auditing."

    def _run(self, directory: str) -> str:
        if not os.path.exists(directory):
            return f"Error: Directory {directory} not found."
        
        file_list = []
        for root, dirs, files in os.walk(directory):
            # Skip hidden directories like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if not file.startswith('.'):
                    rel_path = os.path.relpath(os.path.join(root, file), directory)
                    file_list.append(rel_path)
        
        return "\n".join(file_list) if file_list else "No files found in the directory."


class DiffGeneratorTool(BaseTool):
    name: str = "diff_generator"
    description: str = "Create unified diffs of old → new content."

    def _run(self, old_text: str, new_text: str, file_path: str = "") -> str:
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        from_file = file_path if file_path else "before"
        to_file = file_path if file_path else "after"

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_file,
            tofile=to_file,
            lineterm=""
        )
        diff_text = "\n".join(diff)
        return diff_text if diff_text else "No differences found."


class SrsParserTool(BaseTool):
    name: str = "SRS Parser"
    description: str = "Parses local SRS markdown files and extracts headings, requirement IDs, and summary text."

    def _run(self, path: str) -> str:
        if not os.path.exists(path):
            return f"Error: Path {path} not found."

        md_files = []
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file in files:
                    if file.lower().endswith(".md") and not file.startswith('.'):
                        md_files.append(os.path.join(root, file))
        else:
            if not path.lower().endswith(".md"):
                return "Error: SRS Parser expects a markdown (.md) file or a directory containing markdown files."
            md_files = [path]

        results = []
        req_pattern = re.compile(r"\b([A-Z]{2,}-\d+)\b")
        for md_file in md_files:
            content = _safe_read_text(md_file)
            headings = [line.strip() for line in content.splitlines() if line.strip().startswith("#")]
            req_ids = list(dict.fromkeys(req_pattern.findall(content)))
            summary = content[:400].strip().replace("\n", " ")
            results.append({
                "file": md_file,
                "headings": headings,
                "requirement_ids": req_ids,
                "summary": summary
            })

        return str(results) if results else "No markdown content found to parse."


class GitAnalyzerTool(BaseTool):
    name: str = "git_analyzer"
    description: str = "Gets file modification history and last-changed date using git log."

    def _run(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."

        repo_root = self._find_git_root(os.path.dirname(file_path))
        if not repo_root:
            last_changed = datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
            return f"No git repository found. Last modified (filesystem): {last_changed}"

        try:
            log_cmd = [
                "git", "-C", repo_root, "log", "-n", "5",
                "--format=%ct|%H|%an|%ad|%s", "--", file_path
            ]
            output = subprocess.check_output(log_cmd, text=True).strip()
            if not output:
                return "No git history found for this file."

            entries = []
            for line in output.splitlines():
                ts, commit, author, date, subject = line.split("|", 4)
                entries.append({
                    "timestamp": int(ts),
                    "date": date,
                    "commit": commit,
                    "author": author,
                    "subject": subject
                })

            last_changed_date = entries[0]["date"] if entries else "unknown"
            return str({"last_changed": last_changed_date, "history": entries})
        except subprocess.CalledProcessError as exc:
            return f"Error running git log: {exc}"

    def _find_git_root(self, start_dir: str) -> str:
        current = start_dir
        while current and current != os.path.dirname(current):
            if os.path.isdir(os.path.join(current, ".git")):
                return current
            current = os.path.dirname(current)
        return ""


class ApplyFixTool(BaseTool):
    name: str = "apply_fix"
    description: str = (
        "Writes the corrected documentation content to a file, applying the fix. "
        "Use this tool to actually update documentation files after generating a diff."
    )

    def _run(self, file_path: str, new_content: str) -> str:
        """Write new_content to file_path, creating dirs if needed."""
        if not file_path:
            return "Error: file_path is required."
        try:
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Successfully wrote {len(new_content)} bytes to {file_path}"
        except Exception as exc:
            return f"Error writing to {file_path}: {exc}"


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = "Reads the entire content of a file and returns it as a string."

    def _run(self, file_path: str) -> str:
        if not file_path:
            return "Error: file_path is required."
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."
        try:
            return _safe_read_text(file_path)
        except Exception as exc:
            return f"Error reading {file_path}: {exc}"
