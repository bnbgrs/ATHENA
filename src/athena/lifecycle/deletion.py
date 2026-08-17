"""Payload-free durable deletion ledger and restore reapplication."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from athena.common.ids import (
    new_uuid7,
    uuid_from_blob,
    uuid_to_blob,
)
from athena.common.time import utc_now_us

PERSONAL_MEMORY_ENTITY_TYPE = (
    "personal_memory_entry"
)

RESTORE_DELETION_ENTITY_TYPES = frozenset(
    {
        PERSONAL_MEMORY_ENTITY_TYPE,
        "knowledge_unit",
        "source",
        "chat",
        "chat_message",
        "protection_scope",
    }
)



class DeletionLedgerError(RuntimeError):
    """Raised when durable deletion state cannot be applied safely."""


@dataclass(
    frozen=True,
    slots=True,
)
class DeletionLedgerRecord:
    ledger_seq: int
    deletion_id: uuid.UUID
    entity_id: uuid.UUID
    entity_type: str
    deleted_at_us: int
    deletion_commit_seq: int
    deleted_by_actor_id: uuid.UUID


def record_deletion(
    connection: sqlite3.Connection,
    *,
    entity_id: uuid.UUID,
    entity_type: str,
    deleted_at_us: int,
    deletion_commit_seq: int,
    deleted_by_actor_id: uuid.UUID,
) -> DeletionLedgerRecord:
    """Persist one idempotent payload-free permanent-deletion marker."""
    normalized_type = entity_type.strip()

    if not normalized_type:
        raise ValueError(
            "Deletion entity_type must not be empty."
        )

    if deleted_at_us < 0:
        raise ValueError(
            "Deletion timestamp must be non-negative."
        )

    if deletion_commit_seq <= 0:
        raise ValueError(
            "Deletion commit sequence must be positive."
        )

    entity_blob = uuid_to_blob(
        entity_id
    )

    existing = connection.execute(
        """
        SELECT
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        FROM deletion_ledger
        WHERE entity_id = ?
        """,
        (entity_blob,),
    ).fetchone()

    if existing is not None:
        record = _record_from_row(
            existing
        )

        if (
            record.entity_type
            != normalized_type
            or record.deleted_by_actor_id
            != deleted_by_actor_id
            or record.deletion_commit_seq
            != deletion_commit_seq
            or record.deleted_at_us
            != deleted_at_us
        ):
            raise DeletionLedgerError(
                "Existing deletion marker disagrees "
                "with the requested deletion."
            )

        return record

    deletion_id = new_uuid7()

    connection.execute(
        """
        INSERT INTO deletion_ledger (
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            uuid_to_blob(
                deletion_id
            ),
            entity_blob,
            normalized_type,
            deleted_at_us,
            deletion_commit_seq,
            uuid_to_blob(
                deleted_by_actor_id
            ),
        ),
    )

    row = connection.execute(
        """
        SELECT
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        FROM deletion_ledger
        WHERE entity_id = ?
        """,
        (entity_blob,),
    ).fetchone()

    if row is None:
        raise DeletionLedgerError(
            "Deletion marker vanished after insert."
        )

    return _record_from_row(
        row
    )


def current_deletion_watermark(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(
            MAX(ledger_seq),
            0
        )
        FROM deletion_ledger
        """
    ).fetchone()

    if row is None:
        return 0

    value = int(
        row[0]
    )

    if value < 0:
        raise DeletionLedgerError(
            "Deletion ledger watermark is invalid."
        )

    return value


def read_deletion_records(
    connection: sqlite3.Connection,
    *,
    after_seq: int = 0,
) -> tuple[
    DeletionLedgerRecord,
    ...,
]:
    if after_seq < 0:
        raise ValueError(
            "Deletion ledger cursor must be non-negative."
        )

    rows = connection.execute(
        """
        SELECT
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        FROM deletion_ledger
        WHERE ledger_seq > ?
        ORDER BY ledger_seq
        """,
        (after_seq,),
    ).fetchall()

    return tuple(
        _record_from_row(
            row
        )
        for row in rows
    )


def _mark_restored_scope_blob_deleted(
    connection: sqlite3.Connection,
    *,
    blob_id: bytes,
) -> None:
    """Tombstone a restored crypto-erased Protected Blob."""

    entity = connection.execute(
        """
        SELECT
            entity_type,
            lifecycle_state,
            protection_scope_id
        FROM entity_registry
        WHERE entity_id = ?
        """,
        (
            blob_id,
        ),
    ).fetchone()

    if entity is None:
        raise DeletionLedgerError(
            "Restored ProtectionScope references "
            "a missing Blob entity."
        )

    if str(
        entity[
            "entity_type"
        ]
    ) != "blob_record":
        raise DeletionLedgerError(
            "Restored ProtectionScope Blob "
            "has an unexpected entity type."
        )

    if str(
        entity[
            "lifecycle_state"
        ]
    ) == "deleted":
        return

    replay = connection.execute(
        """
        SELECT
            history.valid_from_commit_seq,
            history.changed_by_actor_id
        FROM sources AS source
        JOIN entity_state_history AS history
          ON history.entity_id = source.source_id
        WHERE source.blob_id = ?
          AND history.lifecycle_state = 'deleted'
          AND history.valid_to_commit_seq IS NULL
        ORDER BY
            history.valid_from_commit_seq DESC
        LIMIT 1
        """,
        (
            blob_id,
        ),
    ).fetchone()

    if replay is None:
        scope_actor = connection.execute(
            """
            SELECT
                ledger.deletion_commit_seq,
                ledger.deleted_by_actor_id
            FROM deletion_ledger AS ledger
            JOIN entity_registry AS blob_entity
              ON blob_entity.protection_scope_id =
                 ledger.entity_id
            WHERE blob_entity.entity_id = ?
              AND ledger.entity_type =
                  'protection_scope'
            LIMIT 1
            """,
            (
                blob_id,
            ),
        ).fetchone()

        if scope_actor is None:
            raise DeletionLedgerError(
                "Restored Protected Blob has no "
                "deletion audit anchor."
            )

        commit_seq = int(
            scope_actor[
                "deletion_commit_seq"
            ]
        )

        actor_id = bytes(
            scope_actor[
                "deleted_by_actor_id"
            ]
        )

    else:
        commit_seq = int(
            replay[
                "valid_from_commit_seq"
            ]
        )

        actor_id = bytes(
            replay[
                "changed_by_actor_id"
            ]
        )

    open_history = connection.execute(
        """
        SELECT valid_from_commit_seq
        FROM entity_state_history
        WHERE entity_id = ?
          AND valid_to_commit_seq IS NULL
        """,
        (
            blob_id,
        ),
    ).fetchall()

    if len(open_history) != 1:
        raise DeletionLedgerError(
            "Restored Protected Blob has "
            "ambiguous lifecycle history."
        )

    open_from = int(
        open_history[0][
            "valid_from_commit_seq"
        ]
    )

    if commit_seq <= open_from:
        commit_seq = open_from + 1

        synthetic = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id,
                committed_at_us,
                actor_id,
                operation_type,
                reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(
                    new_uuid7()
                ),
                record_deleted_at_us := utc_now_us(),
                actor_id,
                (
                    "restore.lifecycle."
                    "protection_scope_blob"
                ),
                (
                    "restore replay of "
                    "ProtectionScope Blob "
                    "crypto-erasure"
                ),
            ),
        )

        if synthetic.lastrowid is None:
            raise DeletionLedgerError(
                "Could not allocate restore "
                "Blob tombstone commit."
            )

        commit_seq = int(
            synthetic.lastrowid
        )

        _ = record_deleted_at_us

    closed = connection.execute(
        """
        UPDATE entity_state_history
        SET valid_to_commit_seq = ?
        WHERE entity_id = ?
          AND valid_to_commit_seq IS NULL
        """,
        (
            commit_seq,
            blob_id,
        ),
    )

    if closed.rowcount != 1:
        raise DeletionLedgerError(
            "Restored Protected Blob lifecycle "
            "could not be closed."
        )

    raw_scope = entity[
        "protection_scope_id"
    ]

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
        ) VALUES (
            ?, ?, NULL, 'deleted',
            ?, ?, ?
        )
        """,
        (
            blob_id,
            commit_seq,
            (
                None
                if raw_scope is None
                else bytes(
                    raw_scope
                )
            ),
            actor_id,
            (
                "restored ProtectionScope "
                "Blob crypto-erasure"
            ),
        ),
    )

    updated = connection.execute(
        """
        UPDATE entity_registry
        SET lifecycle_state = 'deleted'
        WHERE entity_id = ?
        """,
        (
            blob_id,
        ),
    )

    if updated.rowcount != 1:
        raise DeletionLedgerError(
            "Restored Protected Blob "
            "tombstone failed."
        )

    connection.execute(
        """
        INSERT INTO commit_changes (
            commit_seq,
            entity_id,
            revision_id,
            change_type
        ) VALUES (
            ?, ?, NULL, 'deleted'
        )
        """,
        (
            commit_seq,
            blob_id,
        ),
    )


def _apply_protection_scope_deletion(
    connection: sqlite3.Connection,
    record: DeletionLedgerRecord,
) -> None:
    """Remove restored decryptability for one deleted ProtectionScope."""

    scope_blob = uuid_to_blob(
        record.entity_id
    )

    scope = connection.execute(
        """
        SELECT 1
        FROM protection_scopes
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    ).fetchone()

    # A deletion can legitimately post-date a snapshot
    # in which this scope did not yet exist.
    if scope is None:
        return

    source_rows = connection.execute(
        """
        SELECT DISTINCT
            source.source_id,
            source.blob_id
        FROM sources AS source
        JOIN entity_registry AS entity
          ON entity.entity_id =
             source.source_id
        WHERE
            entity.protection_scope_id = ?
            OR EXISTS (
                SELECT 1
                FROM protected_sources
                    AS protected
                WHERE
                    protected.source_id =
                        source.source_id
                    AND
                    protected.protection_scope_id = ?
            )
        ORDER BY source.source_id
        """,
        (
            scope_blob,
            scope_blob,
        ),
    ).fetchall()

    source_ids = tuple(
        bytes(
            row[
                "source_id"
            ]
        )
        for row in source_rows
    )

    blob_ids = tuple(
        bytes(
            row[
                "blob_id"
            ]
        )
        for row in source_rows
    )
    envelope_blob_rows = connection.execute(
        """
        SELECT blob_id
        FROM protected_blob_envelopes
        WHERE protection_scope_id = ?
        ORDER BY blob_id
        """,
        (
            scope_blob,
        ),
    ).fetchall()

    blob_ids = tuple(
        sorted(
            set(blob_ids)
            | {
                bytes(row["blob_id"])
                for row in envelope_blob_rows
            }
        )
    )


    # 15e2 records Source deletions before the Scope
    # deletion. Therefore an old snapshot must already
    # have replayed each associated Source tombstone
    # before the Scope key material can be destroyed.
    for source_id in source_ids:
        ledger = connection.execute(
            """
            SELECT entity_type
            FROM deletion_ledger
            WHERE entity_id = ?
            """,
            (
                source_id,
            ),
        ).fetchone()

        entity = connection.execute(
            """
            SELECT lifecycle_state
            FROM entity_registry
            WHERE entity_id = ?
            """,
            (
                source_id,
            ),
        ).fetchone()

        if (
            ledger is None
            or str(
                ledger[
                    "entity_type"
                ]
            )
            != "source"
            or entity is None
            or str(
                entity[
                    "lifecycle_state"
                ]
            )
            != "deleted"
        ):
            raise DeletionLedgerError(
                "ProtectionScope deletion is "
                "missing its corresponding "
                "deleted Source state."
            )

    # Existing-source protection transitions deliberately
    # guard Source metadata against mutation. A restored
    # obsolete transition must therefore be removed first.
    for blob_id in blob_ids:
        _mark_restored_scope_blob_deleted(
            connection,
            blob_id=blob_id,
        )

    connection.execute(
        """
        DELETE FROM
            source_protection_transitions
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    )

    if source_ids:
        placeholders = ", ".join(
            "?"
            for _source_id
            in source_ids
        )

        connection.execute(
            f"""
            UPDATE sources
            SET
                source_type = 'other',
                original_name = NULL,
                original_modified_at_us = NULL,
                mime_type = NULL,
                source_uri = NULL
            WHERE source_id IN (
                {placeholders}
            )
            """,
            source_ids,
        )

    if blob_ids:
        placeholders = ", ".join(
            "?"
            for _blob_id
            in blob_ids
        )

        connection.execute(
            f"""
            DELETE FROM
                archive_replication_outbox
            WHERE blob_id IN (
                {placeholders}
            )
            """,
            blob_ids,
        )

    # Delete every object that could still carry a DEK
    # wrapped by the Scope Key before deleting the Scope Key.
    connection.execute(
        """
        DELETE FROM protected_sources
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    )

    connection.execute(
        """
        DELETE FROM
            protected_blob_envelopes
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    )

    connection.execute(
        """
        DELETE FROM protected_payloads
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    )

    # Break the current-key FK before removing key rows.
    updated = connection.execute(
        """
        UPDATE protection_scopes
        SET
            lifecycle_state = 'pending_delete',
            current_scope_key_id = NULL,
            neutral_label = NULL
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    )

    if updated.rowcount != 1:
        raise DeletionLedgerError(
            "ProtectionScope restore deletion "
            "could not update the scope row."
        )

    connection.execute(
        """
        DELETE FROM protection_scope_keys
        WHERE protection_scope_id = ?
        """,
        (
            scope_blob,
        ),
    )


def apply_deletion_records(
    connection: sqlite3.Connection,
    records: tuple[
        DeletionLedgerRecord,
        ...,
    ],
) -> int:
    """Merge ledger records and reapply supported deletions transactionally."""
    if connection.in_transaction:
        raise DeletionLedgerError(
            "Deletion restore application requires "
            "no active transaction."
        )

    ordered = tuple(
        sorted(
            records,
            key=lambda item: (
                item.ledger_seq,
                item.deletion_id.int,
            ),
        )
    )

    previous_seq = 0

    for record in ordered:
        if (
            record.ledger_seq <= 0
            or record.ledger_seq
            <= previous_seq
        ):
            raise DeletionLedgerError(
                "Deletion ledger sequence is "
                "not strictly increasing."
            )

        previous_seq = (
            record.ledger_seq
        )

    applied = 0

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        for record in ordered:
            _merge_record(
                connection,
                record,
            )

            entity_blob = uuid_to_blob(
                record.entity_id
            )

            if record.entity_type == "protection_scope":
                _apply_protection_scope_deletion(
                    connection,
                    record,
                )
                continue

            entity = connection.execute(
                """
                SELECT
                    entity_type,
                    lifecycle_state,
                    protection_scope_id
                FROM entity_registry
                WHERE entity_id = ?
                """,
                (entity_blob,),
            ).fetchone()

            # The deletion may refer to an entity created after
            # the restored snapshot. Keep its marker anyway.
            if entity is None:
                continue

            actual_type = str(
                entity["entity_type"]
            )

            if (
                actual_type
                != record.entity_type
            ):
                raise DeletionLedgerError(
                    "Deletion marker entity type "
                    "does not match restored entity."
                )

            if (
                str(
                    entity[
                        "lifecycle_state"
                    ]
                )
                == "deleted"
            ):
                continue

            if (
                actual_type
                not in RESTORE_DELETION_ENTITY_TYPES
            ):
                raise DeletionLedgerError(
                    "Restore encountered a deletion "
                    "entity type without an explicit "
                    "safe reapplication handler."
                )

            actor_blob = uuid_to_blob(
                record.deleted_by_actor_id
            )

            actor = connection.execute(
                """
                SELECT actor_id
                FROM actors
                WHERE actor_id = ?
                """,
                (actor_blob,),
            ).fetchone()

            if actor is None:
                raise DeletionLedgerError(
                    "Deletion actor required for "
                    "restore audit history is absent."
                )

            commit_id = new_uuid7()
            restored_at_us = (
                utc_now_us()
            )

            cursor = connection.execute(
                """
                INSERT INTO commit_records (
                    commit_id,
                    committed_at_us,
                    actor_id,
                    operation_type,
                    reason
                ) VALUES (
                    ?,
                    ?,
                    ?,
                    'restore.apply_deletion_ledger',
                    'durable deletion ledger reapplication'
                )
                """,
                (
                    uuid_to_blob(
                        commit_id
                    ),
                    restored_at_us,
                    actor_blob,
                ),
            )

            if cursor.lastrowid is None:
                raise DeletionLedgerError(
                    "SQLite did not return a restore "
                    "deletion commit sequence."
                )

            restore_commit_seq = int(
                cursor.lastrowid
            )

            closed = connection.execute(
                """
                UPDATE entity_state_history
                SET valid_to_commit_seq = ?
                WHERE entity_id = ?
                  AND valid_to_commit_seq IS NULL
                """,
                (
                    restore_commit_seq,
                    entity_blob,
                ),
            )

            if closed.rowcount != 1:
                raise DeletionLedgerError(
                    "Restored entity has ambiguous "
                    "open lifecycle history."
                )

            protection_scope_id = (
                bytes(
                    entity[
                        "protection_scope_id"
                    ]
                )
                if entity[
                    "protection_scope_id"
                ] is not None
                else None
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
                ) VALUES (
                    ?,
                    ?,
                    NULL,
                    'deleted',
                    ?,
                    ?,
                    'durable deletion ledger reapplication'
                )
                """,
                (
                    entity_blob,
                    restore_commit_seq,
                    protection_scope_id,
                    actor_blob,
                ),
            )

            connection.execute(
                """
                UPDATE entity_registry
                SET lifecycle_state = 'deleted'
                WHERE entity_id = ?
                """,
                (entity_blob,),
            )

            if actual_type == "chat":
                updated_chat = connection.execute(
                    """
                    UPDATE chats
                    SET lifecycle_state = 'deleted'
                    WHERE chat_id = ?
                    """,
                    (entity_blob,),
                )

                if updated_chat.rowcount != 1:
                    raise DeletionLedgerError(
                        "Restored Chat deletion has no "
                        "matching canonical chat row."
                    )

            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq,
                    entity_id,
                    revision_id,
                    change_type
                ) VALUES (
                    ?,
                    ?,
                    NULL,
                    'deleted_restore'
                )
                """,
                (
                    restore_commit_seq,
                    entity_blob,
                ),
            )

            applied += 1

        connection.execute(
            "COMMIT"
        )

    except BaseException:
        connection.rollback()
        raise

    return applied


def _merge_record(
    connection: sqlite3.Connection,
    record: DeletionLedgerRecord,
) -> None:
    """Insert idempotently and reject every identity collision."""
    entity_blob = uuid_to_blob(
        record.entity_id
    )

    deletion_blob = uuid_to_blob(
        record.deletion_id
    )

    actor_blob = uuid_to_blob(
        record.deleted_by_actor_id
    )

    connection.execute(
        """
        INSERT OR IGNORE INTO deletion_ledger (
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.ledger_seq,
            deletion_blob,
            entity_blob,
            record.entity_type,
            record.deleted_at_us,
            record.deletion_commit_seq,
            actor_blob,
        ),
    )

    entity_rows = connection.execute(
        """
        SELECT
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        FROM deletion_ledger
        WHERE entity_id = ?
        """,
        (
            entity_blob,
        ),
    ).fetchall()

    if len(entity_rows) != 1:
        raise DeletionLedgerError(
            "Deletion ledger entity_id did not resolve uniquely."
        )

    entity_record = _record_from_row(
        entity_rows[0]
    )

    if entity_record != record:
        raise DeletionLedgerError(
            "Deletion ledger conflict for entity_id."
        )

    deletion_rows = connection.execute(
        """
        SELECT
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        FROM deletion_ledger
        WHERE deletion_id = ?
        """,
        (
            deletion_blob,
        ),
    ).fetchall()

    if len(deletion_rows) != 1:
        raise DeletionLedgerError(
            "Deletion ledger deletion_id did not resolve uniquely."
        )

    deletion_record = _record_from_row(
        deletion_rows[0]
    )

    if deletion_record != record:
        raise DeletionLedgerError(
            "Deletion ledger conflict for deletion_id."
        )

    sequence_rows = connection.execute(
        """
        SELECT
            ledger_seq,
            deletion_id,
            entity_id,
            entity_type,
            deleted_at_us,
            deletion_commit_seq,
            deleted_by_actor_id
        FROM deletion_ledger
        WHERE ledger_seq = ?
        """,
        (
            record.ledger_seq,
        ),
    ).fetchall()

    if len(sequence_rows) != 1:
        raise DeletionLedgerError(
            "Deletion ledger ledger_seq did not resolve uniquely."
        )

    sequence_record = _record_from_row(
        sequence_rows[0]
    )

    if sequence_record != record:
        raise DeletionLedgerError(
            "Deletion ledger conflict for ledger_seq."
        )








def _record_from_row(
    row: sqlite3.Row,
) -> DeletionLedgerRecord:
    return DeletionLedgerRecord(
        ledger_seq=int(
            row["ledger_seq"]
        ),
        deletion_id=uuid_from_blob(
            bytes(
                row[
                    "deletion_id"
                ]
            )
        ),
        entity_id=uuid_from_blob(
            bytes(
                row[
                    "entity_id"
                ]
            )
        ),
        entity_type=str(
            row["entity_type"]
        ),
        deleted_at_us=int(
            row["deleted_at_us"]
        ),
        deletion_commit_seq=int(
            row[
                "deletion_commit_seq"
            ]
        ),
        deleted_by_actor_id=(
            uuid_from_blob(
                bytes(
                    row[
                        "deleted_by_actor_id"
                    ]
                )
            )
        ),
    )
