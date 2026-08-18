"""Transactional persistence for ATHENA Protected Content."""

from __future__ import annotations

import sqlite3
import uuid

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.security.models import (
    Argon2idParameters,
    KeySlotType,
    KeyStatus,
    PasswordKeySlotRecord,
    ProtectedPayloadRecord,
    ProtectionScopeKeyRecord,
    ProtectionScopeLifecycle,
    ProtectionScopeRecord,
)
from athena.storage.database import SQLiteDatabase


class ProtectionRepositoryError(
    RuntimeError
):
    """Base persistence error for Protected Content."""


class ProtectionInitializationConflictError(
    ProtectionRepositoryError
):
    """Raised when a second initial Root-Key slot would be created."""


class ProtectionScopeNotFoundError(
    LookupError
):
    """Raised when a ProtectionScope does not exist."""


class ProtectionPayloadNotFoundError(
    LookupError
):
    """Raised when a protected payload does not exist."""


class ProtectionRepositoryIntegrityError(
    ProtectionRepositoryError
):
    """Raised when persisted security state violates runtime invariants."""


class ProtectionRepository:
    """Persistence adapter for key slots, scopes, scope keys, and payloads."""

    def __init__(
        self,
        database: SQLiteDatabase,
    ) -> None:
        self.database = database

    def has_any_key_slots(
        self,
    ) -> bool:
        row = (
            self.database.connection.execute(
                "SELECT 1 FROM key_slots LIMIT 1"
            ).fetchone()
        )

        return row is not None

    def active_password_slot(
        self,
    ) -> PasswordKeySlotRecord | None:
        rows = (
            self.database.connection.execute(
                """
                SELECT
                    key_slot_id,
                    slot_type,
                    kdf_algorithm,
                    kdf_parameters_json,
                    salt,
                    wrap_algorithm,
                    wrap_nonce,
                    wrapped_root_key,
                    created_at_us,
                    retired_at_us,
                    status
                FROM key_slots
                WHERE slot_type = 'password'
                  AND status = 'active'
                ORDER BY
                    created_at_us DESC,
                    key_slot_id DESC
                LIMIT 2
                """
            ).fetchall()
        )

        if not rows:
            return None

        if len(rows) != 1:
            raise ProtectionRepositoryIntegrityError(
                "ATHENA security state has multiple "
                "active password key slots."
            )

        return self._password_slot_from_row(
            rows[0]
        )

    def create_initial_password_slot(
        self,
        record: PasswordKeySlotRecord,
    ) -> None:
        if (
            record.slot_type
            is not KeySlotType.PASSWORD
        ):
            raise ValueError(
                "Initial key slot must be "
                "a password slot."
            )

        if (
            record.status
            is not KeyStatus.ACTIVE
        ):
            raise ValueError(
                "Initial password key slot "
                "must be active."
            )

        try:
            with (
                self.database.write_transaction()
                as connection
            ):
                existing = (
                    connection.execute(
                        """
                        SELECT 1
                        FROM key_slots
                        LIMIT 1
                        """
                    ).fetchone()
                )

                if existing is not None:
                    raise (
                        ProtectionInitializationConflictError(
                            "ATHENA Root Key is "
                            "already initialized."
                        )
                    )

                connection.execute(
                    """
                    INSERT INTO key_slots (
                        key_slot_id,
                        slot_type,
                        kdf_algorithm,
                        kdf_parameters_json,
                        salt,
                        wrap_algorithm,
                        wrap_nonce,
                        wrapped_root_key,
                        created_at_us,
                        retired_at_us,
                        status
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        uuid_to_blob(
                            record.key_slot_id
                        ),
                        record.slot_type.value,
                        record.kdf_algorithm,
                        record.kdf_parameters.to_json(),
                        record.salt,
                        record.wrap_algorithm,
                        record.wrap_nonce,
                        record.wrapped_root_key,
                        record.created_at_us,
                        record.retired_at_us,
                        record.status.value,
                    ),
                )

        except sqlite3.IntegrityError as exc:
            raise ProtectionRepositoryIntegrityError(
                "Initial password key slot violates "
                "the Protected-Content schema."
            ) from exc

    def create_scope_with_key(
        self,
        scope: ProtectionScopeRecord,
        scope_key: ProtectionScopeKeyRecord,
    ) -> None:
        if (
            scope.current_scope_key_id
            != scope_key.scope_key_id
        ):
            raise ValueError(
                "ProtectionScope current key does not "
                "match supplied key."
            )

        if (
            scope.protection_scope_id
            != scope_key.protection_scope_id
        ):
            raise ValueError(
                "ProtectionScope and ScopeKey "
                "identities disagree."
            )

        if (
            scope.lifecycle_state
            is not ProtectionScopeLifecycle.ACTIVE
        ):
            raise ValueError(
                "New ProtectionScopes must start active."
            )

        if (
            scope_key.status
            is not KeyStatus.ACTIVE
        ):
            raise ValueError(
                "New ProtectionScope keys "
                "must start active."
            )

        try:
            with (
                self.database.write_transaction()
                as connection
            ):
                connection.execute(
                    """
                    INSERT INTO protection_scopes (
                        protection_scope_id,
                        lifecycle_state,
                        created_at_us,
                        current_scope_key_id,
                        neutral_label
                    ) VALUES (?, ?, ?, NULL, ?)
                    """,
                    (
                        uuid_to_blob(
                            scope.protection_scope_id
                        ),
                        scope.lifecycle_state.value,
                        scope.created_at_us,
                        scope.neutral_label,
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO protection_scope_keys (
                        scope_key_id,
                        protection_scope_id,
                        key_version,
                        wrap_algorithm,
                        wrap_nonce,
                        wrapped_scope_key,
                        created_at_us,
                        retired_at_us,
                        status
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        uuid_to_blob(
                            scope_key.scope_key_id
                        ),
                        uuid_to_blob(
                            scope_key.protection_scope_id
                        ),
                        scope_key.key_version,
                        scope_key.wrap_algorithm,
                        scope_key.wrap_nonce,
                        scope_key.wrapped_scope_key,
                        scope_key.created_at_us,
                        scope_key.retired_at_us,
                        scope_key.status.value,
                    ),
                )

                updated = connection.execute(
                    """
                    UPDATE protection_scopes
                    SET current_scope_key_id = ?
                    WHERE protection_scope_id = ?
                      AND current_scope_key_id IS NULL
                    """,
                    (
                        uuid_to_blob(
                            scope_key.scope_key_id
                        ),
                        uuid_to_blob(
                            scope.protection_scope_id
                        ),
                    ),
                )

                if updated.rowcount != 1:
                    raise (
                        ProtectionRepositoryIntegrityError(
                            "ProtectionScope current key "
                            "could not be installed atomically."
                        )
                    )

        except sqlite3.IntegrityError as exc:
            raise ProtectionRepositoryIntegrityError(
                "ProtectionScope state violates "
                "the Protected-Content schema."
            ) from exc

    def get_scope(
        self,
        protection_scope_id: uuid.UUID,
    ) -> ProtectionScopeRecord:
        row = (
            self.database.connection.execute(
                """
                SELECT
                    protection_scope_id,
                    lifecycle_state,
                    created_at_us,
                    current_scope_key_id,
                    neutral_label
                FROM protection_scopes
                WHERE protection_scope_id = ?
                """,
                (
                    uuid_to_blob(
                        protection_scope_id
                    ),
                ),
            ).fetchone()
        )

        if row is None:
            raise ProtectionScopeNotFoundError(
                str(
                    protection_scope_id
                )
            )

        current_raw = row[
            "current_scope_key_id"
        ]

        return ProtectionScopeRecord(
            protection_scope_id=uuid_from_blob(
                bytes(
                    row[
                        "protection_scope_id"
                    ]
                )
            ),
            lifecycle_state=(
                ProtectionScopeLifecycle(
                    str(
                        row[
                            "lifecycle_state"
                        ]
                    )
                )
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
            current_scope_key_id=(
                None
                if current_raw is None
                else uuid_from_blob(
                    bytes(
                        current_raw
                    )
                )
            ),
            neutral_label=(
                None
                if row["neutral_label"] is None
                else str(
                    row["neutral_label"]
                )
            ),
        )

    def get_current_scope_key(
        self,
        protection_scope_id: uuid.UUID,
    ) -> ProtectionScopeKeyRecord:
        row = (
            self.database.connection.execute(
                """
                SELECT
                    k.scope_key_id,
                    k.protection_scope_id,
                    k.key_version,
                    k.wrap_algorithm,
                    k.wrap_nonce,
                    k.wrapped_scope_key,
                    k.created_at_us,
                    k.retired_at_us,
                    k.status
                FROM protection_scopes AS s
                JOIN protection_scope_keys AS k
                  ON
                    k.scope_key_id
                    = s.current_scope_key_id
                  AND
                    k.protection_scope_id
                    = s.protection_scope_id
                WHERE s.protection_scope_id = ?
                """,
                (
                    uuid_to_blob(
                        protection_scope_id
                    ),
                ),
            ).fetchone()
        )

        if row is None:
            scope = self.get_scope(
                protection_scope_id
            )

            if (
                scope.current_scope_key_id
                is None
            ):
                raise (
                    ProtectionRepositoryIntegrityError(
                        "ProtectionScope has no "
                        "current Scope Key."
                    )
                )

            raise (
                ProtectionRepositoryIntegrityError(
                    "ProtectionScope current Scope Key "
                    "is missing or belongs to "
                    "another scope."
                )
            )

        return self._scope_key_from_row(
            row
        )

    def get_scope_key(
        self,
        scope_key_id: uuid.UUID,
    ) -> ProtectionScopeKeyRecord:
        row = (
            self.database.connection.execute(
                """
                SELECT
                    scope_key_id,
                    protection_scope_id,
                    key_version,
                    wrap_algorithm,
                    wrap_nonce,
                    wrapped_scope_key,
                    created_at_us,
                    retired_at_us,
                    status
                FROM protection_scope_keys
                WHERE scope_key_id = ?
                """,
                (
                    uuid_to_blob(
                        scope_key_id
                    ),
                ),
            ).fetchone()
        )

        if row is None:
            raise (
                ProtectionRepositoryIntegrityError(
                    "Referenced ProtectionScope "
                    "Key is missing."
                )
            )

        return self._scope_key_from_row(
            row
        )

    def insert_payload(
        self,
        record: ProtectedPayloadRecord,
    ) -> None:
        with (
            self.database.write_transaction()
            as connection
        ):
            self.insert_payload_in_transaction(
                connection,
                record,
            )

    def insert_payload_in_transaction(
        self,
        connection: sqlite3.Connection,
        record: ProtectedPayloadRecord,
    ) -> None:
        """Insert one encrypted payload inside the caller's transaction."""
        if not connection.in_transaction:
            raise RuntimeError(
                "Protected payload insertion requires "
                "an active transaction."
            )

        try:
            connection.execute(
                """
                INSERT INTO protected_payloads (
                    protected_payload_id,
                    protection_scope_id,
                    scope_key_id,
                    cipher_suite,
                    ciphertext,
                    nonce,
                    wrapped_dek,
                    dek_wrap_nonce,
                    aad_version,
                    ciphertext_hash,
                    created_at_us
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    uuid_to_blob(
                        record.protected_payload_id
                    ),
                    uuid_to_blob(
                        record.protection_scope_id
                    ),
                    uuid_to_blob(
                        record.scope_key_id
                    ),
                    record.cipher_suite,
                    record.ciphertext,
                    record.nonce,
                    record.wrapped_dek,
                    record.dek_wrap_nonce,
                    record.aad_version,
                    record.ciphertext_hash,
                    record.created_at_us,
                ),
            )

        except sqlite3.IntegrityError as exc:
            raise (
                ProtectionRepositoryIntegrityError(
                    "Protected payload violates "
                    "the Protected-Content schema."
                )
            ) from exc

    def get_payload(
        self,
        protected_payload_id: uuid.UUID,
    ) -> ProtectedPayloadRecord:
        row = (
            self.database.connection.execute(
                """
                SELECT
                    protected_payload_id,
                    protection_scope_id,
                    scope_key_id,
                    cipher_suite,
                    ciphertext,
                    nonce,
                    wrapped_dek,
                    dek_wrap_nonce,
                    aad_version,
                    ciphertext_hash,
                    created_at_us
                FROM protected_payloads
                WHERE protected_payload_id = ?
                """,
                (
                    uuid_to_blob(
                        protected_payload_id
                    ),
                ),
            ).fetchone()
        )

        if row is None:
            raise ProtectionPayloadNotFoundError(
                str(
                    protected_payload_id
                )
            )

        return ProtectedPayloadRecord(
            protected_payload_id=uuid_from_blob(
                bytes(
                    row[
                        "protected_payload_id"
                    ]
                )
            ),
            protection_scope_id=uuid_from_blob(
                bytes(
                    row[
                        "protection_scope_id"
                    ]
                )
            ),
            scope_key_id=uuid_from_blob(
                bytes(
                    row["scope_key_id"]
                )
            ),
            cipher_suite=str(
                row["cipher_suite"]
            ),
            ciphertext=bytes(
                row["ciphertext"]
            ),
            nonce=bytes(
                row["nonce"]
            ),
            wrapped_dek=bytes(
                row["wrapped_dek"]
            ),
            dek_wrap_nonce=bytes(
                row["dek_wrap_nonce"]
            ),
            aad_version=int(
                row["aad_version"]
            ),
            ciphertext_hash=bytes(
                row["ciphertext_hash"]
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
        )

    @staticmethod
    def _password_slot_from_row(
        row: sqlite3.Row,
    ) -> PasswordKeySlotRecord:
        raw_parameters = row[
            "kdf_parameters_json"
        ]

        if not isinstance(
            raw_parameters,
            str,
        ):
            raise (
                ProtectionRepositoryIntegrityError(
                    "Active password key slot has no "
                    "Argon2id parameters."
                )
            )

        try:
            parameters = (
                Argon2idParameters.from_json(
                    raw_parameters
                )
            )
            slot_type = KeySlotType(
                str(
                    row["slot_type"]
                )
            )
            status = KeyStatus(
                str(
                    row["status"]
                )
            )

        except ValueError as exc:
            raise (
                ProtectionRepositoryIntegrityError(
                    "Active password key slot "
                    "metadata is invalid."
                )
            ) from exc

        raw_salt = row["salt"]
        raw_wrap_nonce = row[
            "wrap_nonce"
        ]
        raw_wrapped_root_key = row[
            "wrapped_root_key"
        ]

        if not isinstance(
            raw_salt,
            bytes,
        ):
            raise (
                ProtectionRepositoryIntegrityError(
                    "Active password key slot "
                    "salt is invalid."
                )
            )

        if not isinstance(
            raw_wrap_nonce,
            bytes,
        ):
            raise (
                ProtectionRepositoryIntegrityError(
                    "Active password key slot "
                    "nonce is invalid."
                )
            )

        if not isinstance(
            raw_wrapped_root_key,
            bytes,
        ):
            raise (
                ProtectionRepositoryIntegrityError(
                    "Active password key slot "
                    "wrapped key is invalid."
                )
            )

        raw_retired_at = row[
            "retired_at_us"
        ]

        return PasswordKeySlotRecord(
            key_slot_id=uuid_from_blob(
                bytes(
                    row["key_slot_id"]
                )
            ),
            slot_type=slot_type,
            kdf_algorithm=str(
                row["kdf_algorithm"]
            ),
            kdf_parameters=parameters,
            salt=raw_salt,
            wrap_algorithm=str(
                row["wrap_algorithm"]
            ),
            wrap_nonce=raw_wrap_nonce,
            wrapped_root_key=(
                raw_wrapped_root_key
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
            retired_at_us=(
                None
                if raw_retired_at is None
                else int(
                    raw_retired_at
                )
            ),
            status=status,
        )

    @staticmethod
    def _scope_key_from_row(
        row: sqlite3.Row,
    ) -> ProtectionScopeKeyRecord:
        raw_retired_at = row[
            "retired_at_us"
        ]

        try:
            status = KeyStatus(
                str(
                    row["status"]
                )
            )
        except ValueError as exc:
            raise (
                ProtectionRepositoryIntegrityError(
                    "ProtectionScope Key "
                    "status is invalid."
                )
            ) from exc

        return ProtectionScopeKeyRecord(
            scope_key_id=uuid_from_blob(
                bytes(
                    row["scope_key_id"]
                )
            ),
            protection_scope_id=uuid_from_blob(
                bytes(
                    row[
                        "protection_scope_id"
                    ]
                )
            ),
            key_version=int(
                row["key_version"]
            ),
            wrap_algorithm=str(
                row["wrap_algorithm"]
            ),
            wrap_nonce=bytes(
                row["wrap_nonce"]
            ),
            wrapped_scope_key=bytes(
                row["wrapped_scope_key"]
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
            retired_at_us=(
                None
                if raw_retired_at is None
                else int(
                    raw_retired_at
                )
            ),
            status=status,
        )
