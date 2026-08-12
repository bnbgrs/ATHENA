from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.blob_store import (
    BlobIntegrityError,
    SourceChangedDuringCaptureError,
    SourceFileNotReadableError,
)
from athena.source.models import BlobStorageArea, SourceLifecycleState


def _started_app(tmp_path: Path, *, archive_root: Path | None = None) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "local",
            archive_root=archive_root,
        )
    )
    app.start()
    return app


def test_file_capture_survives_restart_with_identical_original_bytes(tmp_path) -> None:
    original = tmp_path / "example.txt"
    payload = ("ATHENA raw archive\n" * 2048).encode()
    original.write_bytes(payload)

    first = _started_app(tmp_path)
    result = first.sources.capture_file(original)
    source_id = result.source.source_id

    assert result.source.lifecycle_state is SourceLifecycleState.CAPTURED
    assert result.blob.storage_area is BlobStorageArea.SPOOL
    assert result.blob.byte_length == len(payload)
    assert result.source.content_sha256 == result.blob.integrity_sha256
    stored_path = first.sources.verify(source_id)
    assert stored_path.read_bytes() == payload
    first.stop()

    second = _started_app(tmp_path)
    source, blob = second.sources.get(source_id)
    assert source.source_id == source_id
    assert source.blob_id == blob.blob_id
    assert second.sources.verify(source_id).read_bytes() == payload
    second.stop()


def test_byte_identical_imports_keep_distinct_sources_but_reuse_blob(tmp_path) -> None:
    original = tmp_path / "duplicate.bin"
    original.write_bytes(b"same immutable bytes")

    app = _started_app(tmp_path)
    first = app.sources.capture_file(original)
    second = app.sources.capture_file(original)

    assert first.source.source_id != second.source.source_id
    assert first.blob.blob_id == second.blob.blob_id
    assert not first.reused_blob
    assert second.reused_blob
    assert app.database.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
    assert app.database.connection.execute("SELECT COUNT(*) FROM blob_records").fetchone()[0] == 1
    app.stop()


def test_reachable_archive_root_is_preferred_over_spool(tmp_path) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    original = tmp_path / "document.pdf"
    original.write_bytes(b"%PDF-1.7\nminimal-test")

    app = _started_app(tmp_path, archive_root=archive_root)
    result = app.sources.capture_file(original)

    assert result.blob.storage_area is BlobStorageArea.ARCHIVE
    stored_path = app.sources.verify(result.source.source_id)
    assert stored_path.is_relative_to(archive_root)
    assert stored_path.read_bytes() == original.read_bytes()
    assert result.source.mime_type == "application/pdf"
    app.stop()


def test_missing_archive_root_falls_back_to_durable_spool(tmp_path) -> None:
    archive_root = tmp_path / "offline-archive"
    original = tmp_path / "offline.txt"
    original.write_text("safe locally", encoding="utf-8")

    app = _started_app(tmp_path, archive_root=archive_root)
    result = app.sources.capture_file(original)

    assert not archive_root.exists()
    assert result.blob.storage_area is BlobStorageArea.SPOOL
    assert app.sources.verify(result.source.source_id).read_text(encoding="utf-8") == "safe locally"
    app.stop()


def test_integrity_verification_fails_closed_after_blob_corruption(tmp_path) -> None:
    original = tmp_path / "integrity.txt"
    original.write_text("original", encoding="utf-8")

    app = _started_app(tmp_path)
    result = app.sources.capture_file(original)
    stored_path = app.blob_store.resolve_blob_path(
        storage_area=result.blob.storage_area,
        storage_locator=result.blob.storage_locator,
    )
    stored_path.write_text("corrupt", encoding="utf-8")

    with pytest.raises(BlobIntegrityError, match="integrity verification failed"):
        app.sources.verify(result.source.source_id)
    app.stop()


def test_single_file_capture_rejects_symlink(tmp_path) -> None:
    original = tmp_path / "target.txt"
    original.write_text("target", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("Symlink creation is unavailable in this environment.")

    app = _started_app(tmp_path)
    with pytest.raises(SourceFileNotReadableError, match="does not follow symbolic-link"):
        app.sources.capture_file(link)
    assert app.database.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    app.stop()


def test_source_capture_registers_raw_archive_entities_and_provenance(tmp_path) -> None:
    original = tmp_path / "provenance.txt"
    original.write_text("trace me", encoding="utf-8")

    app = _started_app(tmp_path)
    result = app.sources.capture_file(original)
    rows = app.database.connection.execute(
        """
        SELECT entity_id, entity_type, domain
        FROM entity_registry
        WHERE entity_id IN (?, ?)
        ORDER BY entity_type
        """,
        (result.blob.blob_id.bytes, result.source.source_id.bytes),
    ).fetchall()
    assert [(str(row["entity_type"]), str(row["domain"])) for row in rows] == [
        ("blob_record", "raw_archive"),
        ("source", "raw_archive"),
    ]
    provenance = app.database.connection.execute(
        """
        SELECT operation, subject_entity_id
        FROM provenance_records
        WHERE provenance_id = ?
        """,
        (result.source.provenance_id.bytes,),
    ).fetchone()
    assert provenance is not None
    assert provenance["operation"] == "source.capture.file"
    assert bytes(provenance["subject_entity_id"]) == result.source.source_id.bytes
    app.stop()


def test_source_change_during_streaming_fails_before_source_commit(
    tmp_path, monkeypatch
) -> None:
    import athena.source.blob_store as blob_store_module

    original = tmp_path / "changing.txt"
    original.write_text("stable at start", encoding="utf-8")
    initial_stat = original.stat()

    app = _started_app(tmp_path)
    real_fsync = blob_store_module.os.fsync
    mutated = False

    def fsync_then_mutate_source(fd: int) -> None:
        nonlocal mutated
        real_fsync(fd)
        if mutated:
            return
        mutated = True
        blob_store_module.os.utime(
            original,
            ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns + 5_000_000_000),
        )

    monkeypatch.setattr(blob_store_module.os, "fsync", fsync_then_mutate_source)

    try:
        with pytest.raises(SourceChangedDuringCaptureError, match="changed while ATHENA"):
            app.sources.capture_file(original)
        assert mutated
        assert app.database.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    finally:
        app.stop()
