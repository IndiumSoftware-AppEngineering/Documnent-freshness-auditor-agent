
from typing import Any ,Dict
from crewai.tools import tool


@tool("freshness_scorer")
def freshness_scorer(
    file_path: str,
    metrics: Dict[str, Any],
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Compute weighted freshness score, severity, and confidence level based on raw metrics.
    Ensures 100% deterministic results by moving math into the tool.
    
    Args:
        file_path: Path to the file being analyzed
        metrics: Dictionary containing:
            - doc_type: 'inline_docstring', 'readme', 'api_spec', etc.
            - total_functions, functions_with_docstrings
            - total_params, documented_params
            - critical_issues, major_issues, minor_issues
            - last_updated_iso: (optional) ISO date string
    """
    doc_type = metrics.get("doc_type", "unknown")
    t_func = float(metrics.get("total_functions", 0))
    f_doc = float(metrics.get("functions_with_docstrings", 0))
    t_param = float(metrics.get("total_params", 0))
    d_param = float(metrics.get("documented_params", 0))
    crit = float(metrics.get("critical_issues", 0))
    maj = float(metrics.get("major_issues", 0))
    min_i = float(metrics.get("minor_issues", 0))
    
    # 1. Structural Match
    if t_param > 0:
        structural_match = d_param / t_param
    elif t_func > 0:
        structural_match = f_doc / t_func
    else:
        structural_match = 1.0
        
    # 2. Semantic Accuracy
    semantic_accuracy = max(0.0, 1.0 - (crit * 0.4 + maj * 0.2 + min_i * 0.05))
    
    # 3. Completeness
    completeness = f_doc / t_func if t_func > 0 else 1.0
    
    # 4. Recency (Default to 1.0 if unknown)
    recency_factor = 1.0
    last_upd = metrics.get("last_updated_iso")
    if last_upd:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(last_upd.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            days = (now - dt).days
            if days < 30: recency_factor = 1.0
            elif days < 90: recency_factor = 0.7
            elif days < 365: recency_factor = 0.3
            else: recency_factor = 0.0
        except Exception:
            pass

    # 5. Confidence Variables
    total_issues = crit + maj + min_i
    mismatch_clarity = max(0.0, 1.0 - (total_issues * 0.1))
    code_complexity = 0.5 # Default moderate
    doc_structure_quality = 1.0 # Default
    
    # Weighted Score calculation
    # match (40%), accuracy (30%), recency (20%), completeness (10%)
    freshness_score = (
        structural_match * 0.40 +
        semantic_accuracy * 0.30 +
        recency_factor * 0.20 +
        completeness * 0.10
    ) * 100
    
    if freshness_score < 40:
        severity = "critical"
    elif freshness_score < 70:
        severity = "major"
    else:
        severity = "minor"
    
    confidence = (mismatch_clarity * 0.50 + (1.0 - code_complexity) * 0.30 + doc_structure_quality * 0.20)
    
    return {
        "file": file_path,
        "doc_type": doc_type,
        "freshness_score": round(freshness_score, 1),
        "severity": severity,
        "confidence": round(confidence, 2),
        "components": {
            "structural_match": round(structural_match, 2),
            "semantic_accuracy": round(semantic_accuracy, 2),
            "recency_factor": round(recency_factor, 2),
            "completeness": round(completeness, 2)
        }
    }