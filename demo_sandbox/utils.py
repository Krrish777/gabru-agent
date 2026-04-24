"""String utilities for the Gabru-Agent pipeline dry run."""

from __future__ import annotations


def reverse_str(s: str) -> str:
    """Return ``s`` reversed.

    Args:
        s: The string to reverse.

    Returns:
        A new string containing the characters of ``s`` in reverse order.
    """
    return s[::-1]
