import os
import re
import json
import warnings
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

from document_freshness_auditor.crew import DocumentFreshnessAuditor
from document_freshness_auditor import db
from document_freshness_auditor import hitl


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    hitl.install()
    yield
    hitl.uninstall()


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


class AnalyzeRequest(BaseModel):
    project_name: str = Field(..., min_length=1, description="Human-readable project name")
    project_path: str = Field(..., min_length=1, description="Absolute path to the project directory")


class HITLFeedbackRequest(BaseModel):
    report_id: str = Field(..., min_length=1, description="The report_id returned by /analyze/start")
    feedback: str = Field(
        "",
        description="Human feedback text. Empty string = approve as-is.",
    )


class ProjectOut(BaseModel):
    id: str
    name: str
    path: str
    created_at: str


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


def _try_extract_json_array(text: str) -> str:
    """Try to extract a JSON array of file-analysis dicts from raw text."""
    if not text or not text.strip():
        return ""

    text = text.strip()

    # Try direct parse
    candidates: list[str] = [text]

    # Try fenced code block
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    # Try bracket extraction (outermost [...])
    bracket = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket:
        candidates.append(bracket.group(0).strip())

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, list) or not data:
            continue
        # Check it looks like analysis output
        looks_right = any(
            isinstance(item, dict)
            and any(k in item for k in ("file_path", "freshness_score", "issues", "severity"))
            for item in data
        )
        if looks_right:
            return json.dumps(data, ensure_ascii=False)

    return ""


def grab_outputs(result):
    analysis_json = ""
    audit_raw = ""
    all_candidates: list[str] = []

    if hasattr(result, "tasks_output") and result.tasks_output:
        for i, task_out in enumerate(result.tasks_output):
            name = (getattr(task_out, "name", "") or "").lower()
            raw = getattr(task_out, "raw", "") or ""
            desc = (getattr(task_out, "description", "") or "")[:80]
            print(f"[grab_outputs] task #{i} name={name!r} desc={desc!r} raw_len={len(raw)}")

            parsed = _try_extract_json_array(raw)
            if parsed:
                all_candidates.append(parsed)
                print(f"[grab_outputs]   -> found valid JSON array in task #{i}")

            if "scorer" in name or "freshness" in name:
                if parsed:
                    analysis_json = parsed
                    print(f"[grab_outputs]   -> matched as scorer task")
            elif any(k in name for k in ("suggest", "suggestion", "fix", "recommend", "fixer")):
                if not analysis_json and parsed:
                    analysis_json = parsed
            elif "audit" in name:
                audit_raw = raw

    # Fallback: if no name matched, use any valid JSON array we found
    if not analysis_json and all_candidates:
        analysis_json = all_candidates[0]
        print(f"[grab_outputs] using fallback candidate (first valid JSON array found)")

    # Last resort: check the result's own .raw
    if not analysis_json and hasattr(result, "raw"):
        parsed = _try_extract_json_array(result.raw or "")
        if parsed:
            analysis_json = parsed
            print(f"[grab_outputs] extracted from result.raw")

    print(f"[grab_outputs] final analysis_json length={len(analysis_json)}, audit_raw length={len(audit_raw)}")
    return analysis_json, audit_raw


def run_crew_background(report_id, project_path):
    try:
        hitl.link_report(report_id)
        auditor = DocumentFreshnessAuditor()

        result = auditor.hitl_crew().kickoff(
            inputs={
                "project_path": project_path,
                "current_year": str(datetime.now().year),
            }
        )

        analysis_json, audit_raw = grab_outputs(result)

        report_md = ""
        report_file = os.path.join(os.getcwd(), "freshness_audit_report.md")
        if os.path.exists(report_file):
            with open(report_file, "r", encoding="utf-8", errors="replace") as f:
                report_md = f.read()

        if not analysis_json:
            print(f"[API] WARNING: no structured analysis_json captured for {report_id}")
            # Dump all task outputs for debugging
            if hasattr(result, "tasks_output") and result.tasks_output:
                for i, t in enumerate(result.tasks_output):
                    r = (getattr(t, "raw", "") or "")
                    print(f"[API] task #{i} raw (first 500 chars): {r[:500]}")

        db.finalize_report(report_id, report_md, analysis_json, audit_raw)
        print(f"[API] crew finished for report {report_id}")

    except Exception as e:
        print(f"[API] crew failed for report {report_id}: {e}")
        db.set_status(report_id, "failed")
    finally:
        hitl.remove(report_id)


@app.post("/analyze/start")
def start_audit(req: AnalyzeRequest):
    if not os.path.isdir(req.project_path):
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.project_path}")

    project = db.create_project(name=req.project_name, path=req.project_path)
    report = db.create_hitl_report(project_id=project["id"])

    t = threading.Thread(
        target=run_crew_background,
        args=(report["id"], req.project_path),
        daemon=True,
    )
    t.start()

    return {
        "report_id": report["id"],
        "project_id": project["id"],
        "status": "processing",
        "message": "Audit started. Poll GET /hitl/status/{report_id} for progress.",
    }


@app.get("/hitl/status/{report_id}")
def check_status(report_id: str):
    report = db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    resp: dict[str, Any] = {
        "report_id": report_id,
        "status": report["status"],
    }

    if report["status"] == "pending_human_input":
        resp["agent_output"] = report.get("agent_output", "")
        resp["message"] = (
            "The fix_suggester agent has produced a draft. "
            "Review agent_output and POST /hitl/feedback with your feedback "
            "(or empty string to approve as-is)."
        )
    elif report["status"] == "processing":
        resp["message"] = "Crew is still running. Please poll again."
    elif report["status"] == "completed":
        resp["message"] = "Audit complete. Fetch full report at GET /reports/{report_id}."
    elif report["status"] == "failed":
        resp["message"] = "Crew run failed. Check server logs."

    return resp


@app.post("/hitl/feedback")
def give_feedback(req: HITLFeedbackRequest):
    report = db.get_report(req.report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report["status"] != "pending_human_input":
        raise HTTPException(
            status_code=409,
            detail=f"Report is not awaiting feedback (current status: {report['status']})",
        )

    ok = hitl.send_feedback(req.report_id, req.feedback)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="No pending HITL request found for this report (may have timed out).",
        )

    action = "approved as-is" if req.feedback.strip() == "" else "feedback submitted"
    return {
        "report_id": req.report_id,
        "status": "processing",
        "message": f"Human feedback {action}. Crew is resuming.",
    }


@app.get("/history", response_model=list[AuditHistoryOut])
def get_history():
    return db.get_audit_history()


@app.get("/reports/{report_id}", response_model=FullReportOut)
def get_report(report_id: str):
    r = db.get_full_report(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    return r


@app.get("/projects", response_model=list[ProjectOut])
def get_projects():
    return db.list_projects()


@app.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@app.get("/projects/find")
def find_project(name: str, path: str):
    p = db.get_project_by_name_path(name, path)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": p["id"]}


@app.get("/projects/{project_id}/reports", response_model=list[AuditHistoryOut])
def get_project_reports(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.list_reports_for_project(project_id)
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


def serve():
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run(
        "document_freshness_auditor.api:app",
        host=host,
        port=port,
        reload=reload,
        reload_excludes=["**/demo-project/**"] if reload else None,
    )
