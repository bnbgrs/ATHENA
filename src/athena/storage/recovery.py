"""Read-only startup inspection for ATHENA's canonical SQLite database."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from athena.storage.schema import (
    ATHENA_APPLICATION_ID,
    SCHEMA_VERSION,
    DatabaseCompatibilityError,
)


class DatabaseRecoveryRequiredError(DatabaseCompatibilityError):
    """Raised when normal writer startup must stop and recovery is required."""


@dataclass(frozen=True, slots=True)
class DatabasePreflightReport:
    """Read-only facts established before the live database is opened for writes."""

    path: Path
    exists: bool
    application_id: int | None
    schema_version: int | None
    wal_present: bool
    shm_present: bool


def inspect_database_read_only(path: Path) -> DatabasePreflightReport:
    """Validate an existing ATHENA database before any normal writer connection."""

    requested = path.expanduser().absolute()
    wal_path = requested.with_name(f"{requested.name}-wal")
    shm_path = requested.with_name(f"{requested.name}-shm")

    if requested.is_symlink():
        raise DatabaseRecoveryRequiredError(
            "ATHENA database path is a symbolic link; recovery review is required."
        )

    if not requested.exists():
        orphaned = tuple(
            sidecar
            for sidecar in (wal_path, shm_path)
            if os.path.lexists(sidecar)
        )

        if orphaned:
            raise DatabaseRecoveryRequiredError(
                "SQLite WAL/SHM sidecar exists without the primary ATHENA database."
            )

        return DatabasePreflightReport(
            path=requested,
            exists=False,
            application_id=None,
            schema_version=None,
            wal_present=False,
            shm_present=False,
        )

    if not requested.is_file():
        raise DatabaseRecoveryRequiredError(
            "ATHENA database path is not a regular file."
        )

    for sidecar in (wal_path, shm_path):
        if sidecar.is_symlink():
            raise DatabaseRecoveryRequiredError(
                "SQLite WAL/SHM sidecar is a symbolic link; recovery review is required."
            )

        if os.path.lexists(sidecar) and not sidecar.is_file():
            raise DatabaseRecoveryRequiredError(
                "SQLite WAL/SHM sidecar is not a regular file."
            )

    try:
        connection = sqlite3.connect(
            f"{requested.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=5.0,
            autocommit=True,
        )
    except sqlite3.Error as exc:
        raise DatabaseRecoveryRequiredError(
            "ATHENA database could not be opened read-only for startup preflight."
        ) from exc

    try:
        connection.execute("PRAGMA query_only = ON")

        application_id = int(
            connection.execute("PRAGMA application_id").fetchone()[0]
        )
        schema_version = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )

        if application_id == 0:
            raise DatabaseRecoveryRequiredError(
                "Refusing to adopt a non-empty SQLite database without "
                "ATHENA application_id."
            )

        if application_id != ATHENA_APPLICATION_ID:
            raise DatabaseRecoveryRequiredError(
                "Database application_id does not belong to ATHENA."
            )

        if schema_version < 1:
            raise DatabaseRecoveryRequiredError(
                "Existing ATHENA database has no supported schema version."
            )

        if schema_version > SCHEMA_VERSION:
            raise DatabaseRecoveryRequiredError(
                f"Database schema version {schema_version} is newer than supported "
                f"version {SCHEMA_VERSION}."
            )

        quick_check_rows = connection.execute(
            "PRAGMA quick_check"
        ).fetchall()

        quick_check = tuple(
            str(row[0])
            for row in quick_check_rows
        )

        if quick_check != ("ok",):
            detail = "; ".join(
                quick_check[:8]
            ) or "no result"

            raise DatabaseRecoveryRequiredError(
                f"SQLite startup quick_check failed: {detail}"
            )

    except DatabaseRecoveryRequiredError:
        raise
    except (
        sqlite3.Error,
        TypeError,
        ValueError,
        IndexError,
    ) as exc:
        raise DatabaseRecoveryRequiredError(
            "ATHENA database read-only startup preflight "
            "could not establish integrity."
        ) from exc
    finally:
        connection.close()

    return DatabasePreflightReport(
        path=requested,
        exists=True,
        application_id=application_id,
        schema_version=schema_version,
        wal_present=os.path.lexists(wal_path),
        shm_present=os.path.lexists(shm_path),
    )
