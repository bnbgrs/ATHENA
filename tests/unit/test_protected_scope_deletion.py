from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest

from athena.config.settings import (
    AthenaSettings,
)
from athena.core.application import (
    AthenaApplication,
)
from athena.lifecycle.protected_purge import (
    ProtectedScopeDeletionPreviewStaleError,
)
from athena.operations.cli import (
    add_operational_parsers,
    run_operational_command,
)
from athena.security.models import (
    Argon2idParameters,
)
from athena.security.repository import (
    ProtectionPayloadNotFoundError,
)
from athena.security.service import (
    ProtectionScopeUnavailableError,
)
from athena.source.repository import (
    SourceNotFoundError,
)

_TEST_KDF = Argon2idParameters(
    iterations=1,
    lanes=1,
    memory_cost_kib=8 * 1024,
    length=32,
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


def _scope(
    app: AthenaApplication,
    *,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )

    scope = (
        app.protected_content
        .create_scope(
            password,
            neutral_label=(
                "private scope label"
            ),
        )
    )

    app.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    return scope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    add_operational_parsers(
        commands
    )

    return parser


def test_protected_scope_crypto_erasure_removes_current_decryptability(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime"
    )

    target = (
        tmp_path
        / "backup-target"
    )

    source_file = (
        tmp_path
        / "secret.bin"
    )

    secret = (
        b"PROTECTED-SCOPE-SECRET-"
        b"15e2b-7f43d1"
    )

    password = (
        b"protected-scope-password"
    )

    source_file.write_bytes(
        secret
    )

    app = _app(
        runtime
    )

    try:
        app.backup.register_target(
            target
        )

        scope = _scope(
            app,
            password=password,
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

        extra_payload = (
            app.protected_content
            .store_payload(
                scope.protection_scope_id,
                b"extra protected payload",
            )
        )

        ciphertext_path = (
            app.blob_store
            .resolve_blob_path(
                storage_area=(
                    captured
                    .blob
                    .storage_area
                ),
                storage_locator=(
                    captured
                    .blob
                    .storage_locator
                ),
            )
        )

        assert (
            ciphertext_path.is_file()
        )

        assert (
            secret
            not in ciphertext_path
            .read_bytes()
        )

        preview = (
            app.protected_scope_purge
            .preview(
                scope
                .protection_scope_id
            )
        )

        assert (
            preview.source_count
            == 1
        )

        assert (
            preview
            .protected_payload_count
            >= 2
        )

        assert (
            preview
            .protected_blob_count
            == 1
        )

        assert (
            preview.scope_key_count
            >= 1
        )

        result = (
            app.protected_scope_purge
            .delete(
                scope
                .protection_scope_id,
                preview_digest=(
                    preview
                    .preview_digest
                ),
            )
        )

        assert (
            result.deleted_source_ids
            == (
                captured
                .source
                .source_id,
            )
        )

        assert (
            result
            .destroyed_scope_key_count
            >= 1
        )

        assert (
            result
            .removed_payload_count
            >= 2
        )

        assert (
            result
            .removed_blob_envelope_count
            == 1
        )

        assert (
            result
            .deleted_replica_count
            >= 1
        )

        assert not (
            ciphertext_path.exists()
        )

        connection = (
            app.database.connection
        )

        scope_row = (
            connection.execute(
                """
                SELECT
                    lifecycle_state,
                    current_scope_key_id,
                    neutral_label
                FROM protection_scopes
                WHERE protection_scope_id = ?
                """,
                (
                    scope
                    .protection_scope_id
                    .bytes,
                ),
            ).fetchone()
        )

        assert (
            scope_row is not None
        )

        assert (
            scope_row[
                "lifecycle_state"
            ]
            == "pending_delete"
        )

        assert (
            scope_row[
                "current_scope_key_id"
            ]
            is None
        )

        assert (
            scope_row[
                "neutral_label"
            ]
            is None
        )

        for table in (
            "protection_scope_keys",
            "protected_payloads",
            "protected_blob_envelopes",
            "protected_sources",
        ):
            count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE protection_scope_id = ?
                    """,
                    (
                        scope
                        .protection_scope_id
                        .bytes,
                    ),
                ).fetchone()[0]
            )

            assert count == 0

        entity = connection.execute(
            """
            SELECT lifecycle_state
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                captured
                .source
                .source_id
                .bytes,
            ),
        ).fetchone()

        assert (
            entity is not None
        )

        assert (
            entity[
                "lifecycle_state"
            ]
            == "deleted"
        )

        ledger = connection.execute(
            """
            SELECT entity_type
            FROM deletion_ledger
            WHERE entity_id IN (?, ?)
            ORDER BY ledger_seq
            """,
            (
                captured
                .source
                .source_id
                .bytes,
                scope
                .protection_scope_id
                .bytes,
            ),
        ).fetchall()

        assert {
            str(
                row[
                    "entity_type"
                ]
            )
            for row in ledger
        } == {
            "source",
            "protection_scope",
        }

        with pytest.raises(
            SourceNotFoundError
        ):
            app.sources.get(
                captured
                .source
                .source_id
            )

        with pytest.raises(
            ProtectionScopeUnavailableError
        ):
            (
                app.protected_content
                .unlock_scope(
                    scope
                    .protection_scope_id,
                    password,
                )
            )

        with pytest.raises(
            ProtectionPayloadNotFoundError
        ):
            (
                app.protected_content
                .load_payload(
                    extra_payload
                    .protected_payload_id
                )
            )

        sidecar_root = (
            target
            / "deletion-ledger"
        )

        sidecar_bytes = b"".join(
            path.read_bytes()
            for path
            in sidecar_root.rglob(
                "*.json"
            )
        )

        assert (
            secret
            not in sidecar_bytes
        )

        assert (
            password
            not in sidecar_bytes
        )

    finally:
        app.stop()


def test_protected_scope_preview_digest_detects_new_payload(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime-stale"
    )

    password = (
        b"preview-stale-password"
    )

    try:
        scope = _scope(
            app,
            password=password,
        )

        preview = (
            app.protected_scope_purge
            .preview(
                scope
                .protection_scope_id
            )
        )

        app.protected_content.store_payload(
            scope
            .protection_scope_id,
            b"created after preview",
        )

        with pytest.raises(
            ProtectedScopeDeletionPreviewStaleError
        ):
            (
                app.protected_scope_purge
                .delete(
                    scope
                    .protection_scope_id,
                    preview_digest=(
                        preview
                        .preview_digest
                    ),
                )
            )

        row = (
            app.database.connection
            .execute(
                """
                SELECT
                    lifecycle_state,
                    current_scope_key_id
                FROM protection_scopes
                WHERE protection_scope_id = ?
                """,
                (
                    scope
                    .protection_scope_id
                    .bytes,
                ),
            ).fetchone()
        )

        assert (
            row is not None
        )

        assert (
            row[
                "lifecycle_state"
            ]
            == "active"
        )

        assert (
            row[
                "current_scope_key_id"
            ]
            is not None
        )

    finally:
        app.stop()


def test_protected_scope_cli_preview_path_executes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _app(
        tmp_path
        / "runtime-cli"
    )

    password = (
        b"cli-preview-password"
    )

    try:
        scope = _scope(
            app,
            password=password,
        )

        parser = _parser()

        args = parser.parse_args(
            [
                "delete",
                "protected-scope-preview",
                str(
                    scope
                    .protection_scope_id
                ),
            ]
        )

        assert (
            run_operational_command(
                app,
                args,
            )
            == 0
        )

        output = (
            capsys
            .readouterr()
            .out
        )

        assert (
            "Preview digest:"
            in output
        )

        assert (
            str(
                scope
                .protection_scope_id
            )
            in output
        )

    finally:
        app.stop()


def test_old_snapshot_restore_destroys_restored_scope_keys_and_ciphertext(
    tmp_path: Path,
) -> None:
    runtime = (
        tmp_path
        / "runtime-restore"
    )

    target = (
        tmp_path
        / "backup"
    )

    destination = (
        tmp_path
        / "restored"
    )

    source_file = (
        tmp_path
        / "restore-secret.bin"
    )

    source_file.write_bytes(
        b"scope restore "
        b"anti-resurrection"
    )

    password = (
        b"restore-password"
    )

    app = _app(
        runtime
    )

    try:
        scope = _scope(
            app,
            password=password,
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
            app.backup
            .create_snapshot(
                target_root=target
            )
        )

        preview = (
            app.protected_scope_purge
            .preview(
                scope
                .protection_scope_id
            )
        )

        (
            app.protected_scope_purge
            .delete(
                scope
                .protection_scope_id,
                preview_digest=(
                    preview
                    .preview_digest
                ),
            )
        )

        app.backup.restore_to(
            snapshot.snapshot_id,
            destination_root=(
                destination
            ),
        )

    finally:
        app.stop()

    restored = sqlite3.connect(
        destination
        / "state"
        / "athena.db"
    )

    restored.row_factory = (
        sqlite3.Row
    )

    try:
        scope_row = (
            restored.execute(
                """
                SELECT
                    lifecycle_state,
                    current_scope_key_id,
                    neutral_label
                FROM protection_scopes
                WHERE protection_scope_id = ?
                """,
                (
                    scope
                    .protection_scope_id
                    .bytes,
                ),
            ).fetchone()
        )

        assert (
            scope_row is not None
        )

        assert (
            scope_row[
                "lifecycle_state"
            ]
            == "pending_delete"
        )

        assert (
            scope_row[
                "current_scope_key_id"
            ]
            is None
        )

        assert (
            scope_row[
                "neutral_label"
            ]
            is None
        )

        for table in (
            "protection_scope_keys",
            "protected_payloads",
            "protected_blob_envelopes",
            "protected_sources",
        ):
            assert int(
                restored.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE protection_scope_id = ?
                    """,
                    (
                        scope
                        .protection_scope_id
                        .bytes,
                    ),
                ).fetchone()[0]
            ) == 0

        source_entity = (
            restored.execute(
                """
                SELECT lifecycle_state
                FROM entity_registry
                WHERE entity_id = ?
                """,
                (
                    captured
                    .source
                    .source_id
                    .bytes,
                ),
            ).fetchone()
        )

        assert (
            source_entity
            is not None
        )

        assert (
            source_entity[
                "lifecycle_state"
            ]
            == "deleted"
        )

        scope_ledger = (
            restored.execute(
                """
                SELECT entity_type
                FROM deletion_ledger
                WHERE entity_id = ?
                """,
                (
                    scope
                    .protection_scope_id
                    .bytes,
                ),
            ).fetchone()
        )

        assert (
            scope_ledger
            is not None
        )

        assert (
            scope_ledger[
                "entity_type"
            ]
            == "protection_scope"
        )

        assert (
            restored.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        restored.close()

    restored_ciphertext = (
        destination
        / "state"
        / "spool"
        / Path(
            captured
            .blob
            .storage_locator
        )
    )

    assert not (
        restored_ciphertext.exists()
    )
