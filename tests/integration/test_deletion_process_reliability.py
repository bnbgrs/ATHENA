from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters

_CHILD = r'''
from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.repository import SourceNotFoundError


def app_for(root: Path) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=root,
        )
    )
    app.start()
    return app


operation = sys.argv[1]


if operation == "delete-source":
    runtime = Path(sys.argv[2])
    source_id = uuid.UUID(sys.argv[3])
    digest = sys.argv[4]

    app = app_for(runtime)

    try:
        try:
            result = app.lifecycle_deletion.delete(
                source_id,
                preview_digest=digest,
            )
        except Exception as exc:
            expected = {
                "LifecycleDeletionAlreadyDeletedError",
                "LifecycleDeletionNotFoundError",
                "LifecycleDeletionPreviewStaleError",
            }

            if exc.__class__.__name__ not in expected:
                raise

            print(
                "ALREADY:"
                + exc.__class__.__name__
            )
        else:
            print(
                "DELETED:"
                + str(result.commit_id)
            )
    finally:
        app.stop()


elif operation == "restart-sync":
    runtime = Path(sys.argv[2])

    app = app_for(runtime)

    try:
        connection = app.database.connection

        local_watermark = int(
            connection.execute(
                "SELECT COALESCE(MAX(ledger_seq), 0) "
                "FROM deletion_ledger"
            ).fetchone()[0]
        )

        targets = connection.execute(
            "SELECT deletion_ledger_watermark "
            "FROM backup_targets "
            "ORDER BY target_id"
        ).fetchall()

        if not targets:
            raise AssertionError(
                "Registered backup target disappeared."
            )

        for row in targets:
            if (
                int(
                    row[
                        "deletion_ledger_watermark"
                    ]
                )
                != local_watermark
            ):
                raise AssertionError(
                    "Restart did not catch the target "
                    "Deletion Ledger up to the local watermark."
                )

        print(
            "SYNCED:"
            + str(local_watermark)
        )
    finally:
        app.stop()


elif operation == "purge-source":
    runtime = Path(sys.argv[2])
    source_id = uuid.UUID(sys.argv[3])

    app = app_for(runtime)

    try:
        result = (
            app.lifecycle_purge
            .purge_deleted_source_blob(
                source_id
            )
        )

        print(
            "PURGED:"
            + str(
                result.deleted_replica_count
            )
        )
    finally:
        app.stop()


elif operation == "delete-scope":
    runtime = Path(sys.argv[2])
    scope_id = uuid.UUID(sys.argv[3])
    digest = sys.argv[4]

    app = app_for(runtime)

    try:
        try:
            result = (
                app.protected_scope_purge
                .delete(
                    scope_id,
                    preview_digest=digest,
                )
            )
        except Exception as exc:
            expected = {
                "ProtectedScopeAlreadyDeletedError",
                "ProtectedScopeDeletionPreviewStaleError",
            }

            if exc.__class__.__name__ not in expected:
                raise

            print(
                "ALREADY:"
                + exc.__class__.__name__
            )
        else:
            print(
                "DELETED:"
                + str(result.commit_id)
            )
    finally:
        app.stop()


elif operation == "verify-protected-live":
    runtime = Path(sys.argv[2])
    scope_id = uuid.UUID(sys.argv[3])
    source_id = uuid.UUID(sys.argv[4])
    storage_locator = sys.argv[5]

    app = app_for(runtime)

    try:
        connection = app.database.connection

        scope = connection.execute(
            "SELECT lifecycle_state, "
            "current_scope_key_id, neutral_label "
            "FROM protection_scopes "
            "WHERE protection_scope_id = ?",
            (
                scope_id.bytes,
            ),
        ).fetchone()

        if scope is None:
            raise AssertionError(
                "ProtectionScope tombstone disappeared."
            )

        if (
            str(
                scope[
                    "lifecycle_state"
                ]
            )
            != "pending_delete"
        ):
            raise AssertionError(
                "ProtectionScope is not pending_delete."
            )

        if (
            scope[
                "current_scope_key_id"
            ]
            is not None
        ):
            raise AssertionError(
                "ProtectionScope still has a current key."
            )

        if (
            scope[
                "neutral_label"
            ]
            is not None
        ):
            raise AssertionError(
                "ProtectionScope neutral label survived purge."
            )

        for table in (
            "protection_scope_keys",
            "protected_payloads",
            "protected_blob_envelopes",
            "protected_sources",
        ):
            count = int(
                connection.execute(
                    "SELECT COUNT(*) "
                    f"FROM {table} "
                    "WHERE protection_scope_id = ?",
                    (
                        scope_id.bytes,
                    ),
                ).fetchone()[0]
            )

            if count != 0:
                raise AssertionError(
                    "Protected table survived purge: "
                    + table
                )

        source = connection.execute(
            "SELECT lifecycle_state "
            "FROM entity_registry "
            "WHERE entity_id = ?",
            (
                source_id.bytes,
            ),
        ).fetchone()

        if (
            source is None
            or str(
                source[
                    "lifecycle_state"
                ]
            )
            != "deleted"
        ):
            raise AssertionError(
                "Protected Source is not tombstoned."
            )

        blob_entity = connection.execute(
            "SELECT entity.lifecycle_state "
            "FROM blob_records AS blob "
            "JOIN entity_registry AS entity "
            "ON entity.entity_id = blob.blob_id "
            "WHERE blob.storage_locator = ?",
            (
                storage_locator,
            ),
        ).fetchone()

        if (
            blob_entity is None
            or str(
                blob_entity[
                    "lifecycle_state"
                ]
            )
            != "deleted"
        ):
            raise AssertionError(
                "Crypto-erased Protected Blob "
                "is not tombstoned."
            )

        source_ledger = int(
            connection.execute(
                "SELECT COUNT(*) "
                "FROM deletion_ledger "
                "WHERE entity_id = ? "
                "AND entity_type = 'source'",
                (
                    source_id.bytes,
                ),
            ).fetchone()[0]
        )

        scope_ledger = int(
            connection.execute(
                "SELECT COUNT(*) "
                "FROM deletion_ledger "
                "WHERE entity_id = ? "
                "AND entity_type = 'protection_scope'",
                (
                    scope_id.bytes,
                ),
            ).fetchone()[0]
        )

        if (
            source_ledger != 1
            or scope_ledger != 1
        ):
            raise AssertionError(
                "Protected deletion ledger "
                "is missing or duplicated."
            )

        ciphertext = (
            runtime
            / "state"
            / "spool"
            / Path(
                storage_locator
            )
        )

        if ciphertext.exists():
            raise AssertionError(
                "Protected ciphertext remains after purge."
            )

        print("PROTECTED-LIVE-VERIFIED")
    finally:
        app.stop()


elif operation == "restore-public":
    controller = Path(sys.argv[2])
    snapshot = Path(sys.argv[3])
    destination = Path(sys.argv[4])
    source_id = uuid.UUID(sys.argv[5])
    storage_locator = sys.argv[6]

    app = app_for(controller)

    try:
        restored = app.backup.restore_path(
            snapshot,
            destination_root=destination,
        )

        if restored != destination.resolve():
            raise AssertionError(
                "Unexpected public restore destination."
            )
    finally:
        app.stop()

    restored_app = app_for(destination)

    try:
        try:
            restored_app.sources.get(
                source_id
            )
        except SourceNotFoundError:
            pass
        else:
            raise AssertionError(
                "Deleted Source resurrected."
            )

        connection = (
            restored_app.database.connection
        )

        entity = connection.execute(
            "SELECT lifecycle_state "
            "FROM entity_registry "
            "WHERE entity_id = ?",
            (
                source_id.bytes,
            ),
        ).fetchone()

        if (
            entity is None
            or str(
                entity[
                    "lifecycle_state"
                ]
            )
            != "deleted"
        ):
            raise AssertionError(
                "Restored Source tombstone missing."
            )

        ledger_count = int(
            connection.execute(
                "SELECT COUNT(*) "
                "FROM deletion_ledger "
                "WHERE entity_id = ? "
                "AND entity_type = 'source'",
                (
                    source_id.bytes,
                ),
            ).fetchone()[0]
        )

        if ledger_count != 1:
            raise AssertionError(
                "Restored Source deletion ledger "
                "is missing or duplicated."
            )

        blob_path = (
            destination
            / "state"
            / "spool"
            / Path(
                storage_locator
            )
        )

        if blob_path.exists():
            raise AssertionError(
                "Deleted Source bytes resurrected."
            )

        print("PUBLIC-RESTORE-VERIFIED")
    finally:
        restored_app.stop()


elif operation == "restore-protected":
    controller = Path(sys.argv[2])
    snapshot = Path(sys.argv[3])
    destination = Path(sys.argv[4])
    scope_id = uuid.UUID(sys.argv[5])
    source_id = uuid.UUID(sys.argv[6])
    storage_locator = sys.argv[7]

    app = app_for(controller)

    try:
        restored = app.backup.restore_path(
            snapshot,
            destination_root=destination,
        )

        if restored != destination.resolve():
            raise AssertionError(
                "Unexpected protected restore destination."
            )
    finally:
        app.stop()

    restored_app = app_for(destination)

    try:
        connection = (
            restored_app.database.connection
        )

        scope = connection.execute(
            "SELECT lifecycle_state, "
            "current_scope_key_id, neutral_label "
            "FROM protection_scopes "
            "WHERE protection_scope_id = ?",
            (
                scope_id.bytes,
            ),
        ).fetchone()

        if (
            scope is None
            or str(
                scope[
                    "lifecycle_state"
                ]
            )
            != "pending_delete"
            or scope[
                "current_scope_key_id"
            ]
            is not None
            or scope[
                "neutral_label"
            ]
            is not None
        ):
            raise AssertionError(
                "Deleted ProtectionScope resurrected."
            )

        for table in (
            "protection_scope_keys",
            "protected_payloads",
            "protected_blob_envelopes",
            "protected_sources",
        ):
            count = int(
                connection.execute(
                    "SELECT COUNT(*) "
                    f"FROM {table} "
                    "WHERE protection_scope_id = ?",
                    (
                        scope_id.bytes,
                    ),
                ).fetchone()[0]
            )

            if count != 0:
                raise AssertionError(
                    "Protected state resurrected in "
                    + table
                )

        source = connection.execute(
            "SELECT lifecycle_state "
            "FROM entity_registry "
            "WHERE entity_id = ?",
            (
                source_id.bytes,
            ),
        ).fetchone()

        if (
            source is None
            or str(
                source[
                    "lifecycle_state"
                ]
            )
            != "deleted"
        ):
            raise AssertionError(
                "Protected Source resurrected."
            )

        blob_path = (
            destination
            / "state"
            / "spool"
            / Path(
                storage_locator
            )
        )

        if blob_path.exists():
            raise AssertionError(
                "Protected ciphertext resurrected."
            )

        if (
            connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
        ):
            raise AssertionError(
                "Protected restored DB has FK violations."
            )

        print("PROTECTED-RESTORE-VERIFIED")
    finally:
        restored_app.stop()


else:
    raise AssertionError(
        "Unknown child operation: "
        + operation
    )
'''


def _run_child(
    operation: str,
    *args: object,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD,
            operation,
            *(
                str(arg)
                for arg in args
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, (
        "Child operation failed: "
        f"{operation}\n"
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    return result


def _race(
    operation: str,
    *args: object,
) -> tuple[str, str]:
    command = [
        sys.executable,
        "-c",
        _CHILD,
        operation,
        *(
            str(arg)
            for arg in args
        ),
    ]

    first = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    second = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    first_stdout, first_stderr = (
        first.communicate(
            timeout=120
        )
    )

    second_stdout, second_stderr = (
        second.communicate(
            timeout=120
        )
    )

    assert first.returncode == 0, (
        "First race process failed.\n"
        f"stdout:\n{first_stdout}\n"
        f"stderr:\n{first_stderr}"
    )

    assert second.returncode == 0, (
        "Second race process failed.\n"
        f"stdout:\n{second_stdout}\n"
        f"stderr:\n{second_stderr}"
    )

    outputs = (
        first_stdout,
        second_stdout,
    )

    assert sum(
        "DELETED:" in output
        for output in outputs
    ) == 1, outputs

    assert sum(
        "ALREADY:" in output
        for output in outputs
    ) == 1, outputs

    return outputs


def test_process_separated_public_delete_offline_sync_purge_and_restore(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "public-runtime"
    )

    backup_root = (
        tmp_path
        / "public-backup"
    )

    offline_root = (
        tmp_path
        / "public-backup-offline"
    )

    source_file = (
        tmp_path
        / "public-source.bin"
    )

    source_file.write_bytes(
        b"SLICE15F_PUBLIC_CANARY_"
        b"4B71A93E"
    )

    app = AthenaApplication(
        AthenaSettings(
            local_root=runtime,
        )
    )

    app.start()

    try:
        app.backup.register_target(
            backup_root
        )

        captured = (
            app.sources.capture_file(
                source_file
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=backup_root,
            )
        )

        preview = (
            app.lifecycle_deletion.preview(
                captured.source.source_id
            )
        )

        source_id = (
            captured.source.source_id
        )

        storage_locator = (
            captured.blob.storage_locator
        )

        snapshot_relative_path = (
            snapshot.relative_path
        )

        preview_digest = (
            preview.preview_digest
        )

    finally:
        app.stop()

    snapshot_path = (
        backup_root
        / snapshot_relative_path
    )

    assert snapshot_path.is_dir()

    backup_root.rename(
        offline_root
    )

    assert not backup_root.exists()

    _race(
        "delete-source",
        runtime,
        source_id,
        preview_digest,
    )

    database = sqlite3.connect(
        runtime
        / "state"
        / "athena.db"
    )

    try:
        count = int(
            database.execute(
                "SELECT COUNT(*) "
                "FROM deletion_ledger "
                "WHERE entity_id = ? "
                "AND entity_type = 'source'",
                (
                    source_id.bytes,
                ),
            ).fetchone()[0]
        )

        assert count == 1

    finally:
        database.close()

    offline_root.rename(
        backup_root
    )

    assert backup_root.exists()

    restart = _run_child(
        "restart-sync",
        runtime,
    )

    assert "SYNCED:" in restart.stdout

    head = json.loads(
        (
            backup_root
            / "deletion-ledger"
            / "head.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert int(
        head[
            "watermark"
        ]
    ) >= 1

    sidecar_records = tuple(
        (
            backup_root
            / "deletion-ledger"
            / "records"
        ).glob(
            "*.json"
        )
    )

    assert sidecar_records

    sidecar_text = "\n".join(
        path.read_text(
            encoding="utf-8"
        )
        for path in sidecar_records
    )

    assert str(
        source_id
    ) in sidecar_text

    purge = _run_child(
        "purge-source",
        runtime,
        source_id,
    )

    assert "PURGED:" in purge.stdout

    runtime_blob = (
        runtime
        / "state"
        / "spool"
        / Path(
            storage_locator
        )
    )

    assert not runtime_blob.exists()

    snapshot_path = (
        backup_root
        / snapshot_relative_path
    )

    assert snapshot_path.is_dir()

    shutil.rmtree(
        runtime
    )

    assert not runtime.exists()

    controller = (
        tmp_path
        / "public-controller"
    )

    restored = (
        tmp_path
        / "public-restored"
    )

    result = _run_child(
        "restore-public",
        controller,
        snapshot_path,
        restored,
        source_id,
        storage_locator,
    )

    assert (
        "PUBLIC-RESTORE-VERIFIED"
        in result.stdout
    )


def test_process_separated_protected_scope_race_and_restore(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "protected-runtime"
    )

    backup_root = (
        tmp_path
        / "protected-backup"
    )

    source_file = (
        tmp_path
        / "protected-source.bin"
    )

    source_file.write_bytes(
        b"SLICE15F_PROTECTED_CANARY_"
        b"79A4D2"
    )

    password = (
        b"slice15f-protected-password-"
        b"79A4D2"
    )

    app = AthenaApplication(
        AthenaSettings(
            local_root=runtime,
        )
    )

    app.start()

    try:
        app.protected_content.initialize_password(
            password,
            parameters=Argon2idParameters(
                iterations=1,
                lanes=1,
                memory_cost_kib=8 * 1024,
                length=32,
            ),
        )

        scope = (
            app.protected_content
            .create_scope(
                password,
                neutral_label=(
                    "Slice 15f protected"
                ),
            )
        )

        app.protected_content.unlock_scope(
            scope.protection_scope_id,
            password,
        )

        app.backup.register_target(
            backup_root
        )

        captured = (
            app.sources
            .capture_protected_file(
                source_file,
                protection_scope_id=(
                    scope
                    .protection_scope_id
                ),
            )
        )

        snapshot = (
            app.backup.create_snapshot(
                target_root=backup_root,
            )
        )

        preview = (
            app.protected_scope_purge
            .preview(
                scope.protection_scope_id
            )
        )

        scope_id = (
            scope.protection_scope_id
        )

        source_id = (
            captured.source.source_id
        )

        storage_locator = (
            captured.blob.storage_locator
        )

        snapshot_relative_path = (
            snapshot.relative_path
        )

        preview_digest = (
            preview.preview_digest
        )

    finally:
        app.stop()

    snapshot_path = (
        backup_root
        / snapshot_relative_path
    )

    assert snapshot_path.is_dir()

    _race(
        "delete-scope",
        runtime,
        scope_id,
        preview_digest,
    )

    verification = _run_child(
        "verify-protected-live",
        runtime,
        scope_id,
        source_id,
        storage_locator,
    )

    assert (
        "PROTECTED-LIVE-VERIFIED"
        in verification.stdout
    )

    sidecar_records = tuple(
        (
            backup_root
            / "deletion-ledger"
            / "records"
        ).glob(
            "*.json"
        )
    )

    assert sidecar_records

    sidecar_text = "\n".join(
        path.read_text(
            encoding="utf-8"
        )
        for path in sidecar_records
    )

    assert str(
        scope_id
    ) in sidecar_text

    assert str(
        source_id
    ) in sidecar_text

    shutil.rmtree(
        runtime
    )

    assert not runtime.exists()

    controller = (
        tmp_path
        / "protected-controller"
    )

    restored = (
        tmp_path
        / "protected-restored"
    )

    result = _run_child(
        "restore-protected",
        controller,
        snapshot_path,
        restored,
        scope_id,
        source_id,
        storage_locator,
    )

    assert (
        "PROTECTED-RESTORE-VERIFIED"
        in result.stdout
    )