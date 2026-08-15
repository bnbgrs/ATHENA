from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import athena.backup.service as backup_module
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication


def test_backup_is_verified_and_restores_snapshot_without_later_changes(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    backup_root = tmp_path / "backup"
    restored_root = tmp_path / "restored"
    app = AthenaApplication(settings=AthenaSettings(local_root=runtime))
    app.start()

    first_path = tmp_path / "first.txt"
    first_path.write_text("first immutable source", encoding="utf-8")
    first = app.sources.capture_file(first_path)
    snapshot = app.backup.create_snapshot(target_root=backup_root)
    assert snapshot.state == "complete"
    assert snapshot.verification_status == "verified_light"
    assert snapshot.object_count == 1
    pins = app.database.connection.execute(
        "SELECT COUNT(*) FROM backup_snapshot_pins WHERE snapshot_id = ?",
        (snapshot.snapshot_id.bytes,),
    ).fetchone()
    assert pins is not None and int(pins[0]) == 0

    second_path = tmp_path / "second.txt"
    second_path.write_text("later source not in snapshot", encoding="utf-8")
    app.sources.capture_file(second_path)

    verified = app.backup.verify(snapshot.snapshot_id)
    assert verified.manifest_sha256 == snapshot.manifest_sha256
    app.backup.restore_to(snapshot.snapshot_id, destination_root=restored_root)
    assert (restored_root / "state" / "restore.complete").is_file()

    restored_db = sqlite3.connect(restored_root / "state" / "athena.db")
    restored_db.row_factory = sqlite3.Row
    try:
        source_rows = restored_db.execute(
            "SELECT source_id, blob_id FROM sources ORDER BY created_at_us"
        ).fetchall()
        assert len(source_rows) == 1
        assert bytes(source_rows[0]["source_id"]) == first.source.source_id.bytes
        blob = restored_db.execute(
            """
            SELECT storage_area, storage_locator, integrity_sha256
            FROM blob_records
            WHERE blob_id = ?
            """,
            (bytes(source_rows[0]["blob_id"]),),
        ).fetchone()
        assert blob is not None
        assert blob["storage_area"] == "spool"
        restored_blob = restored_root / "state" / "spool" / str(blob["storage_locator"])
        assert restored_blob.is_file()
        assert hashlib.sha256(restored_blob.read_bytes()).digest() == bytes(
            blob["integrity_sha256"]
        )
        assert restored_db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        restored_db.close()

    app.stop()


def test_completed_backup_restores_from_path_without_original_snapshot_metadata(
    tmp_path: Path,
) -> None:
    source_runtime = tmp_path / "source-runtime"
    backup_root = tmp_path / "backup-disaster"
    restored_root = tmp_path / "disaster-restored"
    app = AthenaApplication(settings=AthenaSettings(local_root=source_runtime))
    app.start()
    source_path = tmp_path / "disaster.txt"
    source_path.write_text("disaster recovery source", encoding="utf-8")
    source = app.sources.capture_file(source_path).source
    snapshot = app.backup.create_snapshot(target_root=backup_root)
    snapshot_root = backup_root / snapshot.relative_path
    assert (snapshot_root / "complete.marker").is_file()
    app.stop()

    fresh = AthenaApplication(
        settings=AthenaSettings(local_root=tmp_path / "fresh-controller")
    )
    fresh.start()
    fresh.backup.restore_path(snapshot_root, destination_root=restored_root)
    fresh.stop()

    restored_db = sqlite3.connect(restored_root / "state" / "athena.db")
    try:
        rows = restored_db.execute("SELECT source_id FROM sources").fetchall()
        assert any(bytes(row[0]) == source.source_id.bytes for row in rows)
    finally:
        restored_db.close()

def test_backup_verifier_rejects_manifest_that_omits_snapshot_database_blob(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "manifest-runtime"))
    app.start()
    source_path = tmp_path / "manifest-source.txt"
    source_path.write_text("manifest completeness evidence", encoding="utf-8")
    app.sources.capture_file(source_path)
    backup_root = tmp_path / "manifest-backup"
    snapshot = app.backup.create_snapshot(target_root=backup_root)
    snapshot_root = backup_root / snapshot.relative_path

    manifest_path = snapshot_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["objects"]
    manifest["objects"] = []
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    manifest_path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).digest()
    (snapshot_root / "complete.marker").write_text(
        digest.hex() + "\n",
        encoding="ascii",
    )

    assert not app.backup._verify_path(
        target=backup_root,
        snapshot_root=snapshot_root,
        expected_manifest_sha256=digest,
        expected_snapshot_id=snapshot.snapshot_id,
    )
    app.stop()


def test_keyboard_interrupt_before_backup_marker_releases_pins_and_marks_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "interrupt-runtime"))
    app.start()
    source_path = tmp_path / "interrupt-source.txt"
    source_path.write_text("interrupt evidence", encoding="utf-8")
    app.sources.capture_file(source_path)

    def interrupted_verify_blob(**kwargs):
        del kwargs
        raise KeyboardInterrupt()

    monkeypatch.setattr(app.blob_store, "verify_blob", interrupted_verify_blob)
    with pytest.raises(KeyboardInterrupt):
        app.backup.create_snapshot(target_root=tmp_path / "interrupt-backup")

    failed = app.database.connection.execute(
        """
        SELECT snapshot_id, state, verification_status
        FROM backup_snapshots
        ORDER BY created_at_us DESC
        LIMIT 1
        """
    ).fetchone()
    assert failed is not None
    assert failed["state"] == "failed"
    assert failed["verification_status"] == "failed"
    pins = app.database.connection.execute(
        "SELECT COUNT(*) FROM backup_snapshot_pins WHERE snapshot_id = ?",
        (bytes(failed["snapshot_id"]),),
    ).fetchone()
    assert pins is not None and int(pins[0]) == 0
    app.stop()


def test_restore_failure_never_publishes_partial_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "restore-runtime"))
    app.start()
    source_path = tmp_path / "restore-source.txt"
    source_path.write_text("restore atomicity evidence", encoding="utf-8")
    app.sources.capture_file(source_path)
    snapshot = app.backup.create_snapshot(target_root=tmp_path / "restore-backup")
    destination = tmp_path / "atomic-restored"

    original_copy = backup_module._copy_verified

    def fail_restore_copy(source, target, **kwargs):
        if ".restore-partial" in str(target):
            raise OSError("synthetic restore crash")
        return original_copy(source, target, **kwargs)

    monkeypatch.setattr(backup_module, "_copy_verified", fail_restore_copy)
    with pytest.raises(OSError):
        app.backup.restore_to(snapshot.snapshot_id, destination_root=destination)

    assert not destination.exists()
    assert not tuple(destination.parent.glob(f".{destination.name}.*.restore-partial"))
    app.stop()


def test_recover_incomplete_finalizes_valid_published_marker_and_releases_pins(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "recovery-runtime"))
    app.start()
    source_path = tmp_path / "recovery-source.txt"
    source_path.write_text("hard crash recovery evidence", encoding="utf-8")
    source = app.sources.capture_file(source_path)
    snapshot = app.backup.create_snapshot(target_root=tmp_path / "recovery-backup")

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE backup_snapshots
            SET state = 'creating',
                verification_status = 'unverified',
                snapshot_commit_seq = NULL,
                schema_version = NULL,
                db_sha256 = NULL,
                manifest_sha256 = NULL,
                object_count = 0,
                completed_at_us = NULL,
                failure_detail = NULL
            WHERE snapshot_id = ?
            """,
            (snapshot.snapshot_id.bytes,),
        )
        connection.execute(
            """
            INSERT INTO backup_snapshot_pins (snapshot_id, blob_id, pinned_at_us)
            VALUES (?, ?, 1)
            """,
            (snapshot.snapshot_id.bytes, source.blob.blob_id.bytes),
        )

    recovered = app.backup.recover_incomplete()
    assert recovered == (snapshot.snapshot_id,)
    restored_record = app.backup.get_snapshot(snapshot.snapshot_id)
    assert restored_record.state == "complete"
    assert restored_record.verification_status == "verified_light"
    pins = app.database.connection.execute(
        "SELECT COUNT(*) FROM backup_snapshot_pins WHERE snapshot_id = ?",
        (snapshot.snapshot_id.bytes,),
    ).fetchone()
    assert pins is not None and int(pins[0]) == 0
    app.stop()
