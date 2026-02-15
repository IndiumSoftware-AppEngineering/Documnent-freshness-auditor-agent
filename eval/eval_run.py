import os
import sys
import re
import argparse
from typing import Dict, Optional, List
from pathlib import Path
from langsmith import Client, evaluate
from langchain_community.llms import Ollama
from difflib import SequenceMatcher
from typing import Dict, Optional
from document_freshness_auditor.crew import DocumentFreshnessAuditor
from dotenv import load_dotenv

load_dotenv()

# Command Line Arguments

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Documentation Freshness Auditor - LLM Judge Evaluation"
    )
    
    parser.add_argument(
        "--project-path",
        "-p",
        type=str,
        help="Path to demo/test project folder",
        default=None
    )
    
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        help="LLM model to use as judge (default: mistral:7b)",
        default=os.getenv("OLLAMA_MODEL", "mistral:7b")
    )
    
    parser.add_argument(
        "--ollama-url",
        "-u",
        type=str,
        help="Ollama base URL (default: http://localhost:11434)",
        default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    
    parser.add_argument(
        "--files",
        "-f",
        type=str,
        nargs="+",
        help="Specific files to audit (default: all)",
        default=None
    )
    
    parser.add_argument(
        "--experiment",
        "-e",
        type=str,
        help="Experiment prefix for LangSmith",
        default="doc-audit-llm-judge"
    )
    
    return parser.parse_args()


# Setup Demo Project Path

def get_demo_project_path(provided_path: Optional[str] = None) -> str:
    """Get demo project path from argument or default"""
    if provided_path:
        path = Path(provided_path).resolve()
        if not path.exists():
            print(f"Error: Path does not exist: {provided_path}")
            sys.exit(1)
        if not path.is_dir():
            print(f"Error: Path is not a directory: {provided_path}")
            sys.exit(1)
        print(f"Using provided project path: {path}")
        return str(path)
    
    # Default path
    default_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src/document_freshness_auditor/demo-project"
    )
    
    if not Path(default_path).exists():
        print(f"Default demo project not found: {default_path}")
        print(f"\nProvide a project path using:")
        print(f"   uv run eval/eval_run.py --project-path /path/to/project")
        sys.exit(1)
    
    print(f"Using default project path: {default_path}")
    return default_path


# Initialize Judge LLM

class JudgeLLM:
    """Judge LLM for evaluating audit results"""
    
    def __init__(self, model: str, base_url: str):
        """Initialize the judge with Ollama"""
        self.base_url = base_url
        self.model = model
        
        print(f"🔌 Connecting to Ollama...")
        print(f"   Model: {self.model}")
        print(f"   URL: {self.base_url}")
        
        self.judge = Ollama(
            base_url=self.base_url,
            model=self.model,
            temperature=0.1,
            top_k=40,
            top_p=0.9,
        )
        
        # Test connection
        try:
            test = self.judge.invoke("Hello")
            print(f"Judge LLM connected successfully\n")
        except Exception as e:
            print(f"Failed to connect to Ollama: {e}")
            print(f"   Make sure Ollama is running:")
            print(f"   ollama serve")
            sys.exit(1)
    
    def evaluate(self, prompt: str) -> str:
        """Call judge LLM with prompt"""
        try:
            response = self.judge.invoke(prompt)
            return response
        except Exception as e:
            return f"Error: {str(e)}"
    
    def extract_score(self, response: str) -> float:
        """Extract score 0-100 from LLM response"""
        try:
            patterns = [
                r'score[:\s]+(\d+)',
                r'(\d+)\s*(?:/100|%)',
                r'rating[:\s]+(\d+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, response.lower())
                if match:
                    score = float(match.group(1))
                    return min(100, max(0, score)) / 100.0
            
            numbers = re.findall(r'\d+', response)
            if numbers:
                score = float(numbers[0])
                return min(100, max(0, score)) / 100.0
        except:
            pass
        
        return 0.5

# Global judge instance
_judge = None

def get_judge(model: str = "mistral:7b", base_url: str = "http://localhost:11434") -> JudgeLLM:
    """Get or create judge LLM instance"""
    global _judge
    if _judge is None:
        _judge = JudgeLLM(model, base_url)
    return _judge

# Helper Functions

def safe_get_expected_issues(example):
    try:
        result = {"critical": [], "major": [], "minor": []}

        entries = example.outputs.get("entries", [])
        for group in entries:
            severity = group.get("severity")
            issues = group.get("issues", [])
            if severity in result:
                result[severity].extend(issues)

        return result

    except Exception as e:
        print(f"Error extracting issues: {e}")
        return {"critical": [], "major": [], "minor": []}

def get_files_from_project(project_path: str, file_filter: Optional[List[str]] = None) -> Dict[str, str]:
    """Read all relevant files from project"""
    files_content = {}
    project_path = Path(project_path)
    
    # Extensions to include
    extensions = {'.py', '.md', '.yaml', '.yml', '.txt', '.json'}
    
    print(f"\nScanning project for files...")
    
    for file_path in project_path.rglob('*'):
        if not file_path.is_file():
            continue
        
        # Skip common non-content files
        if file_path.name.startswith('.'):
            continue
        if file_path.suffix not in extensions:
            continue
        if any(skip in str(file_path) for skip in ['__pycache__', '.git', '.venv', 'venv']):
            continue
        
        # Get relative path
        rel_path = file_path.relative_to(project_path)
        
        # Filter if specific files requested
        if file_filter:
            if str(rel_path) not in file_filter and file_path.name not in file_filter:
                continue
        
        # Read file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                files_content[str(rel_path)] = content
                print(f"   ✓ {rel_path} ({len(content)} chars)")
        except Exception as e:
            print(f"   ✗ {rel_path} (Error: {str(e)[:30]})")
    
    if not files_content:
        print(f"No files found in {project_path}")
        sys.exit(1)
    
    return files_content

# Evaluation Functions

def correctness_evaluator(run, example) -> Optional[Dict]:
    """Judge: Did agent find the expected issues?"""
    judge = get_judge()
    output = str(run.outputs.get("output", ""))
    
    if not output or len(output) < 10:
        return {"key": "correctness", "score": 0.0, "comment": "Empty output"}
    
    expected_issues = safe_get_expected_issues(example)
    expected_critical = len(expected_issues.get("critical", []))
    expected_major = len(expected_issues.get("major", []))
    expected_minor = len(expected_issues.get("minor", []))
    total_expected = expected_critical + expected_major + expected_minor
    
    prompt = f"""You are an expert evaluator for documentation auditing.

EXPECTED ISSUES TO FIND:
- {expected_critical} critical issues
- {expected_major} major issues  
- {expected_minor} minor issues
- Total: {total_expected} issues

AUDIT OUTPUT:
{output[:1000]}

EVALUATE: Did it cover MOST expected issues even if phrasing differs?
Allow additional valid findings.

Rate the CORRECTNESS on a scale of 0-100.

Respond with: "Score: [0-100]" """

    print(f"Evaluating correctness...")
    response = judge.evaluate(prompt)
    score = judge.extract_score(response)
    
    return {
        "key": "correctness",
        "score": score,
        "comment": f"Correctness: {score:.0%}"
    }

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def hallucination_evaluator(run, example) -> Optional[Dict]:
    """
    Deterministic hallucination check with fuzzy matching.
    Measures how many expected issues appear in output.
    """

    try:
        output = str(run.outputs.get("output", "")).lower()

        if not output.strip():
            return {
                "key": "hallucination",
                "score": 0.0,
                "comment": "Empty output"
            }

        expected = safe_get_expected_issues(example)

        expected_text = []
        for severity in ["critical", "major", "minor"]:
            for issue in expected[severity]:
                desc = issue.get("description", "").lower().strip()
                if desc:
                    expected_text.append(desc)

        if not expected_text:
            return {
                "key": "hallucination",
                "score": 1.0,
                "comment": "No ground truth issues"
            }

        output_lines = [line.strip() for line in output.split("\n") if line.strip()]

        matched = 0

        for desc in expected_text:
            for line in output_lines:
                if similarity(desc, line) > 0.65:  
                    matched += 1
                    break

        score = matched / len(expected_text)

        return {
            "key": "hallucination",
            "score": round(score, 3),
            "comment": f"Matched {matched}/{len(expected_text)} issues"
        }

    except Exception as e:
        return {
            "key": "hallucination",
            "score": 0.0,
            "comment": f"Evaluation error: {e}"
        }

def severity_evaluator(run, example) -> Optional[Dict]:
    """Judge: Are severity levels correctly assigned?"""
    judge = get_judge()
    output = str(run.outputs.get("output", ""))
    
    if not output or len(output) < 10:
        return {"key": "severity", "score": 0.5, "comment": "Empty output"}
    
    expected_issues = safe_get_expected_issues(example)
    expected_critical = expected_issues.get("critical", [])
    expected_major = expected_issues.get("major", [])
    
    critical_issues = "\n".join([f"- {i.get('description', 'N/A')}" for i in expected_critical[:2]])
    major_issues = "\n".join([f"- {i.get('description', 'N/A')}" for i in expected_major[:3]])
    
    prompt = f"""You are an expert evaluator for documentation auditing.

CRITICAL ISSUES (blocking, breaks functionality):
{critical_issues if critical_issues else "None"}

MAJOR ISSUES (misleading, causes problems):
{major_issues if major_issues else "None"}

AUDIT OUTPUT:
{output[:1000]}

EVALUATE: Did the audit correctly classify issues by severity?

Rate SEVERITY ACCURACY on a scale of 0-100.

Respond with: "Score: [0-100]" """

    print(f"Evaluating severity accuracy...")
    response = judge.evaluate(prompt)
    score = judge.extract_score(response)
    
    return {
        "key": "severity",
        "score": score,
        "comment": f"Severity accuracy: {score:.0%}"
    }

def completeness_evaluator(run, example) -> Optional[Dict]:
    """Judge: Is the audit report complete and well-structured?"""
    judge = get_judge()
    output = str(run.outputs.get("output", ""))
    
    if not output or len(output) < 10:
        return {"key": "completeness", "score": 0.0, "comment": "Empty output"}
    
    expected_total = example.outputs.get("total_issues", 0)
    
    prompt = f"""You are an expert evaluator for documentation auditing.

A comprehensive audit report should include:
1. SUMMARY - Overview and total issues
2. ISSUES LIST - Clear enumeration of all issues
3. SEVERITY BREAKDOWN - Count by critical/major/minor
4. FILE BREAKDOWN - Issues grouped by file

EXPECTED: ~{expected_total} issues documented

AUDIT OUTPUT:
{output[:1500]}

EVALUATE: Is the report complete and well-structured?

Rate COMPLETENESS on a scale of 0-100.

Respond with: "Score: [0-100]" """

    print(f"Evaluating completeness...")
    response = judge.evaluate(prompt)
    score = judge.extract_score(response)
    
    return {
        "key": "completeness",
        "score": score,
        "comment": f"Completeness: {score:.0%}"
    }

def actionability_evaluator(run, example) -> Optional[Dict]:
    """Judge: Are the recommendations actionable?"""
    judge = get_judge()
    output = str(run.outputs.get("output", ""))
    
    if not output or len(output) < 10:
        return {"key": "actionability", "score": 0.5, "comment": "Empty output"}
    
    prompt = f"""You are an expert evaluator for documentation auditing.

An actionable report should:
1. Clearly identify WHAT is wrong
2. Explain WHY it's a problem  
3. Show WHERE the issue is
4. Provide HOW to fix it

AUDIT OUTPUT:
{output[:1500]}

EVALUATE: Are recommendations ACTIONABLE? Can developers implement them?

Rate ACTIONABILITY on a scale of 0-100.

Respond with: "Score: [0-100]" """

    print(f"Evaluating actionability...")
    response = judge.evaluate(prompt)
    score = judge.extract_score(response)
    
    return {
        "key": "actionability",
        "score": score,
        "comment": f"Actionability: {score:.0%}"
    }

# Crew Target

def crew_target(inputs: dict) -> Dict:
    """Run crew on project (force all files from project)"""
    try:
        project_path = inputs.get("project_path", "")

        if not project_path or not Path(project_path).exists():
            return {"output": f"Invalid path: {project_path}"}

        # 🔥 Always scan real project files (ignore dataset)
        files_content = get_files_from_project(project_path)
        files_to_audit = list(files_content.keys())

        if not files_content:
            return {"output": "No files found in project"}

        os.environ["CREWAI_HUMAN_INPUT"] = "false"

        print(f"\n🔍 Running audit on {len(files_to_audit)} files:")
        for f in files_to_audit:
            print(f"   • {f}")

        auditor = DocumentFreshnessAuditor()
        crew = auditor.crew()

        for task in crew.tasks:
            if hasattr(task, 'human_input'):
                task.human_input = False

        result = crew.kickoff(inputs={
            "project_path": project_path,
            "files_content": files_content,
            "files_to_audit": files_to_audit
        })

        return {"output": str(result) if result else "No output"}

    except Exception as e:
        import traceback
        return {
            "output": f"Error: {str(e)}",
            "error": traceback.format_exc()[:200]
        }


# Main Evaluation

def run_evaluation(project_path: str, model: str, base_url: str, files_filter: Optional[List[str]], experiment: str):
    """Run evaluation with given parameters"""
    print("=" * 70)
    print("Documentation Freshness Auditor - LLM Judge Evaluation")
    print("=" * 70)
    
    # Initialize judge
    judge = get_judge(model, base_url)
    
    client = Client()
    dataset_name = "Doc_Freshness_Ground_Truth"
    
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        print(f"Dataset: {dataset.example_count} example(s)\n")
    except Exception as e:
        print(f"Dataset not found: {dataset_name}")
        print(f"   Run: python eval/dataset.py --project-path {project_path}")
        return
    
    evaluators = [
        correctness_evaluator,
        hallucination_evaluator,
        severity_evaluator,
        completeness_evaluator,
        actionability_evaluator,
    ]
    
    print(f"Evaluation Metrics: {len(evaluators)} (LLM judge)")
    for e in evaluators:
        print(f"   • {e.__doc__}")
    
    print(f"\nProject Path: {project_path}")
    print(f"   Status: {'exists' if Path(project_path).exists() else 'not exists'}")
    
    # Read files from project
    files_content = get_files_from_project(project_path, files_filter)
    print(f"\n Loaded {len(files_content)} files\n")
    
    print("⏳ Running evaluation with LLM judge...\n")
    
    try:
        results = evaluate(
            crew_target,
            data=dataset_name,
            evaluators=evaluators,
            experiment_prefix=experiment,
            max_concurrency=1
        )
        
        print("\n" + "=" * 70)
        print("Evaluation Complete!")
        print("=" * 70)
        print("\nView results: https://smith.langchain.com/")
        print("=" * 70 + "\n")
        
        return results
        
    except Exception as e:
        print(f"\n Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    args = parse_arguments()
    
    # Get project path
    project_path = get_demo_project_path(args.project_path)
    
    print("\n" + "=" * 70)
    print("Configuration:")
    print("=" * 70)
    print(f"Project Path: {project_path}")
    print(f"LLM Model: {args.model}")
    print(f"Ollama URL: {args.ollama_url}")
    if args.files:
        print(f"Files Filter: {args.files}")
    print(f"Experiment: {args.experiment}")
    print("=" * 70 + "\n")
    
    run_evaluation(
        project_path=project_path,
        model=args.model,
        base_url=args.ollama_url,
        files_filter=args.files,
        experiment=args.experiment
    )