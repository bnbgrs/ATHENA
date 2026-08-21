from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.security.service import (
    ProtectedContentIntegrityError,
    ProtectionScopeLockedError,
)
from athena.source.models import BlobStorageArea
from athena.source.protected_blob import (
    PROTECTED_BLOB_CHUNK_SIZE,
    PROTECTED_BLOB_ENCRYPTION_STATE,
)
from athena.source.representation_store import UnsupportedTextSourceError
from athena.source.service import ProtectedSourcePersistentPathUnavailableError
from athena.storage.schema import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    SCHEMA_VERSION,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
)


def _app(
    local_root: Path,
    *,
    archive_root: Path | None = None,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=local_root,
            archive_root=archive_root,
        )
    )
    app.start()
    return app


def _new_scope(
    app: AthenaApplication,
    *,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )
    scope = app.protected_content.create_scope(
        password,
        neutral_label="P1",
    )
    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )
    return scope


def test_fresh_schema_is_v33_and_allows_protected_blob_records(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    try:
        connection = app.database.connection
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == SCHEMA_VERSION
            == SCHEMA_VERSION
        )
        metadata = connection.execute(
            """
            SELECT schema_version, last_migration_id, minimum_reader_version
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
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "protected_sources" in tables
        blob_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'blob_records'
            """
        ).fetchone()
        assert blob_sql is not None
        assert "protected_v1" in str(blob_sql[0])
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        app.stop()


def test_protected_multichunk_file_is_ciphertext_only_and_roundtrips(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    original = tmp_path / "SECRET_FILENAME_CANARY_73A1.txt"
    canary = b"PROTECTED_FILE_CANARY_73A1"
    payload = canary + b"A" * (PROTECTED_BLOB_CHUNK_SIZE + 137)
    original.write_bytes(payload)
    password = b"protected-file-password"
    app = _app(runtime)
    try:
        scope = _new_scope(app, password=password)
        captured = app.sources.capture_protected_file(
            original,
            protection_scope_id=scope.protection_scope_id,
        )
        source = captured.source
        blob = captured.blob
        assert not captured.reused_blob
        assert source.protection_scope_id == scope.protection_scope_id
        assert source.protected_metadata_payload_id is not None
        assert source.original_name is None
        assert source.original_modified_at_us is None
        assert source.source_uri is None
        assert source.mime_type == "application/octet-stream"
        assert blob.media_type == "application/octet-stream"
        assert blob.encryption_state == PROTECTED_BLOB_ENCRYPTION_STATE
        assert source.content_sha256 == blob.integrity_sha256

        ciphertext_path = app.blob_store.resolve_blob_path(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
        )
        ciphertext = ciphertext_path.read_bytes()
        assert canary not in ciphertext
        assert hashlib.sha256(ciphertext).digest() == blob.integrity_sha256
        assert len(ciphertext) == blob.byte_length

        envelope = app.source_repository.get_protected_blob_envelope(blob.blob_id)
        assert len(envelope.nonce_prefix) == 8
        assert envelope.chunk_size == PROTECTED_BLOB_CHUNK_SIZE
        assert len(envelope.wrapped_dek) == 48
        assert len(envelope.dek_wrap_nonce) == 12

        metadata = app.sources.load_protected_metadata(source.source_id)
        assert metadata.original_name == original.name
        assert metadata.source_uri == original.resolve().as_uri()
        assert metadata.mime_type == "text/plain"
        assert metadata.plaintext_byte_length == len(payload)
        assert app.sources.read_protected_bytes(source.source_id) == payload

        with pytest.raises(ProtectedSourcePersistentPathUnavailableError):
            app.sources.verify(source.source_id)

        app.protected_content.lock_scope(scope.protection_scope_id)
        with pytest.raises(ProtectionScopeLockedError):
            app.sources.read_protected_bytes(source.source_id)
        with pytest.raises(ProtectionScopeLockedError):
            app.sources.verify(source.source_id)
    finally:
        app.stop()

    for path in runtime.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert canary not in data, path
            assert original.name.encode("ascii") not in data, path
            assert password not in data, path


def test_protected_duplicates_do_not_deduplicate_and_restart_is_locked(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    original = tmp_path / "duplicate.bin"
    payload = b"same protected plaintext"
    original.write_bytes(payload)
    password = b"no-clear-dedup"
    first_app = _app(runtime)
    scope = _new_scope(first_app, password=password)
    first = first_app.sources.capture_protected_file(
        original,
        protection_scope_id=scope.protection_scope_id,
    )
    second = first_app.sources.capture_protected_file(
        original,
        protection_scope_id=scope.protection_scope_id,
    )
    assert first.blob.blob_id != second.blob.blob_id
    assert first.blob.integrity_sha256 != second.blob.integrity_sha256
    assert not first.reused_blob
    assert not second.reused_blob
    source_id = first.source.source_id
    first_app.stop()

    restarted = _app(runtime)
    try:
        assert not restarted.protected_content.is_unlocked(
            scope.protection_scope_id
        )
        with pytest.raises(ProtectionScopeLockedError):
            restarted.sources.read_protected_bytes(source_id)
        restarted.protected_content.unlock_scope(
            scope.protection_scope_id,
            password,
        )
        assert restarted.sources.read_protected_bytes(source_id) == payload
    finally:
        restarted.stop()


def test_protected_blob_tamper_with_recomputed_public_hash_fails_gcm(
    tmp_path: Path,
) -> None:
    original = tmp_path / "tamper.bin"
    original.write_bytes(b"tamper protected bytes")
    password = b"tamper-source-password"
    app = _app(tmp_path / "runtime")
    try:
        scope = _new_scope(app, password=password)
        captured = app.sources.capture_protected_file(
            original,
            protection_scope_id=scope.protection_scope_id,
        )
        blob = captured.blob
        path = app.blob_store.resolve_blob_path(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
        )
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 0x01
        path.write_bytes(raw)
        new_hash = hashlib.sha256(raw).digest()
        with app.database.write_transaction() as connection:
            connection.execute(
                "UPDATE blob_records SET integrity_sha256 = ? WHERE blob_id = ?",
                (new_hash, blob.blob_id.bytes),
            )
            connection.execute(
                "UPDATE sources SET content_sha256 = ? WHERE source_id = ?",
                (new_hash, captured.source.source_id.bytes),
            )
        with pytest.raises(
            ProtectedContentIntegrityError,
            match="authentication failed",
        ):
            app.sources.read_protected_bytes(captured.source.source_id)
    finally:
        app.stop()


def test_protected_spool_replication_moves_ciphertext_only(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    archive = tmp_path / "archive"
    original = tmp_path / "archive-protected.bin"
    canary = b"ARCHIVE_PROTECTED_CANARY_9182"
    payload = canary + b"-payload"
    original.write_bytes(payload)
    password = b"archive-protected-password"
    app = _app(runtime, archive_root=archive)
    try:
        scope = _new_scope(app, password=password)
        captured = app.sources.capture_protected_file(
            original,
            protection_scope_id=scope.protection_scope_id,
        )
        assert captured.blob.storage_area is BlobStorageArea.SPOOL
        spool_path = app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.SPOOL,
            storage_locator=captured.blob.storage_locator,
        )
        assert canary not in spool_path.read_bytes()
        archive.mkdir()
        synced = app.archive_replication.sync_pending()
        assert synced.failed == 0
        assert synced.verified == 1
        source, promoted = app.sources.get(captured.source.source_id)
        assert promoted.storage_area is BlobStorageArea.ARCHIVE
        archive_path = app.blob_store.resolve_blob_path(
            storage_area=BlobStorageArea.ARCHIVE,
            storage_locator=promoted.storage_locator,
        )
        assert canary not in archive_path.read_bytes()
        assert app.sources.read_protected_bytes(source.source_id) == payload
    finally:
        app.stop()


def test_normal_text_processing_fails_closed_on_protected_source(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    original = tmp_path / "PROCESSING_CANARY_4419.txt"
    canary = b"PROCESSING_CANARY_4419"
    original.write_bytes(canary + b" protected text")
    password = b"processing-block-password"
    app = _app(runtime)
    try:
        scope = _new_scope(app, password=password)
        captured = app.sources.capture_protected_file(
            original,
            protection_scope_id=scope.protection_scope_id,
        )
        with pytest.raises(UnsupportedTextSourceError):
            app.source_text.build(captured.source.source_id)
    finally:
        app.stop()

    derived_root = runtime / "derived"
    if derived_root.exists():
        for path in derived_root.rglob("*"):
            if path.is_file():
                assert canary not in path.read_bytes()
