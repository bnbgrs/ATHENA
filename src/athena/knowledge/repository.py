"""Transactional persistence for canonical ATHENA KnowledgeUnits."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.models import (
    EpistemicStatus,
    KnowledgeKind,
    KnowledgeUnitDraft,
    KnowledgeUnitRevision,
    KnowledgeUnitSnapshot,
    ProvenanceInputRef,
)
from athena.storage.database import SQLiteDatabase


class KnowledgeNotFoundError(LookupError):
    """Raised when a requested KnowledgeUnit does not exist."""


class KnowledgeConflictError(RuntimeError):
    """Raised when a write is based on a stale current revision."""


class KnowledgeSourceError(ValueError):
    """Raised when a provenance input is not a valid stable entity revision."""


class KnowledgeActorError(LookupError):
    """Raised when the requested write actor does not exist or is inactive."""


class KnowledgeRepository:
    """Versioned KnowledgeUnit repository with explicit semantic provenance."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_knowledge_unit(
        self,
        *,
        actor_id: uuid.UUID,
        draft: KnowledgeUnitDraft,
        source_entity_id: uuid.UUID | None = None,
        source_revision_id: uuid.UUID | None = None,
        input_role: str = "source",
        reason: str | None = None,
    ) -> KnowledgeUnitRevision:
        """Create one stable KnowledgeUnit and immutable revision 1."""
        if (source_entity_id is None) != (source_revision_id is None):
            raise KnowledgeSourceError(
                "source_entity_id and source_revision_id must be supplied together."
            )

        knowledge_id = new_uuid7()
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _knowledge_payload_hash(draft)

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            if source_entity_id is not None and source_revision_id is not None:
                self._require_source_revision(
                    connection,
                    entity_id=source_entity_id,
                    revision_id=source_revision_id,
                )

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="knowledge.create",
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_entity(
                connection,
                knowledge_id=knowledge_id,
                actor_id=actor_id,
                created_at_us=created_at_us,
                commit_seq=commit_seq,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                knowledge_id=knowledge_id,
                revision_id=revision_id,
                operation="knowledge.create",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            if source_entity_id is not None and source_revision_id is not None:
                self._insert_provenance_input(
                    connection,
                    provenance_id=provenance_id,
                    input_entity_id=source_entity_id,
                    input_revision_id=source_revision_id,
                    input_role=input_role,
                    ordinal=0,
                )

            self._insert_revision(
                connection,
                knowledge_id=knowledge_id,
                revision_id=revision_id,
                revision_no=1,
                parent_revision_id=None,
                actor_id=actor_id,
                provenance_id=provenance_id,
                commit_id=commit_id,
                created_at_us=created_at_us,
                payload_hash=payload_hash,
                change_kind="create",
            )
            connection.execute(
                """
                INSERT INTO entity_heads (
                    entity_id, current_revision_id, current_revision_no
                ) VALUES (?, ?, 1)
                """,
                (uuid_to_blob(knowledge_id), uuid_to_blob(revision_id)),
            )
            connection.execute(
                "INSERT INTO knowledge_units (knowledge_id) VALUES (?)",
                (uuid_to_blob(knowledge_id),),
            )
            self._insert_payload(connection, revision_id=revision_id, draft=draft)
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'create')
                """,
                (
                    commit_seq,
                    uuid_to_blob(knowledge_id),
                    uuid_to_blob(revision_id),
                ),
            )

        return KnowledgeUnitRevision(
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            revision_no=1,
            created_at_us=created_at_us,
            created_by_actor_id=actor_id,
            provenance_id=provenance_id,
            payload=draft,
        )

    def revise_knowledge_unit(
        self,
        *,
        actor_id: uuid.UUID,
        knowledge_id: uuid.UUID,
        expected_revision_id: uuid.UUID,
        draft: KnowledgeUnitDraft,
        source_entity_id: uuid.UUID | None = None,
        source_revision_id: uuid.UUID | None = None,
        input_role: str = "source",
        reason: str | None = None,
    ) -> KnowledgeUnitRevision:
        """Append a new immutable revision using optimistic head validation."""
        if (source_entity_id is None) != (source_revision_id is None):
            raise KnowledgeSourceError(
                "source_entity_id and source_revision_id must be supplied together."
            )

        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _knowledge_payload_hash(draft)

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            current_revision_id, current_revision_no = self._require_current_head(
                connection,
                knowledge_id=knowledge_id,
            )
            if current_revision_id != expected_revision_id:
                raise KnowledgeConflictError(
                    "KnowledgeUnit changed since it was loaded; refusing a lost update."
                )

            if source_entity_id is not None and source_revision_id is not None:
                self._require_source_revision(
                    connection,
                    entity_id=source_entity_id,
                    revision_id=source_revision_id,
                )

            next_revision_no = current_revision_no + 1
            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="knowledge.revise",
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                knowledge_id=knowledge_id,
                revision_id=revision_id,
                operation="knowledge.revise",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            if source_entity_id is not None and source_revision_id is not None:
                self._insert_provenance_input(
                    connection,
                    provenance_id=provenance_id,
                    input_entity_id=source_entity_id,
                    input_revision_id=source_revision_id,
                    input_role=input_role,
                    ordinal=0,
                )

            self._insert_revision(
                connection,
                knowledge_id=knowledge_id,
                revision_id=revision_id,
                revision_no=next_revision_no,
                parent_revision_id=current_revision_id,
                actor_id=actor_id,
                provenance_id=provenance_id,
                commit_id=commit_id,
                created_at_us=created_at_us,
                payload_hash=payload_hash,
                change_kind="revise",
            )
            self._insert_payload(connection, revision_id=revision_id, draft=draft)
            connection.execute(
                """
                UPDATE entity_heads
                SET current_revision_id = ?, current_revision_no = ?
                WHERE entity_id = ? AND current_revision_id = ?
                """,
                (
                    uuid_to_blob(revision_id),
                    next_revision_no,
                    uuid_to_blob(knowledge_id),
                    uuid_to_blob(expected_revision_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'revise')
                """,
                (
                    commit_seq,
                    uuid_to_blob(knowledge_id),
                    uuid_to_blob(revision_id),
                ),
            )

        return KnowledgeUnitRevision(
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            revision_no=next_revision_no,
            created_at_us=created_at_us,
            created_by_actor_id=actor_id,
            provenance_id=provenance_id,
            payload=draft,
        )

    def load_current(self, knowledge_id: uuid.UUID) -> KnowledgeUnitSnapshot:
        row = self.database.connection.execute(
            """
            SELECT
                e.entity_id AS knowledge_id,
                e.lifecycle_state,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                kr.knowledge_kind,
                kr.title,
                kr.body,
                kr.valid_from_us,
                kr.valid_to_us,
                kr.epistemic_status
            FROM knowledge_units AS k
            JOIN entity_registry AS e
              ON e.entity_id = k.knowledge_id
            JOIN entity_heads AS h
              ON h.entity_id = k.knowledge_id
            JOIN revisions AS r
              ON r.revision_id = h.current_revision_id
            JOIN knowledge_unit_revisions AS kr
              ON kr.revision_id = r.revision_id
            WHERE k.knowledge_id = ?
              AND e.lifecycle_state != 'deleted'
            """,
            (uuid_to_blob(knowledge_id),),
        ).fetchone()
        if row is None:
            raise KnowledgeNotFoundError(str(knowledge_id))
        return KnowledgeUnitSnapshot(
            knowledge_id=knowledge_id,
            lifecycle_state=str(row["lifecycle_state"]),
            revision=self._revision_from_row(row),
        )

    def list_current(self, *, limit: int = 50) -> tuple[KnowledgeUnitSnapshot, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Knowledge list limit must be between 1 and 500.")
        rows = self.database.connection.execute(
            """
            SELECT
                e.entity_id AS knowledge_id,
                e.lifecycle_state,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                kr.knowledge_kind,
                kr.title,
                kr.body,
                kr.valid_from_us,
                kr.valid_to_us,
                kr.epistemic_status
            FROM knowledge_units AS k
            JOIN entity_registry AS e
              ON e.entity_id = k.knowledge_id
            JOIN entity_heads AS h
              ON h.entity_id = k.knowledge_id
            JOIN revisions AS r
              ON r.revision_id = h.current_revision_id
            JOIN knowledge_unit_revisions AS kr
              ON kr.revision_id = r.revision_id
            WHERE e.lifecycle_state != 'deleted'
            ORDER BY r.created_at_us DESC, e.entity_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(
            KnowledgeUnitSnapshot(
                knowledge_id=uuid_from_blob(bytes(row["knowledge_id"])),
                lifecycle_state=str(row["lifecycle_state"]),
                revision=self._revision_from_row(row),
            )
            for row in rows
        )

    def list_revisions(self, knowledge_id: uuid.UUID) -> tuple[KnowledgeUnitRevision, ...]:
        rows = self.database.connection.execute(
            """
            SELECT
                r.entity_id AS knowledge_id,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                kr.knowledge_kind,
                kr.title,
                kr.body,
                kr.valid_from_us,
                kr.valid_to_us,
                kr.epistemic_status
            FROM revisions AS r
            JOIN knowledge_units AS k
              ON k.knowledge_id = r.entity_id
            JOIN entity_registry AS e
              ON e.entity_id = k.knowledge_id
            JOIN knowledge_unit_revisions AS kr
              ON kr.revision_id = r.revision_id
            WHERE r.entity_id = ?
              AND e.lifecycle_state != 'deleted'
            ORDER BY r.revision_no ASC
            """,
            (uuid_to_blob(knowledge_id),),
        ).fetchall()
        if not rows:
            raise KnowledgeNotFoundError(str(knowledge_id))
        return tuple(self._revision_from_row(row) for row in rows)

    def list_provenance_inputs(
        self,
        provenance_id: uuid.UUID,
    ) -> tuple[ProvenanceInputRef, ...]:
        rows = self.database.connection.execute(
            """
            SELECT
                provenance_id,
                input_entity_id,
                input_revision_id,
                input_role,
                ordinal
            FROM provenance_inputs
            WHERE provenance_id = ?
            ORDER BY ordinal ASC
            """,
            (uuid_to_blob(provenance_id),),
        ).fetchall()
        return tuple(
            ProvenanceInputRef(
                provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
                input_entity_id=uuid_from_blob(bytes(row["input_entity_id"])),
                input_revision_id=(
                    uuid_from_blob(bytes(row["input_revision_id"]))
                    if row["input_revision_id"] is not None
                    else None
                ),
                input_role=str(row["input_role"]),
                ordinal=int(row["ordinal"]),
            )
            for row in rows
        )

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> KnowledgeUnitRevision:
        return KnowledgeUnitRevision(
            knowledge_id=uuid_from_blob(bytes(row["knowledge_id"])),
            revision_id=uuid_from_blob(bytes(row["revision_id"])),
            revision_no=int(row["revision_no"]),
            created_at_us=int(row["created_at_us"]),
            created_by_actor_id=uuid_from_blob(bytes(row["created_by_actor_id"])),
            provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
            payload=KnowledgeUnitDraft(
                knowledge_kind=KnowledgeKind(str(row["knowledge_kind"])),
                title=str(row["title"]) if row["title"] is not None else None,
                body=str(row["body"]),
                valid_from_us=(
                    int(row["valid_from_us"]) if row["valid_from_us"] is not None else None
                ),
                valid_to_us=(
                    int(row["valid_to_us"]) if row["valid_to_us"] is not None else None
                ),
                epistemic_status=EpistemicStatus(str(row["epistemic_status"])),
            ),
        )

    @staticmethod
    def _require_active_actor(connection: sqlite3.Connection, actor_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT active FROM actors WHERE actor_id = ?",
            (uuid_to_blob(actor_id),),
        ).fetchone()
        if row is None or int(row["active"]) != 1:
            raise KnowledgeActorError(str(actor_id))

    @staticmethod
    def _require_source_revision(
        connection: sqlite3.Connection,
        *,
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            """
            SELECT 1
            FROM revisions
            WHERE entity_id = ? AND revision_id = ?
            """,
            (uuid_to_blob(entity_id), uuid_to_blob(revision_id)),
        ).fetchone()
        if row is None:
            raise KnowledgeSourceError(
                "The provenance source revision does not belong to the supplied entity."
            )

    @staticmethod
    def _require_current_head(
        connection: sqlite3.Connection,
        *,
        knowledge_id: uuid.UUID,
    ) -> tuple[uuid.UUID, int]:
        row = connection.execute(
            """
            SELECT h.current_revision_id, h.current_revision_no
            FROM knowledge_units AS k
            JOIN entity_heads AS h
              ON h.entity_id = k.knowledge_id
            JOIN entity_registry AS e
              ON e.entity_id = k.knowledge_id
            WHERE k.knowledge_id = ?
              AND e.lifecycle_state != 'deleted'
            """,
            (uuid_to_blob(knowledge_id),),
        ).fetchone()
        if row is None:
            raise KnowledgeNotFoundError(str(knowledge_id))
        return (
            uuid_from_blob(bytes(row["current_revision_id"])),
            int(row["current_revision_no"]),
        )

    @staticmethod
    def _insert_commit(
        connection: sqlite3.Connection,
        *,
        commit_id: uuid.UUID,
        actor_id: uuid.UUID,
        operation_type: str,
        committed_at_us: int,
        reason: str | None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO commit_records (
                commit_id, committed_at_us, actor_id, operation_type, reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(commit_id),
                committed_at_us,
                uuid_to_blob(actor_id),
                operation_type,
                reason,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a commit sequence.")
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_entity(
        connection: sqlite3.Connection,
        *,
        knowledge_id: uuid.UUID,
        actor_id: uuid.UUID,
        created_at_us: int,
        commit_seq: int,
        reason: str | None,
    ) -> None:
        entity_blob = uuid_to_blob(knowledge_id)
        actor_blob = uuid_to_blob(actor_id)
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
            ) VALUES (?, 'knowledge_unit', 'knowledge', ?, ?, 'active', NULL, 1)
            """,
            (entity_blob, created_at_us, actor_blob),
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
            ) VALUES (?, ?, NULL, 'active', NULL, ?, ?)
            """,
            (entity_blob, commit_seq, actor_blob, reason),
        )

    @staticmethod
    def _insert_provenance(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        knowledge_id: uuid.UUID,
        revision_id: uuid.UUID,
        operation: str,
        actor_id: uuid.UUID,
        created_at_us: int,
        reason: str | None,
        model_signature_id: uuid.UUID | None = None,
        processing_run_id: uuid.UUID | None = None,
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(knowledge_id),
                uuid_to_blob(revision_id),
                operation,
                uuid_to_blob(actor_id),
                created_at_us,
                uuid_to_blob(model_signature_id) if model_signature_id is not None else None,
                uuid_to_blob(processing_run_id) if processing_run_id is not None else None,
                reason,
            ),
        )

    @staticmethod
    def _insert_provenance_input(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        input_entity_id: uuid.UUID,
        input_revision_id: uuid.UUID,
        input_role: str,
        ordinal: int,
    ) -> None:
        normalized_role = input_role.strip()
        if not normalized_role:
            raise KnowledgeSourceError("input_role must not be empty.")
        connection.execute(
            """
            INSERT INTO provenance_inputs (
                provenance_id,
                input_entity_id,
                input_revision_id,
                input_role,
                ordinal
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(input_entity_id),
                uuid_to_blob(input_revision_id),
                normalized_role,
                ordinal,
            ),
        )

    @staticmethod
    def _insert_revision(
        connection: sqlite3.Connection,
        *,
        knowledge_id: uuid.UUID,
        revision_id: uuid.UUID,
        revision_no: int,
        parent_revision_id: uuid.UUID | None,
        actor_id: uuid.UUID,
        provenance_id: uuid.UUID,
        commit_id: uuid.UUID,
        created_at_us: int,
        payload_hash: bytes,
        change_kind: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO revisions (
                revision_id,
                entity_id,
                revision_no,
                parent_revision_id,
                created_at_us,
                created_by_actor_id,
                provenance_id,
                schema_version,
                payload_hash,
                change_kind,
                commit_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                uuid_to_blob(revision_id),
                uuid_to_blob(knowledge_id),
                revision_no,
                (
                    uuid_to_blob(parent_revision_id)
                    if parent_revision_id is not None
                    else None
                ),
                created_at_us,
                uuid_to_blob(actor_id),
                uuid_to_blob(provenance_id),
                payload_hash,
                change_kind,
                uuid_to_blob(commit_id),
            ),
        )

    @staticmethod
    def _insert_payload(
        connection: sqlite3.Connection,
        *,
        revision_id: uuid.UUID,
        draft: KnowledgeUnitDraft,
    ) -> None:
        connection.execute(
            """
            INSERT INTO knowledge_unit_revisions (
                revision_id,
                knowledge_kind,
                title,
                body,
                valid_from_us,
                valid_to_us,
                epistemic_status,
                protected_payload_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                uuid_to_blob(revision_id),
                draft.knowledge_kind.value,
                draft.title,
                draft.body,
                draft.valid_from_us,
                draft.valid_to_us,
                draft.epistemic_status.value,
            ),
        )


def _knowledge_payload_hash(draft: KnowledgeUnitDraft) -> bytes:
    canonical_payload = json.dumps(
        {
            "body": draft.body,
            "epistemic_status": draft.epistemic_status.value,
            "knowledge_kind": draft.knowledge_kind.value,
            "title": draft.title,
            "valid_from_us": draft.valid_from_us,
            "valid_to_us": draft.valid_to_us,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_payload).digest()
