"""
Utility helpers for the calculator project.

Contains formatting, validation, and logging utilities.
"""

import logging

# HACK: global logger — should use dependency injection
logger = logging.getLogger("calculator")


def format_result(value, precision=2):
    """Format a numeric result for display.

    Args:
        value: The numeric value

    Returns:
        Formatted string
    """
    # TODO: support locale-aware formatting
    return f"{value:.{precision}f}"


def validate_number(value):
    """Check if a value is a valid number.

    Args:
        value: The value to validate
        strict: Whether to reject infinity — PARAM REMOVED but still documented

    Returns:
        True if valid number

    Raises:
        TypeError: If value is not numeric
    """
    if not isinstance(value, (int, float)):
        raise TypeError(f"Expected number, got {type(value).__name__}")
    return True


def clamp(value, min_val=0, max_val=100):
    """Clamp value to [min_val, max_val] range."""
    return max(min_val, min(max_val, value))


def percentage(part, whole):
    """Calculate percentage.

    Args:
        part: The part value
        whole: The whole value
        decimals: Number of decimal places — PARAM REMOVED

    Returns:
        Percentage as float
    """
    if whole == 0:
        return 0.0
    return (part / whole) * 100


# DEPRECATED: use format_result instead
def old_format(value):
    return str(round(value, 2))
