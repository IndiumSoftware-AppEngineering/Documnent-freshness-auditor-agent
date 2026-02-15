
from typing import Any ,Dict
from crewai.tools import tool


@tool("freshness_scorer")
def freshness_scorer(
    file_path: str,
    doc_type: str,
    structural_match: float,
    semantic_accuracy: float,
    recency_factor: float,
    completeness: float,
    mismatch_clarity: float,
    code_complexity: float,
    doc_structure_quality: float,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Compute weighted freshness score , severity and confidence level based on multiple factors.
    
    Args:
        file_path: Path to the file being analyzed
 '       doc_type: Type of documentation (e.g.,'docstring','openapi', 'comment', 'readme', 'srs','yaml')
        structural_match: 0-1, alignment of params/returns/endpoints
        semantic_accuracy: 0-1, description vs behavior match
        recency_factor: 0-1, time gap impact
        completeness: 0-1, documentation coverage
        mismatch_clarity: 0-1, how clear the mismatches are
        code_complexity: 0-1, complexity of code (inverted - simpler = higher)
        doc_structure_quality: 0-1, quality of documentation structure
    
    Returns:
        Dictionary with file info ,freshness score, severity, confidence, and breakdown
    
    Raises:
        ValueError: If any numeric parameter is outside 0-1 range   
    """
    
    freshness_score = (
        structural_match * 0.40 +
        semantic_accuracy * 0.30 +
        recency_factor * 0.20 +
        completeness * 0.10
    ) * 100
    
   
    if freshness_score < 50:
        severity = "critical"
    elif freshness_score < 75:
        severity = "major"
    else:
        severity = "minor"
    
    
    confidence = (
        mismatch_clarity * 0.50 +
        (1 - code_complexity) * 0.30 +
        doc_structure_quality * 0.20
    )
    
    return {
        "file_path":file_path,
        "doc_type":doc_type,
        "freshness_score": round(freshness_score, 2),
        "severity": severity,
        "confidence": round(confidence, 3),
        "score_breakdown": {
            "structural_match": structural_match,
            "semantic_accuracy": semantic_accuracy,
            "recency_factor": recency_factor,
            "completeness": completeness
        },
        "confidence_factors": {
            "mismatch_clarity": mismatch_clarity,
            "code_complexity": code_complexity,
            "doc_structure_quality": doc_structure_quality
        }
    }