from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.lifecycle.purge import (
    PhysicalPurgeBlockedError,
)
from athena.lifecycle.runtime_lock import (
    runtime_data_lock,
)


def _app(
    root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=root,
        )
    )

    app.start()

    return app


def _logical_delete(
    app: AthenaApplication,
    source_id,
) -> None:
    preview = (
        app.lifecycle_deletion.preview(
            source_id
        )
    )

    app.lifecycle_deletion.delete(
        source_id,
        preview_digest=(
            preview.preview_digest
        ),
    )


def test_runtime_data_lock_is_reentrant(
    tmp_path: Path,
) -> None:
    state_root = (
        tmp_path
        / "state"
    )

    with runtime_data_lock(
        state_root
    ):
        with runtime_data_lock(
            state_root
        ):
            assert (
                state_root
                / ".athena-runtime-data.lock"
            ).is_file()


def test_shared_raw_blob_is_not_purged_while_live_source_exists(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    input_file = (
        tmp_path
        / "shared.txt"
    )

    input_file.write_text(
        "shared physical purge payload",
        encoding="utf-8",
    )

    app = _app(
        runtime
    )

    try:
        first = (
            app.sources.capture_file(
                input_file
            )
        )

        second = (
            app.sources.capture_file(
                input_file
            )
        )

        assert (
            first.blob.blob_id
            == second.blob.blob_id
        )

        path = (
            app.blob_store.resolve_blob_path(
                storage_area=(
                    first.blob.storage_area
                ),
                storage_locator=(
                    first.blob.storage_locator
                ),
            )
        )

        assert path.is_file()

        _logical_delete(
            app,
            first.source.source_id,
        )

        with pytest.raises(
            PhysicalPurgeBlockedError,
            match="non-deleted Source",
        ):
            (
                app.lifecycle_purge
                .purge_deleted_source_blob(
                    first.source.source_id
                )
            )

        assert path.is_file()

        _logical_delete(
            app,
            second.source.source_id,
        )

        result = (
            app.lifecycle_purge
            .purge_deleted_source_blob(
                first.source.source_id
            )
        )

        assert (
            result.blob_id
            == first.blob.blob_id
        )

        assert set(
            result.sanitized_source_ids
        ) == {
            first.source.source_id,
            second.source.source_id,
        }

        assert (
            result.deleted_replica_count
            == 1
        )

        assert not path.exists()

        rows = (
            app.database.connection.execute(
                """
                SELECT
                    original_name,
                    original_modified_at_us,
                    source_uri
                FROM sources
                WHERE source_id IN (?, ?)
                ORDER BY source_id
                """,
                (
                    first.source.source_id.bytes,
                    second.source.source_id.bytes,
                ),
            ).fetchall()
        )

        assert len(
            rows
        ) == 2

        assert all(
            row[
                "original_name"
            ]
            is None
            and row[
                "original_modified_at_us"
            ]
            is None
            and row[
                "source_uri"
            ]
            is None
            for row in rows
        )

        # An explicit later re-import is a new Source,
        # but may safely reuse the technical content-addressed
        # BlobRecord after recreating the bytes.
        third = (
            app.sources.capture_file(
                input_file
            )
        )

        assert (
            third.source.source_id
            not in {
                first.source.source_id,
                second.source.source_id,
            }
        )

        assert (
            third.blob.blob_id
            == first.blob.blob_id
        )

        assert path.is_file()

    finally:
        app.stop()


def test_backup_pin_blocks_physical_source_purge(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-pin"
    )

    target = (
        tmp_path
        / "backup-pin"
    )

    input_file = (
        tmp_path
        / "pin.txt"
    )

    input_file.write_text(
        "backup pin purge payload",
        encoding="utf-8",
    )

    app = _app(
        runtime
    )

    try:
        captured = (
            app.sources.capture_file(
                input_file
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        _logical_delete(
            app,
            captured.source.source_id,
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO backup_snapshot_pins (
                    snapshot_id,
                    blob_id,
                    pinned_at_us
                ) VALUES (?, ?, ?)
                """,
                (
                    snapshot.snapshot_id.bytes,
                    captured.blob.blob_id.bytes,
                    1,
                ),
            )

        with pytest.raises(
            PhysicalPurgeBlockedError,
            match="pinned",
        ):
            (
                app.lifecycle_purge
                .purge_deleted_source_blob(
                    captured.source.source_id
                )
            )

        path = (
            app.blob_store.resolve_blob_path(
                storage_area=(
                    captured.blob.storage_area
                ),
                storage_locator=(
                    captured.blob.storage_locator
                ),
            )
        )

        assert path.is_file()

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                DELETE FROM backup_snapshot_pins
                WHERE snapshot_id = ?
                  AND blob_id = ?
                """,
                (
                    snapshot.snapshot_id.bytes,
                    captured.blob.blob_id.bytes,
                ),
            )

        result = (
            app.lifecycle_purge
            .purge_deleted_source_blob(
                captured.source.source_id
            )
        )

        assert (
            result.deleted_replica_count
            == 1
        )

        assert not path.exists()

    finally:
        app.stop()


def test_backup_after_source_purge_excludes_orphaned_raw_blob(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-backup"
    )

    target = (
        tmp_path
        / "backup-after-purge"
    )

    input_file = (
        tmp_path
        / "backup-after-purge.txt"
    )

    input_file.write_text(
        "must not be copied after physical purge",
        encoding="utf-8",
    )

    app = _app(
        runtime
    )

    try:
        captured = (
            app.sources.capture_file(
                input_file
            )
        )

        _logical_delete(
            app,
            captured.source.source_id,
        )

        (
            app.lifecycle_purge
            .purge_deleted_source_blob(
                captured.source.source_id
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        manifest = json.loads(
            (
                target
                / snapshot.relative_path
                / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        assert all(
            item[
                "blob_id"
            ]
            != str(
                captured.blob.blob_id
            )
            for item
            in manifest[
                "objects"
            ]
        )

        verified = (
            app.backup.verify_deep(
                snapshot.snapshot_id
            )
        )

        assert (
            verified.verification_status
            == "verified_deep"
        )

    finally:
        app.stop()


def test_old_snapshot_restore_does_not_reactivate_purged_source_bytes(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-restore"
    )

    target = (
        tmp_path
        / "backup-restore"
    )

    destination = (
        tmp_path
        / "restored"
    )

    input_file = (
        tmp_path
        / "restore-purge.txt"
    )

    payload = (
        b"old snapshot raw source bytes "
        b"must not reactivate"
    )

    input_file.write_bytes(
        payload
    )

    app = _app(
        runtime
    )

    try:
        captured = (
            app.sources.capture_file(
                input_file
            )
        )

        old_snapshot = (
            app.backup.create_snapshot(
                target_root=target
            )
        )

        _logical_delete(
            app,
            captured.source.source_id,
        )

        (
            app.lifecycle_purge
            .purge_deleted_source_blob(
                captured.source.source_id
            )
        )

        app.backup.restore_to(
            old_snapshot.snapshot_id,
            destination_root=destination,
        )

    finally:
        app.stop()

    restored_blob = (
        destination
        / "state"
        / "spool"
        / Path(
            captured.blob.storage_locator
        )
    )

    assert not restored_blob.exists()

    restored = sqlite3.connect(
        destination
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
                captured.source.source_id.bytes,
            ),
        ).fetchone()

        assert entity is not None

        assert (
            entity[
                "lifecycle_state"
            ]
            == "deleted"
        )

        source = restored.execute(
            """
            SELECT
                original_name,
                original_modified_at_us,
                source_uri
            FROM sources
            WHERE source_id = ?
            """,
            (
                captured.source.source_id.bytes,
            ),
        ).fetchone()

        assert source is not None

        assert (
            source[
                "original_name"
            ]
            is None
        )

        assert (
            source[
                "original_modified_at_us"
            ]
            is None
        )

        assert (
            source[
                "source_uri"
            ]
            is None
        )

        assert (
            restored.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        restored.close()
