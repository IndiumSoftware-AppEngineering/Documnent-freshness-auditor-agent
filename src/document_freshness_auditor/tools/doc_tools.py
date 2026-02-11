import os
import ast
import re
import subprocess
import difflib
from datetime import datetime
from crewai.tools import BaseTool

class DocstringSignatureTool(BaseTool):
    name: str = "Docstring Signature Auditor"
    description: str = "Compares function signatures with their docstrings to identify missing parameters or type mismatches."

    def _run(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."
        
        with open(file_path, "r") as f:
            tree = ast.parse(f.read())
        
        results = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_name = node.name
                signature_args = [arg.arg for arg in node.args.args if arg.arg != 'self']
                docstring = ast.get_docstring(node)
                
                if docstring:
                    # Very basic check: are all signature args mentioned in docstring?
                    missing_in_doc = [arg for arg in signature_args if arg not in docstring]
                    if missing_in_doc:
                        results.append(f"Function '{func_name}': Docstring is missing parameters: {', '.join(missing_in_doc)}")
                else:
                    results.append(f"Function '{func_name}': Missing docstring entirely.")
        
        return "\n".join(results) if results else "All function signatures match their docstrings in this file."

class ReadmeStructureTool(BaseTool):
    name: str = "README Structure Auditor"
    description: str = "Compares file/directory mentions in README with actual project structure."

    def _run(self, root_dir: str) -> str:
        readme_path = os.path.join(root_dir, "README.md")
        if not os.path.exists(readme_path):
            return "README.md not found in root directory."
        
        with open(readme_path, "r") as f:
            content = f.read()
        
        # Look for patterns that look like file paths or names
        mentions = re.findall(r'`([^`]+\.[a-z]+)`', content)
        results = []
        for mention in mentions:
            # Check if mentioned file exists relative to root
            if not os.path.exists(os.path.join(root_dir, mention)):
                results.append(f"README mentions `{mention}`, but it does not exist.")
        
        return "\n".join(results) if results else "All files mentioned in README exist."

class ApiImplementationTool(BaseTool):
    name: str = "API Implementation Auditor"
    description: str = "Placeholder for comparing API specs with implementation. Currently checks for existence of FastAPI/Flask routes."

    def _run(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."
        
        with open(file_path, "r") as f:
            content = f.read()
        
        # Simple regex for common route decorators
        routes = re.findall(r'@(?:app|router)\.(?:get|post|put|delete|patch)\("([^"]+)"\)', content)
        return f"Found routes in implementation: {', '.join(routes)}" if routes else "No API routes found in this file."

class CodeCommentTool(BaseTool):
    name: str = "Code Comment Auditor"
    description: str = "Extracts inline comments and surrounding code for LLM-based verification of correctness."

    def _run(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} not found."
        
        with open(file_path, "r") as f:
            lines = f.readlines()

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
    name: str = "List Files Tool"
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
            with open(md_file, "r") as f:
                content = f.read()
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
