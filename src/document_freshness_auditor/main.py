#!/usr/bin/env python
import sys
import warnings
import os
import argparse
from datetime import datetime
from rich.console import Console
from document_freshness_auditor.crew import DocumentFreshnessAuditor

from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

console = Console()
DB_URI = os.getenv("DATABASE_URL", "")
OUTPUT_DIR_BASE = os.getcwd()

def run():
    """
    Run the crew.
    Usage:
        uv run run_crew [project_path] [docs_path] [--seq-id SEQ_ID]
    If docs_path is omitted, project_path is used for both code and docs.
    If --seq-id is provided, project_id and artifact_id are resolved via DB
    and the report is written to the Liftr directory structure.
    """
    parser = argparse.ArgumentParser(description="Document Freshness Auditor")
    parser.add_argument("project_path", nargs="?", default=os.getcwd(),
                        help="Path to the project source code")
    parser.add_argument("docs_path", nargs="?", default=None,
                        help="Path to the documentation directory")
    parser.add_argument("--seq-id", dest="seq_id", type=str, default=None,
                        help="Pipeline sequence ID for DB lookup")
    args = parser.parse_args()

    if args.docs_path is None:
        args.docs_path = args.project_path

    args.project_id = None
    args.artifact_id = None

    # DB Lookup for IDs if seq_id is provided
    if args.seq_id:
        db_url = os.getenv("DATABASE_URL") or DB_URI
        if not db_url:
            console.print("[red]Error: DATABASE_URL not set. Cannot perform DB lookup for seq-id.[/red]")
            sys.exit(1)
        try:
            import psycopg
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT project_id, artifact_id FROM artifact_pipeline WHERE seq_id = %s",
                        (str(args.seq_id),)
                    )
                    result = cur.fetchone()
                    if result:
                        args.project_id = str(result[0])
                        args.artifact_id = str(result[1])
                        console.print(f"[green]DB Lookup Success:[/green] project_id={args.project_id}, artifact_id={args.artifact_id}")
                    else:
                        console.print(f"[red]Error: No pipeline found for seq_id: {args.seq_id}[/red]")
                        sys.exit(1)
        except Exception as e:
            console.print(f"[red]DB Lookup Error: {e}[/red]")
            sys.exit(1)

    if args.project_id and args.artifact_id:
        # Use Liftr directory structure
        base_dir = os.path.expanduser("~")
        output_dir = os.path.join(
            base_dir,
            "lifter",
            "projects",
            args.project_id,
            "outputs",
            args.artifact_id,
            "insights",
            "Doc_freshness_audit"
        )
    else:
        # Fallback to default structure
        run_name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_dir = os.path.join(OUTPUT_DIR_BASE, run_name)

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "freshness_audit_report.md")
    console.print(f"[blue]Output will be written to:[/blue] {output_file}")

    inputs = {
        'project_path': args.project_path,
        'docs_path': args.docs_path,
        'current_year': str(datetime.now().year),
        'audit_output_path': output_file,
    }

    try:
        DocumentFreshnessAuditor().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")

# ... (rest of the functions remain similar, but could be updated if needed)
def train():
    inputs = {
        "project_path": os.getcwd(),
        'current_year': str(datetime.now().year)
    }
    try:
        DocumentFreshnessAuditor().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    try:
        DocumentFreshnessAuditor().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    inputs = {
        "project_path": os.getcwd(),
        "current_year": str(datetime.now().year)
    }
    try:
        DocumentFreshnessAuditor().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def serve():
    """Start the FastAPI server."""
    from document_freshness_auditor.api import serve as _serve
    _serve()
