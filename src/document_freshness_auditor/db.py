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


def _extract_issue_text(iss):
    """Extract the issue description from a dict, trying many possible key names."""
    if not isinstance(iss, dict):
        return str(iss) if iss else ""
    for key in (
        "issue_name", "description", "issue", "problem", "finding", "title",
        "message", "detail", "text", "name", "summary", "msg",
    ):
        val = iss.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    # fallback: join all string values in the dict
    parts = [str(v) for v in iss.values() if isinstance(v, str) and v.strip()]
    return "; ".join(parts) if parts else str(iss)


def _extract_field(iss, *keys):
    """Return the first non-empty string value for any of the given keys."""
    if not isinstance(iss, dict):
        return ""
    for key in keys:
        val = iss.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _to_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _get_file_path(item):
    """Extract file path from a dict trying multiple key names."""
    for key in ("file_path", "file", "path"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _build_recommendations(issues):
    """Build concise, actionable recommendation strings from issue dicts."""
    recs = []
    for iss in issues:
        if not isinstance(iss, dict):
            continue
        issue_text = iss.get("issue", "").strip()
        actual = iss.get("actual", "").strip()
        location = iss.get("location", "").strip()
        priority = iss.get("fix_priority", "").strip()
        severity = iss.get("severity", "").strip()

        # Build: "Fix <issue> at <location>: update docs to match <actual>. (Priority: High)"
        if not issue_text:
            continue
        rec = f"Fix: {issue_text}"
        if location:
            rec += f" (at {location})"
        if actual:
            rec += f" — update docs to match: {actual}"
        tag_parts = []
        if priority:
            tag_parts.append(priority)
        if severity:
            tag_parts.append(severity)
        if tag_parts:
            rec += f"  [{', '.join(tag_parts)}]"
        recs.append(rec)
    return recs


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

    if not isinstance(data, list) or not data:
        return empty

    severity_rank = {"minor": 1, "major": 2, "critical": 3}

    # Detect shape: scorer output has freshness_score per item
    has_scored_shape = any(
        isinstance(item, dict)
        and _get_file_path(item)
        and "freshness_score" in item
        for item in data
    )

    if has_scored_shape:
        # --- Mode A: scorer JSON (per-file freshness objects) ---
        grouped = {}

        for item in data:
            if not isinstance(item, dict):
                continue
            file_path = _get_file_path(item)
            if not file_path:
                continue

            sev = str(item.get("severity", "minor")).lower()
            if sev not in severity_rank:
                sev = "minor"

            issues = item.get("issues", []) or []
            if not isinstance(issues, list):
                issues = []

            numbered = []
            for i, iss in enumerate(issues, 1):
                if isinstance(iss, str):
                    iss = {"description": iss}
                if not isinstance(iss, dict):
                    continue
                numbered.append({
                    "number": i,
                    "issue": _extract_issue_text(iss),
                    "location": _extract_field(iss, "location", "line"),
                    "impact": _extract_field(iss, "impact", "why_it_matters", "reason"),
                    "expected": _extract_field(iss, "expected", "what_docs_say", "documented"),
                    "actual": _extract_field(iss, "actual", "what_code_does", "reality"),
                    "fix_priority": _extract_field(iss, "fix_priority", "priority"),
                    "severity": _extract_field(iss, "severity"),
                })

            recs = item.get("recommendations", []) or []
            if isinstance(recs, str):
                recs = [recs]
            elif not isinstance(recs, list):
                recs = []

            # Auto-generate recommendations from issues when none provided
            if not recs and numbered:
                recs = _build_recommendations(numbered)

            score = _to_float(item.get("freshness_score", 0.0))
            confidence = _to_float(item.get("confidence", 0.0))
            doc_type = _extract_field(item, "doc_type", "type", "category", "kind")
            breakdown = item.get("score_breakdown") or item.get("components") or {}
            if not isinstance(breakdown, dict):
                breakdown = {}

            entry = grouped.get(file_path)
            if not entry:
                grouped[file_path] = {
                    "file": file_path,
                    "doc_type": doc_type,
                    "severity": sev,
                    "freshness_score": score,
                    "confidence": confidence,
                    "score_breakdown": breakdown,
                    "issues": numbered,
                    "recommendations": recs,
                }
            else:
                if severity_rank.get(sev, 1) > severity_rank.get(entry["severity"], 1):
                    entry["severity"] = sev
                if score > 0:
                    entry["freshness_score"] = score
                if confidence > 0:
                    entry["confidence"] = confidence
                if doc_type and not entry.get("doc_type"):
                    entry["doc_type"] = doc_type
                if breakdown and not entry.get("score_breakdown"):
                    entry["score_breakdown"] = breakdown
                if numbered:
                    start = len(entry["issues"])
                    for idx, v in enumerate(numbered, start + 1):
                        v["number"] = idx
                        entry["issues"].append(v)
                if recs:
                    entry["recommendations"].extend(
                        [r for r in recs if r not in entry["recommendations"]]
                    )

        files = list(grouped.values())

    else:
        # --- Mode B: audit-finding list (one row per issue) ---
        from collections import defaultdict

        grouped = defaultdict(list)
        for item in data:
            if not isinstance(item, dict):
                continue
            file_path = _get_file_path(item)
            if not file_path:
                continue
            grouped[file_path].append(item)

        files = []
        for file_path, rows in grouped.items():
            by_sev = {"critical": 0, "major": 0, "minor": 0}
            doc_type = ""
            issue_rows = []

            for r in rows:
                sev = str(r.get("severity", "minor")).lower()
                if sev not in by_sev:
                    sev = "minor"
                by_sev[sev] += 1

                if not doc_type:
                    doc_type = _extract_field(r, "doc_type", "type", "category", "kind")

                location = str(r.get("location", "") or "")
                if not location:
                    line = r.get("line")
                    if isinstance(line, int):
                        location = f"Line {line}"

                issue_rows.append({
                    "number": 0,
                    "issue": _extract_issue_text(r),
                    "location": location,
                    "impact": _extract_field(r, "impact", "why_it_matters", "reason"),
                    "expected": _extract_field(r, "expected", "what_docs_say", "documented"),
                    "actual": _extract_field(r, "actual", "what_code_does", "reality"),
                    "fix_priority": _extract_field(r, "fix_priority", "priority"),
                    "severity": _extract_field(r, "severity"),
                })

            if by_sev["critical"] > 0:
                file_sev = "critical"
            elif by_sev["major"] > 0:
                file_sev = "major"
            else:
                file_sev = "minor"

            score = max(0.0, 100.0 - (
                by_sev["critical"] * 35.0
                + by_sev["major"] * 10.0
                + by_sev["minor"] * 4.0
            ))

            for i, it in enumerate(issue_rows, 1):
                it["number"] = i

            # Auto-generate recommendations from issues
            recs = _build_recommendations(issue_rows)

            files.append({
                "file": file_path,
                "doc_type": doc_type,
                "severity": file_sev,
                "freshness_score": round(score, 1),
                "confidence": 0.7,
                "score_breakdown": {},
                "issues": issue_rows,
                "recommendations": recs,
            })

    if not files:
        return empty

    crit = 0
    major = 0
    minor = 0
    score_total = 0.0

    for f in files:
        issue_count = len(f.get("issues", []))
        sev = f.get("severity", "minor")
        if sev == "critical":
            crit += issue_count
        elif sev == "major":
            major += issue_count
        else:
            minor += issue_count
        score_total += _to_float(f.get("freshness_score", 0.0))

    total = len(files)
    avg = round(score_total / total, 2) if total else 0.0

    if crit > 0 and crit >= major and crit >= minor:
        overall = "critical"
    elif major > 0 and major >= minor:
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

    if parsed["total_files"] == 0:
        health = "No structured issue data available"
    elif parsed["critical_issues"] > 0 and parsed["critical_issues"] >= parsed["major_issues"] and parsed["critical_issues"] >= parsed["minor_issues"]:
        health = "Critical – immediate remediation required"
    elif parsed["major_issues"] > 0 and parsed["major_issues"] >= parsed["minor_issues"]:
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
