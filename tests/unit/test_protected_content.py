from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.security.models import Argon2idParameters
from athena.security.service import (
    ProtectedContentIntegrityError,
    ProtectedContentUnlockError,
    ProtectionScopeLockedError,
)
from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    ARCHIVE_REPLICATION_MIGRATION_ID,
    ARCHIVE_REPLICATION_SCHEMA_VERSION,
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
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=local_root,
        )
    )
    app.start()
    return app


def _initialize_scope(
    app: AthenaApplication,
    *,
    password: bytes,
):
    app.protected_content.initialize_password(
        password,
        parameters=_TEST_KDF,
    )

    return (
        app.protected_content.create_scope(
            password,
            neutral_label="Protected 1",
        )
    )


def _security_tables() -> set[str]:
    return {
        "key_slots",
        "protection_scopes",
        "protection_scope_keys",
        "protected_payloads",
        "protected_blob_envelopes",
    }


def test_fresh_schema_has_v32_security_tables_without_persistent_unlock_state(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        connection = (
            app.database.connection
        )

        assert (
            connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            == SCHEMA_VERSION
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

        assert (
            _security_tables()
            <= tables
        )

        scope_columns = {
            str(row[1])
            for row in connection.execute(
                """
                PRAGMA table_info(
                    protection_scopes
                )
                """
            )
        }

        assert {
            "protection_scope_id",
            "lifecycle_state",
            "created_at_us",
            "current_scope_key_id",
            "neutral_label",
        } <= scope_columns

        assert (
            "locked"
            not in scope_columns
        )
        assert (
            "unlocked"
            not in scope_columns
        )
        assert (
            "is_unlocked"
            not in scope_columns
        )

        metadata = (
            connection.execute(
                """
                SELECT
                    schema_version,
                    last_migration_id,
                    minimum_reader_version
                FROM schema_metadata
                WHERE singleton_id = 1
                """
            ).fetchone()
        )

        assert metadata is not None

        assert tuple(
            metadata
        ) == (
            SCHEMA_VERSION,
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
            SCHEMA_VERSION,
        )

        assert connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []

    finally:
        app.stop()


def test_password_scope_payload_roundtrip_and_manual_lock(
    tmp_path: Path,
) -> None:
    password = (
        b"correct horse battery staple"
    )

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _initialize_scope(
            app,
            password=password,
        )

        assert not (
            app.protected_content
            .is_unlocked(
                scope.protection_scope_id
            )
        )

        context = (
            app.protected_content
            .unlock_scope(
                scope.protection_scope_id,
                password,
            )
        )

        assert context.allows(
            scope.protection_scope_id
        )

        plaintext = (
            b"protected structured payload"
        )

        record = (
            app.protected_content
            .store_payload(
                scope.protection_scope_id,
                plaintext,
            )
        )

        assert (
            record.ciphertext
            != plaintext
        )

        assert (
            record.ciphertext_hash
            == hashlib.sha256(
                record.ciphertext
            ).digest()
        )

        assert (
            app.protected_content
            .load_payload(
                record.protected_payload_id
            )
            == plaintext
        )

        locked = (
            app.protected_content
            .lock_scope(
                scope.protection_scope_id
            )
        )

        assert not locked.allows(
            scope.protection_scope_id
        )

        with pytest.raises(
            ProtectionScopeLockedError
        ):
            (
                app.protected_content
                .load_payload(
                    record.protected_payload_id
                )
            )

    finally:
        app.stop()


def test_wrong_password_fails_closed_without_unlocking_scope(
    tmp_path: Path,
) -> None:
    password = b"right-password"

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _initialize_scope(
            app,
            password=password,
        )

        with pytest.raises(
            ProtectedContentUnlockError,
            match="unlock failed",
        ):
            (
                app.protected_content
                .unlock_scope(
                    scope.protection_scope_id,
                    b"wrong-password",
                )
            )

        assert not (
            app.protected_content
            .is_unlocked(
                scope.protection_scope_id
            )
        )

        assert (
            app.protected_content
            .context
            .unlocked_protection_scopes
            == frozenset()
        )

    finally:
        app.stop()


def test_restart_always_returns_protected_scope_to_locked_state(
    tmp_path: Path,
) -> None:
    local_root = (
        tmp_path
        / "runtime"
    )

    password = b"restart-password"

    plaintext = (
        b"restart protected payload"
    )

    first = _app(
        local_root
    )

    scope = _initialize_scope(
        first,
        password=password,
    )

    first.protected_content.unlock_scope(
        scope.protection_scope_id,
        password,
    )

    record = (
        first.protected_content
        .store_payload(
            scope.protection_scope_id,
            plaintext,
        )
    )

    assert (
        first.protected_content
        .is_unlocked(
            scope.protection_scope_id
        )
    )

    first.stop()

    second = _app(
        local_root
    )

    try:
        assert not (
            second.protected_content
            .is_unlocked(
                scope.protection_scope_id
            )
        )

        with pytest.raises(
            ProtectionScopeLockedError
        ):
            (
                second.protected_content
                .load_payload(
                    record.protected_payload_id
                )
            )

        (
            second.protected_content
            .unlock_scope(
                scope.protection_scope_id,
                password,
            )
        )

        assert (
            second.protected_content
            .load_payload(
                record.protected_payload_id
            )
            == plaintext
        )

    finally:
        second.stop()


def test_ciphertext_bitflip_with_recomputed_public_hash_fails_gcm_authentication(
    tmp_path: Path,
) -> None:
    password = b"tamper-password"

    app = _app(
        tmp_path
        / "runtime"
    )

    try:
        scope = _initialize_scope(
            app,
            password=password,
        )

        (
            app.protected_content
            .unlock_scope(
                scope.protection_scope_id,
                password,
            )
        )

        record = (
            app.protected_content
            .store_payload(
                scope.protection_scope_id,
                b"authenticated secret payload",
            )
        )

        tampered = bytearray(
            record.ciphertext
        )

        tampered[0] ^= 0x01

        tampered_bytes = bytes(
            tampered
        )

        # An attacker with DB-write access can also
        # recompute the public ciphertext hash.
        # GCM authentication must still reject it.
        with (
            app.database.write_transaction()
            as connection
        ):
            connection.execute(
                """
                UPDATE protected_payloads
                SET ciphertext = ?,
                    ciphertext_hash = ?
                WHERE protected_payload_id = ?
                """,
                (
                    tampered_bytes,
                    hashlib.sha256(
                        tampered_bytes
                    ).digest(),
                    record
                    .protected_payload_id
                    .bytes,
                ),
            )

        with pytest.raises(
            ProtectedContentIntegrityError,
            match="authentication failed",
        ):
            (
                app.protected_content
                .load_payload(
                    record.protected_payload_id
                )
            )

    finally:
        app.stop()


def test_protected_canary_and_password_never_reach_persistent_plaintext(
    tmp_path: Path,
) -> None:
    local_root = (
        tmp_path
        / "runtime"
    )

    password = (
        b"PASSWORD-CANARY-31f26058"
    )

    canary = (
        b"PROTECTED-CANARY-a8a238d2"
    )

    app = _app(
        local_root
    )

    scope = _initialize_scope(
        app,
        password=password,
    )

    (
        app.protected_content
        .unlock_scope(
            scope.protection_scope_id,
            password,
        )
    )

    record = (
        app.protected_content
        .store_payload(
            scope.protection_scope_id,
            canary,
        )
    )

    row = (
        app.database.connection.execute(
            """
            SELECT
                ciphertext,
                ciphertext_hash,
                wrapped_dek
            FROM protected_payloads
            WHERE protected_payload_id = ?
            """,
            (
                record
                .protected_payload_id
                .bytes,
            ),
        ).fetchone()
    )

    assert row is not None

    assert canary not in bytes(
        row["ciphertext"]
    )

    assert canary not in bytes(
        row["wrapped_dek"]
    )

    app.protected_content.lock_all()
    app.stop()

    scanned_files = 0

    for path in local_root.rglob(
        "*"
    ):
        if not path.is_file():
            continue

        data = path.read_bytes()
        scanned_files += 1

        assert canary not in data, path
        assert password not in data, path

    assert scanned_files > 0


def test_root_scope_and_dek_keys_are_never_persisted_in_cleartext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_root = (
        tmp_path
        / "runtime"
    )

    password = (
        b"key-wrapping-password"
    )

    root_key = b"R" * 32
    scope_key = b"S" * 32
    dek = b"D" * 32

    generated = [
        root_key,
        scope_key,
        dek,
    ]

    app = _app(
        local_root
    )

    def fake_random_key() -> bytes:
        assert generated
        return generated.pop(0)

    monkeypatch.setattr(
        app.crypto_provider,
        "random_key",
        fake_random_key,
    )

    scope = _initialize_scope(
        app,
        password=password,
    )

    (
        app.protected_content
        .unlock_scope(
            scope.protection_scope_id,
            password,
        )
    )

    (
        app.protected_content
        .store_payload(
            scope.protection_scope_id,
            b"wrapped-key test payload",
        )
    )

    assert generated == []

    slot = (
        app.database.connection.execute(
            """
            SELECT
                kdf_algorithm,
                kdf_parameters_json,
                salt,
                wrap_nonce,
                wrapped_root_key
            FROM key_slots
            WHERE slot_type = 'password'
              AND status = 'active'
            """
        ).fetchone()
    )

    assert slot is not None

    assert (
        slot["kdf_algorithm"]
        == "argon2id"
    )

    assert (
        slot["kdf_parameters_json"]
        == _TEST_KDF.to_json()
    )

    assert len(
        bytes(
            slot["salt"]
        )
    ) >= 16

    assert len(
        bytes(
            slot["wrap_nonce"]
        )
    ) == 12

    assert len(
        bytes(
            slot["wrapped_root_key"]
        )
    ) == 48

    app.stop()

    for path in local_root.rglob(
        "*"
    ):
        if not path.is_file():
            continue

        data = path.read_bytes()

        assert root_key not in data, path
        assert scope_key not in data, path
        assert dek not in data, path


def test_v31_database_is_upgraded_additively_to_protected_content_v32(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "athena.db"
    )

    latest = SQLiteDatabase(
        path
    )

    latest.start()
    latest.stop()

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

    # Reconstruct exact v31 by removing
    # only the additive v32 security objects.
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_blob_reuse")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_delete")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_representation")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_update")
    legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_delete")
    legacy.execute("DROP TABLE source_protection_transitions")
    legacy.execute(
        """
        DROP TABLE
        protected_sources
        """
    )

    legacy.execute(
        """
        DROP TABLE
        protected_blob_envelopes
        """
    )

    legacy.execute(
        """
        DROP TABLE
        protected_payloads
        """
    )

    legacy.execute(
        """
        DROP TABLE
        protection_scope_keys
        """
    )

    legacy.execute(
        """
        DROP TABLE
        protection_scopes
        """
    )

    legacy.execute(
        """
        DROP TABLE
        key_slots
        """
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
            ARCHIVE_REPLICATION_SCHEMA_VERSION,
            ARCHIVE_REPLICATION_MIGRATION_ID,
            ARCHIVE_REPLICATION_SCHEMA_VERSION,
        ),
    )

    legacy.execute(
        f"PRAGMA user_version = "
        f"{ARCHIVE_REPLICATION_SCHEMA_VERSION}"
    )

    legacy.close()

    upgraded = SQLiteDatabase(
        path
    )

    upgraded.start()

    try:
        connection = (
            upgraded.connection
        )

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

        assert (
            _security_tables()
            <= tables
        )

        metadata = (
            connection.execute(
                """
                SELECT
                    schema_version,
                    last_migration_id,
                    minimum_reader_version
                FROM schema_metadata
                WHERE singleton_id = 1
                """
            ).fetchone()
        )

        assert metadata is not None

        assert tuple(
            metadata
        ) == (
            SCHEMA_VERSION,
            GROUNDED_RESPONSE_RECEIPT_MIGRATION_ID,
            SCHEMA_VERSION,
        )

        assert connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []

    finally:
        upgraded.stop()
