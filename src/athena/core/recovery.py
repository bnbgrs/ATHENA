"""Minimal read-only ATHENA recovery core.

This module deliberately depends only on storage-level recovery inspection.
It does not import or start the normal application, models, news, plugins,
background jobs, or Protected Content services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from athena.storage.recovery import (
    DatabaseRecoveryRequiredError,
    inspect_database_read_only,
)


class RecoveryDatabaseStatus(str, Enum):
    """Trust classification of the canonical database in recovery mode."""

    MISSING = "missing"
    HEALTHY = "healthy"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Structured, payload-free read-only recovery diagnosis."""

    mode: str
    database_path: Path
    database_status: RecoveryDatabaseStatus
    canonical_integrity_confirmed: bool
    normal_writes_allowed: bool
    protected_scopes_locked: bool
    optional_components_started: bool
    application_id: int | None
    schema_version: int | None
    wal_present: bool
    shm_present: bool
    detail: str | None


class ReadOnlyRecoveryCore:
    """Inspect canonical state without starting normal ATHENA services."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().absolute()

    def inspect(self) -> RecoveryReport:
        """Return one read-only diagnosis without repairing or mutating state."""

        try:
            preflight = inspect_database_read_only(
                self.database_path
            )
        except DatabaseRecoveryRequiredError as exc:
            return RecoveryReport(
                mode="read_only_safe_mode",
                database_path=self.database_path,
                database_status=(
                    RecoveryDatabaseStatus.RECOVERY_REQUIRED
                ),
                canonical_integrity_confirmed=False,
                normal_writes_allowed=False,
                protected_scopes_locked=True,
                optional_components_started=False,
                application_id=None,
                schema_version=None,
                wal_present=os.path.lexists(
                    self.database_path.with_name(
                        f"{self.database_path.name}-wal"
                    )
                ),
                shm_present=os.path.lexists(
                    self.database_path.with_name(
                        f"{self.database_path.name}-shm"
                    )
                ),
                detail=str(exc),
            )

        if not preflight.exists:
            return RecoveryReport(
                mode="read_only_safe_mode",
                database_path=preflight.path,
                database_status=RecoveryDatabaseStatus.MISSING,
                canonical_integrity_confirmed=False,
                normal_writes_allowed=False,
                protected_scopes_locked=True,
                optional_components_started=False,
                application_id=None,
                schema_version=None,
                wal_present=preflight.wal_present,
                shm_present=preflight.shm_present,
                detail="Canonical ATHENA database is absent.",
            )

        return RecoveryReport(
            mode="read_only_safe_mode",
            database_path=preflight.path,
            database_status=RecoveryDatabaseStatus.HEALTHY,
            canonical_integrity_confirmed=True,
            normal_writes_allowed=False,
            protected_scopes_locked=True,
            optional_components_started=False,
            application_id=preflight.application_id,
            schema_version=preflight.schema_version,
            wal_present=preflight.wal_present,
            shm_present=preflight.shm_present,
            detail=None,
        )
