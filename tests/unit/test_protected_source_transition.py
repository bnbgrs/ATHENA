from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.security.service import ProtectionScopeLockedError
from athena.source.protection_transition import (
    SourceProtectionTransitionState,
    SourceProtectionUnsafeError,
)
from athena.source.repository import SourceProtectionTransitionPendingError
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
    PROTECTED_SOURCE_BLOB_MIGRATION_ID,
    PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
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


def _scope(
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
        neutral_label="transition-test",
    )
    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )
    return scope


def test_existing_source_transition_preserves_identity_and_removes_runtime_plaintext(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "runtime"
    original = tmp_path / "ATHENA_METADATA_CANARY_93A9E321.txt"
    canary = b"ATHENA_TRANSITION_CANARY_93A9E321"
    password = b"transition-password-93A9E321"
    original.write_bytes(canary)

    app = _app(local_root)
    scope = _scope(app, password=password)
    captured = app.sources.capture_file(original)
    source_id = captured.source.source_id
    old_blob_id = captured.blob.blob_id
    old_path = app.blob_store.resolve_blob_path(
        storage_area=captured.blob.storage_area,
        storage_locator=captured.blob.storage_locator,
    )
    assert old_path.read_bytes() == canary
    before = app.archive_replication.status()
    assert before.pending_count == 1
    assert before.contiguous_verified_seq == 0
    assert before.max_outbox_seq == 1

    protected = app.sources.protect_existing_source(
        source_id,
        scope.protection_scope_id,
    )

    assert protected.source.source_id == source_id
    assert protected.blob.blob_id != old_blob_id
    assert protected.blob.encryption_state == "protected_v1"
    assert protected.source.protection_scope_id == scope.protection_scope_id
    assert protected.source.protected_metadata_payload_id is not None
    assert protected.source.original_name is None
    assert protected.source.original_modified_at_us is None
    assert protected.source.source_uri is None
    assert protected.source.mime_type == "application/octet-stream"
    assert protected.source.content_sha256 == protected.blob.integrity_sha256
    assert not old_path.exists()

    metadata = app.sources.load_protected_metadata(source_id)
    assert metadata.original_name == original.name
    assert metadata.source_uri == original.resolve().as_uri()
    assert metadata.mime_type == "text/plain"
    assert metadata.plaintext_byte_length == len(canary)
    assert app.sources.read_protected_bytes(source_id) == canary

    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM blob_records WHERE blob_id = ?",
        (old_blob_id.bytes,),
    ).fetchone()[0] == 0
    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM source_protection_transitions"
    ).fetchone()[0] == 0
    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM archive_replication_outbox WHERE blob_id = ?",
        (old_blob_id.bytes,),
    ).fetchone()[0] == 0

    after = app.archive_replication.status()
    assert after.pending_count == 1
    assert after.verified_count == 0
    assert after.contiguous_verified_seq == 1
    assert after.max_outbox_seq == 2

    app.stop()

    scanned = 0
    for path in local_root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        scanned += 1
        assert canary not in data, path
        assert password not in data, path
    assert scanned > 0
    metadata_canary = original.name.encode("ascii")
    uri_canary = original.resolve().as_uri().encode("ascii")
    for path in local_root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert metadata_canary not in data, path
        assert uri_canary not in data, path


def test_prepared_transition_recovers_after_restart_without_unlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_root = tmp_path / "restart-runtime"
    original = tmp_path / "restart-transition.txt"
    canary = b"ATHENA_PREPARED_RESTART_CANARY_4C9D"
    password = b"prepared-restart-password"
    original.write_bytes(canary)

    first = _app(local_root)
    scope = _scope(first, password=password)
    captured = first.sources.capture_file(original)
    old_path = first.blob_store.resolve_blob_path(
        storage_area=captured.blob.storage_area,
        storage_locator=captured.blob.storage_locator,
    )

    class SyntheticCrash(RuntimeError):
        pass

    def crash_sanitize(
        *,
        transition_id: object,
    ) -> object:
        del transition_id
        raise SyntheticCrash("after plaintext delete before DB sanitization")

    monkeypatch.setattr(
        first.source_protection_repository,
        "sanitize_prepared",
        crash_sanitize,
    )

    with pytest.raises(SyntheticCrash):
        first.sources.protect_existing_source(
            captured.source.source_id,
            scope.protection_scope_id,
        )

    transition = first.source_protection_repository.get_for_source(
        captured.source.source_id
    )
    assert transition is not None
    assert transition.state is SourceProtectionTransitionState.PREPARED
    assert transition.target_blob_id is not None
    assert not old_path.exists()

    with pytest.raises(SourceProtectionTransitionPendingError):
        first.sources.get(captured.source.source_id)

    first.stop()

    second = _app(local_root)
    try:
        assert second.source_protection_repository.get_for_source(
            captured.source.source_id
        ) is None
        source, blob = second.sources.get(captured.source.source_id)
        assert source.protection_scope_id == scope.protection_scope_id
        assert blob.encryption_state == "protected_v1"
        assert not second.protected_content.is_unlocked(
            scope.protection_scope_id
        )
        with pytest.raises(ProtectionScopeLockedError):
            second.sources.read_protected_bytes(captured.source.source_id)

        second.protected_content.unlock_scope(
            scope.protection_scope_id,
            password,
        )
        assert (
            second.sources.read_protected_bytes(captured.source.source_id)
            == canary
        )
    finally:
        second.stop()


def test_sanitized_transition_recovers_after_checkpoint_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_root = tmp_path / "sanitized-runtime"
    original = tmp_path / "ATHENA_SANITIZE_METADATA_CANARY_E51C.txt"
    canary = b"ATHENA_SANITIZED_RESTART_CANARY_E51C"
    password = b"sanitized-restart-password"
    original.write_bytes(canary)

    first = _app(local_root)
    scope = _scope(first, password=password)
    captured = first.sources.capture_file(original)

    class SyntheticCheckpointCrash(RuntimeError):
        pass

    def crash_checkpoint() -> None:
        raise SyntheticCheckpointCrash("after DB sanitization before WAL scrub")

    monkeypatch.setattr(
        first.source_protection_repository,
        "checkpoint_plaintext_scrub",
        crash_checkpoint,
    )

    with pytest.raises(SyntheticCheckpointCrash):
        first.sources.protect_existing_source(
            captured.source.source_id,
            scope.protection_scope_id,
        )

    transition = first.source_protection_repository.get_for_source(
        captured.source.source_id
    )
    assert transition is not None
    assert transition.state is SourceProtectionTransitionState.SANITIZED

    row = first.database.connection.execute(
        """
        SELECT
            original_name,
            original_modified_at_us,
            mime_type,
            source_uri,
            blob_id
        FROM sources
        WHERE source_id = ?
        """,
        (captured.source.source_id.bytes,),
    ).fetchone()
    assert row is not None
    assert row["original_name"] is None
    assert row["original_modified_at_us"] is None
    assert row["source_uri"] is None
    assert row["mime_type"] == "application/octet-stream"
    assert transition.target_blob_id is not None
    assert bytes(row["blob_id"]) == transition.target_blob_id.bytes

    with pytest.raises(SourceProtectionTransitionPendingError):
        first.sources.get(captured.source.source_id)

    first.stop()

    second = _app(local_root)
    try:
        assert second.source_protection_repository.get_for_source(
            captured.source.source_id
        ) is None
        with pytest.raises(ProtectionScopeLockedError):
            second.sources.read_protected_bytes(captured.source.source_id)
        second.protected_content.unlock_scope(
            scope.protection_scope_id,
            password,
        )
        assert (
            second.sources.read_protected_bytes(captured.source.source_id)
            == canary
        )
    finally:
        second.stop()


def test_shared_unprotected_blob_fails_closed_before_transition(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    password = b"shared-blob-password"
    scope = _scope(app, password=password)
    first_path = tmp_path / "shared-a.txt"
    second_path = tmp_path / "shared-b.txt"
    payload = b"shared raw blob"
    first_path.write_bytes(payload)
    second_path.write_bytes(payload)

    first = app.sources.capture_file(first_path)
    second = app.sources.capture_file(second_path)
    assert first.blob.blob_id == second.blob.blob_id

    with pytest.raises(SourceProtectionUnsafeError):
        app.sources.protect_existing_source(
            first.source.source_id,
            scope.protection_scope_id,
        )

    assert app.source_protection_repository.get_for_source(
        first.source.source_id
    ) is None
    current, blob = app.sources.get(first.source.source_id)
    assert current.protection_scope_id is None
    assert blob.encryption_state == "none"
    app.stop()


def test_existing_persistent_representation_blocks_protection(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    password = b"representation-block-password"
    scope = _scope(app, password=password)
    original = tmp_path / "represented.txt"
    original.write_text(
        "plain representation must block later protection",
        encoding="utf-8",
    )
    captured = app.sources.capture_file(original)
    app.source_text.build(captured.source.source_id)

    with pytest.raises(SourceProtectionUnsafeError):
        app.sources.protect_existing_source(
            captured.source.source_id,
            scope.protection_scope_id,
        )

    assert app.source_protection_repository.get_for_source(
        captured.source.source_id
    ) is None
    app.stop()


def test_pending_transition_blocks_source_reuse_updates_and_representations(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "runtime")
    password = b"transition-guard-password"
    scope = _scope(app, password=password)
    original = tmp_path / "guarded.txt"
    original.write_text("guarded transition bytes", encoding="utf-8")
    captured = app.sources.capture_file(original)

    transition = app.source_protection_repository.begin(
        source_id=captured.source.source_id,
        protection_scope_id=scope.protection_scope_id,
    )
    assert transition.state is SourceProtectionTransitionState.PENDING

    trigger_names = {
        str(row[0])
        for row in app.database.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name LIKE 'trg_source_protection_transition_%'
            """
        )
    }
    assert trigger_names == {
        "trg_source_protection_transition_block_blob_reuse",
        "trg_source_protection_transition_block_source_update",
        "trg_source_protection_transition_block_source_delete",
        "trg_source_protection_transition_block_representation",
        "trg_source_protection_transition_block_old_blob_update",
        "trg_source_protection_transition_block_old_blob_delete",
    }

    with pytest.raises(SourceProtectionTransitionPendingError):
        app.sources.get(captured.source.source_id)

    with pytest.raises(SourceProtectionTransitionPendingError):
        app.source_text.build(captured.source.source_id)

    duplicate = tmp_path / "guarded-copy.txt"
    duplicate.write_text("guarded transition bytes", encoding="utf-8")
    with pytest.raises(sqlite3.IntegrityError, match="source protection transition"):
        app.sources.capture_file(duplicate)

    with pytest.raises(sqlite3.IntegrityError, match="source protection transition"):
        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE sources
                SET lifecycle_state = lifecycle_state
                WHERE source_id = ?
                """,
                (captured.source.source_id.bytes,),
            )

    with pytest.raises(sqlite3.IntegrityError, match="source protection transition"):
        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE blob_records
                SET verified_at_us = verified_at_us
                WHERE blob_id = ?
                """,
                (captured.blob.blob_id.bytes,),
            )

    app.stop()


def test_v33_database_upgrades_additively_to_transition_v34(
    tmp_path: Path,
) -> None:
    path = tmp_path / "athena.db"
    latest = SQLiteDatabase(path)
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
    legacy.row_factory = sqlite3.Row

    trigger_names = (
        "trg_source_protection_transition_block_blob_reuse",
        "trg_source_protection_transition_block_source_update",
        "trg_source_protection_transition_block_source_delete",
        "trg_source_protection_transition_block_representation",
        "trg_source_protection_transition_block_old_blob_update",
        "trg_source_protection_transition_block_old_blob_delete",
    )
    for trigger_name in trigger_names:
        legacy.execute(
            f"DROP TRIGGER {trigger_name}"
        )
    legacy.execute(
        "DROP TABLE source_protection_transitions"
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
            PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
            PROTECTED_SOURCE_BLOB_MIGRATION_ID,
            PROTECTED_SOURCE_BLOB_SCHEMA_VERSION,
        ),
    )
    legacy.execute(
        f"PRAGMA user_version = {PROTECTED_SOURCE_BLOB_SCHEMA_VERSION}"
    )
    legacy.close()

    upgraded = SQLiteDatabase(path)
    upgraded.start()
    try:
        connection = upgraded.connection
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] == SCHEMA_VERSION
        assert SCHEMA_VERSION == SCHEMA_VERSION
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
        assert "source_protection_transitions" in tables
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
