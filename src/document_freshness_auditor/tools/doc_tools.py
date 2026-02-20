import os
import ast
import re
import yaml
import subprocess
import difflib
import locale
import sys
from datetime import datetime
from typing import Dict, List, Set, Optional, Any
from crewai.tools import BaseTool
from pathlib import Path


def _get_abs_path(file_path: str, project_root: str = "") -> str:
    """Helper to get absolute path from relative file_path and project_root."""
    if os.path.isabs(file_path):
        return file_path
    if project_root:
        return os.path.join(project_root, file_path)
    return os.path.abspath(file_path)


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

    def _run(self, file_path: str, project_root: str = "") -> Dict[str, Any]:
        abs_path = _get_abs_path(file_path, project_root)
        if not os.path.isfile(abs_path) or not abs_path.endswith(".py"):
            return {"status": "error", "message": f"Invalid or missing .py file: {abs_path}"}

        try:
            content = _safe_read_text(abs_path)
            tree = ast.parse(content, filename=abs_path)
        except Exception as e:
            return {"status": "error", "message": f"Parse error: {str(e)}"}

        issues = []
        metrics = {
            "total_functions": 0,
            "functions_with_docstrings": 0,
            "total_params": 0,
            "documented_params": 0,
            "critical_issues": 0,
            "major_issues": 0,
            "minor_issues": 0
        }

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._process_node(node, issues, metrics)

        # Normalize path for display
        display_path = file_path
        if project_root:
            try:
                display_path = os.path.relpath(abs_path, project_root)
            except Exception:
                pass

        return {
            "status": "ok" if not issues else "issues_found",
            "file": display_path,
            "metrics": {
                "total_functions": metrics["total_functions"],
                "functions_with_docstrings": metrics["functions_with_docstrings"],
                "total_params": metrics["total_params"],
                "documented_params": metrics["documented_params"],
                "critical_issues": metrics["critical_issues"],
                "major_issues": metrics["major_issues"],
                "minor_issues": metrics["minor_issues"],
                "issue_count": len(issues),
                "doc_type": "inline_docstring"
            },
            "issues": issues
        }

    def _process_node(self, node: ast.AST, issues: List[Dict], metrics: Dict):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            metrics["total_functions"] += 1
            if ast.get_docstring(node):
                metrics["functions_with_docstrings"] += 1
            
            issue = self._check_function(node)
            self._update_metrics_from_issue(issue, node, issues, metrics)

        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    metrics["total_functions"] += 1
                    if ast.get_docstring(item):
                        metrics["functions_with_docstrings"] += 1
                    
                    issue = self._check_function(item, class_name=node.name)
                    self._update_metrics_from_issue(issue, item, issues, metrics)

    def _update_metrics_from_issue(self, issue: Optional[Dict], node: ast.AST, issues: List[Dict], metrics: Dict):
        if issue:
            issues.append(issue)
            # Default to major for mismatches, critical for missing docs
            severity = "major"
            if "Missing docstring" in issue.get("message", ""):
                severity = "critical"
            
            issue["severity"] = severity
            metrics[f"{severity}_issues"] += 1
            
            metrics["total_params"] += issue.get("_total_params", 0)
            metrics["documented_params"] += issue.get("_documented_params", 0)
        else:
            # If no issue, it means all params were documented
            p_list = [arg.arg for arg in node.args.args]
            if p_list and p_list[0] in ("self", "cls"):
                p_list = p_list[1:]
            metrics["total_params"] += len(p_list)
            metrics["documented_params"] += len(p_list)

    def _check_function(self, node: ast.FunctionDef, class_name: str = None) -> Dict or None:
        name = f"{class_name}.{node.name}" if class_name else node.name
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
        # Handle :param name: or :param type name: or :param name (type):
        for match in re.findall(r':param\s+[\w\[\], ]+\s+(\w+)', doc):
            documented.add(match)
        for match in re.findall(r':param\s+(\w+)', doc):
            documented.add(match)
            
        for line in doc.splitlines():
            # Handle "name: description" or "name (type): description"
            m = re.match(r'^\s*(\w+)(\s*\([\w\[\], ]+\))?\s*:', line.strip())
            if m:
                documented.add(m.group(1))

        missing = [p for p in params if p not in documented]
        stale = [p for p in documented if p not in params]

        # Internal metrics for recursion / summary
        res = {
            "function": name, 
            "line": line, 
            "_total_params": len(params),
            "_documented_params": len(params) - len(missing)
        }

        if not missing and not stale:
            return None

        msg = []
        if missing:
            msg.append(f"Missing params in doc: {', '.join(missing)}")
        if stale:
            msg.append(f"Stale params in doc: {', '.join(stale)}")

        res["message"] = "; ".join(msg)
        return res

class ReadmeStructureTool(BaseTool):
    name: str = "README Structure Auditor"
    description: str = "Checks one README.md for mentioned files/dirs that don't exist."

    def _run(self, readme_path: str, project_root: str = "") -> Dict[str, Any]:
        abs_readme = _get_abs_path(readme_path, project_root)
        if not os.path.isfile(abs_readme) or not abs_readme.endswith(".md"):
            return {"status": "error", "message": f"Invalid or missing README.md: {abs_readme}"}

        if project_root and not os.path.isdir(project_root):
            return {"status": "error", "message": f"Invalid project root: {project_root}"}

        try:
            content = _safe_read_text(abs_readme)
        except Exception as e:
            return {"status": "error", "message": f"Read error: {str(e)}"}

        issues = self._find_issues(content, project_root or os.path.dirname(abs_readme))

        # Add severity to issues and count
        critical_issues = 0
        major_issues = 0
        minor_issues = 0
        for issue in issues:
            issue["severity"] = "major"  # README mismatches are major by default
            major_issues += 1

        # Normalize paths
        display_path = readme_path
        if project_root:
            try:
                display_path = os.path.relpath(abs_readme, project_root)
            except Exception:
                pass

        return {
            "status": "ok" if not issues else "issues_found",
            "file": display_path,
            "metrics": {
                "critical_issues": critical_issues,
                "major_issues": major_issues,
                "minor_issues": minor_issues,
                "issue_count": len(issues),
                "doc_type": "readme"
            },
            "issues": issues
        }

    def _find_issues(self, content: str, root: str) -> List[Dict]:
        issues = []

        # Simple file/dir mention extraction
        # regex findall returns tuples if there are multiple groups
        raw_mentions = re.findall(r'\b([\w/-]+\.(py|md|txt|yaml|json|toml))\b', content)
        mentions = {m[0] if isinstance(m, tuple) else m for m in raw_mentions}
        
        # Add basic directories
        dirs = re.findall(r'\b(src|tests|docs|lib|config)/?\b', content)
        mentions.update(dirs)

        # Get real relative paths
        real_paths = set()
        root_path = Path(root)
        for path in root_path.rglob("*"):
            if path.is_file() or path.is_dir():
                try:
                    rel = str(path.relative_to(root_path))
                    real_paths.add(rel)
                except ValueError:
                    continue

        # Check mentioned but missing
        for mention in mentions:
            # Normalize mention (strip trailing slash)
            m = mention.rstrip('/')
            if m not in real_paths:
                issues.append({
                    "type": "missing_mention",
                    "message": f"Mentioned '{m}' does not exist in project"
                })

        return issues

class ApiImplementationTool(BaseTool):
    name: str = "API Implementation Auditor"
    description: str = "Compares OpenAPI/Swagger spec against API implementation code."

    def _run(self, spec_path: str, impl_path: str, **kwargs: Any) -> Dict:
        project_root = kwargs.get("project_root", "")
        abs_spec = _get_abs_path(spec_path, project_root)
        abs_impl = _get_abs_path(impl_path, project_root)

        if not os.path.isfile(abs_spec):
            return {"status": "error", "message": f"OpenAPI spec not found: {abs_spec}"}
        
        if os.path.isdir(abs_impl):
            # Try to find a likely implementation file in the directory
            possible_files = ["api.py", "app.py", "main.py", "server.py"]
            found = False
            for pf in possible_files:
                check_path = os.path.join(abs_impl, pf)
                if os.path.isfile(check_path):
                    abs_impl = check_path
                    found = True
                    break
            if not found:
                # Fallback: look for any .py file
                py_files = [f for f in os.listdir(abs_impl) if f.endswith(".py")]
                if len(py_files) == 1:
                    abs_impl = os.path.join(abs_impl, py_files[0])
                else:
                    return {"status": "error", "message": f"Implementation directory found but no clear entry point (api.py, app.py, etc.) in {abs_impl}"}

        if not os.path.isfile(abs_impl):
            return {"status": "error", "message": f"Implementation file not found: {abs_impl}"}

        # Read spec
        try:
            with open(abs_spec, "r", encoding="utf-8") as f:
                if abs_spec.endswith(".yaml") or abs_spec.endswith(".yml"):
                    spec = yaml.safe_load(f)
                else:
                    spec = json.load(f)
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse spec: {str(e)}"}

        # Read implementation code
        try:
            with open(abs_impl, "r", encoding="utf-8") as f:
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

        # Normalize endpoints
        issues = []

        # In spec but missing in code
        for path in spec_endpoints - code_routes:
            issues.append({
                "type": "missing_implementation",
                "severity": "critical",
                "message": f"Endpoint {path} in spec but not in code"
            })

        # In code but missing in spec
        for path in code_routes - spec_endpoints:
            issues.append({
                "type": "undocumented_endpoint",
                "severity": "major",
                "message": f"Endpoint {path} in code but not in spec"
            })

        critical_count = sum(1 for i in issues if i["severity"] == "critical")
        major_count = sum(1 for i in issues if i["severity"] == "major")

        return {
            "status": "ok" if not issues else "issues_found",
            "spec_file": spec_path,
            "impl_file": impl_path,
            "metrics": {
                "critical_issues": critical_count,
                "major_issues": major_count,
                "minor_issues": 0,
                "issue_count": len(issues),
                "doc_type": "api_spec"
            },
            "issues": issues
        }



class CodeCommentTool(BaseTool):
    name: str = "Code Comment Auditor"
    description: str = "Extracts inline comments and surrounding code for LLM-based verification of correctness."

    def _run(self, file_path: str, project_root: str = "") -> Dict[str, Any]:
        abs_path = _get_abs_path(file_path, project_root)
        if not os.path.exists(abs_path):
            return {"status": "error", "message": f"File {abs_path} not found."}

        content = _safe_read_text(abs_path)
        lines = content.splitlines(keepends=True)

        comments_with_context = []
        self._find_python_comment_context(lines, comments_with_context)
        self._find_block_comment_context(lines, comments_with_context)

        return {
            "status": "ok" if comments_with_context else "no_comments",
            "file": file_path,
            "metrics": {
                "critical_issues": 0,
                "major_issues": 0,
                "minor_issues": 0,
                "issue_count": len(comments_with_context),
                "doc_type": "inline_comment"
            },
            "issues": comments_with_context
        }

    def _find_python_comment_context(self, lines: List[str], results: List[Dict]):
        # Line comments: Python (#) and C/JS (//)
        for i, line in enumerate(lines):
            if re.search(r"(^|\s)#", line) or re.search(r"(^|\s)//", line):
                context = lines[max(0, i-2):min(len(lines), i+3)]
                results.append({
                    "line_number": i + 1,
                    "comment": line.strip(),
                    "context": "".join(context)
                })

    def _find_block_comment_context(self, lines: List[str], results: List[Dict]):
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
                    results.append({
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
                    results.append({
                        "line_range": f"{block_start + 1}-{i + 1}",
                        "comment": "".join(block_lines).strip(),
                        "context": "".join(context)
                    })



class ListFilesTool(BaseTool):
    name: str = "list_files"
    description: str = "Recursively lists all files in a given directory to help identify which files need auditing."

    def _run(self, directory: str) -> str:
        if not os.path.exists(directory):
            return f"Error: Directory {directory} not found."
        
        file_list = []
        self._collect_files(directory, file_list)
        
        return "\n".join(file_list) if file_list else "No files found in the directory."

    def _collect_files(self, base_dir: str, file_list: List[str]):
        for root, dirs, files in os.walk(base_dir):
            # Skip hidden directories like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if not file.startswith('.'):
                    f_path = os.path.join(root, file)
                    rel_path = os.path.relpath(f_path, base_dir)
                    file_list.append(rel_path)


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

    def _run(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            return {"status": "error", "message": f"Path {path} not found."}

        md_files = []
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file in files:
                    if file.lower().endswith(".md") and not file.startswith('.'):
                        md_files.append(os.path.join(root, file))
        else:
            if not path.lower().endswith(".md"):
                return {"status": "error", "message": "SRS Parser expects a markdown (.md) file or a directory containing markdown files."}
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

        return {
            "status": "ok" if results else "no_srs_found",
            "metrics": {
                "critical_issues": 0,
                "major_issues": 0,
                "minor_issues": 0,
                "issue_count": 0,
                "doc_type": "srs"
            },
            "files_parsed": results
        }


class GitAnalyzerTool(BaseTool):
    name: str = "git_analyzer"
    description: str = "Gets file modification history and last-changed date using git log."

    def _run(self, file_path: str, project_root: str = "") -> Dict[str, Any]:
        abs_path = _get_abs_path(file_path, project_root)
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found."

        repo_root = self._find_git_root(os.path.dirname(abs_path))
        if not repo_root:
            last_changed = datetime.fromtimestamp(os.path.getmtime(abs_path)).isoformat()
            return {
                "status": "no_git",
                "last_changed": last_changed,
                "last_updated_iso": last_changed,
                "message": "No git repository found."
            }

        try:
            log_cmd = [
                "git", "-C", repo_root, "log", "-n", "5",
                "--date=iso8601",
                "--format=%ct|%H|%an|%ad|%s", "--", abs_path
            ]
            output = subprocess.check_output(log_cmd, text=True).strip()
            if not output:
                return {"last_changed": "unknown", "last_updated_iso": None, "history": []}

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
            return {
                "last_changed": last_changed_date, 
                "last_updated_iso": entries[0]["date"] if entries else None,
                "history": entries
            }
        except subprocess.CalledProcessError as exc:
            return {"status": "error", "message": f"Error running git log: {exc}"}

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
