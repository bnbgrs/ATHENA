"""Pure operational-error sanitization support for schema evolution."""

from __future__ import annotations

import json
import re

_PERSISTED_ERROR_CODE_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_.-]{0,127}"
    r"(?::[A-Za-z_][A-Za-z0-9_.-]{0,127})*\Z",
    re.ASCII,
)


_PERSISTED_ERROR_SCALAR_FIELDS = (
    ("processing_runs", "error_detail"),
    ("archive_replication_outbox", "last_error_detail"),
    ("backup_snapshots", "failure_detail"),
    ("news_discoveries", "failure_reason"),
    ("news_source_run_failures", "detail"),
    ("news_source_states", "last_error"),
    ("jobs", "blocked_reason"),
)


def _sanitize_persisted_error_value(
    value: str,
) -> str | None:
    normalized = value.strip()

    if not normalized:
        return None

    if _PERSISTED_ERROR_CODE_RE.fullmatch(normalized) is not None:
        return normalized

    prefix, separator, _suffix = normalized.partition(":")

    if separator:
        normalized_prefix = prefix.strip()

        if (
            _PERSISTED_ERROR_CODE_RE.fullmatch(
                normalized_prefix
            )
            is not None
        ):
            return normalized_prefix

    return "OperationalError"


_PERSISTED_ERROR_CHECKPOINT_JOB_TYPES = frozenset(
    {
        "research.exhaustive",
        "source.analyze",
        "source.extract",
    }
)


def _sanitize_checkpoint_error_payload(
    *,
    job_type: str,
    value: object,
) -> tuple[object, bool]:
    """Sanitize only historically known operational checkpoint fields."""
    if (
        job_type
        not in _PERSISTED_ERROR_CHECKPOINT_JOB_TYPES
        or not isinstance(value, dict)
    ):
        return value, False

    sanitized = dict(value)

    if job_type == "source.extract":
        raw_error = value.get("error")

        if not isinstance(raw_error, str):
            return value, False

        replacement = _sanitize_persisted_error_value(
            raw_error
        )

        if replacement == raw_error:
            return value, False

        sanitized["error"] = replacement

        return sanitized, True

    raw_reason = value.get("reason")
    raw_detail = value.get("detail")

    if (
        not isinstance(raw_reason, str)
        or not isinstance(raw_detail, str)
    ):
        return value, False

    replacement = _sanitize_persisted_error_value(
        raw_detail
    )

    if replacement == raw_detail:
        return value, False

    sanitized["detail"] = replacement

    return sanitized, True


def _canonical_migration_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


# Preserve the historical private function import/pickle path.
_sanitize_persisted_error_value.__module__ = "athena.storage.schema"
_sanitize_checkpoint_error_payload.__module__ = "athena.storage.schema"
_canonical_migration_json.__module__ = "athena.storage.schema"
