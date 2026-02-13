import sqlite3
import uuid
import json
import re
import os
from datetime import datetime, timezone


DB_PATH = os.getenv("FRESHNESS_DB_PATH", "freshness_auditor.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            path        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reports (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'completed',
            total_files     INTEGER NOT NULL DEFAULT 0,
            critical_issues INTEGER NOT NULL DEFAULT 0,
            major_issues    INTEGER NOT NULL DEFAULT 0,
            minor_issues    INTEGER NOT NULL DEFAULT 0,
            average_score   REAL NOT NULL DEFAULT 0.0,
            severity        TEXT NOT NULL DEFAULT 'minor',
            report_md       TEXT,
            analysis_json   TEXT,
            audit_raw       TEXT,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
    """)
    conn.commit()
    conn.close()


# ── analysis parser ──────────────────────────────────────────────

def _parse_analysis(analysis_json_str: str) -> dict:
    """Parse the raw analysis JSON string and compute summary stats."""
    defaults = {
        "total_files": 0,
        "critical_issues": 0,
        "major_issues": 0,
        "minor_issues": 0,
        "average_score": 0.0,
        "severity": "minor",
        "files": [],
    }

    if not analysis_json_str or not analysis_json_str.strip():
        return defaults

    raw = analysis_json_str.strip()

    # try to pull a JSON array out of the raw string
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # sometimes the LLM wraps JSON in markdown fences
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                pass

    if not isinstance(data, list):
        return defaults

    total_files = len(data)
    critical = 0
    major = 0
    minor = 0
    score_sum = 0.0
    files = []

    for entry in data:
        if not isinstance(entry, dict):
            continue

        sev = str(entry.get("severity", "minor")).lower()
        file_issues = entry.get("issues", []) or []

        # count issues by severity at the file level
        if sev == "critical":
            critical += len(file_issues) if file_issues else 1
        elif sev == "major":
            major += len(file_issues) if file_issues else 1
        else:
            minor += len(file_issues) if file_issues else 1

        fs = float(entry.get("freshness_score", 0))
        score_sum += fs

        # build the per-file object the UI expects
        numbered_issues = []
        for idx, iss in enumerate(file_issues, 1):
            numbered_issues.append({
                "number": idx,
                "issue": iss.get("description", ""),
                "location": iss.get("location", ""),
                "impact": iss.get("impact", ""),
                "expected": iss.get("expected", ""),
                "actual": iss.get("actual", ""),
            })

        recommendations = entry.get("recommendations", []) or []

        files.append({
            "file": entry.get("file_path", ""),
            "doc_type": entry.get("doc_type", ""),
            "severity": sev,
            "freshness_score": fs,
            "confidence": float(entry.get("confidence", 0)),
            "score_breakdown": entry.get("score_breakdown", {}),
            "issues": numbered_issues,
            "recommendations": recommendations,
        })

    avg = round(score_sum / total_files, 2) if total_files else 0.0

    # overall severity = whichever bucket has the most issues
    if critical >= major and critical >= minor:
        overall = "critical"
    elif major >= minor:
        overall = "major"
    else:
        overall = "minor"

    return {
        "total_files": total_files,
        "critical_issues": critical,
        "major_issues": major,
        "minor_issues": minor,
        "average_score": avg,
        "severity": overall,
        "files": files,
    }


# ── project helpers ──────────────────────────────────────────────

def create_project(name: str, path: str) -> dict:
    # If a project with the same name AND path already exists, return it.
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM projects WHERE name = ? AND path = ?",
        (name, path),
    ).fetchone()
    if row:
        existing = dict(row)
        conn.close()
        return existing

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, name, path, created_at) VALUES (?, ?, ?, ?)",
        (project_id, name, path, now),
    )
    conn.commit()
    conn.close()
    return {"id": project_id, "name": name, "path": path, "created_at": now}


def get_project(project_id: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_projects() -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project_by_name_path(name: str, path: str) -> dict | None:
    """Return a project matching the given `name` AND `path`, or None."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM projects WHERE name = ? AND path = ?",
        (name, path),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── report helpers ───────────────────────────────────────────────

def create_report(
    project_id: str,
    report_md: str = "",
    analysis_json: str = "",
    audit_raw: str = "",
) -> dict:
    report_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    stats = _parse_analysis(analysis_json)

    conn = _connect()
    conn.execute(
        """INSERT INTO reports
           (id, project_id, status, total_files, critical_issues, major_issues,
            minor_issues, average_score, severity, report_md, analysis_json,
            audit_raw, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report_id, project_id, "completed",
            stats["total_files"], stats["critical_issues"], stats["major_issues"],
            stats["minor_issues"], stats["average_score"], stats["severity"],
            report_md, analysis_json, audit_raw, now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "id": report_id,
        "project_id": project_id,
        "status": "completed",
        "total_files": stats["total_files"],
        "critical_issues": stats["critical_issues"],
        "major_issues": stats["major_issues"],
        "minor_issues": stats["minor_issues"],
        "average_score": stats["average_score"],
        "severity": stats["severity"],
        "created_at": now,
    }


def create_pending_report(
    project_id: str,
    analysis_json: str = "",
    audit_raw: str = "",
) -> dict:
    report_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    stats = _parse_analysis(analysis_json)

    conn = _connect()
    conn.execute(
        """INSERT INTO reports
           (id, project_id, status, total_files, critical_issues, major_issues,
            minor_issues, average_score, severity, report_md, analysis_json,
            audit_raw, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report_id, project_id, "awaiting_user_input",
            stats["total_files"], stats["critical_issues"], stats["major_issues"],
            stats["minor_issues"], stats["average_score"], stats["severity"],
            "", analysis_json, audit_raw, now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "id": report_id,
        "project_id": project_id,
        "status": "awaiting_user_input",
        "total_files": stats["total_files"],
        "critical_issues": stats["critical_issues"],
        "major_issues": stats["major_issues"],
        "minor_issues": stats["minor_issues"],
        "average_score": stats["average_score"],
        "severity": stats["severity"],
        "created_at": now,
    }


def finalize_report(report_id: str, report_md: str) -> dict | None:
    conn = _connect()
    conn.execute(
        "UPDATE reports SET report_md = ?, status = 'completed' WHERE id = ?",
        (report_md, report_id),
    )
    conn.commit()
    row = conn.execute(
        """SELECT id, project_id, status, total_files, critical_issues, major_issues,
                  minor_issues, average_score, severity, created_at
           FROM reports WHERE id = ?""",
        (report_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_report(report_id: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    # parse analysis_json into structured files list for the UI
    d["_parsed"] = _parse_analysis(d.get("analysis_json", "") or "")
    return d


def list_reports_for_project(project_id: str) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        """SELECT id, project_id, status, total_files, critical_issues,
                  major_issues, minor_issues, average_score, severity, created_at
           FROM reports WHERE project_id = ?
           ORDER BY created_at DESC""",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_audit_history() -> list[dict]:
    """Return every report with its project name — for the history list UI."""
    conn = _connect()
    rows = conn.execute(
        """SELECT r.id, p.name AS project_name, r.created_at AS audit_date,
                  r.status, r.total_files, r.critical_issues,
                  r.major_issues, r.minor_issues, r.average_score, r.severity
           FROM reports r
           JOIN projects p ON r.project_id = p.id
           ORDER BY r.created_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_full_report(report_id: str) -> dict | None:
    """Return the full structured report matching the UI's expected shape."""
    conn = _connect()
    row = conn.execute(
        """SELECT r.*, p.name AS project_name
           FROM reports r
           JOIN projects p ON r.project_id = p.id
           WHERE r.id = ?""",
        (report_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None

    d = dict(row)
    parsed = _parse_analysis(d.get("analysis_json", "") or "")

    # determine overall_health label
    if parsed["critical_issues"] >= parsed["major_issues"] and parsed["critical_issues"] >= parsed["minor_issues"]:
        health = "Critical – immediate remediation required"
    elif parsed["major_issues"] >= parsed["minor_issues"]:
        health = "Major – should be addressed soon"
    else:
        health = "Minor – low priority improvements"

    return {
        "id": d["id"],
        "project": d["project_name"],
        "project_id": d["project_id"],
        "audit_date": d["created_at"],
        "status": d["status"],
        "report_md": d.get("report_md", ""),
        "summary": {
            "total_files": parsed["total_files"],
            "critical_issues": parsed["critical_issues"],
            "major_issues": parsed["major_issues"],
            "minor_issues": parsed["minor_issues"],
            "average_freshness_score": parsed["average_score"],
            "overall_health": health,
        },
        "files": parsed["files"],
    }
