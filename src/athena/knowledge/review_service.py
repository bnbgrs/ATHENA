"""Persistent semantic review queue and deterministic review policy."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import cast

from athena.chat.models import ChatMessage
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.deduplication import CanonicalMergeCandidate
from athena.knowledge.extraction_models import ChatExtractionResult, ProposalEntityType
from athena.knowledge.models import EvidenceRole
from athena.storage.database import SQLiteDatabase


class ReviewError(ValueError):
    """Raised when a semantic review action cannot be applied safely."""


class ReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    review_id: uuid.UUID
    review_type: str
    status: ReviewStatus
    created_at_us: int
    resolved_at_us: int | None
    processing_run_id: uuid.UUID
    model_signature_id: uuid.UUID
    left_entity_id: uuid.UUID | None
    left_revision_id: uuid.UUID | None
    right_entity_id: uuid.UUID | None
    right_revision_id: uuid.UUID | None
    confidence: float
    reason: str
    decision_actor_id: uuid.UUID | None
    decision_reason: str | None


@dataclass(frozen=True, slots=True)
class MergeReviewDetails:
    review_id: uuid.UUID
    proposal_type: ProposalEntityType
    proposal_index: int
    source_entity_id: uuid.UUID
    source_revision_id: uuid.UUID
    proposal_text: str
    proposal_kind: str
    proposal_epistemic_status: str
    similarity: float
    decision: str | None
    existing_entity_id: uuid.UUID
    existing_revision_id: uuid.UUID



class ReviewService:
    """Persist, inspect, and resolve semantic decisions requiring human review."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def enqueue_contradiction(
        connection: sqlite3.Connection,
        *,
        processing_run_id: uuid.UUID,
        model_signature_id: uuid.UUID,
        left_entity_id: uuid.UUID,
        left_revision_id: uuid.UUID,
        right_entity_id: uuid.UUID,
        right_revision_id: uuid.UUID,
        confidence: float,
        reason: str,
        created_at_us: int,
    ) -> uuid.UUID:
        left_id, left_rev, right_id, right_rev = (
            (left_entity_id, left_revision_id, right_entity_id, right_revision_id)
            if left_entity_id.bytes < right_entity_id.bytes
            else (right_entity_id, right_revision_id, left_entity_id, left_revision_id)
        )
        existing = connection.execute(
            """
            SELECT review_id
            FROM semantic_review_items
            WHERE review_type = 'contradiction'
              AND status = 'pending'
              AND left_entity_id = ?
              AND right_entity_id = ?
            """,
            (uuid_to_blob(left_id), uuid_to_blob(right_id)),
        ).fetchone()
        if existing is not None:
            return uuid_from_blob(bytes(existing["review_id"]))

        review_id = new_uuid7()
        connection.execute(
            """
            INSERT INTO semantic_review_items (
                review_id, review_type, status, created_at_us, resolved_at_us,
                processing_run_id, model_signature_id,
                left_entity_id, left_revision_id,
                right_entity_id, right_revision_id,
                confidence, reason, decision_actor_id, decision_reason
            ) VALUES (
                ?, 'contradiction', 'pending', ?, NULL,
                ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL
            )
            """,
            (
                uuid_to_blob(review_id),
                created_at_us,
                uuid_to_blob(processing_run_id),
                uuid_to_blob(model_signature_id),
                uuid_to_blob(left_id),
                uuid_to_blob(left_rev),
                uuid_to_blob(right_id),
                uuid_to_blob(right_rev),
                confidence,
                reason,
            ),
        )
        return review_id

    def enqueue_merge_candidates(
        self,
        *,
        result: ChatExtractionResult,
        candidates: tuple[CanonicalMergeCandidate, ...],
        source_by_sequence: Mapping[int, ChatMessage],
    ) -> tuple[uuid.UUID, ...]:
        """Persist unresolved canonical near-duplicate decisions without canonical writes."""
        review_ids: list[uuid.UUID] = []
        created_at_us = utc_now_us()
        with self.database.write_transaction() as connection:
            for candidate in candidates:
                if candidate.proposal_type is ProposalEntityType.KNOWLEDGE:
                    knowledge_proposal = result.proposals.knowledge_units[
                        candidate.proposal_index
                    ]
                    source_sequence_no = knowledge_proposal.source_sequence_no
                    proposal_text = knowledge_proposal.body
                    proposal_kind = knowledge_proposal.knowledge_kind.value
                    proposal_epistemic_status = knowledge_proposal.epistemic_status.value
                else:
                    claim_proposal = result.proposals.claims[candidate.proposal_index]
                    source_sequence_no = claim_proposal.source_sequence_no
                    proposal_text = claim_proposal.statement
                    proposal_kind = claim_proposal.claim_kind.value
                    proposal_epistemic_status = claim_proposal.epistemic_status.value

                source = source_by_sequence[source_sequence_no]
                source_entity_id = source.message_id
                source_revision_id = source.revision_id

                existing = connection.execute(
                    """
                    SELECT p.review_id
                    FROM semantic_merge_review_payloads AS p
                    JOIN semantic_review_items AS r ON r.review_id = p.review_id
                    WHERE p.proposal_type = ?
                      AND p.source_entity_id = ?
                      AND p.source_revision_id = ?
                      AND p.proposal_kind = ?
                      AND p.proposal_epistemic_status = ?
                      AND p.proposal_text = ?
                      AND r.left_entity_id = ?
                      AND r.left_revision_id = ?
                    """,
                    (
                        candidate.proposal_type.value,
                        uuid_to_blob(source_entity_id),
                        uuid_to_blob(source_revision_id),
                        proposal_kind,
                        proposal_epistemic_status,
                        proposal_text,
                        uuid_to_blob(candidate.existing_entity_id),
                        uuid_to_blob(candidate.existing_revision_id),
                    ),
                ).fetchone()
                if existing is not None:
                    review_ids.append(uuid_from_blob(bytes(existing["review_id"])))
                    continue

                review_id = new_uuid7()
                connection.execute(
                    """
                    INSERT INTO semantic_review_items (
                        review_id, review_type, status, created_at_us, resolved_at_us,
                        processing_run_id, model_signature_id,
                        left_entity_id, left_revision_id,
                        right_entity_id, right_revision_id,
                        confidence, reason, decision_actor_id, decision_reason
                    ) VALUES (
                        ?, 'merge_candidate', 'pending', ?, NULL,
                        ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, NULL
                    )
                    """,
                    (
                        uuid_to_blob(review_id),
                        created_at_us,
                        uuid_to_blob(result.processing_run.processing_run_id),
                        uuid_to_blob(result.model_signature.model_signature_id),
                        uuid_to_blob(candidate.existing_entity_id),
                        uuid_to_blob(candidate.existing_revision_id),
                        candidate.similarity,
                        candidate.reason,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO semantic_merge_review_payloads (
                        review_id, proposal_type, proposal_index,
                        source_entity_id, source_revision_id,
                        proposal_text, proposal_kind, proposal_epistemic_status,
                        similarity, decision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        uuid_to_blob(review_id),
                        candidate.proposal_type.value,
                        candidate.proposal_index,
                        uuid_to_blob(source_entity_id),
                        uuid_to_blob(source_revision_id),
                        proposal_text,
                        proposal_kind,
                        proposal_epistemic_status,
                        candidate.similarity,
                    ),
                )
                review_ids.append(review_id)
        return tuple(review_ids)

    def merge_details(self, review_id: uuid.UUID) -> MergeReviewDetails:
        row = self.database.connection.execute(
            """
            SELECT
                p.*,
                r.left_entity_id,
                r.left_revision_id
            FROM semantic_merge_review_payloads AS p
            JOIN semantic_review_items AS r ON r.review_id = p.review_id
            WHERE p.review_id = ?
            """,
            (uuid_to_blob(review_id),),
        ).fetchone()
        if row is None:
            raise ReviewError(f"Merge review payload not found: {review_id}")
        return MergeReviewDetails(
            review_id=review_id,
            proposal_type=ProposalEntityType(str(row["proposal_type"])),
            proposal_index=int(row["proposal_index"]),
            source_entity_id=uuid_from_blob(bytes(row["source_entity_id"])),
            source_revision_id=uuid_from_blob(bytes(row["source_revision_id"])),
            proposal_text=str(row["proposal_text"]),
            proposal_kind=str(row["proposal_kind"]),
            proposal_epistemic_status=str(row["proposal_epistemic_status"]),
            similarity=float(row["similarity"]),
            decision=None if row["decision"] is None else str(row["decision"]),
            existing_entity_id=uuid_from_blob(bytes(row["left_entity_id"])),
            existing_revision_id=uuid_from_blob(bytes(row["left_revision_id"])),
        )

    def resolve_merge(
        self,
        review_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        decision: str,
    ) -> ReviewItem:
        if decision not in {"merge", "keep_separate"}:
            raise ReviewError("Merge decision must be 'merge' or 'keep_separate'.")
        with self.database.write_transaction() as connection:
            row = self._require_pending(connection, review_id)
            if str(row["review_type"]) != "merge_candidate":
                raise ReviewError("Review item is not a merge candidate.")
            self._validate_single_current_revision(
                connection,
                entity_blob=row["left_entity_id"],
                revision_blob=row["left_revision_id"],
            )
            payload = connection.execute(
                "SELECT source_entity_id, source_revision_id "
                "FROM semantic_merge_review_payloads WHERE review_id = ?",
                (uuid_to_blob(review_id),),
            ).fetchone()
            if payload is None:
                raise ReviewError("Merge review payload is missing.")
            self._validate_source_revision(
                connection,
                entity_blob=payload["source_entity_id"],
                revision_blob=payload["source_revision_id"],
            )
            connection.execute(
                "UPDATE semantic_merge_review_payloads SET decision = ? WHERE review_id = ?",
                (decision, uuid_to_blob(review_id)),
            )
            self._resolve(
                connection,
                row,
                status=ReviewStatus.ACCEPTED,
                actor_id=actor_id,
                decision_reason=f"explicit user merge decision: {decision}",
            )
        return self.get(review_id)

    def lookup_merge_decision(
        self,
        *,
        candidate: CanonicalMergeCandidate,
        result: ChatExtractionResult,
        source_entity_id: uuid.UUID,
        source_revision_id: uuid.UUID,
    ) -> str | None:
        if candidate.proposal_type is ProposalEntityType.KNOWLEDGE:
            knowledge_proposal = result.proposals.knowledge_units[
                candidate.proposal_index
            ]
            proposal_text = knowledge_proposal.body
            proposal_kind = knowledge_proposal.knowledge_kind.value
            proposal_epistemic_status = knowledge_proposal.epistemic_status.value
        else:
            claim_proposal = result.proposals.claims[candidate.proposal_index]
            proposal_text = claim_proposal.statement
            proposal_kind = claim_proposal.claim_kind.value
            proposal_epistemic_status = claim_proposal.epistemic_status.value
        row = self.database.connection.execute(
            """
            SELECT p.decision
            FROM semantic_merge_review_payloads AS p
            JOIN semantic_review_items AS r ON r.review_id = p.review_id
            WHERE p.proposal_type = ?
              AND p.source_entity_id = ?
              AND p.source_revision_id = ?
              AND p.proposal_kind = ?
              AND p.proposal_epistemic_status = ?
              AND p.proposal_text = ?
              AND r.left_entity_id = ?
              AND r.left_revision_id = ?
              AND r.status = 'accepted'
            """,
            (
                candidate.proposal_type.value,
                uuid_to_blob(source_entity_id),
                uuid_to_blob(source_revision_id),
                proposal_kind,
                proposal_epistemic_status,
                proposal_text,
                uuid_to_blob(candidate.existing_entity_id),
                uuid_to_blob(candidate.existing_revision_id),
            ),
        ).fetchone()
        if row is None or row["decision"] is None:
            return None
        return str(row["decision"])

    def list_pending(
        self,
        *,
        review_type: str | None = None,
        limit: int = 100,
    ) -> tuple[ReviewItem, ...]:
        if not 1 <= limit <= 500:
            raise ReviewError("limit must be between 1 and 500.")
        params: list[object] = []
        where = "status = 'pending'"
        if review_type is not None:
            if review_type not in {"contradiction", "merge_candidate"}:
                raise ReviewError("Unsupported review type.")
            where += " AND review_type = ?"
            params.append(review_type)
        params.append(limit)
        rows = self.database.connection.execute(
            f"""
            SELECT *
            FROM semantic_review_items
            WHERE {where}
            ORDER BY confidence DESC, created_at_us ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def get(self, review_id: uuid.UUID) -> ReviewItem:
        row = self.database.connection.execute(
            "SELECT * FROM semantic_review_items WHERE review_id = ?",
            (uuid_to_blob(review_id),),
        ).fetchone()
        if row is None:
            raise ReviewError(f"Review item not found: {review_id}")
        return self._from_row(row)

    def accept(self, review_id: uuid.UUID, *, actor_id: uuid.UUID) -> ReviewItem:
        with self.database.write_transaction() as connection:
            row = self._require_pending(connection, review_id)
            if str(row["review_type"]) != "contradiction":
                raise ReviewError("Only contradiction review acceptance is implemented in Step 7.")
            self._validate_current_revisions(connection, row)
            left_id = uuid_from_blob(bytes(row["left_entity_id"]))
            right_id = uuid_from_blob(bytes(row["right_entity_id"]))
            left_rev = uuid_from_blob(bytes(row["left_revision_id"]))
            right_rev = uuid_from_blob(bytes(row["right_revision_id"]))

            if not self._contradiction_exists(connection, left_id, right_id):
                self._insert_contradiction_pair(
                    connection=connection,
                    actor_id=actor_id,
                    created_at_us=utc_now_us(),
                    processing_run_id=uuid_from_blob(bytes(row["processing_run_id"])),
                    model_signature_id=uuid_from_blob(bytes(row["model_signature_id"])),
                    left_claim_id=left_id,
                    left_revision_id=left_rev,
                    right_claim_id=right_id,
                    right_revision_id=right_rev,
                    reason="user accepted queued contradiction review",
                )
            self._resolve(
                connection,
                row,
                status=ReviewStatus.ACCEPTED,
                actor_id=actor_id,
                decision_reason="explicit user review acceptance",
            )
        return self.get(review_id)

    def reject(self, review_id: uuid.UUID, *, actor_id: uuid.UUID) -> ReviewItem:
        with self.database.write_transaction() as connection:
            row = self._require_pending(connection, review_id)
            if str(row["review_type"]) != "contradiction":
                raise ReviewError(
                    "Merge candidates require 'review merge' or 'review keep-separate'."
                )
            self._resolve(
                connection,
                row,
                status=ReviewStatus.REJECTED,
                actor_id=actor_id,
                decision_reason="explicit user review rejection",
            )
        return self.get(review_id)

    def accept_all(
        self,
        *,
        actor_id: uuid.UUID,
        review_type: str = "contradiction",
        min_confidence: float = 0.0,
    ) -> tuple[uuid.UUID, ...]:
        if not 0.0 <= min_confidence <= 1.0:
            raise ReviewError("min_confidence must be between 0 and 1.")
        items = tuple(
            item
            for item in self.list_pending(review_type=review_type, limit=500)
            if item.confidence >= min_confidence
        )
        accepted: list[uuid.UUID] = []
        for item in items:
            self.accept(item.review_id, actor_id=actor_id)
            accepted.append(item.review_id)
        return tuple(accepted)

    @staticmethod
    def _require_pending(
        connection: sqlite3.Connection,
        review_id: uuid.UUID,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM semantic_review_items WHERE review_id = ?",
            (uuid_to_blob(review_id),),
        ).fetchone()
        if row is None:
            raise ReviewError(f"Review item not found: {review_id}")
        if str(row["status"]) != ReviewStatus.PENDING.value:
            raise ReviewError("Review item is no longer pending.")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _validate_single_current_revision(
        connection: sqlite3.Connection,
        *,
        entity_blob: object,
        revision_blob: object,
    ) -> None:
        if not isinstance(entity_blob, (bytes, bytearray, memoryview)):
            raise ReviewError("Merge review lacks a valid canonical entity.")
        if not isinstance(revision_blob, (bytes, bytearray, memoryview)):
            raise ReviewError("Merge review lacks a valid canonical revision.")
        current = connection.execute(
            """
            SELECT h.current_revision_id, e.lifecycle_state
            FROM entity_heads AS h
            JOIN entity_registry AS e ON e.entity_id = h.entity_id
            WHERE h.entity_id = ?
            """,
            (bytes(entity_blob),),
        ).fetchone()
        if (
            current is None
            or str(current["lifecycle_state"]) != "active"
            or bytes(current["current_revision_id"]) != bytes(revision_blob)
        ):
            raise ReviewError(
                "Canonical merge target changed since review was queued; re-extraction is required."
            )

    @staticmethod
    def _validate_source_revision(
        connection: sqlite3.Connection,
        *,
        entity_blob: object,
        revision_blob: object,
    ) -> None:
        if not isinstance(entity_blob, (bytes, bytearray, memoryview)):
            raise ReviewError("Merge review lacks a valid source entity.")
        if not isinstance(revision_blob, (bytes, bytearray, memoryview)):
            raise ReviewError("Merge review lacks a valid source revision.")
        row = connection.execute(
            "SELECT 1 FROM revisions WHERE entity_id = ? AND revision_id = ?",
            (bytes(entity_blob), bytes(revision_blob)),
        ).fetchone()
        if row is None:
            raise ReviewError(
                "Merge review source revision changed or disappeared; re-extraction is required."
            )

    @staticmethod
    def _validate_current_revisions(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        for entity_column, revision_column in (
            ("left_entity_id", "left_revision_id"),
            ("right_entity_id", "right_revision_id"),
        ):
            entity_blob = row[entity_column]
            revision_blob = row[revision_column]
            if entity_blob is None or revision_blob is None:
                raise ReviewError("Review item lacks canonical entity/revision references.")
            current = connection.execute(
                """
                SELECT h.current_revision_id, e.lifecycle_state
                FROM entity_heads AS h
                JOIN entity_registry AS e ON e.entity_id = h.entity_id
                WHERE h.entity_id = ?
                """,
                (entity_blob,),
            ).fetchone()
            if (
                current is None
                or str(current["lifecycle_state"]) != "active"
                or bytes(current["current_revision_id"]) != bytes(revision_blob)
            ):
                raise ReviewError(
                    "Canonical Claim changed since review was queued; re-extraction is required."
                )

    @staticmethod
    def _resolve(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        status: ReviewStatus,
        actor_id: uuid.UUID,
        decision_reason: str,
    ) -> None:
        connection.execute(
            """
            UPDATE semantic_review_items
            SET status = ?, resolved_at_us = ?, decision_actor_id = ?, decision_reason = ?
            WHERE review_id = ? AND status = 'pending'
            """,
            (
                status.value,
                utc_now_us(),
                uuid_to_blob(actor_id),
                decision_reason,
                row["review_id"],
            ),
        )

    @staticmethod
    def _contradiction_exists(
        connection: sqlite3.Connection,
        left_claim_id: uuid.UUID,
        right_claim_id: uuid.UUID,
    ) -> bool:
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
        return row is not None

    @staticmethod
    def _insert_contradiction_pair(
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        created_at_us: int,
        processing_run_id: uuid.UUID,
        model_signature_id: uuid.UUID,
        left_claim_id: uuid.UUID,
        left_revision_id: uuid.UUID,
        right_claim_id: uuid.UUID,
        right_revision_id: uuid.UUID,
        reason: str,
    ) -> None:
        for subject_id, subject_revision_id, evidence_id, evidence_revision_id in (
            (left_claim_id, left_revision_id, right_claim_id, right_revision_id),
            (right_claim_id, right_revision_id, left_claim_id, left_revision_id),
        ):
            provenance_id = new_uuid7()
            ClaimRepository._insert_provenance(
                connection,
                provenance_id=provenance_id,
                claim_id=subject_id,
                revision_id=subject_revision_id,
                operation="claim.evidence.contradicts.from_review",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason=reason,
                model_signature_id=model_signature_id,
                processing_run_id=processing_run_id,
            )
            ClaimRepository._insert_claim_evidence(
                connection,
                claim_id=subject_id,
                evidence_entity_id=evidence_id,
                evidence_revision_id=evidence_revision_id,
                evidence_role=EvidenceRole.CONTRADICTS,
                provenance_id=provenance_id,
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ReviewItem:
        def maybe_uuid(value: object) -> uuid.UUID | None:
            if value is None:
                return None
            if not isinstance(value, (bytes, bytearray, memoryview)):
                raise ReviewError("Invalid UUID BLOB in semantic review row.")
            return uuid_from_blob(bytes(value))

        return ReviewItem(
            review_id=uuid_from_blob(bytes(row["review_id"])),
            review_type=str(row["review_type"]),
            status=ReviewStatus(str(row["status"])),
            created_at_us=int(row["created_at_us"]),
            resolved_at_us=None if row["resolved_at_us"] is None else int(row["resolved_at_us"]),
            processing_run_id=uuid_from_blob(bytes(row["processing_run_id"])),
            model_signature_id=uuid_from_blob(bytes(row["model_signature_id"])),
            left_entity_id=maybe_uuid(row["left_entity_id"]),
            left_revision_id=maybe_uuid(row["left_revision_id"]),
            right_entity_id=maybe_uuid(row["right_entity_id"]),
            right_revision_id=maybe_uuid(row["right_revision_id"]),
            confidence=float(row["confidence"]),
            reason=str(row["reason"]),
            decision_actor_id=maybe_uuid(row["decision_actor_id"]),
            decision_reason=None if row["decision_reason"] is None else str(row["decision_reason"]),
        )
