"""Lease sizing for bounded blocking operations."""

from __future__ import annotations

import math


def blocking_operation_lease_seconds(
    *,
    timeout_seconds: object,
    base_extend_seconds: int,
) -> int:
    """Return enough lease time for one bounded blocking operation."""
    if base_extend_seconds < 1:
        raise ValueError("base_extend_seconds must be positive.")

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        return base_extend_seconds

    return max(
        base_extend_seconds,
        math.ceil(timeout_seconds) + base_extend_seconds,
    )
