#!/usr/bin/env python
import sys
import warnings
import os
from datetime import datetime
from document_freshness_auditor.crew import DocumentFreshnessAuditor

from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

def run():
    """
    Run the crew.
    """
    # Use the current directory as the project path by default
    # Or use the first command line argument if provided
    project_path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    
    inputs = {
        'project_path': project_path,
        'current_year': str(datetime.now().year)
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
