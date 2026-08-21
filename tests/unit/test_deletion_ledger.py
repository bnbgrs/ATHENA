from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from athena.common.ids import uuid_to_blob
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.lifecycle.deletion import (
    current_deletion_watermark,
    read_deletion_records,
)
from athena.memory.repository import (
    PersonalMemoryNotFoundError,
)
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    BACKUP_RETENTION_MIGRATION_ID,
    BACKUP_RETENTION_SCHEMA_VERSION,
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    SCHEMA_VERSION,
)


def _app(
    root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=root,
        )
    )

    app.start()

    return app


def test_personal_memory_delete_records_payload_free_ledger(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        secret = (
            "SLICE15A_SECRET_MEMORY_PAYLOAD_"
            "D90E6F31"
        )

        created = (
            app.personal_memory.remember(
                content=secret
            )
        )

        assert (
            current_deletion_watermark(
                app.database.connection
            )
            == 0
        )

        commit_id = (
            app.personal_memory.delete(
                created.memory_id
            )
        )

        assert commit_id is not None

        records = (
            read_deletion_records(
                app.database.connection
            )
        )

        assert len(records) == 1

        record = records[0]

        assert record.ledger_seq == 1
        assert (
            record.entity_id
            == created.memory_id
        )
        assert (
            record.entity_type
            == "personal_memory_entry"
        )
        assert (
            record.deletion_commit_seq
            > 0
        )

        columns = {
            str(row[1])
            for row in (
                app.database.connection.execute(
                    "PRAGMA table_info(deletion_ledger)"
                )
            )
        }

        assert "content" not in columns
        assert "payload" not in columns
        assert "reason" not in columns
        assert "original_name" not in columns

        row = (
            app.database.connection.execute(
                """
                SELECT
                    entity_type,
                    deleted_at_us,
                    deletion_commit_seq
                FROM deletion_ledger
                WHERE entity_id = ?
                """,
                (
                    uuid_to_blob(
                        created.memory_id
                    ),
                ),
            ).fetchone()
        )

        assert row is not None
        assert secret not in repr(
            tuple(row)
        )

        with pytest.raises(
            PersonalMemoryNotFoundError
        ):
            app.personal_memory.load(
                created.memory_id
            )

    finally:
        app.stop()


def test_personal_memory_reset_records_each_deletion_once(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "reset-runtime"
    )

    try:
        first = (
            app.personal_memory.remember(
                content="first"
            )
        )

        second = (
            app.personal_memory.remember(
                content="second"
            )
        )

        result = (
            app.personal_memory.reset()
        )

        assert result.deleted_count == 2

        records = (
            read_deletion_records(
                app.database.connection
            )
        )

        assert {
            item.entity_id
            for item in records
        } == {
            first.memory_id,
            second.memory_id,
        }

        assert [
            item.ledger_seq
            for item in records
        ] == [
            1,
            2,
        ]

        second_reset = (
            app.personal_memory.reset()
        )

        assert (
            second_reset.deleted_count
            == 0
        )

        assert (
            len(
                read_deletion_records(
                    app.database.connection
                )
            )
            == 2
        )

    finally:
        app.stop()


def test_old_snapshot_restore_reapplies_newer_memory_deletion(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path / "runtime"
    )

    backup_root = (
        tmp_path / "backup"
    )

    restored_root = (
        tmp_path / "restored"
    )

    app = _app(
        runtime
    )

    try:
        created = (
            app.personal_memory.remember(
                content=(
                    "must remain deleted "
                    "after old restore"
                )
            )
        )

        old_snapshot = (
            app.backup.create_snapshot(
                target_root=backup_root
            )
        )

        assert (
            old_snapshot.deletion_ledger_watermark
            == 0
        )

        manifest = json.loads(
            (
                backup_root
                / old_snapshot.relative_path
                / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        assert (
            manifest[
                "deletion_ledger_watermark"
            ]
            == 0
        )

        app.personal_memory.delete(
            created.memory_id
        )

        assert (
            current_deletion_watermark(
                app.database.connection
            )
            == 1
        )

        app.backup.restore_to(
            old_snapshot.snapshot_id,
            destination_root=restored_root,
        )

        restored = sqlite3.connect(
            restored_root
            / "state"
            / "athena.db"
        )

        restored.row_factory = (
            sqlite3.Row
        )

        try:
            entity = restored.execute(
                """
                SELECT lifecycle_state
                FROM entity_registry
                WHERE entity_id = ?
                """,
                (
                    uuid_to_blob(
                        created.memory_id
                    ),
                ),
            ).fetchone()

            assert entity is not None
            assert (
                entity[
                    "lifecycle_state"
                ]
                == "deleted"
            )

            ledger = restored.execute(
                """
                SELECT
                    ledger_seq,
                    entity_type
                FROM deletion_ledger
                WHERE entity_id = ?
                """,
                (
                    uuid_to_blob(
                        created.memory_id
                    ),
                ),
            ).fetchone()

            assert ledger is not None
            assert (
                int(
                    ledger[
                        "ledger_seq"
                    ]
                )
                == 1
            )

            assert (
                ledger[
                    "entity_type"
                ]
                == "personal_memory_entry"
            )

            open_history = (
                restored.execute(
                    """
                    SELECT lifecycle_state
                    FROM entity_state_history
                    WHERE entity_id = ?
                      AND valid_to_commit_seq IS NULL
                    """,
                    (
                        uuid_to_blob(
                            created.memory_id
                        ),
                    ),
                ).fetchall()
            )

            assert (
                len(open_history)
                == 1
            )

            assert (
                open_history[0][
                    "lifecycle_state"
                ]
                == "deleted"
            )

            audit = restored.execute(
                """
                SELECT COUNT(*)
                FROM commit_records
                WHERE operation_type =
                    'restore.apply_deletion_ledger'
                """
            ).fetchone()

            assert audit is not None
            assert int(
                audit[0]
            ) == 1

            assert (
                restored.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
                == "ok"
            )

            assert (
                restored.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                == []
            )

        finally:
            restored.close()

    finally:
        app.stop()


def test_new_backup_captures_and_publishes_deletion_watermark(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "watermark-runtime"
    )

    backup_root = (
        tmp_path
        / "watermark-backup"
    )

    try:
        created = (
            app.personal_memory.remember(
                content="delete me"
            )
        )

        app.personal_memory.delete(
            created.memory_id
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=backup_root
            )
        )

        assert (
            snapshot.deletion_ledger_watermark
            == 1
        )

        manifest = json.loads(
            (
                backup_root
                / snapshot.relative_path
                / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        assert (
            manifest[
                "deletion_ledger_watermark"
            ]
            == 1
        )

        target = (
            app.backup.get_target(
                snapshot.target_id
            )
        )

        assert (
            target.deletion_ledger_watermark
            == 1
        )

        assert (
            app.backup.verify_deep(
                snapshot.snapshot_id
            ).verification_status
            == "verified_deep"
        )

    finally:
        app.stop()


def test_v35_database_migrates_additively_to_v36(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path / "migration.db"
    )

    latest = SQLiteDatabase(
        path
    )

    latest.start()
    latest.stop()

    legacy = sqlite3.connect(
        path,
        autocommit=True,
    )

    # This fixture starts from the current schema and
    # reconstructs an older boundary. Remove additive
    # v40 and v39 child state before removing older parents
    # or rewriting schema metadata. Production migration
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

    legacy.execute(
        "DROP TABLE deletion_ledger"
    )

    legacy.execute(
        """
        ALTER TABLE backup_targets
        DROP COLUMN deletion_ledger_watermark
        """
    )

    legacy.execute(
        """
        ALTER TABLE backup_snapshots
        DROP COLUMN deletion_ledger_watermark
        """
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
            BACKUP_RETENTION_SCHEMA_VERSION,
            BACKUP_RETENTION_MIGRATION_ID,
            BACKUP_RETENTION_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{BACKUP_RETENTION_SCHEMA_VERSION}"
    )

    legacy.close()

    upgraded = SQLiteDatabase(
        path
    )

    upgraded.start()

    try:
        connection = (
            upgraded.connection
        )

        assert (
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            == SCHEMA_VERSION
        )

        metadata = connection.execute(
            """
            SELECT
                schema_version,
                last_migration_id,
                minimum_reader_version
            FROM schema_metadata
            WHERE singleton_id = 1
            """
        ).fetchone()

        assert metadata is not None

        assert tuple(
            metadata
        ) == (
            SCHEMA_VERSION,
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
            SCHEMA_VERSION,
        )

        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(deletion_ledger)"
            )
        }

        assert columns >= {
            "ledger_seq",
            "deletion_id",
            "entity_id",
            "entity_type",
            "deleted_at_us",
            "deletion_commit_seq",
            "deleted_by_actor_id",
        }

        assert (
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        upgraded.stop()
