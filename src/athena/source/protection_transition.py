"""Restart-safe protection transitions for existing Raw Archive Sources."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.repository import JobRepository
from athena.lifecycle.runtime_lock import runtime_data_lock
from athena.security.service import (
    ProtectedContentService,
    ProtectionScopeLockedError,
)
from athena.source.blob_store import BlobStore
from athena.source.models import (
    BlobRecord,
    BlobStorageArea,
    SourceCaptureResult,
    SourceRecord,
)
from athena.source.protected_blob import (
    PreparedProtectedBlob,
    ProtectedBlobStore,
    ProtectedSourceMetadata,
)
from athena.source.repository import SourceRepository
from athena.storage.database import SQLiteDatabase


class SourceProtectionTransitionError(RuntimeError):
    """Base error for an existing-Source protection transition."""


class SourceProtectionUnsafeError(SourceProtectionTransitionError):
    """Raised when an existing Source cannot be protected without leakage risk."""


class SourceProtectionOperationalBlockerError(
    SourceProtectionTransitionError
):
    """Raised after pending commits while running dependent jobs terminate."""


class SourceProtectionTransitionState(str, Enum):
    PENDING = "pending"
    PREPARED = "prepared"
    SANITIZED = "sanitized"


@dataclass(frozen=True, slots=True)
class SourceProtectionTransitionRecord:
    transition_id: uuid.UUID
    source_id: uuid.UUID
    protection_scope_id: uuid.UUID
    old_blob_id: uuid.UUID
    target_blob_id: uuid.UUID | None
    protected_metadata_payload_id: uuid.UUID | None
    state: SourceProtectionTransitionState
    created_at_us: int
    updated_at_us: int


SourceOperationalStateCutover = Callable[
    [sqlite3.Connection],
    tuple[
        tuple[uuid.UUID, ...],
        tuple[uuid.UUID, ...],
    ],
]


class SourceProtectionTransitionRepository:
    """Durable copy-on-write state for existing Source protection."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_for_source(
        self,
        source_id: uuid.UUID,
    ) -> SourceProtectionTransitionRecord | None:
        row = self.database.connection.execute(
            """
            SELECT
                transition_id,
                source_id,
                protection_scope_id,
                old_blob_id,
                target_blob_id,
                protected_metadata_payload_id,
                state,
                created_at_us,
                updated_at_us
            FROM source_protection_transitions
            WHERE source_id = ?
            """,
            (uuid_to_blob(source_id),),
        ).fetchone()
        if row is None:
            return None
        return self._record_from_row(row)

    def list_recoverable(
        self,
        *,
        limit: int = 100,
    ) -> tuple[SourceProtectionTransitionRecord, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("Transition recovery limit must be between 1 and 1000.")
        rows = self.database.connection.execute(
            """
            SELECT
                transition_id,
                source_id,
                protection_scope_id,
                old_blob_id,
                target_blob_id,
                protected_metadata_payload_id,
                state,
                created_at_us,
                updated_at_us
            FROM source_protection_transitions
            WHERE state IN ('prepared', 'sanitized')
            ORDER BY created_at_us, transition_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def protected_scope(
        self,
        source_id: uuid.UUID,
    ) -> uuid.UUID | None:
        row = self.database.connection.execute(
            """
            SELECT protection_scope_id
            FROM protected_sources
            WHERE source_id = ?
            """,
            (uuid_to_blob(source_id),),
        ).fetchone()
        if row is None:
            return None
        return uuid_from_blob(bytes(row["protection_scope_id"]))

    def begin(
        self,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
        operational_state_cutover: (
            SourceOperationalStateCutover
            | None
        ) = None,
    ) -> SourceProtectionTransitionRecord:
        now_us = utc_now_us()
        transition_id = new_uuid7()

        blockers: tuple[
            uuid.UUID,
            ...,
        ] = ()

        existing_record: (
            SourceProtectionTransitionRecord
            | None
        ) = None

        with (
            self.database.write_transaction()
            as connection
        ):
            existing = connection.execute(
                """
                SELECT
                    transition_id,
                    source_id,
                    protection_scope_id,
                    old_blob_id,
                    target_blob_id,
                    protected_metadata_payload_id,
                    state,
                    created_at_us,
                    updated_at_us
                FROM source_protection_transitions
                WHERE source_id = ?
                """,
                (
                    uuid_to_blob(
                        source_id
                    ),
                ),
            ).fetchone()

            if existing is not None:
                existing_record = (
                    self._record_from_row(
                        existing
                    )
                )

                if (
                    existing_record
                    .protection_scope_id
                    != protection_scope_id
                ):
                    raise (
                        SourceProtectionUnsafeError(
                            "Source already has a "
                            "protection transition "
                            "for another scope."
                        )
                    )

                if (
                    existing_record.state
                    is SourceProtectionTransitionState.PENDING
                    and operational_state_cutover
                    is not None
                ):
                    (
                        _migrated,
                        blockers,
                    ) = operational_state_cutover(
                        connection
                    )

            else:
                protected = (
                    connection.execute(
                        """
                        SELECT protection_scope_id
                        FROM protected_sources
                        WHERE source_id = ?
                        """,
                        (
                            uuid_to_blob(
                                source_id
                            ),
                        ),
                    ).fetchone()
                )

                if protected is not None:
                    raise (
                        SourceProtectionUnsafeError(
                            "Source is already protected."
                        )
                    )

                row = connection.execute(
                    """
                    SELECT
                        s.source_id,
                        s.original_name,
                        s.source_uri,
                        s.content_sha256,
                        s.blob_id,
                        b.byte_length,
                        b.integrity_sha256,
                        b.encryption_state
                    FROM sources AS s
                    JOIN blob_records AS b
                      ON b.blob_id = s.blob_id
                    WHERE s.source_id = ?
                    """,
                    (
                        uuid_to_blob(
                            source_id
                        ),
                    ),
                ).fetchone()

                if row is None:
                    raise LookupError(
                        str(
                            source_id
                        )
                    )

                if (
                    row["original_name"]
                    is None
                    or not str(
                        row[
                            "original_name"
                        ]
                    ).strip()
                    or row["source_uri"]
                    is None
                    or not str(
                        row[
                            "source_uri"
                        ]
                    ).strip()
                    or str(
                        row[
                            "encryption_state"
                        ]
                    )
                    != "none"
                    or bytes(
                        row[
                            "content_sha256"
                        ]
                    )
                    != bytes(
                        row[
                            "integrity_sha256"
                        ]
                    )
                ):
                    raise (
                        SourceProtectionUnsafeError(
                            "Source does not have "
                            "a complete trustworthy "
                            "unprotected capture."
                        )
                    )

                scope = (
                    connection.execute(
                        """
                        SELECT lifecycle_state
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

                if (
                    scope is None
                    or str(
                        scope[
                            "lifecycle_state"
                        ]
                    )
                    != "active"
                ):
                    raise (
                        SourceProtectionUnsafeError(
                            "Protection transition "
                            "requires an active "
                            "ProtectionScope."
                        )
                    )

                old_blob_id = uuid_from_blob(
                    bytes(
                        row["blob_id"]
                    )
                )

                source_refs = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM sources
                        WHERE blob_id = ?
                        """,
                        (
                            uuid_to_blob(
                                old_blob_id
                            ),
                        ),
                    ).fetchone()
                )

                representation_refs = (
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM source_representations
                        WHERE source_id = ?
                           OR blob_id = ?
                        """,
                        (
                            uuid_to_blob(
                                source_id
                            ),
                            uuid_to_blob(
                                old_blob_id
                            ),
                        ),
                    ).fetchone()
                )

                if (
                    source_refs is None
                    or int(
                        source_refs[0]
                    )
                    != 1
                    or representation_refs
                    is None
                    or int(
                        representation_refs[0]
                    )
                    != 0
                ):
                    raise (
                        SourceProtectionUnsafeError(
                            "Source protection requires "
                            "an exclusive raw Blob with "
                            "no persisted representations."
                        )
                    )

                connection.execute(
                    """
                    INSERT INTO
                    source_protection_transitions (
                        transition_id,
                        source_id,
                        protection_scope_id,
                        old_blob_id,
                        target_blob_id,
                        protected_metadata_payload_id,
                        state,
                        created_at_us,
                        updated_at_us
                    ) VALUES (
                        ?, ?, ?, ?,
                        NULL, NULL,
                        'pending', ?, ?
                    )
                    """,
                    (
                        uuid_to_blob(
                            transition_id
                        ),
                        uuid_to_blob(
                            source_id
                        ),
                        uuid_to_blob(
                            protection_scope_id
                        ),
                        uuid_to_blob(
                            old_blob_id
                        ),
                        now_us,
                        now_us,
                    ),
                )

                if (
                    operational_state_cutover
                    is not None
                ):
                    (
                        _migrated,
                        blockers,
                    ) = operational_state_cutover(
                        connection
                    )

        # Deliberately AFTER the transaction.
        #
        # pending + cancel_requested must remain durable
        # so no new Source-dependent job can race in
        # while the live worker acknowledges cancellation.
        if blockers:
            raise (
                SourceProtectionOperationalBlockerError(
                    "Source protection is pending "
                    "until running dependent jobs "
                    "have terminated."
                )
            )

        if existing_record is not None:
            return existing_record

        reloaded = self.get_for_source(
            source_id
        )

        if reloaded is None:
            raise (
                SourceProtectionTransitionError(
                    "Source Protection transition "
                    "disappeared during durable "
                    "state advancement."
                )
            )

        return reloaded

    def mark_prepared(
        self,
        *,
        transition_id: uuid.UUID,
        actor_id: uuid.UUID,
        prepared: PreparedProtectedBlob,
        protected_metadata_payload_id: uuid.UUID,
    ) -> SourceProtectionTransitionRecord:
        now_us = utc_now_us()
        target_blob_id = prepared.blob_id
        envelope = prepared.envelope
        target = prepared.prepared_blob

        with self.database.write_transaction() as connection:
            transition = self._require_transition(
                connection,
                transition_id=transition_id,
                state=SourceProtectionTransitionState.PENDING,
            )
            if (
                envelope.blob_id != target_blob_id
                or envelope.protection_scope_id != transition.protection_scope_id
                or target.media_type != "application/octet-stream"
            ):
                raise SourceProtectionTransitionError(
                    "Prepared Protected Blob does not match the transition."
                )

            self._require_transition_source_safe(connection, transition)

            payload = connection.execute(
                """
                SELECT protection_scope_id
                FROM protected_payloads
                WHERE protected_payload_id = ?
                """,
                (uuid_to_blob(protected_metadata_payload_id),),
            ).fetchone()
            if (
                payload is None
                or uuid_from_blob(bytes(payload["protection_scope_id"]))
                != transition.protection_scope_id
            ):
                raise SourceProtectionTransitionError(
                    "Protected metadata payload does not belong to the transition scope."
                )

            commit_seq = self._insert_commit(
                connection,
                actor_id=actor_id,
                operation_type="source.protect.prepare",
                committed_at_us=now_us,
            )
            provenance_id = new_uuid7()
            self._insert_entity(
                connection,
                entity_id=target_blob_id,
                entity_type="blob_record",
                actor_id=actor_id,
                created_at_us=now_us,
                commit_seq=commit_seq,
                protection_scope_id=transition.protection_scope_id,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                entity_id=target_blob_id,
                operation="blob.capture.protected_transition",
                actor_id=actor_id,
                created_at_us=now_us,
                protection_scope_id=transition.protection_scope_id,
            )
            connection.execute(
                """
                INSERT INTO blob_records (
                    blob_id,
                    byte_length,
                    media_type,
                    storage_area,
                    storage_locator,
                    integrity_sha256,
                    encryption_state,
                    created_at_us,
                    verified_at_us
                ) VALUES (
                    ?, ?, 'application/octet-stream',
                    ?, ?, ?, 'protected_v1', ?, ?
                )
                """,
                (
                    uuid_to_blob(target_blob_id),
                    target.byte_length,
                    target.storage_area.value,
                    target.storage_locator,
                    target.integrity_sha256,
                    now_us,
                    now_us,
                ),
            )
            connection.execute(
                """
                INSERT INTO protected_blob_envelopes (
                    blob_id,
                    protection_scope_id,
                    scope_key_id,
                    wrapped_dek,
                    dek_wrap_nonce,
                    nonce_prefix,
                    chunk_size,
                    cipher_suite,
                    format_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(envelope.blob_id),
                    uuid_to_blob(envelope.protection_scope_id),
                    uuid_to_blob(envelope.scope_key_id),
                    envelope.wrapped_dek,
                    envelope.dek_wrap_nonce,
                    envelope.nonce_prefix,
                    envelope.chunk_size,
                    envelope.cipher_suite,
                    envelope.format_version,
                ),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, NULL, 'create')
                """,
                (commit_seq, uuid_to_blob(target_blob_id)),
            )
            cursor = connection.execute(
                """
                UPDATE source_protection_transitions
                SET target_blob_id = ?,
                    protected_metadata_payload_id = ?,
                    state = 'prepared',
                    updated_at_us = ?
                WHERE transition_id = ?
                  AND state = 'pending'
                """,
                (
                    uuid_to_blob(target_blob_id),
                    uuid_to_blob(protected_metadata_payload_id),
                    now_us,
                    uuid_to_blob(transition_id),
                ),
            )
            if cursor.rowcount != 1:
                raise SourceProtectionTransitionError(
                    "Protection transition lost its pending state."
                )

        record = self._get_by_id(transition_id)
        if record is None:
            raise SourceProtectionTransitionError(
                "Protection transition disappeared after preparation."
            )
        return record

    def sanitize_prepared(
        self,
        *,
        transition_id: uuid.UUID,
    ) -> SourceProtectionTransitionRecord:
        now_us = utc_now_us()

        with self.database.write_transaction() as connection:
            transition = self._require_transition(
                connection,
                transition_id=transition_id,
                state=SourceProtectionTransitionState.PREPARED,
            )
            if (
                transition.target_blob_id is None
                or transition.protected_metadata_payload_id is None
            ):
                raise SourceProtectionTransitionError(
                    "Prepared transition is missing durable target state."
                )

            self._require_transition_source_safe(connection, transition)
            target_blob = connection.execute(
                """
                SELECT integrity_sha256
                FROM blob_records
                WHERE blob_id = ?
                  AND encryption_state = 'protected_v1'
                """,
                (uuid_to_blob(transition.target_blob_id),),
            ).fetchone()
            if target_blob is None:
                raise SourceProtectionTransitionError(
                    "Prepared transition target Blob disappeared."
                )

            updated = connection.execute(
                """
                UPDATE sources
                SET original_name = NULL,
                    original_modified_at_us = NULL,
                    mime_type = 'application/octet-stream',
                    blob_id = ?,
                    content_sha256 = ?,
                    source_uri = NULL
                WHERE source_id = ?
                  AND blob_id = ?
                """,
                (
                    uuid_to_blob(transition.target_blob_id),
                    bytes(target_blob["integrity_sha256"]),
                    uuid_to_blob(transition.source_id),
                    uuid_to_blob(transition.old_blob_id),
                ),
            )
            if updated.rowcount != 1:
                raise SourceProtectionTransitionError(
                    "Prepared transition could not sanitize its Source row."
                )

            cursor = connection.execute(
                """
                UPDATE source_protection_transitions
                SET state = 'sanitized',
                    updated_at_us = ?
                WHERE transition_id = ?
                  AND state = 'prepared'
                """,
                (
                    now_us,
                    uuid_to_blob(transition_id),
                ),
            )
            if cursor.rowcount != 1:
                raise SourceProtectionTransitionError(
                    "Prepared transition lost its state during sanitization."
                )

        record = self._get_by_id(transition_id)
        if record is None:
            raise SourceProtectionTransitionError(
                "Sanitized transition disappeared."
            )
        return record

    def checkpoint_plaintext_scrub(self) -> None:
        if self.database.connection.in_transaction:
            raise SourceProtectionTransitionError(
                "Plaintext scrub checkpoint requires no active transaction."
            )
        row = self.database.connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        if row is None or int(row[0]) != 0:
            raise SourceProtectionTransitionError(
                "SQLite WAL plaintext scrub checkpoint is busy."
            )

    def finalize_sanitized(
        self,
        *,
        transition_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        now_us = utc_now_us()

        with self.database.write_transaction() as connection:
            transition = self._require_transition(
                connection,
                transition_id=transition_id,
                state=SourceProtectionTransitionState.SANITIZED,
            )
            if (
                transition.target_blob_id is None
                or transition.protected_metadata_payload_id is None
            ):
                raise SourceProtectionTransitionError(
                    "Sanitized transition is missing durable target state."
                )

            self._require_transition_source_safe(connection, transition)
            target_blob_id = transition.target_blob_id
            payload_id = transition.protected_metadata_payload_id

            target = connection.execute(
                """
                SELECT
                    b.integrity_sha256,
                    b.encryption_state,
                    e.protection_scope_id AS envelope_scope_id,
                    p.protection_scope_id AS payload_scope_id
                FROM blob_records AS b
                JOIN protected_blob_envelopes AS e
                  ON e.blob_id = b.blob_id
                JOIN protected_payloads AS p
                  ON p.protected_payload_id = ?
                WHERE b.blob_id = ?
                """,
                (
                    uuid_to_blob(payload_id),
                    uuid_to_blob(target_blob_id),
                ),
            ).fetchone()
            if (
                target is None
                or str(target["encryption_state"]) != "protected_v1"
                or uuid_from_blob(bytes(target["envelope_scope_id"]))
                != transition.protection_scope_id
                or uuid_from_blob(bytes(target["payload_scope_id"]))
                != transition.protection_scope_id
            ):
                raise SourceProtectionTransitionError(
                    "Sanitized transition target is not trustworthy."
                )

            source_row = connection.execute(
                """
                SELECT se.lifecycle_state AS entity_lifecycle_state
                FROM sources AS s
                JOIN entity_registry AS se ON se.entity_id = s.source_id
                WHERE s.source_id = ?
                  AND s.blob_id = ?
                """,
                (
                    uuid_to_blob(transition.source_id),
                    uuid_to_blob(target_blob_id),
                ),
            ).fetchone()
            if source_row is None:
                raise SourceProtectionTransitionError(
                    "Sanitized Source row disappeared."
                )

            deleted = connection.execute(
                """
                DELETE FROM source_protection_transitions
                WHERE transition_id = ?
                  AND state = 'sanitized'
                """,
                (uuid_to_blob(transition_id),),
            )
            if deleted.rowcount != 1:
                raise SourceProtectionTransitionError(
                    "Sanitized transition could not enter finalization."
                )

            commit_seq = self._insert_commit(
                connection,
                actor_id=actor_id,
                operation_type="source.protect",
                committed_at_us=now_us,
            )
            source_provenance_id = new_uuid7()
            old_blob_provenance_id = new_uuid7()
            self._insert_provenance(
                connection,
                provenance_id=source_provenance_id,
                entity_id=transition.source_id,
                operation="source.protect",
                actor_id=actor_id,
                created_at_us=now_us,
                protection_scope_id=transition.protection_scope_id,
            )
            self._insert_provenance(
                connection,
                provenance_id=old_blob_provenance_id,
                entity_id=transition.old_blob_id,
                operation="blob.retire.protected_transition",
                actor_id=actor_id,
                created_at_us=now_us,
                protection_scope_id=transition.protection_scope_id,
            )

            updated_source = connection.execute(
                """
                UPDATE sources
                SET provenance_id = ?
                WHERE source_id = ?
                  AND blob_id = ?
                  AND original_name IS NULL
                  AND source_uri IS NULL
                  AND mime_type = 'application/octet-stream'
                """,
                (
                    uuid_to_blob(source_provenance_id),
                    uuid_to_blob(transition.source_id),
                    uuid_to_blob(target_blob_id),
                ),
            )
            if updated_source.rowcount != 1:
                raise SourceProtectionTransitionError(
                    "Source protection finalization lost its sanitized Source row."
                )

            connection.execute(
                """
                INSERT INTO protected_sources (
                    source_id,
                    protection_scope_id,
                    protected_metadata_payload_id,
                    created_at_us
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(transition.source_id),
                    uuid_to_blob(transition.protection_scope_id),
                    uuid_to_blob(payload_id),
                    now_us,
                ),
            )

            self._advance_entity_state(
                connection,
                entity_id=transition.source_id,
                actor_id=actor_id,
                commit_seq=commit_seq,
                lifecycle_state=str(source_row["entity_lifecycle_state"]),
                protection_scope_id=transition.protection_scope_id,
                reason="source.protect",
            )
            self._advance_entity_state(
                connection,
                entity_id=transition.old_blob_id,
                actor_id=actor_id,
                commit_seq=commit_seq,
                lifecycle_state="retired",
                protection_scope_id=transition.protection_scope_id,
                reason="blob.retire.protected_transition",
            )

            connection.execute(
                """
                DELETE FROM archive_replication_outbox
                WHERE blob_id = ?
                """,
                (uuid_to_blob(transition.old_blob_id),),
            )
            deleted_blob = connection.execute(
                """
                DELETE FROM blob_records
                WHERE blob_id = ?
                  AND encryption_state = 'none'
                """,
                (uuid_to_blob(transition.old_blob_id),),
            )
            if deleted_blob.rowcount != 1:
                raise SourceProtectionTransitionError(
                    "Original plaintext BlobRecord could not be retired."
                )

            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, NULL, 'update')
                """,
                (commit_seq, uuid_to_blob(transition.source_id)),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, NULL, 'retire')
                """,
                (commit_seq, uuid_to_blob(transition.old_blob_id)),
            )
            self._advance_archive_watermark(connection, now_us=now_us)

    def get_blob(
        self,
        blob_id: uuid.UUID,
    ) -> BlobRecord:
        row = self.database.connection.execute(
            """
            SELECT
                blob_id,
                byte_length,
                media_type AS blob_media_type,
                storage_area,
                storage_locator,
                integrity_sha256,
                encryption_state,
                created_at_us AS blob_created_at_us,
                verified_at_us AS blob_verified_at_us
            FROM blob_records
            WHERE blob_id = ?
            """,
            (uuid_to_blob(blob_id),),
        ).fetchone()
        if row is None:
            raise SourceProtectionTransitionError("Transition BlobRecord is missing.")
        return BlobRecord(
            blob_id=uuid_from_blob(bytes(row["blob_id"])),
            byte_length=int(row["byte_length"]),
            media_type=(
                str(row["blob_media_type"])
                if row["blob_media_type"] is not None
                else None
            ),
            storage_area=BlobStorageArea(str(row["storage_area"])),
            storage_locator=str(row["storage_locator"]),
            integrity_sha256=bytes(row["integrity_sha256"]),
            encryption_state=str(row["encryption_state"]),
            created_at_us=int(row["blob_created_at_us"]),
            verified_at_us=int(row["blob_verified_at_us"]),
        )

    def _get_by_id(
        self,
        transition_id: uuid.UUID,
    ) -> SourceProtectionTransitionRecord | None:
        row = self.database.connection.execute(
            """
            SELECT
                transition_id,
                source_id,
                protection_scope_id,
                old_blob_id,
                target_blob_id,
                protected_metadata_payload_id,
                state,
                created_at_us,
                updated_at_us
            FROM source_protection_transitions
            WHERE transition_id = ?
            """,
            (uuid_to_blob(transition_id),),
        ).fetchone()
        if row is None:
            return None
        return self._record_from_row(row)

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> SourceProtectionTransitionRecord:
        return SourceProtectionTransitionRecord(
            transition_id=uuid_from_blob(bytes(row["transition_id"])),
            source_id=uuid_from_blob(bytes(row["source_id"])),
            protection_scope_id=uuid_from_blob(bytes(row["protection_scope_id"])),
            old_blob_id=uuid_from_blob(bytes(row["old_blob_id"])),
            target_blob_id=(
                uuid_from_blob(bytes(row["target_blob_id"]))
                if row["target_blob_id"] is not None
                else None
            ),
            protected_metadata_payload_id=(
                uuid_from_blob(bytes(row["protected_metadata_payload_id"]))
                if row["protected_metadata_payload_id"] is not None
                else None
            ),
            state=SourceProtectionTransitionState(str(row["state"])),
            created_at_us=int(row["created_at_us"]),
            updated_at_us=int(row["updated_at_us"]),
        )

    @staticmethod
    def _require_transition(
        connection: sqlite3.Connection,
        *,
        transition_id: uuid.UUID,
        state: SourceProtectionTransitionState,
    ) -> SourceProtectionTransitionRecord:
        row = connection.execute(
            """
            SELECT
                transition_id,
                source_id,
                protection_scope_id,
                old_blob_id,
                target_blob_id,
                protected_metadata_payload_id,
                state,
                created_at_us,
                updated_at_us
            FROM source_protection_transitions
            WHERE transition_id = ?
            """,
            (uuid_to_blob(transition_id),),
        ).fetchone()
        if row is None:
            raise SourceProtectionTransitionError("Protection transition is missing.")
        record = SourceProtectionTransitionRepository._record_from_row(row)
        if record.state is not state:
            raise SourceProtectionTransitionError(
                f"Protection transition must be {state.value!r}."
            )
        return record

    @staticmethod
    @staticmethod
    def _require_transition_source_safe(
        connection: sqlite3.Connection,
        transition: SourceProtectionTransitionRecord,
    ) -> None:
        row = connection.execute(
            """
            SELECT
                s.blob_id,
                s.original_name,
                s.original_modified_at_us,
                s.mime_type,
                s.content_sha256,
                s.source_uri,
                old_b.encryption_state AS old_encryption_state,
                target_b.integrity_sha256 AS target_integrity_sha256
            FROM sources AS s
            JOIN blob_records AS old_b ON old_b.blob_id = ?
            LEFT JOIN blob_records AS target_b ON target_b.blob_id = ?
            WHERE s.source_id = ?
            """,
            (
                uuid_to_blob(transition.old_blob_id),
                (
                    uuid_to_blob(transition.target_blob_id)
                    if transition.target_blob_id is not None
                    else None
                ),
                uuid_to_blob(transition.source_id),
            ),
        ).fetchone()
        if row is None or str(row["old_encryption_state"]) != "none":
            raise SourceProtectionTransitionError(
                "Transition source lost its original unprotected Blob."
            )

        actual_blob_id = uuid_from_blob(bytes(row["blob_id"]))
        if transition.state in {
            SourceProtectionTransitionState.PENDING,
            SourceProtectionTransitionState.PREPARED,
        }:
            if (
                actual_blob_id != transition.old_blob_id
                or row["original_name"] is None
                or row["source_uri"] is None
            ):
                raise SourceProtectionTransitionError(
                    "Transition source no longer has its original public state."
                )
            expected_source_refs = 1
        else:
            if (
                transition.target_blob_id is None
                or actual_blob_id != transition.target_blob_id
                or row["original_name"] is not None
                or row["original_modified_at_us"] is not None
                or row["source_uri"] is not None
                or row["mime_type"] != "application/octet-stream"
                or row["target_integrity_sha256"] is None
                or bytes(row["content_sha256"])
                != bytes(row["target_integrity_sha256"])
            ):
                raise SourceProtectionTransitionError(
                    "Sanitized transition source is inconsistent."
                )
            expected_source_refs = 0

        source_refs = connection.execute(
            "SELECT COUNT(*) FROM sources WHERE blob_id = ?",
            (uuid_to_blob(transition.old_blob_id),),
        ).fetchone()
        representation_refs = connection.execute(
            """
            SELECT COUNT(*)
            FROM source_representations
            WHERE source_id = ?
               OR blob_id = ?
            """,
            (
                uuid_to_blob(transition.source_id),
                uuid_to_blob(transition.old_blob_id),
            ),
        ).fetchone()
        if (
            source_refs is None
            or int(source_refs[0]) != expected_source_refs
            or representation_refs is None
            or int(representation_refs[0]) != 0
        ):
            raise SourceProtectionUnsafeError(
                "Transition source is no longer exclusive or representation-free."
            )

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        actor_id: uuid.UUID,
        operation_type: str,
        committed_at_us: int,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id,
                committed_at_us,
                actor_id,
                operation_type,
                reason
            ) VALUES (?, ?, ?, ?, NULL)
            """,
            (
                uuid_to_blob(new_uuid7()),
                committed_at_us,
                uuid_to_blob(actor_id),
                operation_type,
            ),
        )
        if cursor.lastrowid is None:
            raise SourceProtectionTransitionError(
                "SQLite did not return a transition commit sequence."
            )
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_entity(
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        entity_type: str,
        actor_id: uuid.UUID,
        created_at_us: int,
        commit_seq: int,
        protection_scope_id: uuid.UUID,
    ) -> None:
        connection.execute(
            """
            INSERT INTO entity_registry (
                entity_id,
                entity_type,
                domain,
                created_at_us,
                created_by_actor_id,
                lifecycle_state,
                protection_scope_id,
                schema_version
            ) VALUES (?, ?, 'raw_archive', ?, ?, 'active', ?, 1)
            """,
            (
                uuid_to_blob(entity_id),
                entity_type,
                created_at_us,
                uuid_to_blob(actor_id),
                uuid_to_blob(protection_scope_id),
            ),
        )
        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id,
                valid_from_commit_seq,
                valid_to_commit_seq,
                lifecycle_state,
                protection_scope_id,
                changed_by_actor_id,
                reason
            ) VALUES (?, ?, NULL, 'active', ?, ?, NULL)
            """,
            (
                uuid_to_blob(entity_id),
                commit_seq,
                uuid_to_blob(protection_scope_id),
                uuid_to_blob(actor_id),
            ),
        )

    @staticmethod
    def _insert_provenance(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        entity_id: uuid.UUID,
        operation: str,
        actor_id: uuid.UUID,
        created_at_us: int,
        protection_scope_id: uuid.UUID,
    ) -> None:
        connection.execute(
            """
            INSERT INTO provenance_records (
                provenance_id,
                subject_entity_id,
                subject_revision_id,
                operation,
                actor_id,
                created_at_us,
                model_signature_id,
                processing_run_id,
                reason,
                protection_scope_id
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(entity_id),
                operation,
                uuid_to_blob(actor_id),
                created_at_us,
                uuid_to_blob(protection_scope_id),
            ),
        )

    @staticmethod
    def _advance_entity_state(
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        actor_id: uuid.UUID,
        commit_seq: int,
        lifecycle_state: str,
        protection_scope_id: uuid.UUID,
        reason: str,
    ) -> None:
        closed = connection.execute(
            """
            UPDATE entity_state_history
            SET valid_to_commit_seq = ?
            WHERE entity_id = ?
              AND valid_to_commit_seq IS NULL
            """,
            (
                commit_seq,
                uuid_to_blob(entity_id),
            ),
        )
        if closed.rowcount != 1:
            raise SourceProtectionTransitionError(
                "Entity transition requires exactly one current state row."
            )
        connection.execute(
            """
            UPDATE entity_registry
            SET lifecycle_state = ?,
                protection_scope_id = ?
            WHERE entity_id = ?
            """,
            (
                lifecycle_state,
                uuid_to_blob(protection_scope_id),
                uuid_to_blob(entity_id),
            ),
        )
        connection.execute(
            """
            INSERT INTO entity_state_history (
                entity_id,
                valid_from_commit_seq,
                valid_to_commit_seq,
                lifecycle_state,
                protection_scope_id,
                changed_by_actor_id,
                reason
            ) VALUES (?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(entity_id),
                commit_seq,
                lifecycle_state,
                uuid_to_blob(protection_scope_id),
                uuid_to_blob(actor_id),
                reason,
            ),
        )

    @staticmethod
    def _advance_archive_watermark(
        connection: sqlite3.Connection,
        *,
        now_us: int,
    ) -> None:
        pending = connection.execute(
            """
            SELECT MIN(outbox_seq) AS first_pending
            FROM archive_replication_outbox
            WHERE state = 'pending'
            """
        ).fetchone()
        maximum = connection.execute(
            """
            SELECT COALESCE(MAX(outbox_seq), 0) AS maximum
            FROM archive_replication_outbox
            """
        ).fetchone()
        current = connection.execute(
            """
            SELECT contiguous_verified_seq
            FROM archive_replication_watermark
            WHERE singleton_id = 1
            """
        ).fetchone()
        if pending is None or maximum is None or current is None:
            raise SourceProtectionTransitionError(
                "Archive replication watermark state is incomplete."
            )
        first_pending = pending["first_pending"]
        candidate = (
            int(maximum["maximum"])
            if first_pending is None
            else int(first_pending) - 1
        )
        previous = int(current["contiguous_verified_seq"])
        connection.execute(
            """
            UPDATE archive_replication_watermark
            SET contiguous_verified_seq = ?,
                updated_at_us = ?
            WHERE singleton_id = 1
            """,
            (
                max(previous, candidate),
                now_us,
            ),
        )


class SourceProtectionTransitionService:
    """Copy-on-write protection with restart-safe irreversible finalization."""

    name = "source-protection-transition"

    def __init__(
        self,
        *,
        repository: SourceProtectionTransitionRepository,
        sources: SourceRepository,
        blob_store: BlobStore,
        protected_content: ProtectedContentService,
        chat: ChatService,
        jobs: JobRepository,
        runtime_lock_root: Path | None = None,
    ) -> None:
        self.repository = repository
        self.sources = sources
        self.blob_store = blob_store
        self.protected_content = (
            protected_content
        )
        self.chat = chat
        self.jobs = jobs
        self.runtime_lock_root = (
            runtime_lock_root
        )

        self.protected_blobs = (
            ProtectedBlobStore(
                blob_store=blob_store,
                protected_content=(
                    protected_content
                ),
            )
        )

    def start(self) -> None:
        with runtime_data_lock(self.runtime_lock_root):
            for transition in self.repository.list_recoverable(limit=1000):
                if not self._recovery_storage_available(transition):
                    continue
                self._finish_transition(transition)

    def stop(self) -> None:
        return

    def protect_existing_source(
        self,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
    ) -> SourceCaptureResult:
        with runtime_data_lock(
            self.runtime_lock_root
        ):
            protected_scope = (
                self.repository
                .protected_scope(
                    source_id
                )
            )

            if protected_scope is not None:
                if (
                    protected_scope
                    != protection_scope_id
                ):
                    raise (
                        SourceProtectionUnsafeError(
                            "Source is already "
                            "protected by another "
                            "ProtectionScope."
                        )
                    )

                source, blob = (
                    self.sources.get(
                        source_id
                    )
                )

                return SourceCaptureResult(
                    source=source,
                    blob=blob,
                    reused_blob=False,
                )

            transition = (
                self.repository
                .get_for_source(
                    source_id
                )
            )

            if (
                transition is not None
                and transition
                .protection_scope_id
                != protection_scope_id
            ):
                raise (
                    SourceProtectionUnsafeError(
                        "Source already has a "
                        "protection transition "
                        "for another scope."
                    )
                )

            if (
                transition is None
                or transition.state
                is SourceProtectionTransitionState.PENDING
            ):
                if not (
                    self.protected_content
                    .is_unlocked(
                        protection_scope_id
                    )
                ):
                    raise (
                        ProtectionScopeLockedError(
                            "ProtectionScope is locked."
                        )
                    )

                if transition is None:
                    source, blob = (
                        self.sources.get(
                            source_id
                        )
                    )

                    self._metadata_for_source(
                        source,
                        blob,
                    )

                def operational_cutover(
                    connection: sqlite3.Connection,
                ) -> tuple[
                    tuple[uuid.UUID, ...],
                    tuple[uuid.UUID, ...],
                ]:
                    return (
                        self._cutover_operational_state(
                            connection,
                            source_id=source_id,
                            protection_scope_id=(
                                protection_scope_id
                            ),
                        )
                    )

                transition = (
                    self.repository.begin(
                        source_id=source_id,
                        protection_scope_id=(
                            protection_scope_id
                        ),
                        operational_state_cutover=(
                            operational_cutover
                        ),
                    )
                )

            if (
                transition.state
                is SourceProtectionTransitionState.PENDING
            ):
                transition = self._prepare(
                    transition
                )

            return self._finish_transition(
                transition
            )

    def _cutover_operational_state(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: uuid.UUID,
        protection_scope_id: uuid.UUID,
    ) -> tuple[
        tuple[uuid.UUID, ...],
        tuple[uuid.UUID, ...],
    ]:
        def payload_writer(
            payload_connection: sqlite3.Connection,
            plaintext: bytes,
        ) -> uuid.UUID:
            if (
                payload_connection
                is not connection
            ):
                raise (
                    SourceProtectionTransitionError(
                        "Operational payload writer "
                        "left the protection "
                        "transaction."
                    )
                )

            record = (
                self.protected_content
                .prepare_payload(
                    protection_scope_id,
                    plaintext,
                )
            )

            self.protected_content.repository.insert_payload_in_transaction(
                connection,
                record,
            )

            return (
                record.protected_payload_id
            )

        return (
            self.jobs
            .protect_source_dependency_payloads(
                connection,
                source_id=source_id,
                protection_scope_id=(
                    protection_scope_id
                ),
                payload_writer=(
                    payload_writer
                ),
            )
        )

    def _prepare(
        self,
        transition: SourceProtectionTransitionRecord,
    ) -> SourceProtectionTransitionRecord:
        source, old_blob = self.sources.get(
            transition.source_id,
            allow_protection_transition=True,
        )
        metadata = self._metadata_for_source(source, old_blob)
        old_path = self.blob_store.verify_blob(
            storage_area=old_blob.storage_area,
            storage_locator=old_blob.storage_locator,
            expected_sha256=old_blob.integrity_sha256,
            expected_length=old_blob.byte_length,
        )
        captured = self.protected_blobs.capture_file(
            old_path,
            protection_scope_id=transition.protection_scope_id,
            source_type=source.source_type,
        )
        prepared = PreparedProtectedBlob(
            blob_id=captured.blob_id,
            prepared_blob=captured.prepared_blob,
            envelope=captured.envelope,
            metadata=metadata,
        )
        payload = self.protected_content.store_payload(
            transition.protection_scope_id,
            metadata.to_payload(),
        )
        actor_id = self.chat.ensure_local_user()
        prepared_transition = self.repository.mark_prepared(
            transition_id=transition.transition_id,
            actor_id=actor_id,
            prepared=prepared,
            protected_metadata_payload_id=payload.protected_payload_id,
        )
        if prepared_transition.target_blob_id is None:
            raise SourceProtectionTransitionError(
                "Prepared transition did not retain its target Blob."
            )
        target_blob = self.repository.get_blob(prepared_transition.target_blob_id)
        self.blob_store.verify_blob(
            storage_area=target_blob.storage_area,
            storage_locator=target_blob.storage_locator,
            expected_sha256=target_blob.integrity_sha256,
            expected_length=target_blob.byte_length,
        )
        return prepared_transition

    def _finish_transition(
        self,
        transition: SourceProtectionTransitionRecord,
    ) -> SourceCaptureResult:
        if transition.target_blob_id is None:
            raise SourceProtectionTransitionError(
                "Recoverable transition is missing its target Blob."
            )
        target_blob = self.repository.get_blob(transition.target_blob_id)
        self.blob_store.verify_blob(
            storage_area=target_blob.storage_area,
            storage_locator=target_blob.storage_locator,
            expected_sha256=target_blob.integrity_sha256,
            expected_length=target_blob.byte_length,
        )

        if transition.state is SourceProtectionTransitionState.PREPARED:
            old_blob = self.repository.get_blob(transition.old_blob_id)
            old_path = self.blob_store.resolve_blob_path(
                storage_area=old_blob.storage_area,
                storage_locator=old_blob.storage_locator,
            )
            if old_path.exists():
                self.blob_store.verify_blob(
                    storage_area=old_blob.storage_area,
                    storage_locator=old_blob.storage_locator,
                    expected_sha256=old_blob.integrity_sha256,
                    expected_length=old_blob.byte_length,
                )
                try:
                    old_path.unlink()
                except OSError as exc:
                    raise SourceProtectionTransitionError(
                        "Verified plaintext Blob could not be removed."
                    ) from exc
                if old_path.exists():
                    raise SourceProtectionTransitionError(
                        "Verified plaintext Blob still exists after deletion."
                    )
            transition = self.repository.sanitize_prepared(
                transition_id=transition.transition_id,
            )

        if transition.state is not SourceProtectionTransitionState.SANITIZED:
            raise SourceProtectionTransitionError(
                "Transition did not reach its sanitized state."
            )

        self.repository.checkpoint_plaintext_scrub()
        actor_id = self.chat.ensure_local_user()
        self.repository.finalize_sanitized(
            transition_id=transition.transition_id,
            actor_id=actor_id,
        )
        source, blob = self.sources.get(transition.source_id)
        return SourceCaptureResult(
            source=source,
            blob=blob,
            reused_blob=False,
        )

    def _recovery_storage_available(
        self,
        transition: SourceProtectionTransitionRecord,
    ) -> bool:
        if transition.target_blob_id is None:
            return False
        blobs = [self.repository.get_blob(transition.target_blob_id)]
        if transition.state is SourceProtectionTransitionState.PREPARED:
            blobs.append(self.repository.get_blob(transition.old_blob_id))
        for blob in blobs:
            if blob.storage_area is BlobStorageArea.ARCHIVE:
                root = self.blob_store.paths.archive_root
                if root is None or not root.is_dir():
                    return False
        return True

    @staticmethod
    def _metadata_for_source(
        source: SourceRecord,
        blob: BlobRecord,
    ) -> ProtectedSourceMetadata:
        if (
            source.protection_scope_id is not None
            or source.protected_metadata_payload_id is not None
            or source.original_name is None
            or not source.original_name.strip()
            or source.source_uri is None
            or not source.source_uri.strip()
            or blob.encryption_state != "none"
            or source.content_sha256 != blob.integrity_sha256
        ):
            raise SourceProtectionUnsafeError(
                "Source metadata is not safe for an unprotected-to-protected transition."
            )
        return ProtectedSourceMetadata(
            source_type=source.source_type,
            original_name=source.original_name,
            source_uri=source.source_uri,
            original_modified_at_us=source.original_modified_at_us,
            mime_type=source.mime_type,
            plaintext_byte_length=blob.byte_length,
        )
