"""Bootstrap configuration for ATHENA."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when ATHENA bootstrap configuration is invalid."""


_VALID_LOG_LEVELS = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
)


def _default_local_root() -> Path:
    """Return the platform-appropriate local ATHENA runtime root.

    Windows uses LOCALAPPDATA. POSIX systems follow XDG_DATA_HOME when it is
    configured and otherwise use the conventional ~/.local/share location.
    """
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "ATHENA"

        # LOCALAPPDATA should normally exist on supported Windows systems,
        # but this deterministic fallback is safer than using the repository.
        return Path.home() / "AppData" / "Local" / "ATHENA"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        xdg_root = Path(xdg_data_home).expanduser()
        if xdg_root.is_absolute():
            return xdg_root / "athena"

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


def _parse_positive_float(raw_value: str | None, *, setting_name: str, default: float) -> float:
    value = raw_value.strip() if raw_value is not None else ""
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{setting_name} must be a number greater than zero, got {value!r}."
        ) from exc
    if parsed <= 0:
        raise ConfigurationError(
            f"{setting_name} must be greater than zero, got {value!r}."
        )
    return parsed


@dataclass(frozen=True, slots=True)
class AthenaSettings:
    """Settings safe to construct before persistent storage exists."""

    log_level: str = "INFO"
    local_root: Path = Path(".")
    archive_root: Path | None = None
    backup_root: Path | None = None
    projection_root: Path | None = None
    lm_studio_base_url: str = "http://127.0.0.1:1234"
    model_request_timeout_seconds: float = 2.0
    model_generation_timeout_seconds: float = 300.0

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

        normalized_base_url = self.lm_studio_base_url.strip().rstrip("/")
        parsed = urlsplit(normalized_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError(
                "ATHENA LM Studio base URL must be an absolute HTTP(S) URL."
            )
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigurationError(
                "ATHENA v1 currently permits LM Studio only on the local machine."
            )
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ConfigurationError(
                "ATHENA LM Studio base URL must be a server root without credentials, "
                "path, query, or fragment."
            )
        object.__setattr__(self, "lm_studio_base_url", normalized_base_url)

        if self.model_request_timeout_seconds <= 0:
            raise ConfigurationError(
                "ATHENA model request timeout must be greater than zero."
            )
        if self.model_generation_timeout_seconds <= 0:
            raise ConfigurationError(
                "ATHENA model generation timeout must be greater than zero."
            )

    @property
    def numeric_log_level(self) -> int:
        return logging.getLevelNamesMapping()[self.log_level]

    @classmethod
    def from_environment(cls) -> "AthenaSettings":
        """Create bootstrap settings from process environment.

        Local operational storage gets a safe platform-local default. Canonical
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
            lm_studio_base_url=os.getenv(
                "ATHENA_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"
            ),
            model_request_timeout_seconds=_parse_positive_float(
                os.getenv("ATHENA_MODEL_REQUEST_TIMEOUT_SECONDS"),
                setting_name="ATHENA_MODEL_REQUEST_TIMEOUT_SECONDS",
                default=2.0,
            ),
            model_generation_timeout_seconds=_parse_positive_float(
                os.getenv("ATHENA_MODEL_GENERATION_TIMEOUT_SECONDS"),
                setting_name="ATHENA_MODEL_GENERATION_TIMEOUT_SECONDS",
                default=300.0,
            ),
        )
