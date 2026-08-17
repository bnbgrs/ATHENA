from __future__ import annotations

from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.security.service import ProtectionScopeLockedError
from athena.source.models import BlobStorageArea

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
        settings=AthenaSettings(
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
        neutral_label="Backup protected scope",
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def _assert_no_plaintext(
    root: Path,
    *,
    forbidden: tuple[bytes, ...],
) -> None:
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue

        data = candidate.read_bytes()

        for needle in forbidden:
            assert needle not in data, (
                f"Plaintext canary leaked into {candidate}"
            )


def test_protected_backup_is_ciphertext_only_and_restores_locked(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    backup_root = tmp_path / "backup"
    restored_root = tmp_path / "restored"

    filename = (
        "BACKUP_SECRET_FILENAME_CANARY_14D.txt"
    )

    canary = (
        b"BACKUP_PROTECTED_PLAINTEXT_CANARY_14D_"
        b"6C98318A"
    )

    password = (
        b"slice14d-backup-password-6C98318A"
    )

    payload = (
        canary
        + b"\n"
        + b"protected backup restore evidence"
    )

    original = tmp_path / filename
    original.write_bytes(payload)

    app = _app(runtime)

    try:
        scope = _new_scope(
            app,
            password=password,
        )

        captured = (
            app.sources.capture_protected_file(
                original,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
            )
        )

        source_id = (
            captured.source.source_id
        )

        scope_id = (
            scope.protection_scope_id
        )

        assert (
            captured.blob.encryption_state
            != "plaintext"
        )

        # Backup creation and verification must never require
        # the protection scope to remain unlocked.
        app.protected_content.lock_scope(
            scope_id
        )

        assert not (
            app.protected_content.is_unlocked(
                scope_id
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=backup_root,
            )
        )

        assert snapshot.state == "complete"
        assert (
            snapshot.verification_status
            == "verified_light"
        )

        deep = app.backup.verify_deep(
            snapshot.snapshot_id
        )

        assert (
            deep.verification_status
            == "verified_deep"
        )

        # Backup target itself must contain no protected
        # plaintext, filename metadata or password material.
        _assert_no_plaintext(
            backup_root,
            forbidden=(
                canary,
                filename.encode("ascii"),
                password,
            ),
        )

        app.backup.restore_to(
            snapshot.snapshot_id,
            destination_root=restored_root,
        )

        _assert_no_plaintext(
            restored_root,
            forbidden=(
                canary,
                filename.encode("ascii"),
                password,
            ),
        )

    finally:
        app.stop()

    restored = _app(
        restored_root
    )

    try:
        # Unlock state is process-memory only and must not
        # survive the backup or disaster restore.
        assert not (
            restored.protected_content.is_unlocked(
                scope_id
            )
        )

        with pytest.raises(
            ProtectionScopeLockedError
        ):
            restored.sources.read_protected_bytes(
                source_id
            )

        restored.protected_content.unlock_scope(
            scope_id,
            password,
        )

        assert (
            restored.sources.read_protected_bytes(
                source_id
            )
            == payload
        )

        # Successful decryption must remain ephemeral:
        # reading the protected source may not materialize
        # the plaintext into persistent runtime storage.
        _assert_no_plaintext(
            restored_root,
            forbidden=(
                canary,
                filename.encode("ascii"),
                password,
            ),
        )

    finally:
        restored.stop()


def test_archive_offline_backup_uses_pending_spool_then_reconnects(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    archive_root = tmp_path / "offline-archive"
    backup_root = tmp_path / "backup"

    canary = (
        b"BACKUP_OFFLINE_ARCHIVE_CANARY_14D_"
        b"9A87C4E1"
    )

    password = (
        b"slice14d-offline-password-9A87C4E1"
    )

    original = (
        tmp_path
        / "OFFLINE_PROTECTED_CANARY_14D.bin"
    )

    payload = (
        canary
        + b"-authoritative-local-spool"
    )

    original.write_bytes(
        payload
    )

    app = _app(
        runtime,
        archive_root=archive_root,
    )

    try:
        scope = _new_scope(
            app,
            password=password,
        )

        captured = (
            app.sources.capture_protected_file(
                original,
                protection_scope_id=(
                    scope.protection_scope_id
                ),
            )
        )

        assert not archive_root.exists()

        assert (
            captured.blob.storage_area
            is BlobStorageArea.SPOOL
        )

        initial_status = (
            app.archive_replication.status()
        )

        assert (
            initial_status.pending_count
            == 1
        )

        spool_path = (
            app.blob_store.resolve_blob_path(
                storage_area=(
                    BlobStorageArea.SPOOL
                ),
                storage_locator=(
                    captured.blob.storage_locator
                ),
            )
        )

        assert spool_path.is_file()
        assert (
            canary
            not in spool_path.read_bytes()
        )

        # Prove backup does not depend on Archive availability
        # or an unlocked protection scope.
        app.protected_content.lock_scope(
            scope.protection_scope_id
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=backup_root,
            )
        )

        assert snapshot.state == "complete"

        deep_before_sync = (
            app.backup.verify_deep(
                snapshot.snapshot_id
            )
        )

        assert (
            deep_before_sync.verification_status
            == "verified_deep"
        )

        _assert_no_plaintext(
            backup_root,
            forbidden=(
                canary,
                password,
                original.name.encode("ascii"),
            ),
        )

        # Archive returns later. Replication must verify the
        # ciphertext target before changing durable metadata
        # or removing the local spool replica.
        archive_root.mkdir()

        synced = (
            app.archive_replication.sync_pending()
        )

        assert synced.failed == 0
        assert synced.verified == 1
        assert (
            synced.cleaned_spool_replicas
            == 1
        )

        assert (
            synced.status.pending_count
            == 0
        )

        source, promoted = (
            app.sources.get(
                captured.source.source_id
            )
        )

        assert (
            promoted.storage_area
            is BlobStorageArea.ARCHIVE
        )

        assert not spool_path.exists()

        archive_path = (
            app.blob_store.resolve_blob_path(
                storage_area=(
                    BlobStorageArea.ARCHIVE
                ),
                storage_locator=(
                    promoted.storage_locator
                ),
            )
        )

        assert archive_path.is_file()

        assert (
            canary
            not in archive_path.read_bytes()
        )

        # The backup is independent of the later live-spool
        # cleanup and remains a valid restore point.
        deep_after_sync = (
            app.backup.verify_deep(
                snapshot.snapshot_id
            )
        )

        assert (
            deep_after_sync.verification_status
            == "verified_deep"
        )

        app.protected_content.unlock_scope(
            scope.protection_scope_id,
            password,
        )

        assert (
            app.sources.read_protected_bytes(
                source.source_id
            )
            == payload
        )

    finally:
        app.stop()
