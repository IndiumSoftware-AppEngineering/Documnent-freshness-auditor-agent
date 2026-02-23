from typing import Any, Dict, Optional
from crewai.tools import tool
from pydantic import BaseModel, Field
from datetime import datetime

class FreshnessMetrics(BaseModel):
    doc_type: str = Field(..., description="Type of document (e.g., 'inline_docstring', 'readme', 'api_spec', 'srs', 'documentation')")
    total_functions: int = Field(0, description="Total number of functions found in the file")
    functions_with_docstrings: int = Field(0, description="Number of functions that have docstrings")
    total_params: int = Field(0, description="Total number of parameters found in the file's functions")
    documented_params: int = Field(0, description="Number of parameters documented in docstrings")
    critical_issues: int = Field(0, description="Count of critical documentation issues")
    major_issues: int = Field(0, description="Count of major documentation issues")
    minor_issues: int = Field(0, description="Count of minor documentation issues")
    last_updated_iso: Optional[str] = Field(None, description="The ISO date string of the last modification (YYYY-MM-DD)")

@tool("freshness_scorer")
def freshness_scorer(
    file_path: str,
    metrics: FreshnessMetrics,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Compute a weighted documentation freshness score.
    Updated with dynamic confidence logic and proportional structural penalties.
    """
    # Handle dict input if passed via crewAI agent
    if isinstance(metrics, dict):
        metrics = FreshnessMetrics(**metrics)

    # 1. Evaluate Data Presence
    # Calculate "Data Points" to drive dynamic confidence
    structural_points = metrics.total_functions + metrics.total_params
    issue_points = metrics.critical_issues + metrics.major_issues + metrics.minor_issues
    has_data = structural_points > 0 or issue_points > 0

    # 2. Structural Match (S) - 40% Weight
    if metrics.total_functions > 0:
        fn_coverage = metrics.functions_with_docstrings / metrics.total_functions
        if metrics.total_params > 0:
            param_coverage = metrics.documented_params / metrics.total_params
            structural_match = (fn_coverage + param_coverage) / 2
        else:
            structural_match = fn_coverage
    else:
        # Penalize non-code docs (like README) if they contain semantic errors
        # If the doc is "wrong" about the structure, the structural match isn't 1.0
        structural_match = 0.5 if issue_points > 0 else 1.0

    # 3. Semantic Accuracy (A) - 30% Weight
    # Weighted penalty based on severity
    total_penalty = (metrics.critical_issues * 3.0) + (metrics.major_issues * 1.5) + (metrics.minor_issues * 0.5)
    semantic_accuracy = max(0.0, 100.0 - total_penalty) / 100.0

    # 4. Recency Factor (R) - 20% Weight
    recency_factor = 1.0
    if metrics.last_updated_iso and any(c.isdigit() for c in metrics.last_updated_iso):
        try:
            date_part = metrics.last_updated_iso.split('T')[0]
            last_update = datetime.fromisoformat(date_part)
            days_old = (datetime.now() - last_update).days
            # Linear decay over 300 days, floor at 0.5
            recency_factor = max(0.5, 1.0 - (days_old / 300))
        except (ValueError, TypeError):
            recency_factor = 0.8
    else:
        # Default to 0.5 if no date is provided and the file has no data
        recency_factor = 0.5 if not has_data else 0.8

    # 5. Completeness (C) - 10% Weight
    # Measures how "clean" the document is relative to found issues
    completeness = 1.0 if total_penalty == 0 else max(0.2, 1.0 - (total_penalty / 10))

    # 6. DYNAMIC CONFIDENCE CALCULATION
    # Instead of a hardcoded 0.85, we scale confidence based on total signals found
    # Base confidence is 0.3 (guessing). We add 0.05 per data point, capping at 0.95.
    if not has_data:
        confidence = 0.30
    else:
        # A file with 10 functions/params/issues hits the 0.80+ range
        dynamic_val = 0.40 + (min(11, structural_points + issue_points) * 0.05)
        confidence = min(0.95, dynamic_val)

    # 7. Final Score Summation
    freshness_score = (
        (structural_match * 0.40) +
        (semantic_accuracy * 0.30) +
        (recency_factor * 0.20) +
        (completeness * 0.10)
    ) * 100

    # Severity Labeling
    if freshness_score < 40:
        severity = "critical"
    elif freshness_score < 70:
        severity = "major"
    else:
        severity = "minor"

    return {
        "file": file_path,
        "doc_type": metrics.doc_type,
        "freshness_score": f"{freshness_score:.1f}",
        "severity": severity,
        "confidence": f"{confidence:.2f}",
        "components": {
            "structural_match": f"{structural_match:.2f}",
            "semantic_accuracy": f"{semantic_accuracy:.2f}",
            "recency_factor": f"{recency_factor:.2f}",
            "completeness": f"{completeness:.2f}"
        }
    }