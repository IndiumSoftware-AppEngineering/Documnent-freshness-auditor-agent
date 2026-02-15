"""Evaluation configuration and constants"""

EVAL_CONFIG = {
    "judge_model": "claude-3-5-sonnet-20241022",
    
    "evaluators": [
        "correctness",
        "hallucination",
        "confidence_calibration",
        "severity_accuracy",
        "freshness_score_validity"
    ],
    
    "thresholds": {
        "correctness_min": 0.7,
        "hallucination_max": 0.15,
        "confidence_calibration_min": 0.6,
        "severity_accuracy_min": 0.75,
        "freshness_score_validity_min": 0.8,
        "overall_min": 0.7
    },
    
    "scoring": {
        "correctness_accuracy_weight": 0.6,
        "correctness_completeness_weight": 0.4,
    }
}

# Expected score ranges for each test case
EXPECTED_SCORE_RANGES = {
    "test_case_1": {"min": 0.40, "max": 0.60},
    "test_case_2": {"min": 0.50, "max": 0.70},
    "test_case_3": {"min": 0.60, "max": 0.80},
    "test_case_4": {"min": 0.70, "max": 0.85},
    "test_case_5": {"min": 0.80, "max": 0.95},
}