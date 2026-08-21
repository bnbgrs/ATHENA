from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from athena.backup.retention import (
    BackupRetentionPolicy,
    RetentionCandidate,
    plan_retention,
)
from athena.backup.service import BackupRestoreError
from athena.backup.target_lock import (
    BackupTargetBusyError,
    backup_target_lock,
)
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    SCHEMA_VERSION,
    SOURCE_PROTECTION_TRANSITION_MIGRATION_ID,
    SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION,
)


def _us(
    year: int,
    month: int,
    day: int,
) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            tzinfo=UTC,
        ).timestamp()
        * 1_000_000
    )


def test_v34_to_v35_adds_backup_retention_schema(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path
        / "athena.db"
    )

    latest = SQLiteDatabase(
        database_path
    )
    latest.start()
    latest.stop()

    legacy = sqlite3.connect(
        database_path,
        autocommit=True,
    )

    # This fixture starts from the current schema and
    # reconstructs an older boundary. Remove additive
    # v39 child state before removing older parents or
    # rewriting schema metadata. Production migration
    # behavior intentionally remains fail-closed.
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "grounded_response_receipts"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protection_representation_blobs"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protected_semantic_payloads"
    )

    try:
        legacy.execute(
            "DROP INDEX "
            "uq_backup_snapshots_one_creating_per_target"
        )
        legacy.execute(
            "DROP INDEX "
            "idx_backup_snapshots_target_retention"
        )

        legacy.execute(
            "ALTER TABLE backup_targets "
            "DROP COLUMN identity_initialized"
        )
        legacy.execute(
            "ALTER TABLE backup_targets "
            "DROP COLUMN retention_daily"
        )
        legacy.execute(
            "ALTER TABLE backup_targets "
            "DROP COLUMN retention_weekly"
        )
        legacy.execute(
            "ALTER TABLE backup_targets "
            "DROP COLUMN retention_monthly"
        )
        legacy.execute(
            "ALTER TABLE backup_targets "
            "DROP COLUMN retention_yearly"
        )
        legacy.execute(
            "ALTER TABLE backup_snapshots "
            "DROP COLUMN last_verified_at_us"
        )
        legacy.execute(
            "ALTER TABLE backup_snapshots "
            "DROP COLUMN pruned_at_us"
        )

        legacy.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?,
                last_migration_id = ?,
                minimum_reader_version = ?
            WHERE singleton_id = 1
            """,
            (
                SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION,
                SOURCE_PROTECTION_TRANSITION_MIGRATION_ID,
                SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION,
            ),
        )
        legacy.execute(
            "PRAGMA user_version = "
            f"{SOURCE_PROTECTION_TRANSITION_SCHEMA_VERSION}"
        )

    finally:
        legacy.close()

    upgraded = SQLiteDatabase(
        database_path
    )
    upgraded.start()

    try:
        assert (
            upgraded.connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            == SCHEMA_VERSION
        )

        metadata = (
            upgraded.connection.execute(
                """
                SELECT schema_version,
                       last_migration_id,
                       minimum_reader_version
                FROM schema_metadata
                WHERE singleton_id = 1
                """
            ).fetchone()
        )

        assert metadata is not None
        assert int(metadata[0]) == (
            SCHEMA_VERSION
        )
        assert str(metadata[1]) == (
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID
        )
        assert int(metadata[2]) == (
            SCHEMA_VERSION
        )

        target_columns = {
            str(row[1])
            for row in upgraded.connection.execute(
                "PRAGMA table_info(backup_targets)"
            )
        }
        snapshot_columns = {
            str(row[1])
            for row in upgraded.connection.execute(
                "PRAGMA table_info(backup_snapshots)"
            )
        }

        assert {
            "identity_initialized",
            "retention_daily",
            "retention_weekly",
            "retention_monthly",
            "retention_yearly",
        }.issubset(
            target_columns
        )
        assert {
            "last_verified_at_us",
            "pruned_at_us",
        }.issubset(
            snapshot_columns
        )
        assert (
            upgraded.connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        upgraded.stop()


def test_retention_planner_is_deterministic(
) -> None:
    target_id = uuid.UUID(
        int=500
    )

    candidates = (
        RetentionCandidate(
            uuid.UUID(int=1),
            _us(2024, 12, 31),
        ),
        RetentionCandidate(
            uuid.UUID(int=2),
            _us(2025, 1, 1),
        ),
        RetentionCandidate(
            uuid.UUID(int=3),
            _us(2025, 12, 31),
        ),
        RetentionCandidate(
            uuid.UUID(int=4),
            _us(2026, 1, 1),
        ),
        RetentionCandidate(
            uuid.UUID(int=5),
            _us(2026, 2, 1),
        ),
        RetentionCandidate(
            uuid.UUID(int=6),
            _us(2026, 2, 2),
        ),
    )

    plan = plan_retention(
        target_id=target_id,
        snapshots=candidates,
        policy=BackupRetentionPolicy(
            daily=1,
            weekly=2,
            monthly=2,
            yearly=2,
        ),
    )

    assert set(
        plan.keep_snapshot_ids
    ) == {
        uuid.UUID(int=3),
        uuid.UUID(int=4),
        uuid.UUID(int=5),
        uuid.UUID(int=6),
    }
    assert set(
        plan.prune_snapshot_ids
    ) == {
        uuid.UUID(int=1),
        uuid.UUID(int=2),
    }

    tied = plan_retention(
        target_id=target_id,
        snapshots=(
            RetentionCandidate(
                uuid.UUID(int=10),
                _us(2026, 1, 1),
            ),
            RetentionCandidate(
                uuid.UUID(int=11),
                _us(2026, 1, 1),
            ),
        ),
        policy=BackupRetentionPolicy(
            daily=0,
            weekly=0,
            monthly=0,
            yearly=0,
        ),
    )

    assert tied.keep_snapshot_ids == (
        uuid.UUID(int=11),
    )
    assert tied.prune_snapshot_ids == (
        uuid.UUID(int=10),
    )


def test_target_identity_survives_path_change_and_offline_root_is_not_recreated(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )
    app.start()

    try:
        first_root = (
            tmp_path
            / "backup-a"
        )
        second_root = (
            tmp_path
            / "backup-b"
        )

        target = app.backup.register_target(
            first_root
        )

        source_path = (
            tmp_path
            / "identity-source.txt"
        )
        source_path.write_text(
            "stable target identity",
            encoding="utf-8",
        )
        app.sources.capture_file(
            source_path
        )
        app.backup.create_snapshot(
            target_id=target.target_id
        )

        shutil.move(
            str(first_root),
            str(second_root),
        )

        reattached = (
            app.backup.register_target(
                second_root
            )
        )

        assert (
            reattached.target_id
            == target.target_id
        )
        assert (
            reattached.root_path
            == second_root.resolve()
        )

        shutil.rmtree(
            second_root
        )

        with pytest.raises(
            BackupRestoreError
        ):
            app.backup.create_snapshot(
                target_id=target.target_id
            )

        assert not second_root.exists()
        assert (
            app.backup.get_target(
                target.target_id
            ).status
            == "offline"
        )

    finally:
        app.stop()


def test_retention_prunes_old_snapshot_without_deleting_shared_blob(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )
    app.start()

    try:
        source_path = (
            tmp_path
            / "shared.txt"
        )
        payload = (
            b"shared immutable backup blob"
        )
        source_path.write_bytes(
            payload
        )
        captured = app.sources.capture_file(
            source_path
        )

        backup_root = (
            tmp_path
            / "backup"
        )

        first = app.backup.create_snapshot(
            target_root=backup_root
        )
        second = app.backup.create_snapshot(
            target_id=first.target_id
        )

        app.backup.set_retention_policy(
            first.target_id,
            daily=0,
            weekly=0,
            monthly=0,
            yearly=0,
        )

        result = app.backup.apply_retention(
            first.target_id
        )

        assert result.pruned_snapshot_ids == (
            first.snapshot_id,
        )
        assert result.plan.keep_snapshot_ids == (
            second.snapshot_id,
        )

        first_after = app.backup.get_snapshot(
            first.snapshot_id
        )
        assert (
            first_after.pruned_at_us
            is not None
        )

        with pytest.raises(
            BackupRestoreError
        ):
            app.backup.verify(
                first.snapshot_id
            )

        second_verified = app.backup.verify(
            second.snapshot_id
        )
        assert (
            second_verified.last_verified_at_us
            is not None
        )

        digest = (
            captured.blob.integrity_sha256
        )
        value = digest.hex()
        shared_object = (
            backup_root
            / "objects"
            / "sha256"
            / value[:2]
            / value[2:4]
            / f"{value}.blob"
        )

        assert shared_object.is_file()
        assert (
            hashlib.sha256(
                shared_object.read_bytes()
            ).digest()
            == digest
        )
        assert (
            shared_object.read_bytes()
            == payload
        )

    finally:
        app.stop()


def test_target_lock_blocks_parallel_backup_and_verify_refreshes_timestamp(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )
    app.start()

    try:
        target = app.backup.register_target(
            tmp_path
            / "backup"
        )

        with backup_target_lock(
            target.root_path
        ):
            with pytest.raises(
                BackupTargetBusyError
            ):
                app.backup.create_snapshot(
                    target_id=target.target_id
                )

        source_path = (
            tmp_path
            / "verify.txt"
        )
        source_path.write_text(
            "verification timestamp",
            encoding="utf-8",
        )
        app.sources.capture_file(
            source_path
        )

        snapshot = app.backup.create_snapshot(
            target_id=target.target_id
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE backup_snapshots
                SET last_verified_at_us = NULL
                WHERE snapshot_id = ?
                """,
                (
                    snapshot.snapshot_id.bytes,
                ),
            )

        verified = app.backup.verify(
            snapshot.snapshot_id
        )

        assert (
            verified.last_verified_at_us
            is not None
        )

    finally:
        app.stop()
