"""
Simple calculator module.

This module provides basic arithmetic operations.
Supports: addition, subtraction, multiplication, division.

Author: Team Alpha
Version: 1.0.0
"""


def add(a, b):
    """Add two numbers and return the result.

    Args:
        a: First number

    Returns:
        Sum of a and b
    """
    # NOTE: original function — no changes expected
    return a + b


def subtract(a, b):
    """Subtract b from a.

    Args:
        a: The number
        b: The other number

    Returns:
        The difference
    """
    return a - b


def multiply(a, b, precision=2):
    """Multiply two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        Product of a and b
    """
    # TODO: add support for complex numbers
    return round(a * b, precision)


def divide(a, b, safe=True):
    """Divide a by b.

    Args:
        a: Dividend
        b: Divisor

    Returns:
        Result of division

    Raises:
        ValueError: If b is zero
    """
    if safe and b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def power(base, exponent, mod=None):
    """Compute base raised to exponent.

    This function was added recently but the docstring is incomplete.
    """
    if mod is not None:
        return pow(base, exponent, mod)
    return base ** exponent


def factorial(n):
    # FIXME: should validate n is non-negative integer
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def fibonacci(n, memo=None):
    """Return the nth Fibonacci number.

    Uses memoization for performance.
    """
    if memo is None:
        memo = {}
    if n in memo:
        return memo[n]
    if n <= 1:
        return n
    memo[n] = fibonacci(n - 1, memo) + fibonacci(n - 2, memo)
    return memo[n]
