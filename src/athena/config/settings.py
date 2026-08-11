"""Bootstrap configuration for ATHENA."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when ATHENA bootstrap configuration is invalid."""


_VALID_LOG_LEVELS = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
)


def _default_local_root() -> Path:
    """Return a user-local default root for ATHENA runtime data.

    On Windows this resolves below LOCALAPPDATA. The fallback is primarily
    useful for development and non-Windows test environments.
    """
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ATHENA"

    return Path.home() / ".local" / "share" / "athena"


def _parse_absolute_path(
    raw_value: str | None,
    *,
    setting_name: str,
    default: Path | None = None,
) -> Path | None:
    value = raw_value.strip() if raw_value is not None else ""

    if not value:
        return default

    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(
            f"{setting_name} must be an absolute path, got {value!r}."
        )

    return path


@dataclass(frozen=True, slots=True)
class AthenaSettings:
    """Settings safe to construct before persistent storage exists."""

    log_level: str = "INFO"
    local_root: Path = Path(".")
    archive_root: Path | None = None
    backup_root: Path | None = None
    projection_root: Path | None = None

    def __post_init__(self) -> None:
        normalized = self.log_level.strip().upper()
        if normalized not in _VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ConfigurationError(
                f"Invalid ATHENA log level {self.log_level!r}. "
                f"Allowed values: {allowed}."
            )
        object.__setattr__(self, "log_level", normalized)

        local_root = self.local_root.expanduser()
        if not local_root.is_absolute():
            raise ConfigurationError(
                f"ATHENA local_root must be absolute, got {str(local_root)!r}."
            )
        object.__setattr__(self, "local_root", local_root)

        for field_name in ("archive_root", "backup_root", "projection_root"):
            value = getattr(self, field_name)
            if value is None:
                continue
            normalized_path = value.expanduser()
            if not normalized_path.is_absolute():
                raise ConfigurationError(
                    f"ATHENA {field_name} must be absolute, "
                    f"got {str(normalized_path)!r}."
                )
            object.__setattr__(self, field_name, normalized_path)

    @property
    def numeric_log_level(self) -> int:
        return logging.getLevelNamesMapping()[self.log_level]

    @classmethod
    def from_environment(cls) -> "AthenaSettings":
        """Create bootstrap settings from process environment.

        Local operational storage gets a safe user-local default. Canonical
        archive, backup, and projection roots remain optional until explicitly
        configured; Phase 0 must not silently invent long-term storage.
        """
        local_root = _parse_absolute_path(
            os.getenv("ATHENA_LOCAL_ROOT"),
            setting_name="ATHENA_LOCAL_ROOT",
            default=_default_local_root(),
        )

        assert local_root is not None

        return cls(
            log_level=os.getenv("ATHENA_LOG_LEVEL", "INFO"),
            local_root=local_root,
            archive_root=_parse_absolute_path(
                os.getenv("ATHENA_ARCHIVE_ROOT"),
                setting_name="ATHENA_ARCHIVE_ROOT",
            ),
            backup_root=_parse_absolute_path(
                os.getenv("ATHENA_BACKUP_ROOT"),
                setting_name="ATHENA_BACKUP_ROOT",
            ),
            projection_root=_parse_absolute_path(
                os.getenv("ATHENA_PROJECTION_ROOT"),
                setting_name="ATHENA_PROJECTION_ROOT",
            ),
        )
