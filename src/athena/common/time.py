"""Time primitives used by persistent ATHENA state."""

from __future__ import annotations

import time


def utc_now_us() -> int:
    """Return Unix epoch time in integer microseconds."""
    return time.time_ns() // 1_000
