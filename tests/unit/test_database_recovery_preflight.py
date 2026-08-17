from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import athena.storage.database as database_module
from athena.storage.database import SQLiteDatabase
from athena.storage.recovery import (
    DatabaseRecoveryRequiredError,
    inspect_database_read_only,
)
from athena.storage.schema import ATHENA_APPLICATION_ID, SCHEMA_VERSION


def test_preflight_allows_missing_database_without_sidecars(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"

    report = inspect_database_read_only(path)

    assert report.path == path.absolute()
    assert report.exists is False
    assert report.application_id is None
    assert report.schema_version is None
    assert report.wal_present is False
    assert report.shm_present is False
    assert not path.exists()


def test_preflight_rejects_orphaned_sqlite_sidecar(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"
    wal_path = tmp_path / "athena.db-wal"
    wal_path.write_bytes(b"orphaned-wal")

    with pytest.raises(
        DatabaseRecoveryRequiredError,
        match="sidecar exists without",
    ):
        inspect_database_read_only(path)

    assert not path.exists()
    assert wal_path.read_bytes() == b"orphaned-wal"


def test_preflight_accepts_healthy_database_without_changing_db_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"
    database = SQLiteDatabase(path)
    database.start()
    database.stop()

    before = path.read_bytes()

    report = inspect_database_read_only(path)

    assert report.exists is True
    assert report.application_id == ATHENA_APPLICATION_ID
    assert report.schema_version == SCHEMA_VERSION
    assert path.read_bytes() == before


def test_preflight_reads_committed_wal_after_unclean_process_exit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"
    database = SQLiteDatabase(path)
    database.start()
    database.stop()

    code = """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1], autocommit=True)
connection.execute("PRAGMA wal_autocheckpoint = 0")
connection.execute(
    "UPDATE schema_metadata "
    "SET created_at_us = created_at_us + 1 "
    "WHERE singleton_id = 1"
)
os._exit(0)
"""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    wal_path = tmp_path / "athena.db-wal"
    assert wal_path.is_file()

    report = inspect_database_read_only(path)

    assert report.exists is True
    assert report.application_id == ATHENA_APPLICATION_ID
    assert report.schema_version == SCHEMA_VERSION
    assert report.wal_present is True

    reopened = SQLiteDatabase(path)
    reopened.start()
    reopened.stop()


def test_database_start_rejects_corrupt_existing_file_without_changing_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"
    corrupt = b"not-a-valid-sqlite-database"
    path.write_bytes(corrupt)

    database = SQLiteDatabase(path)

    with pytest.raises(
        DatabaseRecoveryRequiredError
    ):
        database.start()

    assert path.read_bytes() == corrupt


def test_database_start_fails_before_schema_initialization_on_foreign_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "athena.db"

    foreign = sqlite3.connect(path)
    foreign.execute(
        "CREATE TABLE foreign_data(value TEXT)"
    )
    foreign.commit()
    foreign.close()

    initialize_called = False

    def forbidden_initialize_schema(
        connection: sqlite3.Connection,
        *,
        created_at_us: int,
    ) -> None:
        nonlocal initialize_called

        del connection, created_at_us
        initialize_called = True

        raise AssertionError(
            "initialize_schema must not run before preflight passes"
        )

    monkeypatch.setattr(
        database_module,
        "initialize_schema",
        forbidden_initialize_schema,
    )

    database = database_module.SQLiteDatabase(
        path
    )

    with pytest.raises(
        DatabaseRecoveryRequiredError,
        match="application_id",
    ):
        database.start()

    assert initialize_called is False


def test_preflight_rejects_database_newer_than_running_build(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"

    database = SQLiteDatabase(path)
    database.start()
    database.stop()

    connection = sqlite3.connect(
        path,
        autocommit=True,
    )

    try:
        connection.execute(
            f"PRAGMA user_version = {SCHEMA_VERSION + 1}"
        )
    finally:
        connection.close()

    with pytest.raises(
        DatabaseRecoveryRequiredError,
        match="newer than supported",
    ):
        inspect_database_read_only(path)
