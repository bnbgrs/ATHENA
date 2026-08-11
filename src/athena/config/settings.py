"""Minimal Phase-0 configuration model."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AthenaSettings:
    """Bootstrap settings that are safe to construct before storage exists."""

    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> "AthenaSettings":
        """Create settings from process environment.

        Phase 0 intentionally supports only non-sensitive bootstrap settings.
        Persistent user configuration arrives in a later vertical slice.
        """
        log_level = os.getenv("ATHENA_LOG_LEVEL", "INFO").strip().upper() or "INFO"
        return cls(log_level=log_level)
