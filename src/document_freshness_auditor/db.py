import sqlite3
import uuid
import json
import re
import os
from datetime import datetime, timezone


DB_FILE = os.getenv("FRESHNESS_DB_PATH", "freshness_auditor.db")


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
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
            agent_output    TEXT DEFAULT '',
            created_at      TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
    """)
    try:
        conn.execute("SELECT agent_output FROM reports LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE reports ADD COLUMN agent_output TEXT DEFAULT ''")
    conn.commit()
    conn.close()


def parse_analysis(raw_str):
    empty = {
        "total_files": 0,
        "critical_issues": 0,
        "major_issues": 0,
        "minor_issues": 0,
        "average_score": 0.0,
        "severity": "minor",
        "files": [],
    }

    if not raw_str or not raw_str.strip():
        return empty

    text = raw_str.strip()

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    if not isinstance(data, list):
        return empty

    total = len(data)
    crit = 0
    major = 0
    minor = 0
    score_total = 0.0
    files = []

    for item in data:
        if not isinstance(item, dict):
            continue

        sev = str(item.get("severity", "minor")).lower()
        issues = item.get("issues", []) or []

        if sev == "critical":
            crit += len(issues) if issues else 1
        elif sev == "major":
            major += len(issues) if issues else 1
        else:
            minor += len(issues) if issues else 1

        score = float(item.get("freshness_score", 0))
        score_total += score

        numbered = []
        for i, iss in enumerate(issues, 1):
            numbered.append({
                "number": i,
                "issue": iss.get("description", ""),
                "location": iss.get("location", ""),
                "impact": iss.get("impact", ""),
                "expected": iss.get("expected", ""),
                "actual": iss.get("actual", ""),
            })

        recs = item.get("recommendations", []) or []
        if isinstance(recs, str):
            recs = recs.strip()
            if recs.startswith("[") and recs.endswith("]"):
                try:
                    parsed = json.loads(recs)
                    recs = parsed if isinstance(parsed, list) else [str(parsed)]
                except Exception:
                    recs = [recs]
            else:
                recs = [recs]
        elif not isinstance(recs, list):
            recs = []

        files.append({
            "file": item.get("file_path", ""),
            "doc_type": item.get("doc_type", ""),
            "severity": sev,
            "freshness_score": score,
            "confidence": float(item.get("confidence", 0)),
            "score_breakdown": item.get("score_breakdown", {}),
            "issues": numbered,
            "recommendations": recs,
        })

    avg = round(score_total / total, 2) if total else 0.0

    if crit >= major and crit >= minor:
        overall = "critical"
    elif major >= minor:
        overall = "major"
    else:
        overall = "minor"

    return {
        "total_files": total,
        "critical_issues": crit,
        "major_issues": major,
        "minor_issues": minor,
        "average_score": avg,
        "severity": overall,
        "files": files,
    }


def create_project(name, path):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM projects WHERE name = ? AND path = ?",
        (name, path),
    ).fetchone()
    if row:
        conn.close()
        return dict(row)

    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, name, path, created_at) VALUES (?, ?, ?, ?)",
        (pid, name, path, now),
    )
    conn.commit()
    conn.close()
    return {"id": pid, "name": name, "path": path, "created_at": now}


def get_project(project_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_projects():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project_by_name_path(name, path):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM projects WHERE name = ? AND path = ?",
        (name, path),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_report(project_id, report_md="", analysis_json="", audit_raw=""):
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    stats = parse_analysis(analysis_json)

    conn = get_conn()
    conn.execute(
        """INSERT INTO reports
           (id, project_id, status, total_files, critical_issues, major_issues,
            minor_issues, average_score, severity, report_md, analysis_json,
            audit_raw, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rid, project_id, "completed",
            stats["total_files"], stats["critical_issues"], stats["major_issues"],
            stats["minor_issues"], stats["average_score"], stats["severity"],
            report_md, analysis_json, audit_raw, now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "id": rid,
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


def create_pending_report(project_id, analysis_json="", audit_raw=""):
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    stats = parse_analysis(analysis_json)

    conn = get_conn()
    conn.execute(
        """INSERT INTO reports
           (id, project_id, status, total_files, critical_issues, major_issues,
            minor_issues, average_score, severity, report_md, analysis_json,
            audit_raw, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rid, project_id, "awaiting_user_input",
            stats["total_files"], stats["critical_issues"], stats["major_issues"],
            stats["minor_issues"], stats["average_score"], stats["severity"],
            "", analysis_json, audit_raw, now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "id": rid,
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


def finalize_report(report_id, report_md, analysis_json="", audit_raw=""):
    conn = get_conn()
    if analysis_json:
        stats = parse_analysis(analysis_json)
        conn.execute(
            """UPDATE reports
               SET report_md = ?, status = 'completed',
                   analysis_json = ?, audit_raw = ?,
                   total_files = ?, critical_issues = ?, major_issues = ?,
                   minor_issues = ?, average_score = ?, severity = ?
               WHERE id = ?""",
            (
                report_md, analysis_json, audit_raw,
                stats["total_files"], stats["critical_issues"],
                stats["major_issues"], stats["minor_issues"],
                stats["average_score"], stats["severity"],
                report_id,
            ),
        )
    else:
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


def set_status(report_id, status, agent_output=None):
    conn = get_conn()
    if agent_output is not None:
        conn.execute(
            "UPDATE reports SET status = ?, agent_output = ? WHERE id = ?",
            (status, agent_output, report_id),
        )
    else:
        conn.execute(
            "UPDATE reports SET status = ? WHERE id = ?",
            (status, report_id),
        )
    conn.commit()
    conn.close()


update_report_status = set_status


def create_hitl_report(project_id):
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO reports
           (id, project_id, status, total_files, critical_issues, major_issues,
            minor_issues, average_score, severity, report_md, analysis_json,
            audit_raw, agent_output, created_at)
           VALUES (?, ?, ?, 0, 0, 0, 0, 0.0, 'minor', '', '', '', '', ?)""",
        (rid, project_id, "processing", now),
    )
    conn.commit()
    conn.close()
    return {
        "id": rid,
        "project_id": project_id,
        "status": "processing",
        "created_at": now,
    }


def get_report(report_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["_parsed"] = parse_analysis(d.get("analysis_json", "") or "")
    return d


def list_reports_for_project(project_id):
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, project_id, status, total_files, critical_issues,
                  major_issues, minor_issues, average_score, severity, created_at
           FROM reports WHERE project_id = ?
           ORDER BY created_at DESC""",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_audit_history():
    conn = get_conn()
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


def get_full_report(report_id):
    conn = get_conn()
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
    parsed = parse_analysis(d.get("analysis_json", "") or "")

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
