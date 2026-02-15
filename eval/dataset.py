import os
from dotenv import load_dotenv
from langsmith import Client

load_dotenv()


def create_dataset():
    """Create documentation freshness dataset (2026 ground truth)"""

    client = Client()
    dataset_name = "documentation_freshness_audit_2026"

    
    try:
        client.delete_dataset(dataset_name=dataset_name)
        print(f"🗑️ Deleted existing dataset: {dataset_name}\n")
    except Exception:
        pass

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Ground truth dataset for documentation freshness audit (2026)"
    )

    print(f"Created dataset: {dataset_name}\n")

    ground_truth = {
        "inputs": {
            "project_path": "/home/i3975/Desktop/hackathon/DOCUMENTATION-FRESHNESS-AUDITOR-AGENT-BE/src/document_freshness_auditor/demo-project",
            "files": [
                "README.md",
                "api.py",
                "calculator.py",
                "docs/SRS.md",
                "docs/architecture.md",
                "openapi.yaml",
                "utils.py"
            ]
        },
        "outputs": {
            "dataset_name": "documentation_freshness_audit_2026",
            "estimated_hours": 4.5,
            "summary": {
                "total_issues": 22,
                "critical": 3,
                "major": 19,
                "minor": 0
            },
            "entries": [
                {
                    "severity": "critical",
                    "issues": [
                        {
                            "id": "CRIT-001",
                            "file": "calculator.py",
                            "type": "missing_docstring",
                            "function": "factorial",
                            "description": "Missing docstring for factorial function"
                        },
                        {
                            "id": "CRIT-002",
                            "file": "api.py",
                            "type": "unimplemented_endpoint",
                            "endpoint": "/calculate",
                            "description": "OpenAPI endpoint declared but not implemented"
                        },
                        {
                            "id": "CRIT-003",
                            "file": "api.py",
                            "type": "unimplemented_endpoint",
                            "endpoint": "/history",
                            "description": "OpenAPI endpoint declared but not implemented"
                        }
                    ]
                },
                {
                    "severity": "major",
                    "issues": [
                        {"id": "MAJ-001", "file": "api.py", "function": "calculate", "description": "Docstring lists wrong parameter"},
                        {"id": "MAJ-002", "file": "api.py", "function": "power_endpoint", "description": "Missing parameter documentation"},
                        {"id": "MAJ-003", "file": "api.py", "function": "batch_calculate", "description": "Missing parameter description"},
                        {"id": "MAJ-004", "file": "calculator.py", "function": "add", "description": "Docstring missing parameter 'b'"},
                        {"id": "MAJ-005", "file": "calculator.py", "function": "subtract", "description": "Missing parameter in docstring"},
                        {"id": "MAJ-006", "file": "calculator.py", "function": "multiply", "description": "Missing 'precision' parameter in docstring"},
                        {"id": "MAJ-007", "file": "calculator.py", "function": "divide", "description": "Missing 'safe' parameter documentation"},
                        {"id": "MAJ-008", "file": "calculator.py", "function": "power", "description": "Missing parameters documentation"},
                        {"id": "MAJ-009", "file": "calculator.py", "function": "fibonacci", "description": "Missing parameter documentation"},
                        {"id": "MAJ-010", "file": "README.md", "description": "References non-existent helpers.py and config.yaml"},
                        {"id": "MAJ-011", "file": "README.md", "description": "Documents removed /history endpoint"},
                        {"id": "MAJ-012", "file": "README.md", "description": "Missing /power and /batch endpoints"},
                        {"id": "MAJ-013", "file": "openapi.yaml", "description": "Version mismatch: spec says 2.0.0, code says 2.1.0"},
                        {"id": "MAJ-014", "file": "openapi.yaml", "description": "Missing /power and /batch endpoints"},
                        {"id": "MAJ-015", "file": "openapi.yaml", "description": "Missing precision field in CalcRequest schema"},
                        {"id": "MAJ-016", "file": "docs/architecture.md", "description": "References deleted helpers.py module"},
                        {"id": "MAJ-017", "file": "docs/architecture.md", "description": "References non-existent auth.py"},
                        {"id": "MAJ-018", "file": "docs/SRS.md", "description": "References unimplemented functions"},
                        {"id": "MAJ-019", "file": "docs/SRS.md", "description": "References non-existent modules"}
                    ]
                },
                {
                    "severity": "minor",
                    "issues": []
                }
            ],
            "metadata": {
                "year": 2026,
                "audit_type": "documentation_freshness",
                "files_audited": [
                    "README.md",
                    "api.py",
                    "calculator.py",
                    "docs/SRS.md",
                    "docs/architecture.md",
                    "openapi.yaml",
                    "utils.py"
                ]
            }
        }
    }

    client.create_example(
        inputs=ground_truth["inputs"],
        outputs=ground_truth["outputs"],
        dataset_id=dataset.id
    )

    print("Added ground truth example\n")
    print("Summary:")
    print("   • Critical:", ground_truth["outputs"]["summary"]["critical"])
    print("   • Major:", ground_truth["outputs"]["summary"]["major"])
    print("   • Total:", ground_truth["outputs"]["summary"]["total_issues"])
    print("   • Estimated effort:", ground_truth["outputs"]["estimated_hours"], "hours\n")

    print(f"Dataset ready at: https://smith.langchain.com/o/datasets/{dataset.id}")


if __name__ == "__main__":
    create_dataset()
