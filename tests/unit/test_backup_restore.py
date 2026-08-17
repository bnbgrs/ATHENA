from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import athena.backup.service as backup_module
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.jobs.recovery import (
    CANCELLED_AFTER_RESTORE,
    RECOVERY_REQUIRED_AFTER_RESTORE,
)


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


def test_restore_fences_inflight_jobs_and_preserves_confirmed_checkpoint(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "job-recovery-runtime"
    backup_root = tmp_path / "job-recovery-backup"
    restored_root = tmp_path / "job-recovery-restored"

    app = AthenaApplication(
        settings=AthenaSettings(local_root=runtime)
    )
    app.start()

    running = app.jobs.create(
        job_type="source.process"
    )
    cancelling = app.jobs.create(
        job_type="integrity.sweep"
    )
    queued = app.jobs.create(
        job_type="search.rebuild"
    )

    base = utc_now_us()

    running_lease = app.jobs.acquire(
        running.job_id,
        worker_id="pre-restore-running-worker",
        lease_seconds=3600,
        now_us=base,
    )
    assert running_lease.lease_token is not None

    checkpoint = app.jobs.checkpoint(
        running.job_id,
        lease_token=running_lease.lease_token,
        current_stage="representation",
        progress_state={"completed_units": 3},
        last_confirmed_input={"source_id": "source-before-restore"},
        last_confirmed_output={"representation_id": "confirmed-output"},
        resume_metadata={"next_unit": 4},
        now_us=base + 1,
    )

    cancelling_lease = app.jobs.acquire(
        cancelling.job_id,
        worker_id="pre-restore-cancelling-worker",
        lease_seconds=3600,
        now_us=base,
    )
    assert cancelling_lease.lease_token is not None

    cancel_requested = app.jobs.request_cancel(
        cancelling.job_id
    )
    assert cancel_requested.state is JobState.CANCEL_REQUESTED

    snapshot = app.backup.create_snapshot(
        target_root=backup_root
    )

    app.backup.restore_to(
        snapshot.snapshot_id,
        destination_root=restored_root,
    )

    restored_db = sqlite3.connect(
        restored_root / "state" / "athena.db"
    )
    restored_db.row_factory = sqlite3.Row

    try:
        running_row = restored_db.execute(
            """
            SELECT
                state,
                blocked_reason,
                current_stage,
                last_checkpoint_id,
                retry_count,
                worker_id,
                lease_token,
                lease_acquired_at_us,
                lease_expires_at_us,
                heartbeat_at_us,
                fencing_sequence
            FROM jobs
            WHERE job_id = ?
            """,
            (running.job_id.bytes,),
        ).fetchone()

        assert running_row is not None
        assert running_row["state"] == JobState.PAUSED.value
        assert (
            running_row["blocked_reason"]
            == RECOVERY_REQUIRED_AFTER_RESTORE
        )
        assert running_row["current_stage"] == "representation"
        assert (
            bytes(running_row["last_checkpoint_id"])
            == checkpoint.checkpoint_id.bytes
        )
        assert int(running_row["retry_count"]) == 0
        assert running_row["worker_id"] is None
        assert running_row["lease_token"] is None
        assert running_row["lease_acquired_at_us"] is None
        assert running_row["lease_expires_at_us"] is None
        assert running_row["heartbeat_at_us"] is None
        assert (
            int(running_row["fencing_sequence"])
            == running_lease.fencing_sequence
        )

        checkpoint_row = restored_db.execute(
            """
            SELECT
                current_stage,
                last_checkpoint_id
            FROM jobs
            WHERE job_id = ?
            """,
            (running.job_id.bytes,),
        ).fetchone()

        assert checkpoint_row is not None
        assert checkpoint_row["current_stage"] == "representation"
        assert (
            bytes(checkpoint_row["last_checkpoint_id"])
            == checkpoint.checkpoint_id.bytes
        )

        cancelling_row = restored_db.execute(
            """
            SELECT
                state,
                blocked_reason,
                worker_id,
                lease_token,
                lease_acquired_at_us,
                lease_expires_at_us,
                heartbeat_at_us,
                fencing_sequence
            FROM jobs
            WHERE job_id = ?
            """,
            (cancelling.job_id.bytes,),
        ).fetchone()

        assert cancelling_row is not None
        assert cancelling_row["state"] == JobState.CANCELLED.value
        assert (
            cancelling_row["blocked_reason"]
            == CANCELLED_AFTER_RESTORE
        )
        assert cancelling_row["worker_id"] is None
        assert cancelling_row["lease_token"] is None
        assert cancelling_row["lease_acquired_at_us"] is None
        assert cancelling_row["lease_expires_at_us"] is None
        assert cancelling_row["heartbeat_at_us"] is None
        assert (
            int(cancelling_row["fencing_sequence"])
            == cancelling_lease.fencing_sequence
        )

        queued_row = restored_db.execute(
            """
            SELECT
                state,
                blocked_reason,
                worker_id,
                lease_token,
                fencing_sequence
            FROM jobs
            WHERE job_id = ?
            """,
            (queued.job_id.bytes,),
        ).fetchone()

        assert queued_row is not None
        assert queued_row["state"] == JobState.QUEUED.value
        assert queued_row["blocked_reason"] is None
        assert queued_row["worker_id"] is None
        assert queued_row["lease_token"] is None
        assert int(queued_row["fencing_sequence"]) == 0

        assert (
            restored_db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            == "ok"
        )
        assert (
            restored_db.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        restored_db.close()

    # Reconciliation belongs only to the isolated restore target. The live
    # source runtime must not be rewritten as a side effect of restore.
    assert (
        app.jobs.get(running.job_id).state
        is JobState.RUNNING
    )
    assert (
        app.jobs.get(cancelling.job_id).state
        is JobState.CANCEL_REQUESTED
    )
    assert (
        app.jobs.get(queued.job_id).state
        is JobState.QUEUED
    )

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



def test_restore_post_rename_durability_failure_removes_published_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "post-rename-runtime"
        )
    )
    app.start()

    try:
        source_path = tmp_path / "post-rename-source.txt"
        source_path.write_text(
            "post-rename durability failure evidence",
            encoding="utf-8",
        )
        app.sources.capture_file(source_path)

        snapshot = app.backup.create_snapshot(
            target_root=tmp_path / "post-rename-backup"
        )

        destination = tmp_path / "post-rename-restored"

        real_durable_replace = backup_module.durable_replace

        def fail_after_restore_publication(
            source: Path,
            target: Path,
        ) -> None:
            real_durable_replace(
                source,
                target,
            )

            if (
                source.name.endswith(".restore-partial")
                and target == destination
            ):
                raise OSError(
                    "synthetic post-rename durability failure"
                )

        monkeypatch.setattr(
            backup_module,
            "durable_replace",
            fail_after_restore_publication,
        )

        with pytest.raises(
            OSError,
            match="synthetic post-rename durability failure",
        ):
            app.backup.restore_to(
                snapshot.snapshot_id,
                destination_root=destination,
            )

        assert not destination.exists()
        assert not tuple(
            destination.parent.glob(
                f".{destination.name}.*.restore-partial"
            )
        )
    finally:
        app.stop()
