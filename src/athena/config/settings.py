"""Bootstrap configuration for ATHENA."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when ATHENA bootstrap configuration is invalid."""


_VALID_LOG_LEVELS = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
)


@dataclass(frozen=True, slots=True)
class AthenaSettings:
    """Settings that are safe to construct before persistent storage exists."""

    log_level: str = "INFO"

    def __post_init__(self) -> None:
        normalized = self.log_level.strip().upper()
        if normalized not in _VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ConfigurationError(
                f"Invalid ATHENA log level {self.log_level!r}. "
                f"Allowed values: {allowed}."
            )
        object.__setattr__(self, "log_level", normalized)

    @property
    def numeric_log_level(self) -> int:
        """Return the stdlib logging level represented by this configuration."""
        return logging.getLevelNamesMapping()[self.log_level]

    @classmethod
    def from_environment(cls) -> "AthenaSettings":
        """Create bootstrap settings from process environment.

        Phase 0 deliberately accepts only non-sensitive settings from the
        environment. Persistent user configuration is introduced later.
        """
        raw_log_level = os.getenv("ATHENA_LOG_LEVEL", "INFO")
        return cls(log_level=raw_log_level)
