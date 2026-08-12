"""Transactional persistence for canonical ATHENA Claims and evidence links."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.models import (
    ClaimDraft,
    ClaimEvidenceRef,
    ClaimKind,
    ClaimRevision,
    ClaimSnapshot,
    EpistemicStatus,
    EvidenceRole,
    ProvenanceInputRef,
)
from athena.knowledge.repository import (
    KnowledgeActorError,
    KnowledgeConflictError,
    KnowledgeSourceError,
)
from athena.storage.database import SQLiteDatabase


class ClaimNotFoundError(LookupError):
    """Raised when a requested Claim does not exist."""


class ClaimRelationError(ValueError):
    """Raised when a requested semantic Claim relation is invalid."""


class ClaimRepository:
    """Versioned Claim repository with explicit provenance and evidence."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_claim(
        self,
        *,
        actor_id: uuid.UUID,
        draft: ClaimDraft,
        source_entity_id: uuid.UUID | None = None,
        source_revision_id: uuid.UUID | None = None,
        source_message_id: uuid.UUID | None = None,
        input_role: str = "source",
        reason: str | None = None,
    ) -> ClaimRevision:
        """Create one stable Claim and immutable revision 1."""
        if (source_entity_id is None) != (source_revision_id is None):
            raise KnowledgeSourceError(
                "source_entity_id and source_revision_id must be supplied together."
            )

        claim_id = new_uuid7()
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _claim_payload_hash(draft)

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            if source_entity_id is not None and source_revision_id is not None:
                self._require_source_revision(
                    connection,
                    entity_id=source_entity_id,
                    revision_id=source_revision_id,
                )
            if source_message_id is not None:
                self._require_chat_message(connection, source_message_id)

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="claim.create",
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_entity(
                connection,
                claim_id=claim_id,
                actor_id=actor_id,
                created_at_us=created_at_us,
                commit_seq=commit_seq,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                claim_id=claim_id,
                revision_id=revision_id,
                operation="claim.create",
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
                claim_id=claim_id,
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
                (uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
            )
            connection.execute(
                "INSERT INTO claims (claim_id) VALUES (?)",
                (uuid_to_blob(claim_id),),
            )
            self._insert_payload(connection, revision_id=revision_id, draft=draft)
            if source_message_id is not None:
                connection.execute(
                    """
                    INSERT INTO claim_evidence (
                        claim_id,
                        anchor_id,
                        message_id,
                        evidence_entity_id,
                        evidence_revision_id,
                        evidence_role,
                        provenance_id
                    ) VALUES (?, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(claim_id),
                        uuid_to_blob(source_message_id),
                        uuid_to_blob(source_entity_id)
                        if source_entity_id is not None
                        else None,
                        uuid_to_blob(source_revision_id)
                        if source_revision_id is not None
                        else None,
                        EvidenceRole.ORIGINATES.value,
                        uuid_to_blob(provenance_id),
                    ),
                )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'create')
                """,
                (
                    commit_seq,
                    uuid_to_blob(claim_id),
                    uuid_to_blob(revision_id),
                ),
            )

        return ClaimRevision(
            claim_id=claim_id,
            revision_id=revision_id,
            revision_no=1,
            created_at_us=created_at_us,
            created_by_actor_id=actor_id,
            provenance_id=provenance_id,
            payload=draft,
        )

    def revise_claim(
        self,
        *,
        actor_id: uuid.UUID,
        claim_id: uuid.UUID,
        expected_revision_id: uuid.UUID,
        draft: ClaimDraft,
        reason: str | None = None,
    ) -> ClaimRevision:
        """Append a new immutable Claim revision with lost-update protection."""
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        payload_hash = _claim_payload_hash(draft)

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            current_revision_id, current_revision_no = self._require_current_head(
                connection,
                claim_id=claim_id,
            )
            if current_revision_id != expected_revision_id:
                raise KnowledgeConflictError(
                    "Claim changed since it was loaded; refusing a lost update."
                )

            next_revision_no = current_revision_no + 1
            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="claim.revise",
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=provenance_id,
                claim_id=claim_id,
                revision_id=revision_id,
                operation="claim.revise",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            self._insert_revision(
                connection,
                claim_id=claim_id,
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
            cursor = connection.execute(
                """
                UPDATE entity_heads
                SET current_revision_id = ?, current_revision_no = ?
                WHERE entity_id = ? AND current_revision_id = ?
                """,
                (
                    uuid_to_blob(revision_id),
                    next_revision_no,
                    uuid_to_blob(claim_id),
                    uuid_to_blob(expected_revision_id),
                ),
            )
            if cursor.rowcount != 1:
                raise KnowledgeConflictError(
                    "Claim head changed during write; refusing a lost update."
                )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'revise')
                """,
                (commit_seq, uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
            )

        return ClaimRevision(
            claim_id=claim_id,
            revision_id=revision_id,
            revision_no=next_revision_no,
            created_at_us=created_at_us,
            created_by_actor_id=actor_id,
            provenance_id=provenance_id,
            payload=draft,
        )

    def link_contradiction(
        self,
        *,
        actor_id: uuid.UUID,
        left_claim_id: uuid.UUID,
        right_claim_id: uuid.UUID,
        reason: str | None = None,
    ) -> tuple[ClaimEvidenceRef, ClaimEvidenceRef]:
        """Atomically create reciprocal user-confirmed contradiction links."""
        if left_claim_id == right_claim_id:
            raise ClaimRelationError("A Claim cannot contradict itself.")

        created_at_us = utc_now_us()
        commit_id = new_uuid7()
        left_provenance_id = new_uuid7()
        right_provenance_id = new_uuid7()

        with self.database.write_transaction() as connection:
            self._require_active_actor(connection, actor_id)
            left_revision = self._require_current_claim_revision(
                connection,
                claim_id=left_claim_id,
            )
            right_revision = self._require_current_claim_revision(
                connection,
                claim_id=right_claim_id,
            )
            self._reject_non_overlapping_temporal_claims(left_revision, right_revision)
            self._reject_existing_contradiction(
                connection,
                left_claim_id=left_claim_id,
                right_claim_id=right_claim_id,
            )

            commit_seq = self._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="claim.contradiction.link",
                committed_at_us=created_at_us,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=left_provenance_id,
                claim_id=left_claim_id,
                revision_id=left_revision.revision_id,
                operation="claim.evidence.contradicts",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            self._insert_provenance(
                connection,
                provenance_id=right_provenance_id,
                claim_id=right_claim_id,
                revision_id=right_revision.revision_id,
                operation="claim.evidence.contradicts",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
            )
            self._insert_claim_evidence(
                connection,
                claim_id=left_claim_id,
                evidence_entity_id=right_claim_id,
                evidence_revision_id=right_revision.revision_id,
                evidence_role=EvidenceRole.CONTRADICTS,
                provenance_id=left_provenance_id,
            )
            self._insert_claim_evidence(
                connection,
                claim_id=right_claim_id,
                evidence_entity_id=left_claim_id,
                evidence_revision_id=left_revision.revision_id,
                evidence_role=EvidenceRole.CONTRADICTS,
                provenance_id=right_provenance_id,
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'contradiction_linked')
                """,
                (
                    commit_seq,
                    uuid_to_blob(left_claim_id),
                    uuid_to_blob(left_revision.revision_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO commit_changes (
                    commit_seq, entity_id, revision_id, change_type
                ) VALUES (?, ?, ?, 'contradiction_linked')
                """,
                (
                    commit_seq,
                    uuid_to_blob(right_claim_id),
                    uuid_to_blob(right_revision.revision_id),
                ),
            )

        return (
            ClaimEvidenceRef(
                evidence_role=EvidenceRole.CONTRADICTS,
                provenance_id=left_provenance_id,
                evidence_entity_id=right_claim_id,
                evidence_revision_id=right_revision.revision_id,
            ),
            ClaimEvidenceRef(
                evidence_role=EvidenceRole.CONTRADICTS,
                provenance_id=right_provenance_id,
                evidence_entity_id=left_claim_id,
                evidence_revision_id=left_revision.revision_id,
            ),
        )

    def load_current(self, claim_id: uuid.UUID) -> ClaimSnapshot:
        row = self.database.connection.execute(
            """
            SELECT
                e.entity_id AS claim_id,
                e.lifecycle_state,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                cr.claim_kind,
                cr.statement,
                cr.subject_entity_id,
                cr.predicate,
                cr.object_entity_id,
                cr.attributed_to_entity_id,
                cr.valid_from_us,
                cr.valid_to_us,
                cr.epistemic_status
            FROM claims AS c
            JOIN entity_registry AS e
              ON e.entity_id = c.claim_id
            JOIN entity_heads AS h
              ON h.entity_id = c.claim_id
            JOIN revisions AS r
              ON r.revision_id = h.current_revision_id
            JOIN claim_revisions AS cr
              ON cr.revision_id = r.revision_id
            WHERE c.claim_id = ?
            """,
            (uuid_to_blob(claim_id),),
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(str(claim_id))
        return ClaimSnapshot(
            claim_id=claim_id,
            lifecycle_state=str(row["lifecycle_state"]),
            revision=self._revision_from_row(row),
        )

    def list_current(self, *, limit: int = 50) -> tuple[ClaimSnapshot, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500.")
        rows = self.database.connection.execute(
            """
            SELECT
                e.entity_id AS claim_id,
                e.lifecycle_state,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                cr.claim_kind,
                cr.statement,
                cr.subject_entity_id,
                cr.predicate,
                cr.object_entity_id,
                cr.attributed_to_entity_id,
                cr.valid_from_us,
                cr.valid_to_us,
                cr.epistemic_status
            FROM claims AS c
            JOIN entity_registry AS e ON e.entity_id = c.claim_id
            JOIN entity_heads AS h ON h.entity_id = c.claim_id
            JOIN revisions AS r ON r.revision_id = h.current_revision_id
            JOIN claim_revisions AS cr ON cr.revision_id = r.revision_id
            ORDER BY r.created_at_us DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(
            ClaimSnapshot(
                claim_id=uuid_from_blob(bytes(row["claim_id"])),
                lifecycle_state=str(row["lifecycle_state"]),
                revision=self._revision_from_row(row),
            )
            for row in rows
        )

    def list_revisions(self, claim_id: uuid.UUID) -> tuple[ClaimRevision, ...]:
        rows = self.database.connection.execute(
            """
            SELECT
                r.entity_id AS claim_id,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                cr.claim_kind,
                cr.statement,
                cr.subject_entity_id,
                cr.predicate,
                cr.object_entity_id,
                cr.attributed_to_entity_id,
                cr.valid_from_us,
                cr.valid_to_us,
                cr.epistemic_status
            FROM revisions AS r
            JOIN claims AS c ON c.claim_id = r.entity_id
            JOIN claim_revisions AS cr ON cr.revision_id = r.revision_id
            WHERE r.entity_id = ?
            ORDER BY r.revision_no ASC
            """,
            (uuid_to_blob(claim_id),),
        ).fetchall()
        if not rows:
            raise ClaimNotFoundError(str(claim_id))
        return tuple(self._revision_from_row(row) for row in rows)

    def list_evidence(self, claim_id: uuid.UUID) -> tuple[ClaimEvidenceRef, ...]:
        self.load_current(claim_id)
        rows = self.database.connection.execute(
            """
            SELECT
                anchor_id,
                message_id,
                evidence_entity_id,
                evidence_revision_id,
                evidence_role,
                provenance_id
            FROM claim_evidence
            WHERE claim_id = ?
            ORDER BY evidence_role, evidence_entity_id, evidence_revision_id
            """,
            (uuid_to_blob(claim_id),),
        ).fetchall()
        return tuple(
            ClaimEvidenceRef(
                evidence_role=EvidenceRole(str(row["evidence_role"])),
                provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
                anchor_id=(
                    uuid_from_blob(bytes(row["anchor_id"]))
                    if row["anchor_id"] is not None
                    else None
                ),
                message_id=(
                    uuid_from_blob(bytes(row["message_id"]))
                    if row["message_id"] is not None
                    else None
                ),
                evidence_entity_id=(
                    uuid_from_blob(bytes(row["evidence_entity_id"]))
                    if row["evidence_entity_id"] is not None
                    else None
                ),
                evidence_revision_id=(
                    uuid_from_blob(bytes(row["evidence_revision_id"]))
                    if row["evidence_revision_id"] is not None
                    else None
                ),
            )
            for row in rows
        )

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
    def _revision_from_row(row: sqlite3.Row) -> ClaimRevision:
        return ClaimRevision(
            claim_id=uuid_from_blob(bytes(row["claim_id"])),
            revision_id=uuid_from_blob(bytes(row["revision_id"])),
            revision_no=int(row["revision_no"]),
            created_at_us=int(row["created_at_us"]),
            created_by_actor_id=uuid_from_blob(bytes(row["created_by_actor_id"])),
            provenance_id=uuid_from_blob(bytes(row["provenance_id"])),
            payload=ClaimDraft(
                claim_kind=ClaimKind(str(row["claim_kind"])),
                statement=str(row["statement"]),
                epistemic_status=EpistemicStatus(str(row["epistemic_status"])),
                subject_entity_id=(
                    uuid_from_blob(bytes(row["subject_entity_id"]))
                    if row["subject_entity_id"] is not None
                    else None
                ),
                predicate=(
                    str(row["predicate"]) if row["predicate"] is not None else None
                ),
                object_entity_id=(
                    uuid_from_blob(bytes(row["object_entity_id"]))
                    if row["object_entity_id"] is not None
                    else None
                ),
                attributed_to_entity_id=(
                    uuid_from_blob(bytes(row["attributed_to_entity_id"]))
                    if row["attributed_to_entity_id"] is not None
                    else None
                ),
                valid_from_us=(
                    int(row["valid_from_us"])
                    if row["valid_from_us"] is not None
                    else None
                ),
                valid_to_us=(
                    int(row["valid_to_us"])
                    if row["valid_to_us"] is not None
                    else None
                ),
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
    def _require_chat_message(connection: sqlite3.Connection, message_id: uuid.UUID) -> None:
        row = connection.execute(
            "SELECT 1 FROM chat_messages WHERE message_id = ?",
            (uuid_to_blob(message_id),),
        ).fetchone()
        if row is None:
            raise KnowledgeSourceError("The supplied source_message_id is not a chat message.")

    def _require_current_claim_revision(
        self,
        connection: sqlite3.Connection,
        *,
        claim_id: uuid.UUID,
    ) -> ClaimRevision:
        row = connection.execute(
            """
            SELECT
                r.entity_id AS claim_id,
                r.revision_id,
                r.revision_no,
                r.created_at_us,
                r.created_by_actor_id,
                r.provenance_id,
                cr.claim_kind,
                cr.statement,
                cr.subject_entity_id,
                cr.predicate,
                cr.object_entity_id,
                cr.attributed_to_entity_id,
                cr.valid_from_us,
                cr.valid_to_us,
                cr.epistemic_status
            FROM claims AS c
            JOIN entity_heads AS h ON h.entity_id = c.claim_id
            JOIN revisions AS r ON r.revision_id = h.current_revision_id
            JOIN claim_revisions AS cr ON cr.revision_id = r.revision_id
            WHERE c.claim_id = ?
            """,
            (uuid_to_blob(claim_id),),
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(str(claim_id))
        return self._revision_from_row(row)

    @staticmethod
    def _require_current_head(
        connection: sqlite3.Connection,
        *,
        claim_id: uuid.UUID,
    ) -> tuple[uuid.UUID, int]:
        row = connection.execute(
            """
            SELECT h.current_revision_id, h.current_revision_no
            FROM claims AS c
            JOIN entity_heads AS h ON h.entity_id = c.claim_id
            WHERE c.claim_id = ?
            """,
            (uuid_to_blob(claim_id),),
        ).fetchone()
        if row is None:
            raise ClaimNotFoundError(str(claim_id))
        return (
            uuid_from_blob(bytes(row["current_revision_id"])),
            int(row["current_revision_no"]),
        )

    @staticmethod
    def _reject_non_overlapping_temporal_claims(
        left: ClaimRevision,
        right: ClaimRevision,
    ) -> None:
        left_from = left.payload.valid_from_us
        left_to = left.payload.valid_to_us
        right_from = right.payload.valid_from_us
        right_to = right.payload.valid_to_us
        if left_to is not None and right_from is not None and left_to < right_from:
            raise ClaimRelationError(
                "Claims have non-overlapping validity periods and cannot be marked as the "
                "same temporal contradiction."
            )
        if right_to is not None and left_from is not None and right_to < left_from:
            raise ClaimRelationError(
                "Claims have non-overlapping validity periods and cannot be marked as the "
                "same temporal contradiction."
            )

    @staticmethod
    def _reject_existing_contradiction(
        connection: sqlite3.Connection,
        *,
        left_claim_id: uuid.UUID,
        right_claim_id: uuid.UUID,
    ) -> None:
        row = connection.execute(
            """
            SELECT 1
            FROM claim_evidence
            WHERE claim_id = ?
              AND evidence_entity_id = ?
              AND evidence_role = ?
            LIMIT 1
            """,
            (
                uuid_to_blob(left_claim_id),
                uuid_to_blob(right_claim_id),
                EvidenceRole.CONTRADICTS.value,
            ),
        ).fetchone()
        if row is not None:
            raise ClaimRelationError("These Claims are already linked as contradictions.")

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
        claim_id: uuid.UUID,
        actor_id: uuid.UUID,
        created_at_us: int,
        commit_seq: int,
        reason: str | None,
    ) -> None:
        entity_blob = uuid_to_blob(claim_id)
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
            ) VALUES (?, 'claim', 'knowledge', ?, ?, 'active', NULL, 1)
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
        claim_id: uuid.UUID,
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
                uuid_to_blob(claim_id),
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
        claim_id: uuid.UUID,
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
                uuid_to_blob(claim_id),
                revision_no,
                uuid_to_blob(parent_revision_id)
                if parent_revision_id is not None
                else None,
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
        draft: ClaimDraft,
    ) -> None:
        connection.execute(
            """
            INSERT INTO claim_revisions (
                revision_id,
                claim_kind,
                statement,
                subject_entity_id,
                predicate,
                object_entity_id,
                attributed_to_entity_id,
                valid_from_us,
                valid_to_us,
                epistemic_status,
                protected_payload_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                uuid_to_blob(revision_id),
                draft.claim_kind.value,
                draft.statement,
                uuid_to_blob(draft.subject_entity_id)
                if draft.subject_entity_id is not None
                else None,
                draft.predicate,
                uuid_to_blob(draft.object_entity_id)
                if draft.object_entity_id is not None
                else None,
                uuid_to_blob(draft.attributed_to_entity_id)
                if draft.attributed_to_entity_id is not None
                else None,
                draft.valid_from_us,
                draft.valid_to_us,
                draft.epistemic_status.value,
            ),
        )

    @staticmethod
    def _insert_claim_evidence(
        connection: sqlite3.Connection,
        *,
        claim_id: uuid.UUID,
        evidence_entity_id: uuid.UUID,
        evidence_revision_id: uuid.UUID,
        evidence_role: EvidenceRole,
        provenance_id: uuid.UUID,
    ) -> None:
        connection.execute(
            """
            INSERT INTO claim_evidence (
                claim_id,
                anchor_id,
                message_id,
                evidence_entity_id,
                evidence_revision_id,
                evidence_role,
                provenance_id
            ) VALUES (?, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(claim_id),
                uuid_to_blob(evidence_entity_id),
                uuid_to_blob(evidence_revision_id),
                evidence_role.value,
                uuid_to_blob(provenance_id),
            ),
        )


def _claim_payload_hash(draft: ClaimDraft) -> bytes:
    canonical_payload = json.dumps(
        {
            "attributed_to_entity_id": (
                str(draft.attributed_to_entity_id)
                if draft.attributed_to_entity_id is not None
                else None
            ),
            "claim_kind": draft.claim_kind.value,
            "epistemic_status": draft.epistemic_status.value,
            "object_entity_id": (
                str(draft.object_entity_id) if draft.object_entity_id is not None else None
            ),
            "predicate": draft.predicate,
            "statement": draft.statement,
            "subject_entity_id": (
                str(draft.subject_entity_id)
                if draft.subject_entity_id is not None
                else None
            ),
            "valid_from_us": draft.valid_from_us,
            "valid_to_us": draft.valid_to_us,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_payload).digest()
