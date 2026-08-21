from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import athena.storage.schema as schema_module
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    DELETION_LEDGER_MIGRATION_ID,
    DELETION_LEDGER_SCHEMA_VERSION,
    OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID,
    OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
    DatabaseCompatibilityError,
)


def _read_state(
    path: Path,
) -> tuple[int, tuple[object, ...]]:
    connection = sqlite3.connect(
        path.resolve().as_uri()
        + "?mode=ro",
        uri=True,
    )

    try:
        version = int(
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        )

        metadata = tuple(
            connection.execute(
                """
                SELECT
                    schema_version,
                    last_migration_id,
                    minimum_reader_version
                FROM schema_metadata
                WHERE singleton_id = 1
                """
            ).fetchone()
        )

        return version, metadata

    finally:
        connection.close()


def _create_latest(
    path: Path,
) -> None:
    database = SQLiteDatabase(
        path
    )

    database.start()
    database.stop()


def _set_version(
    path: Path,
    *,
    version: int,
    migration_id: str,
) -> None:
    connection = sqlite3.connect(
        path,
        autocommit=True,
    )

    try:
        if (
            version
            < schema_module.GROUNDED_RESPONSE_RECEIPT_SCHEMA_VERSION
        ):
            connection.execute(
                "DROP TABLE IF EXISTS "
                "grounded_response_receipts"
            )

        if (
            version
            < schema_module.PROTECTED_SOURCE_SEMANTIC_SCHEMA_VERSION
        ):
            connection.execute(
                "DROP TABLE IF EXISTS "
                "source_protection_representation_blobs"
            )
            connection.execute(
                "DROP TABLE IF EXISTS "
                "source_protected_semantic_payloads"
            )

        connection.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?,
                last_migration_id = ?,
                minimum_reader_version = ?
            WHERE singleton_id = 1
            """,
            (
                version,
                migration_id,
                version,
            ),
        )

        connection.execute(
            f"PRAGMA user_version = {version}"
        )

    finally:
        connection.close()


def _raw_canary_count(
    path: Path,
    canary: bytes,
) -> int:
    candidates = (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )

    total = 0

    for candidate in candidates:
        if candidate.is_file():
            total += candidate.read_bytes().count(
                canary
            )

    return total


def _inject_deleted_canary(
    path: Path,
) -> bytes:
    token = os.urandom(16).hex()

    text = (
        "P1_04_PHYSICAL_REMNANT_"
        + token
        + "_"
        + ("X" * 512)
    )

    canary = text.encode(
        "utf-8"
    )

    connection = sqlite3.connect(
        path,
        autocommit=True,
    )

    try:
        mode = str(
            connection.execute(
                "PRAGMA journal_mode = DELETE"
            ).fetchone()[0]
        ).lower()

        assert mode == "delete"

        connection.execute(
            "PRAGMA secure_delete = OFF"
        )

        deletion_id = os.urandom(16)

        connection.execute(
            """
            INSERT INTO deletion_ledger (
                deletion_id,
                entity_id,
                entity_type,
                deleted_at_us,
                deletion_commit_seq,
                deleted_by_actor_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deletion_id,
                os.urandom(16),
                text,
                1,
                1,
                os.urandom(16),
            ),
        )

        connection.execute(
            """
            DELETE FROM deletion_ledger
            WHERE deletion_id = ?
            """,
            (
                deletion_id,
            ),
        )

        mode = str(
            connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()[0]
        ).lower()

        assert mode == "wal"

    finally:
        connection.close()

    assert _raw_canary_count(
        path,
        canary,
    ) > 0

    return canary


def _schema_objects(
    path: Path,
) -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(
        path.resolve().as_uri()
        + "?mode=ro",
        uri=True,
    )

    try:
        return tuple(
            tuple(row)
            for row in connection.execute(
                """
                SELECT
                    type,
                    name,
                    tbl_name,
                    sql
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            )
        )

    finally:
        connection.close()


def _table_counts(
    path: Path,
) -> dict[str, int]:
    connection = sqlite3.connect(
        path.resolve().as_uri()
        + "?mode=ro",
        uri=True,
    )

    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]

        result: dict[str, int] = {}

        for table in tables:
            quoted = (
                '"'
                + table.replace(
                    '"',
                    '""',
                )
                + '"'
            )

            result[table] = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {quoted}"
                ).fetchone()[0]
            )

        return result

    finally:
        connection.close()


def _assert_integrity(
    path: Path,
) -> None:
    connection = sqlite3.connect(
        path.resolve().as_uri()
        + "?mode=ro",
        uri=True,
    )

    try:
        assert tuple(
            str(row[0])
            for row in connection.execute(
                "PRAGMA quick_check"
            )
        ) == ("ok",)

        assert connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []

    finally:
        connection.close()


@pytest.mark.parametrize(
    (
        "legacy_version",
        "legacy_migration_id",
    ),
    [
        (
            OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
            OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID,
        ),
        (
            DELETION_LEDGER_SCHEMA_VERSION,
            DELETION_LEDGER_MIGRATION_ID,
        ),
    ],
)
def test_physical_cleanup_migration_removes_deleted_canary(
    tmp_path: Path,
    legacy_version: int,
    legacy_migration_id: str,
) -> None:
    path = (
        tmp_path
        / f"physical-{legacy_version}.db"
    )

    _create_latest(
        path
    )

    _set_version(
        path,
        version=legacy_version,
        migration_id=legacy_migration_id,
    )

    canary = _inject_deleted_canary(
        path
    )

    objects_before = _schema_objects(
        path
    )

    counts_before = _table_counts(
        path
    )

    database = SQLiteDatabase(
        path
    )

    database.start()
    database.stop()

    version, metadata = _read_state(
        path
    )

    assert version == schema_module.SCHEMA_VERSION

    assert metadata == (
        schema_module.SCHEMA_VERSION,
        schema_module.GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
        schema_module.SCHEMA_VERSION,
    )

    assert _raw_canary_count(
        path,
        canary,
    ) == 0

    objects_after = _schema_objects(
        path
    )

    v39_object_names = {
        "source_protected_semantic_payloads",
        "source_protection_representation_blobs",
        "idx_source_protected_semantic_scope",
        "idx_source_protected_semantic_entity",
        "idx_source_protection_representation_state",
        "idx_source_protection_representation_old_blob",
        "grounded_response_receipts",
        "idx_grounded_response_receipts_chat",
    }

    preserved_objects_after = tuple(
        row
        for row in objects_after
        if str(row[1]) not in v39_object_names
    )

    assert preserved_objects_after == objects_before

    added_objects = {
        (
            str(row[0]),
            str(row[1]),
        )
        for row in objects_after
        if str(row[1]) in v39_object_names
    }

    assert added_objects == {
        (
            "table",
            "source_protected_semantic_payloads",
        ),
        (
            "table",
            "source_protection_representation_blobs",
        ),
        (
            "index",
            "idx_source_protected_semantic_scope",
        ),
        (
            "index",
            "idx_source_protected_semantic_entity",
        ),
        (
            "index",
            "idx_source_protection_representation_state",
        ),
        (
            "index",
            "idx_source_protection_representation_old_blob",
        ),
        (
            "table",
            "grounded_response_receipts",
        ),
        (
            "index",
            "idx_grounded_response_receipts_chat",
        ),
    }

    counts_after = _table_counts(
        path
    )

    v39_tables = {
        "source_protected_semantic_payloads",
        "source_protection_representation_blobs",
        "grounded_response_receipts",
    }

    preserved_counts_after = {
        table: count
        for table, count in counts_after.items()
        if table not in v39_tables
    }

    assert preserved_counts_after == counts_before

    assert {
        table: counts_after[table]
        for table in v39_tables
    } == {
        "source_protected_semantic_payloads": 0,
        "source_protection_representation_blobs": 0,
        "grounded_response_receipts": 0,
    }

    _assert_integrity(
        path
    )


def test_physical_cleanup_failure_does_not_mark_v38(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        tmp_path
        / "cleanup-failure.db"
    )

    _create_latest(
        path
    )

    _set_version(
        path,
        version=(
            OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION
        ),
        migration_id=(
            OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID
        ),
    )

    def fail_cleanup(
        connection: sqlite3.Connection,
    ) -> None:
        del connection

        raise RuntimeError(
            "synthetic physical cleanup failure"
        )

    monkeypatch.setattr(
        schema_module,
        "_physical_cleanup_operational_error_remnants",
        fail_cleanup,
    )

    database = SQLiteDatabase(
        path
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic physical cleanup failure",
    ):
        database.start()

    version, metadata = _read_state(
        path
    )

    assert (
        version
        == OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION
    )

    assert metadata == (
        OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
        OPERATIONAL_ERROR_SANITIZATION_MIGRATION_ID,
        OPERATIONAL_ERROR_SANITIZATION_SCHEMA_VERSION,
    )


def test_v38_second_start_does_not_repeat_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        tmp_path
        / "idempotent.db"
    )

    _create_latest(
        path
    )

    def unexpected_migration(
        connection: sqlite3.Connection,
    ) -> None:
        del connection

        raise AssertionError(
            "v38 cleanup migration repeated"
        )

    monkeypatch.setattr(
        schema_module,
        "_migrate_schema_v37_to_v38",
        unexpected_migration,
    )

    database = SQLiteDatabase(
        path
    )

    database.start()
    database.stop()

    version, metadata = _read_state(
        path
    )

    assert version == schema_module.SCHEMA_VERSION

    assert metadata == (
        schema_module.SCHEMA_VERSION,
        schema_module.GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
        schema_module.SCHEMA_VERSION,
    )


def test_physical_cleanup_checkpoint_busy_fails_closed() -> None:
    class FakeCursor:
        def fetchone(
            self,
        ) -> tuple[int, int, int]:
            return (
                1,
                4,
                0,
            )

    class FakeConnection:
        def execute(
            self,
            statement: str,
        ) -> FakeCursor:
            assert (
                statement
                == "PRAGMA wal_checkpoint(TRUNCATE)"
            )

            return FakeCursor()

    with pytest.raises(
        DatabaseCompatibilityError,
        match="checkpoint is busy",
    ):
        schema_module._checkpoint_wal_truncate_for_physical_cleanup(
            FakeConnection()  # type: ignore[arg-type]
        )
