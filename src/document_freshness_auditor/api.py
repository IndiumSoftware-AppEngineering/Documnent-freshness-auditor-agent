import os
import warnings
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

from document_freshness_auditor.crew import DocumentFreshnessAuditor
from document_freshness_auditor import db


# ── lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="Documentation Freshness Auditor",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── schemas ──────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    project_name: str = Field(..., min_length=1, description="Human-readable project name")
    project_path: str = Field(..., min_length=1, description="Absolute path to the project directory")


class AnalyzeContinueRequest(BaseModel):
    report_id: str = Field(..., min_length=1)
    user_input: str = Field(..., min_length=1)
    apply: bool = Field(False, description="If true, apply fixes to files; otherwise return preview only")


class ProjectOut(BaseModel):
    id: str
    name: str
    path: str
    created_at: str


# History list item — matches the UI card shape
class AuditHistoryOut(BaseModel):
    id: str
    project_name: str
    audit_date: str
    status: str
    total_files: int
    critical_issues: int
    major_issues: int
    minor_issues: int
    average_score: float
    severity: str


# Full report shapes
class IssueSummary(BaseModel):
    total_files: int
    critical_issues: int
    major_issues: int
    minor_issues: int
    average_freshness_score: float
    overall_health: str


class IssueOut(BaseModel):
    number: int
    issue: str
    location: str = ""
    impact: str = ""
    expected: str = ""
    actual: str = ""


class ScoreBreakdownOut(BaseModel):
    structural_match: float = 0
    semantic_accuracy: float = 0
    recency_factor: float = 0
    completeness: float = 0


class FileReportOut(BaseModel):
    file: str
    doc_type: str = ""
    severity: str = ""
    freshness_score: float = 0
    confidence: float = 0
    score_breakdown: dict = {}
    issues: list[IssueOut] = []
    recommendations: list[str] = []


class FullReportOut(BaseModel):
    id: str
    project: str
    project_id: str
    audit_date: str
    status: str
    report_md: str = ""
    summary: IssueSummary
    files: list[FileReportOut] = []


class ReportCreatedOut(BaseModel):
    id: str
    project_id: str
    status: str
    total_files: int
    critical_issues: int
    major_issues: int
    minor_issues: int
    average_score: float
    severity: str
    created_at: str


def _extract_outputs(result) -> tuple[str, str]:
    analysis_json = ""
    audit_raw = ""
    if hasattr(result, "tasks_output") and result.tasks_output:
        for task_out in result.tasks_output:
            task_name = (getattr(task_out, "name", "") or "").lower()
            raw = getattr(task_out, "raw", "") or ""
            if "scorer" in task_name or "freshness" in task_name:
                analysis_json = raw
            elif "audit" in task_name:
                audit_raw = raw
    return analysis_json, audit_raw


# ── endpoints ────────────────────────────────────────────────────

@app.post("/analyze", response_model=ReportCreatedOut, status_code=201)
def analyze_project(req: AnalyzeRequest):
    """
    Kick off a full documentation freshness audit.
    Creates a project record, runs the crew, parses & stores everything.
    """
    if not os.path.isdir(req.project_path):
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.project_path}")

    project = db.create_project(name=req.project_name, path=req.project_path)

    inputs = {
        "project_path": req.project_path,
        "current_year": str(datetime.now().year),
    }

    crew_instance = DocumentFreshnessAuditor()
    result = crew_instance.crew().kickoff(inputs=inputs)

    report_md = ""
    report_file = os.path.join(os.getcwd(), "freshness_audit_report.md")
    if os.path.exists(report_file):
        with open(report_file, "r") as f:
            report_md = f.read()

    analysis_json = ""
    audit_raw = ""
    if hasattr(result, "tasks_output") and result.tasks_output:
        for task_out in result.tasks_output:
            task_name = getattr(task_out, "name", "") or ""
            raw = getattr(task_out, "raw", "") or ""
            if "scorer" in task_name.lower() or "freshness" in task_name.lower():
                analysis_json = raw
            elif "audit" in task_name.lower():
                audit_raw = raw

    report = db.create_report(
        project_id=project["id"],
        report_md=report_md,
        analysis_json=analysis_json,
        audit_raw=audit_raw,
    )

    return ReportCreatedOut(**report)


@app.get("/hitl", response_class=HTMLResponse)
def hitl_page():
    return """
<!doctype html>
<html>
  <body style=\"font-family:Arial;max-width:840px;margin:20px auto\">
    <h2>Documentation Audit HITL</h2>
    <p>Step 1: Run <code>POST /analyze/start</code> and copy report_id.</p>
    <p>Step 2: Paste report_id + your feedback and submit.</p>
    <input id=\"report_id\" placeholder=\"report_id\" style=\"width:100%;padding:8px;margin-bottom:8px;\" />
    <textarea id=\"user_input\" rows=\"8\" style=\"width:100%;padding:8px;\" placeholder=\"Approve / corrections / extra guidance\"></textarea>
    <br/><br/>
        <label style="display:block;margin-top:8px"><input type="checkbox" id="apply"> Apply fixes to files</label>
        <button onclick="go()">Submit Human Input</button>
    <pre id=\"out\" style=\"background:#f4f4f4;padding:12px;\"></pre>
    <script>
      async function go() {
        const payload = {
          report_id: document.getElementById(\"report_id\").value,
          user_input: document.getElementById(\"user_input\").value
                ,
                    apply: document.getElementById("apply").checked
                };
        const r = await fetch(\"/analyze/continue\", {
          method: \"POST\",
          headers: {\"Content-Type\":\"application/json\"},
          body: JSON.stringify(payload)
        });
        document.getElementById(\"out\").textContent = await r.text();
      }
    </script>
  </body>
</html>
"""


@app.post("/analyze/start")
def analyze_start(req: AnalyzeRequest):
    if not os.path.isdir(req.project_path):
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.project_path}")

    project = db.create_project(name=req.project_name, path=req.project_path)
    crew_instance = DocumentFreshnessAuditor()

    result = crew_instance.analysis_only_crew().kickoff(
        inputs={
            "project_path": req.project_path,
            "current_year": str(datetime.now().year),
        }
    )

    analysis_json, audit_raw = _extract_outputs(result)
    report = db.create_pending_report(
        project_id=project["id"],
        analysis_json=analysis_json,
        audit_raw=audit_raw,
    )

    preview = db.get_full_report(report["id"])
    return {
        "report_id": report["id"],
        "project_id": project["id"],
        "status": report["status"],
        "preview": preview,
    }


@app.post("/analyze/continue")
def analyze_continue(req: AnalyzeContinueRequest):
    report = db.get_report(req.report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    project = db.get_project(report["project_id"])
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # If the client only wants a preview (default), return the preview without applying fixes.
    if not req.apply:
        preview = db.get_full_report(req.report_id)
        return {
            "report_id": req.report_id,
            "status": report["status"],
            "preview": preview,
            "message": "Preview generated. Set 'apply' to true to apply fixes."
        }

    # Apply fixes via the fix-only crew when explicitly requested.
    crew_instance = DocumentFreshnessAuditor()
    crew_instance.fix_only_crew().kickoff(
        inputs={
            "project_path": project["path"],
            "current_year": str(datetime.now().year),
            "scored_issues": report.get("_parsed", {}).get("files", []),
            "user_feedback": req.user_input,
        }
    )

    report_file = os.path.join(os.getcwd(), "freshness_audit_report.md")
    report_md = ""
    if os.path.exists(report_file):
        with open(report_file, "r") as f:
            report_md = f.read()

    final_row = db.finalize_report(req.report_id, report_md)
    if not final_row:
        raise HTTPException(status_code=500, detail="Could not finalize report")

    return {
        "report_id": final_row["id"],
        "status": final_row["status"],
        "message": "HITL accepted. Fix report generated.",
    }


# ── Audit History (list view for UI) ─────────────────────────────

@app.get("/history", response_model=list[AuditHistoryOut])
def get_audit_history():
    """Returns all past audits in the shape the UI history list expects."""
    return db.get_audit_history()


# ── Full report (detail view for UI) ─────────────────────────────

@app.get("/reports/{report_id}", response_model=FullReportOut)
def get_full_report(report_id: str):
    """Returns the full structured report matching the UI detail view."""
    r = db.get_full_report(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    return r


# ── Projects ─────────────────────────────────────────────────────

@app.get("/projects", response_model=list[ProjectOut])
def list_projects():
    return db.list_projects()


@app.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@app.get("/projects/find")
def find_project(name: str, path: str):
    """Find a project by both name and path and return its id."""
    p = db.get_project_by_name_path(name, path)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": p["id"]}


@app.get("/projects/{project_id}/reports", response_model=list[AuditHistoryOut])
def list_project_reports(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.list_reports_for_project(project_id)
    # enrich with project name for consistency
    name = p["name"]
    return [
        AuditHistoryOut(
            id=r["id"],
            project_name=name,
            audit_date=r["created_at"],
            status=r["status"],
            total_files=r["total_files"],
            critical_issues=r["critical_issues"],
            major_issues=r["major_issues"],
            minor_issues=r["minor_issues"],
            average_score=r["average_score"],
            severity=r["severity"],
        )
        for r in rows
    ]


# ── runner ───────────────────────────────────────────────────────
def serve():
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("document_freshness_auditor.api:app", host=host, port=port, reload=True)
