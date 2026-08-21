
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobPriority, JobState, WaitingReason
from athena.source.models import BlobStorageArea
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    NEWS_EVENT_ELIGIBILITY_MIGRATION_ID,
    NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
    SCHEMA_VERSION,
)


def _app(
    local_root: Path,
    *,
    archive_root: Path | None,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=local_root,
            archive_root=archive_root,
        )
    )
    app.start()
    return app


def test_offline_capture_creates_pending_outbox_and_survives_restart(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "offline-archive"
    original = tmp_path / "offline.txt"
    payload = b"durable pending archive bytes"

    original.write_bytes(payload)

    first = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = first.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    status = first.archive_replication.status()

    assert status.pending_count == 1
    assert status.verified_count == 0
    assert status.contiguous_verified_seq == 0
    assert status.max_outbox_seq == 1

    source_id = captured.source.source_id

    first.stop()

    second = _app(
        local_root,
        archive_root=archive_root,
    )

    status = second.archive_replication.status()

    assert status.pending_count == 1
    assert status.verified_count == 0
    assert status.contiguous_verified_seq == 0
    assert status.max_outbox_seq == 1

    assert (
        second.sources.verify(
            source_id
        ).read_bytes()
        == payload
    )

    second.stop()


def test_all_new_spool_blob_records_are_enqueued_not_only_raw_file_capture(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "offline-archive"
    original = tmp_path / "normalize.txt"

    # Raw bytes and normalized representation bytes differ.
    original.write_bytes(
        b"\xef\xbb\xbfline one\r\nline two\r\n"
    )

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = app.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    representation = app.source_text.build(
        captured.source.source_id
    )

    assert (
        representation.result.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    assert (
        representation.result.blob.blob_id
        != captured.blob.blob_id
    )

    status = app.archive_replication.status()

    assert status.pending_count == 2
    assert status.verified_count == 0
    assert status.max_outbox_seq == 2

    pending = (
        app.archive_replication_repository
        .list_pending()
    )

    assert {
        item.blob.blob_id
        for item in pending
    } == {
        captured.blob.blob_id,
        representation.result.blob.blob_id,
    }

    app.stop()


def test_archive_reconnect_verifies_target_advances_watermark_and_cleans_spool(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    original = tmp_path / "reconnect.bin"
    payload = b"offline first, archive later"

    original.write_bytes(payload)

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = app.sources.capture_file(
        original
    )

    spool_path = (
        app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=(
                captured.blob.storage_locator
            ),
        )
    )

    assert spool_path.is_file()
    assert not archive_root.exists()

    archive_root.mkdir()

    result = (
        app.archive_replication
        .sync_pending()
    )

    assert result.attempted == 1
    assert result.verified == 1
    assert result.failed == 0
    assert result.blocked_reason is None
    assert result.cleaned_spool_replicas == 1

    assert result.status.pending_count == 0
    assert result.status.verified_count == 1
    assert result.status.contiguous_verified_seq == 1
    assert result.status.max_outbox_seq == 1

    source, blob = app.sources.get(
        captured.source.source_id
    )

    assert source.blob_id == blob.blob_id
    assert (
        blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    archive_path = app.sources.verify(
        source.source_id
    )

    assert archive_path.read_bytes() == payload
    assert archive_path.is_relative_to(
        archive_root
    )
    assert not spool_path.exists()

    app.stop()


def test_unavailable_archive_keeps_pending_bytes_and_does_not_count_attempt(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "offline-archive"
    original = tmp_path / "pending.bin"
    payload = b"stay safely local"

    original.write_bytes(payload)

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = app.sources.capture_file(
        original
    )

    result = (
        app.archive_replication
        .sync_pending()
    )

    assert result.attempted == 0
    assert result.verified == 0
    assert result.failed == 0
    assert (
        result.blocked_reason
        == "archive_root_unavailable"
    )

    pending = (
        app.archive_replication_repository
        .list_pending()
    )

    assert len(pending) == 1
    assert pending[0].attempt_count == 0

    assert (
        app.sources.verify(
            captured.source.source_id
        ).read_bytes()
        == payload
    )

    app.stop()


def test_corrupt_existing_archive_target_fails_closed_without_spool_loss(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    original = tmp_path / "conflict.bin"
    payload = b"authoritative local spool"

    original.write_bytes(payload)

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = app.sources.capture_file(
        original
    )

    spool_path = (
        app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=(
                captured.blob.storage_locator
            ),
        )
    )

    archive_root.mkdir()

    target = (
        archive_root
        / captured.blob.storage_locator
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_bytes(
        b"conflicting corrupt target"
    )

    result = (
        app.archive_replication
        .sync_pending()
    )

    assert result.attempted == 1
    assert result.verified == 0
    assert result.failed == 1

    # Never silently overwrite an existing
    # object that does not match its content address.
    assert target.read_bytes() == (
        b"conflicting corrupt target"
    )

    # Local durable copy remains untouched.
    assert spool_path.read_bytes() == payload

    pending = (
        app.archive_replication_repository
        .list_pending()
    )

    assert len(pending) == 1
    assert pending[0].attempt_count == 1
    assert (
        pending[0].last_error_code
        == "BlobIntegrityError"
    )

    source, blob = app.sources.get(
        captured.source.source_id
    )

    assert (
        blob.storage_area
        is BlobStorageArea.SPOOL
    )

    assert (
        app.sources.verify(
            source.source_id
        ).read_bytes()
        == payload
    )

    app.stop()


def test_restart_after_target_copy_before_db_confirmation_is_idempotent(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    original = tmp_path / "crash-before-db.bin"
    payload = b"copied but not yet confirmed"

    original.write_bytes(payload)

    first = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = first.sources.capture_file(
        original
    )

    spool_path = (
        first.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=(
                captured.blob.storage_locator
            ),
        )
    )

    archive_root.mkdir()

    target = (
        first.blob_store
        .replicate_spool_blob_to_archive(
            storage_locator=(
                captured.blob.storage_locator
            ),
            expected_sha256=(
                captured.blob.integrity_sha256
            ),
            expected_length=(
                captured.blob.byte_length
            ),
        )
    )

    assert target.read_bytes() == payload
    assert spool_path.read_bytes() == payload

    # Simulated process death here:
    # target is already valid but durable Outbox remains pending.
    first.stop()

    second = _app(
        local_root,
        archive_root=archive_root,
    )

    before = second.archive_replication.status()

    assert before.pending_count == 1
    assert before.contiguous_verified_seq == 0

    result = (
        second.archive_replication
        .sync_pending()
    )

    assert result.attempted == 1
    assert result.verified == 1
    assert result.failed == 0

    assert result.status.pending_count == 0
    assert result.status.contiguous_verified_seq == 1

    source, blob = second.sources.get(
        captured.source.source_id
    )

    assert (
        blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    assert (
        second.sources.verify(
            source.source_id
        ).read_bytes()
        == payload
    )

    assert not spool_path.exists()

    second.stop()


def test_restart_after_db_confirmation_before_spool_cleanup_reconciles(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    original = tmp_path / "crash-after-db.bin"
    payload = b"confirmed before cleanup"

    original.write_bytes(payload)

    first = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = first.sources.capture_file(
        original
    )

    spool_path = (
        first.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=(
                captured.blob.storage_locator
            ),
        )
    )

    archive_root.mkdir()

    pending = (
        first.archive_replication_repository
        .list_pending()[0]
    )

    first.archive_replication_repository.mark_attempt(
        pending.outbox_seq
    )

    (
        first.blob_store
        .replicate_spool_blob_to_archive(
            storage_locator=(
                pending.blob.storage_locator
            ),
            expected_sha256=(
                pending.blob.integrity_sha256
            ),
            expected_length=(
                pending.blob.byte_length
            ),
        )
    )

    confirmed = (
        first.archive_replication_repository
        .confirm_verified(
            pending.outbox_seq
        )
    )

    assert (
        confirmed.blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    # DB confirmation and watermark are already durable.
    # Only transfer-only local cleanup has not run.
    assert spool_path.exists()

    first.stop()

    second = _app(
        local_root,
        archive_root=archive_root,
    )

    status = second.archive_replication.status()

    assert status.pending_count == 0
    assert status.verified_count == 1
    assert status.contiguous_verified_seq == 1
    assert spool_path.exists()

    result = (
        second.archive_replication
        .sync_pending()
    )

    assert result.attempted == 0
    assert result.cleaned_spool_replicas == 1
    assert not spool_path.exists()

    second.stop()


def test_watermark_never_crosses_pending_gap(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"

    first_file = tmp_path / "first.bin"
    second_file = tmp_path / "second.bin"

    first_file.write_bytes(
        b"first pending blob"
    )
    second_file.write_bytes(
        b"second pending blob"
    )

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    first = app.sources.capture_file(
        first_file
    )
    second = app.sources.capture_file(
        second_file
    )

    archive_root.mkdir()

    first_target = (
        archive_root
        / first.blob.storage_locator
    )

    first_target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    first_target.write_bytes(
        b"corrupt gap blocker"
    )

    partial = (
        app.archive_replication
        .sync_pending(
            limit=10
        )
    )

    # Seq 2 may be independently verified.
    assert partial.attempted == 2
    assert partial.verified == 1
    assert partial.failed == 1

    # But seq 1 is still pending, so the
    # contiguous watermark MUST remain zero.
    assert partial.status.pending_count == 1
    assert partial.status.verified_count == 1
    assert (
        partial.status.contiguous_verified_seq
        == 0
    )
    assert partial.status.max_outbox_seq == 2

    _, second_blob = app.sources.get(
        second.source.source_id
    )

    assert (
        second_blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    # Repair the external conflict and retry.
    first_target.unlink()

    complete = (
        app.archive_replication
        .sync_pending(
            limit=10
        )
    )

    assert complete.attempted == 1
    assert complete.verified == 1
    assert complete.failed == 0

    assert complete.status.pending_count == 0
    assert complete.status.verified_count == 2
    assert (
        complete.status.contiguous_verified_seq
        == 2
    )
    assert complete.status.max_outbox_seq == 2

    app.stop()


def test_v30_to_v31_migration_creates_replication_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"

    latest = SQLiteDatabase(path)
    latest.start()
    latest.stop()

    # Reconstruct the exact v30 boundary by removing
    # the additive v31/v32 objects and metadata.
    legacy = sqlite3.connect(
        path,
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
    legacy.row_factory = sqlite3.Row

    # Reconstruct a pre-v32 boundary: remove every additive
    # Protected-Content object before downgrading metadata.
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_blob_reuse")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_delete")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_representation")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_delete")
    legacy.execute("DROP TABLE source_protection_transitions")
    legacy.execute(
        "DROP TABLE protected_sources"
    )

    legacy.execute(
        "DROP TABLE "
        "protected_blob_envelopes"
    )
    legacy.execute(
        "DROP TABLE "
        "protected_payloads"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scope_keys"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scopes"
    )
    legacy.execute(
        "DROP TABLE "
        "key_slots"
    )

    legacy.execute(
        "DROP TRIGGER "
        "trg_blob_records_archive_replication_outbox"
    )
    legacy.execute(
        "DROP TABLE archive_replication_watermark"
    )
    legacy.execute(
        "DROP TABLE archive_replication_outbox"
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
            NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
            NEWS_EVENT_ELIGIBILITY_MIGRATION_ID,
            NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION}"
    )

    legacy.close()

    upgraded = SQLiteDatabase(path)
    upgraded.start()

    try:
        connection = upgraded.connection

        assert (
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            == SCHEMA_VERSION
        )

        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        assert {
            "archive_replication_outbox",
            "archive_replication_watermark",
        }.issubset(tables)

        trigger = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name =
                  'trg_blob_records_archive_replication_outbox'
            """
        ).fetchone()

        assert trigger is not None

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

        assert tuple(metadata) == (
            SCHEMA_VERSION,
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
            SCHEMA_VERSION,
        )

        assert connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []

    finally:
        upgraded.stop()


def test_v30_migration_backfills_existing_spool_blob(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "offline-archive"
    original = tmp_path / "legacy-spool.bin"

    original.write_bytes(
        b"pre-v31 durable spool bytes"
    )

    latest = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = latest.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    latest.stop()

    database_path = (
        local_root
        / "state"
        / "athena.db"
    )

    legacy = sqlite3.connect(
        database_path,
        autocommit=True,
    )

    # Normalize additive v39 state before this
    # fixture declares the database to be an
    # older schema boundary. Production migration
    # behavior remains intentionally fail-closed.
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

    # Reconstruct a pre-v32 boundary: remove every additive
    # Protected-Content object before downgrading metadata.
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_blob_reuse")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_delete")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_representation")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_delete")
    legacy.execute("DROP TABLE source_protection_transitions")
    legacy.execute(
        "DROP TABLE protected_sources"
    )

    legacy.execute(
        "DROP TABLE "
        "protected_blob_envelopes"
    )
    legacy.execute(
        "DROP TABLE "
        "protected_payloads"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scope_keys"
    )
    legacy.execute(
        "DROP TABLE "
        "protection_scopes"
    )
    legacy.execute(
        "DROP TABLE "
        "key_slots"
    )

    legacy.execute(
        "DROP TRIGGER "
        "trg_blob_records_archive_replication_outbox"
    )
    legacy.execute(
        "DROP TABLE archive_replication_watermark"
    )
    legacy.execute(
        "DROP TABLE archive_replication_outbox"
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
            NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
            NEWS_EVENT_ELIGIBILITY_MIGRATION_ID,
            NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{NEWS_EVENT_ELIGIBILITY_SCHEMA_VERSION}"
    )

    legacy.close()

    upgraded = _app(
        local_root,
        archive_root=archive_root,
    )

    status = upgraded.archive_replication.status()

    assert status.pending_count == 1
    assert status.verified_count == 0
    assert status.contiguous_verified_seq == 0
    assert status.max_outbox_seq == 1

    pending = (
        upgraded.archive_replication_repository
        .list_pending()
    )

    assert len(pending) == 1
    assert (
        pending[0].blob.blob_id
        == captured.blob.blob_id
    )

    upgraded.stop()



def test_scheduler_waits_offline_and_resumes_same_job_on_reconnect_after_restart(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "detached-storage"
    original = tmp_path / "offline.bin"
    payload = b"durable scheduler reconnect"

    original.write_bytes(payload)

    first = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = first.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    spool_path = (
        first.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=(
                captured.blob.storage_locator
            ),
        )
    )

    offline = first.job_scheduler.tick(
        worker_id="archive-offline"
    )

    assert (
        offline.selected_job_type
        == "archive.replicate"
    )
    assert offline.action == "waiting"
    assert (
        offline.final_state
        is JobState.WAITING
    )
    assert offline.selected_job_id is not None

    job_id = offline.selected_job_id

    waiting = first.jobs.get(
        job_id
    )

    assert (
        waiting.priority
        is JobPriority.DATA_SAFETY
    )
    assert (
        waiting.blocked_reason
        == WaitingReason.STORAGE.value
    )
    assert waiting.next_run_at_us is not None

    # Long-term storage can legitimately remain offline.
    assert waiting.retry_count == 0
    assert spool_path.read_bytes() == payload

    first.stop()

    # Reconnect before the scheduled retry time.
    archive_root.mkdir()

    second = _app(
        local_root,
        archive_root=archive_root,
    )

    resumed = second.job_scheduler.tick(
        worker_id="archive-reconnected"
    )

    assert (
        resumed.selected_job_id
        == job_id
    )
    assert (
        resumed.selected_job_type
        == "archive.replicate"
    )
    assert resumed.action == "completed"
    assert (
        resumed.final_state
        is JobState.COMPLETED
    )

    final_job = second.jobs.get(
        job_id
    )

    assert final_job.retry_count == 0
    assert final_job.fencing_sequence >= 2

    source, blob = second.sources.get(
        captured.source.source_id
    )

    assert (
        blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    verified = second.sources.verify(
        source.source_id
    )

    assert verified.read_bytes() == payload
    assert verified.is_relative_to(
        archive_root
    )
    assert not spool_path.exists()

    status = (
        second.archive_replication.status()
    )

    assert status.pending_count == 0
    assert (
        status.contiguous_verified_seq
        == 1
    )

    second.stop()


def test_archive_reconcile_reuses_existing_nonterminal_job(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "offline"
    original = tmp_path / "singleton.bin"

    original.write_bytes(
        b"one durable archive job"
    )

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    app.sources.capture_file(
        original
    )

    first = (
        app.archive_replication_worker
        .reconcile_pending()
    )

    second = (
        app.archive_replication_worker
        .reconcile_pending()
    )

    assert first is not None
    assert second is not None
    assert first.job_id == second.job_id

    assert (
        first.priority
        is JobPriority.DATA_SAFETY
    )

    active = app.jobs.active_for_type(
        "archive.replicate"
    )

    assert len(active) == 1

    app.stop()


def test_unconfigured_archive_keeps_outbox_without_p0_retry_churn(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    original = tmp_path / "local-only.bin"
    payload = b"valid local-only archive"

    original.write_bytes(payload)

    app = _app(
        local_root,
        archive_root=None,
    )

    captured = app.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    assert (
        app.archive_replication
        .status()
        .pending_count
        == 1
    )

    tick = app.job_scheduler.tick(
        worker_id="local-only"
    )

    assert tick.idle

    assert (
        app.jobs.active_for_type(
            "archive.replicate"
        )
        == ()
    )

    assert (
        app.sources.verify(
            captured.source.source_id
        ).read_bytes()
        == payload
    )

    app.stop()


def test_scheduler_integrity_conflict_waits_for_user_without_overwrite(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    original = tmp_path / "conflict.bin"
    payload = b"authoritative local bytes"

    original.write_bytes(payload)

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = app.sources.capture_file(
        original
    )

    spool_path = (
        app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=(
                captured.blob.storage_locator
            ),
        )
    )

    archive_root.mkdir()

    target = (
        archive_root
        / captured.blob.storage_locator
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_bytes(
        b"conflicting target bytes"
    )

    tick = app.job_scheduler.tick(
        worker_id="archive-conflict"
    )

    assert (
        tick.selected_job_type
        == "archive.replicate"
    )
    assert tick.action == "waiting"
    assert (
        tick.final_state
        is JobState.WAITING
    )
    assert tick.selected_job_id is not None

    waiting = app.jobs.get(
        tick.selected_job_id
    )

    assert (
        waiting.blocked_reason
        == WaitingReason.USER.value
    )
    assert waiting.next_run_at_us is None
    assert waiting.retry_count == 0

    assert target.read_bytes() == (
        b"conflicting target bytes"
    )

    assert (
        spool_path.read_bytes()
        == payload
    )

    # USER wait must not automatically hammer the target.
    second = app.job_scheduler.tick(
        worker_id="archive-conflict-2"
    )

    assert second.idle

    pending = (
        app.archive_replication_repository
        .list_pending()
    )

    assert len(pending) == 1
    assert pending[0].attempt_count == 1
    assert (
        pending[0].last_error_code
        == "BlobIntegrityError"
    )

    app.stop()


def test_archive_root_relocation_preserves_ids_locator_and_bytes(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    old_root = tmp_path / "old-nas"
    new_root = tmp_path / "future-drive"
    original = tmp_path / "portable.bin"
    payload = b"portable ATHENA archive"

    old_root.mkdir()
    original.write_bytes(payload)

    first = _app(
        local_root,
        archive_root=old_root,
    )

    captured = first.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    source_id = captured.source.source_id
    blob_id = captured.blob.blob_id
    locator = captured.blob.storage_locator

    assert not Path(
        locator
    ).is_absolute()

    assert (
        str(old_root)
        not in locator
    )

    assert (
        first.sources.verify(
            source_id
        ).read_bytes()
        == payload
    )

    first.stop()

    # Simulate moving the entire Archive Root from today's NAS to a future
    # HDD/SSD/NAS/other filesystem-backed storage medium.
    shutil.copytree(
        old_root,
        new_root,
    )

    shutil.rmtree(
        old_root
    )

    second = _app(
        local_root,
        archive_root=new_root,
    )

    source, blob = second.sources.get(
        source_id
    )

    assert source.source_id == source_id
    assert source.blob_id == blob_id
    assert blob.blob_id == blob_id
    assert blob.storage_locator == locator

    assert (
        blob.storage_area
        is BlobStorageArea.ARCHIVE
    )

    moved = second.sources.verify(
        source_id
    )

    assert moved.is_relative_to(
        new_root
    )
    assert moved.read_bytes() == payload

    row = (
        second.database.connection.execute(
            """
            SELECT storage_locator
            FROM blob_records
            WHERE blob_id = ?
            """,
            (
                blob_id.bytes,
            ),
        ).fetchone()
    )

    assert row is not None

    persisted = str(
        row["storage_locator"]
    )

    assert persisted == locator
    assert str(old_root) not in persisted
    assert str(new_root) not in persisted

    second.stop()


def test_streaming_archive_copy_reports_progress(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "local"
    archive_root = tmp_path / "archive"
    original = tmp_path / "large.bin"

    payload = (
        b"0123456789abcdef"
        * (
            3
            * 1024
            * 1024
            // 16
            + 1
        )
    )

    original.write_bytes(payload)

    app = _app(
        local_root,
        archive_root=archive_root,
    )

    captured = app.sources.capture_file(
        original
    )

    assert (
        captured.blob.storage_area
        is BlobStorageArea.SPOOL
    )

    archive_root.mkdir()

    callback_count = 0

    def progress() -> None:
        nonlocal callback_count
        callback_count += 1

    target = (
        app.blob_store
        .replicate_spool_blob_to_archive(
            storage_locator=(
                captured.blob.storage_locator
            ),
            expected_sha256=(
                captured.blob.integrity_sha256
            ),
            expected_length=(
                captured.blob.byte_length
            ),
            progress_callback=progress,
        )
    )

    assert target.read_bytes() == payload

    # Source verification, streaming copy, temp verification and target
    # read-back all expose lease-renewal opportunities.
    assert callback_count >= 4

    app.stop()
