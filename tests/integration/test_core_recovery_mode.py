from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import ApplicationState, AthenaApplication
from athena.core.recovery import (
    ReadOnlyRecoveryCore,
    RecoveryDatabaseStatus,
)
from athena.observability.health import HealthStatus
from athena.storage.database import SQLiteDatabase
from athena.storage.recovery import DatabaseRecoveryRequiredError
from athena.storage.schema import ATHENA_APPLICATION_ID, SCHEMA_VERSION


def _filesystem_snapshot(
    root: Path,
    *,
    ignore_sqlite_coordination_sidecars: bool = False,
) -> tuple[tuple[str, str, int | None, bytes | None], ...]:
    if not root.exists():
        return ()

    snapshot: list[
        tuple[str, str, int | None, bytes | None]
    ] = []

    for path in sorted(
        root.rglob("*"),
        key=lambda item: item.as_posix(),
    ):
        relative = path.relative_to(root).as_posix()

        if (
            ignore_sqlite_coordination_sidecars
            and (
                relative.endswith(".db-shm")
                or relative.endswith(".db-wal")
            )
        ):
            continue

        if path.is_file():
            stat = path.stat()
            snapshot.append(
                (
                    relative,
                    "file",
                    stat.st_mtime_ns,
                    path.read_bytes(),
                )
            )
        elif path.is_dir():
            snapshot.append(
                (
                    relative,
                    "directory",
                    None,
                    None,
                )
            )
        else:
            snapshot.append(
                (
                    relative,
                    "other",
                    None,
                    None,
                )
            )

    return tuple(snapshot)


def test_corrupt_database_enters_recovery_before_runtime_layout_writes(
    tmp_path: Path,
) -> None:
    settings = AthenaSettings(local_root=tmp_path)
    app = AthenaApplication(settings=settings)

    app.paths.state_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    corrupt = b"definitely-not-a-sqlite-database"
    app.paths.database_path.write_bytes(corrupt)

    assert not app.paths.spool_root.exists()
    assert not app.paths.derived_root.exists()
    assert not app.paths.log_root.exists()
    assert not app.paths.temp_root.exists()

    with pytest.raises(DatabaseRecoveryRequiredError):
        app.start()

    assert app.state is ApplicationState.RECOVERY_REQUIRED

    health = app.health.snapshot()
    assert health.status is HealthStatus.RECOVERY_REQUIRED
    assert health.detail

    assert app.paths.database_path.read_bytes() == corrupt
    assert not app.paths.spool_root.exists()
    assert not app.paths.derived_root.exists()
    assert not app.paths.log_root.exists()
    assert not app.paths.temp_root.exists()
    assert app.services.started_service_names == ()

    app.stop()

    assert app.state is ApplicationState.STOPPED
    assert app.health.snapshot().status is HealthStatus.STOPPED


def test_recovery_core_reports_corruption_without_mutating_filesystem(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)

    database_path = state_root / "athena.db"
    database_path.write_bytes(
        b"corrupt-canonical-state"
    )

    before = _filesystem_snapshot(tmp_path)

    report = ReadOnlyRecoveryCore(
        database_path
    ).inspect()

    after = _filesystem_snapshot(tmp_path)

    assert report.mode == "read_only_safe_mode"
    assert (
        report.database_status
        is RecoveryDatabaseStatus.RECOVERY_REQUIRED
    )
    assert report.canonical_integrity_confirmed is False
    assert report.normal_writes_allowed is False
    assert report.protected_scopes_locked is True
    assert report.optional_components_started is False
    assert report.application_id is None
    assert report.schema_version is None
    assert report.detail
    assert after == before


def test_recovery_core_reports_healthy_database_without_authoritative_mutation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)

    database_path = state_root / "athena.db"
    wal_path = state_root / "athena.db-wal"
    shm_path = state_root / "athena.db-shm"

    database = SQLiteDatabase(database_path)
    database.start()
    database.stop()

    database_bytes_before = database_path.read_bytes()
    wal_bytes_before = (
        wal_path.read_bytes()
        if wal_path.exists()
        else None
    )

    before = _filesystem_snapshot(
        tmp_path,
        ignore_sqlite_coordination_sidecars=True,
    )

    report = ReadOnlyRecoveryCore(
        database_path
    ).inspect()

    after = _filesystem_snapshot(
        tmp_path,
        ignore_sqlite_coordination_sidecars=True,
    )

    assert report.mode == "read_only_safe_mode"
    assert (
        report.database_status
        is RecoveryDatabaseStatus.HEALTHY
    )
    assert report.canonical_integrity_confirmed is True
    assert report.normal_writes_allowed is False
    assert report.protected_scopes_locked is True
    assert report.optional_components_started is False
    assert report.application_id == ATHENA_APPLICATION_ID
    assert report.schema_version == SCHEMA_VERSION
    assert report.detail is None

    # A mode=ro connection must never alter canonical database bytes.
    assert database_path.read_bytes() == database_bytes_before

    # Existing WAL content is authoritative committed state and must remain
    # byte-identical. On a clean WAL database SQLite may create a new empty
    # -wal plus a transient -shm WAL-index even for a read-only connection.
    if wal_bytes_before is not None:
        assert wal_path.read_bytes() == wal_bytes_before
    elif wal_path.exists():
        assert wal_path.read_bytes() == b""

    # -shm is SQLite's transient coordination/WAL-index file. Its existence
    # or contents are deliberately not treated as canonical ATHENA state.
    if shm_path.exists():
        assert shm_path.is_file()

    # No other file or directory may be created, deleted, or modified.
    assert after == before


def test_recovery_core_does_not_create_missing_database_or_layout(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "never-created"
        / "state"
        / "athena.db"
    )

    assert not tmp_path.joinpath(
        "never-created"
    ).exists()

    report = ReadOnlyRecoveryCore(
        database_path
    ).inspect()

    assert (
        report.database_status
        is RecoveryDatabaseStatus.MISSING
    )
    assert report.canonical_integrity_confirmed is False
    assert report.normal_writes_allowed is False
    assert report.protected_scopes_locked is True
    assert report.optional_components_started is False
    assert not tmp_path.joinpath(
        "never-created"
    ).exists()


def test_recovery_core_import_is_independent_of_normal_optional_runtime(
) -> None:
    code = """
import sys

from athena.core.recovery import ReadOnlyRecoveryCore

del ReadOnlyRecoveryCore

for forbidden in (
    "athena.core.application",
    "athena.model.adapters.lm_studio",
    "athena.news.service",
    "athena.security.service",
):
    if forbidden in sys.modules:
        raise SystemExit(
            f"recovery core imported forbidden runtime module: {forbidden}"
        )
"""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        result.stdout + result.stderr
    )
