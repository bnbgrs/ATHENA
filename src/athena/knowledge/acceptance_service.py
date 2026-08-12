"""Explicit user acceptance of validated Primary Model extraction proposals."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from athena.chat.models import ChatMessage
from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.claim_repository import ClaimRepository, _claim_payload_hash
from athena.knowledge.deduplication import (
    CanonicalDeduplicationService,
    CanonicalMergeCandidate,
    DedupAction,
    DedupDecision,
    DeduplicationPlan,
)
from athena.knowledge.extraction_models import (
    ChatExtractionResult,
    ProposalEntityType,
    ProposedClaim,
    ProposedKnowledgeUnit,
)
from athena.knowledge.models import ClaimDraft, EvidenceRole, KnowledgeUnitDraft
from athena.knowledge.repository import KnowledgeRepository, _knowledge_payload_hash
from athena.knowledge.review_service import ReviewService
from athena.storage.database import SQLiteDatabase


class ProposalAcceptanceError(ValueError):
    """Raised when a proposal set cannot be safely committed."""


@dataclass(frozen=True, slots=True)
class ProposalAcceptanceResult:
    processing_run_id: uuid.UUID
    commit_id: uuid.UUID
    knowledge_ids: tuple[uuid.UUID, ...]
    claim_ids: tuple[uuid.UUID, ...]
    knowledge_created_ids: tuple[uuid.UUID, ...]
    claim_created_ids: tuple[uuid.UUID, ...]
    knowledge_reused_ids: tuple[uuid.UUID, ...]
    claim_reused_ids: tuple[uuid.UUID, ...]
    contradiction_pairs: tuple[tuple[uuid.UUID, uuid.UUID], ...]
    contradiction_pairs_reused: tuple[tuple[uuid.UUID, uuid.UUID], ...]
    contradiction_review_ids: tuple[uuid.UUID, ...]


class ProposalAcceptanceService:
    """Atomically commit one validated extraction result after explicit approval."""

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chat: ChatService,
        knowledge: KnowledgeRepository,
        claims: ClaimRepository,
        reviews: ReviewService,
    ) -> None:
        self.database = database
        self.chat = chat
        self.knowledge = knowledge
        self.claims = claims
        self.reviews = reviews

    def preflight(self, result: ChatExtractionResult) -> DeduplicationPlan:
        """Return deterministic canonical dedup/merge decisions without writing."""
        self._validate_result_header(result)
        if result.proposals.merge_candidates:
            raise ProposalAcceptanceError(
                "Extractor returned unresolved merge candidates; acceptance is blocked."
            )
        plan = CanonicalDeduplicationService.plan(self.database.connection, result)
        return self._apply_resolved_merge_reviews(result, plan)

    def accept_all(
        self,
        result: ChatExtractionResult,
        *,
        expected_plan: DeduplicationPlan | None = None,
    ) -> ProposalAcceptanceResult:
        """Commit the displayed proposal set atomically, reusing exact duplicates."""
        self._validate_result_header(result)
        if result.proposals.merge_candidates:
            raise ProposalAcceptanceError(
                "Proposal sets with unresolved extractor merge candidates cannot be accepted."
            )

        thread = self.chat.load_chat(result.chat_id)
        source_by_sequence = {message.sequence_no: message for message in thread.messages}
        self._validate_snapshot(result, source_by_sequence)
        self._validate_sources(result, source_by_sequence)
        self._validate_relations(result)

        actor_id = self.chat.ensure_local_user()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()

        knowledge_ids: list[uuid.UUID] = []
        knowledge_revision_ids: list[uuid.UUID] = []
        claim_ids: list[uuid.UUID] = []
        claim_revision_ids: list[uuid.UUID] = []
        knowledge_created_ids: list[uuid.UUID] = []
        claim_created_ids: list[uuid.UUID] = []
        knowledge_reused_ids: list[uuid.UUID] = []
        claim_reused_ids: list[uuid.UUID] = []
        contradiction_pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
        contradiction_pairs_reused: list[tuple[uuid.UUID, uuid.UUID]] = []
        contradiction_review_ids: list[uuid.UUID] = []

        with self.database.write_transaction() as connection:
            current_plan = CanonicalDeduplicationService.plan(connection, result)
            current_plan = self._apply_resolved_merge_reviews(result, current_plan)
            if expected_plan is not None and current_plan != expected_plan:
                raise ProposalAcceptanceError(
                    "Canonical state changed after deduplication preflight; review proposals again."
                )
            if current_plan.has_unresolved_merge_candidates:
                raise ProposalAcceptanceError(
                    "Possible near-duplicates require explicit merge resolution before acceptance."
                )

            KnowledgeRepository._require_active_actor(connection, actor_id)
            commit_seq = KnowledgeRepository._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="knowledge.proposal_set.accept.deduplicated",
                committed_at_us=created_at_us,
                reason="explicit user acceptance after canonical deduplication preflight",
            )

            for index, knowledge_proposal in enumerate(result.proposals.knowledge_units):
                source = source_by_sequence[knowledge_proposal.source_sequence_no]
                KnowledgeRepository._require_source_revision(
                    connection,
                    entity_id=source.message_id,
                    revision_id=source.revision_id,
                )
                decision = current_plan.knowledge[index]

                if decision.action is DedupAction.CREATE:
                    knowledge_id, revision_id = self._create_knowledge(
                        connection=connection,
                        actor_id=actor_id,
                        commit_id=commit_id,
                        commit_seq=commit_seq,
                        created_at_us=created_at_us,
                        source=source,
                        result=result,
                        proposal=knowledge_proposal,
                    )
                    knowledge_created_ids.append(knowledge_id)
                else:
                    knowledge_id, revision_id = self._resolve_reused(
                        decision=decision,
                        resolved_ids=knowledge_ids,
                        resolved_revision_ids=knowledge_revision_ids,
                    )
                    self._record_reused_knowledge(
                        connection=connection,
                        actor_id=actor_id,
                        created_at_us=created_at_us,
                        knowledge_id=knowledge_id,
                        revision_id=revision_id,
                        source=source,
                        result=result,
                    )
                    knowledge_reused_ids.append(knowledge_id)
                knowledge_ids.append(knowledge_id)
                knowledge_revision_ids.append(revision_id)

            for index, claim_proposal in enumerate(result.proposals.claims):
                source = source_by_sequence[claim_proposal.source_sequence_no]
                ClaimRepository._require_source_revision(
                    connection,
                    entity_id=source.message_id,
                    revision_id=source.revision_id,
                )
                ClaimRepository._require_chat_message(connection, source.message_id)
                decision = current_plan.claims[index]

                if decision.action is DedupAction.CREATE:
                    claim_id, revision_id = self._create_claim(
                        connection=connection,
                        actor_id=actor_id,
                        commit_id=commit_id,
                        commit_seq=commit_seq,
                        created_at_us=created_at_us,
                        source=source,
                        result=result,
                        proposal=claim_proposal,
                    )
                    claim_created_ids.append(claim_id)
                else:
                    claim_id, revision_id = self._resolve_reused(
                        decision=decision,
                        resolved_ids=claim_ids,
                        resolved_revision_ids=claim_revision_ids,
                    )
                    self._record_reused_claim(
                        connection=connection,
                        actor_id=actor_id,
                        created_at_us=created_at_us,
                        claim_id=claim_id,
                        revision_id=revision_id,
                        source=source,
                        result=result,
                    )
                    claim_reused_ids.append(claim_id)
                claim_ids.append(claim_id)
                claim_revision_ids.append(revision_id)

            for relation in result.proposals.relations:
                if relation.relation_type != EvidenceRole.CONTRADICTS.value:
                    continue
                left_claim_id = claim_ids[relation.left_index]
                right_claim_id = claim_ids[relation.right_index]
                left_revision_id = claim_revision_ids[relation.left_index]
                right_revision_id = claim_revision_ids[relation.right_index]
                if left_claim_id == right_claim_id:
                    raise ProposalAcceptanceError(
                        "Deduplication collapsed both sides of a contradiction to one Claim."
                    )
                if self._contradiction_exists(
                    connection,
                    left_claim_id=left_claim_id,
                    right_claim_id=right_claim_id,
                ):
                    contradiction_pairs_reused.append((left_claim_id, right_claim_id))
                    continue
                review_id = self.reviews.enqueue_contradiction(
                    connection,
                    processing_run_id=result.processing_run.processing_run_id,
                    model_signature_id=result.model_signature.model_signature_id,
                    left_entity_id=left_claim_id,
                    left_revision_id=left_revision_id,
                    right_entity_id=right_claim_id,
                    right_revision_id=right_revision_id,
                    confidence=relation.confidence,
                    reason=(
                        "Primary Model contradiction requires review; model-reported "
                        "confidence is not an authorization signal"
                    ),
                    created_at_us=created_at_us,
                )
                contradiction_review_ids.append(review_id)

        return ProposalAcceptanceResult(
            processing_run_id=result.processing_run.processing_run_id,
            commit_id=commit_id,
            knowledge_ids=tuple(knowledge_ids),
            claim_ids=tuple(claim_ids),
            knowledge_created_ids=tuple(knowledge_created_ids),
            claim_created_ids=tuple(claim_created_ids),
            knowledge_reused_ids=tuple(knowledge_reused_ids),
            claim_reused_ids=tuple(claim_reused_ids),
            contradiction_pairs=tuple(contradiction_pairs),
            contradiction_pairs_reused=tuple(contradiction_pairs_reused),
            contradiction_review_ids=tuple(contradiction_review_ids),
        )

    def queue_merge_reviews(
        self,
        result: ChatExtractionResult,
        plan: DeduplicationPlan,
    ) -> tuple[uuid.UUID, ...]:
        """Persist unresolved canonical merge candidates without canonical semantic writes."""
        thread = self.chat.load_chat(result.chat_id)
        source_by_sequence = {message.sequence_no: message for message in thread.messages}
        self._validate_snapshot(result, source_by_sequence)
        self._validate_sources(result, source_by_sequence)
        return self.reviews.enqueue_merge_candidates(
            result=result,
            candidates=plan.merge_candidates,
            source_by_sequence=source_by_sequence,
        )

    def _apply_resolved_merge_reviews(
        self,
        result: ChatExtractionResult,
        plan: DeduplicationPlan,
    ) -> DeduplicationPlan:
        if not plan.merge_candidates:
            return plan

        thread = self.chat.load_chat(result.chat_id)
        source_by_sequence = {message.sequence_no: message for message in thread.messages}

        knowledge = list(plan.knowledge)
        claims = list(plan.claims)
        unresolved: list[CanonicalMergeCandidate] = []
        merge_target_by_proposal: dict[tuple[str, int], uuid.UUID] = {}

        for candidate in plan.merge_candidates:
            proposal = (
                result.proposals.knowledge_units[candidate.proposal_index]
                if candidate.proposal_type is ProposalEntityType.KNOWLEDGE
                else result.proposals.claims[candidate.proposal_index]
            )
            source = source_by_sequence[proposal.source_sequence_no]
            decision = self.reviews.lookup_merge_decision(
                candidate=candidate,
                result=result,
                source_entity_id=source.message_id,
                source_revision_id=source.revision_id,
            )
            if decision is None:
                unresolved.append(candidate)
                continue
            if decision == "keep_separate":
                continue
            if decision != "merge":
                raise ProposalAcceptanceError(f"Unsupported persisted merge decision: {decision!r}")

            key = (candidate.proposal_type.value, candidate.proposal_index)
            prior_target = merge_target_by_proposal.get(key)
            if prior_target is not None and prior_target != candidate.existing_entity_id:
                raise ProposalAcceptanceError(
                    "Conflicting accepted merge targets exist for one proposal."
                )
            merge_target_by_proposal[key] = candidate.existing_entity_id
            replacement = DedupDecision(
                proposal_type=candidate.proposal_type,
                proposal_index=candidate.proposal_index,
                action=DedupAction.REUSE_CANONICAL,
                existing_entity_id=candidate.existing_entity_id,
                existing_revision_id=candidate.existing_revision_id,
            )
            if candidate.proposal_type is ProposalEntityType.KNOWLEDGE:
                knowledge[candidate.proposal_index] = replacement
            else:
                claims[candidate.proposal_index] = replacement

        # Once a proposal has an explicit merge target, its other near-duplicate
        # candidates no longer need an independent decision for this acceptance.
        filtered_unresolved = tuple(
            candidate
            for candidate in unresolved
            if (
                candidate.proposal_type.value,
                candidate.proposal_index,
            )
            not in merge_target_by_proposal
        )
        return DeduplicationPlan(
            knowledge=tuple(knowledge),
            claims=tuple(claims),
            merge_candidates=filtered_unresolved,
        )

    @staticmethod
    def _validate_result_header(result: ChatExtractionResult) -> None:
        if result.processing_run.status != "succeeded":
            raise ProposalAcceptanceError("Only succeeded extraction runs can be accepted.")
        if result.processing_run.model_signature_id != result.model_signature.model_signature_id:
            raise ProposalAcceptanceError("Extraction run/model signature mismatch.")
        if result.processing_run.processing_run_id is None:
            raise ProposalAcceptanceError("Extraction result has no processing run.")

    @staticmethod
    def _resolve_reused(
        *,
        decision: DedupDecision,
        resolved_ids: list[uuid.UUID],
        resolved_revision_ids: list[uuid.UUID] | None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        if decision.action is DedupAction.REUSE_CANONICAL:
            if decision.existing_entity_id is None or decision.existing_revision_id is None:
                raise ProposalAcceptanceError("Canonical reuse decision is incomplete.")
            return decision.existing_entity_id, decision.existing_revision_id
        if decision.action is DedupAction.REUSE_PROPOSAL:
            prior = decision.duplicate_of_proposal_index
            if prior is None or prior >= len(resolved_ids):
                raise ProposalAcceptanceError("Proposal reuse decision is invalid.")
            if resolved_revision_ids is None:
                raise ProposalAcceptanceError(
                    "Knowledge proposal-to-proposal reuse requires a canonical revision."
                )
            return resolved_ids[prior], resolved_revision_ids[prior]
        raise ProposalAcceptanceError("CREATE decisions cannot be resolved as reuse.")

    def _create_knowledge(
        self,
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        commit_id: uuid.UUID,
        commit_seq: int,
        created_at_us: int,
        source: ChatMessage,
        result: ChatExtractionResult,
        proposal: ProposedKnowledgeUnit,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        knowledge_id = new_uuid7()
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        draft = KnowledgeUnitDraft(
            knowledge_kind=proposal.knowledge_kind,
            title=proposal.title,
            body=proposal.body,
            epistemic_status=proposal.epistemic_status,
        )
        KnowledgeRepository._insert_entity(
            connection,
            knowledge_id=knowledge_id,
            actor_id=actor_id,
            created_at_us=created_at_us,
            commit_seq=commit_seq,
            reason="accepted Primary Model proposal",
        )
        KnowledgeRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            operation="knowledge.create.from_model_proposal",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="explicit user acceptance of validated Primary Model proposal",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        KnowledgeRepository._insert_provenance_input(
            connection,
            provenance_id=provenance_id,
            input_entity_id=source.message_id,
            input_revision_id=source.revision_id,
            input_role="chat_message_source",
            ordinal=0,
        )
        KnowledgeRepository._insert_revision(
            connection,
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            revision_no=1,
            parent_revision_id=None,
            actor_id=actor_id,
            provenance_id=provenance_id,
            commit_id=commit_id,
            created_at_us=created_at_us,
            payload_hash=_knowledge_payload_hash(draft),
            change_kind="create",
        )
        connection.execute(
            "INSERT INTO entity_heads (entity_id, current_revision_id, current_revision_no) "
            "VALUES (?, ?, 1)",
            (uuid_to_blob(knowledge_id), uuid_to_blob(revision_id)),
        )
        connection.execute(
            "INSERT INTO knowledge_units (knowledge_id) VALUES (?)",
            (uuid_to_blob(knowledge_id),),
        )
        KnowledgeRepository._insert_payload(connection, revision_id=revision_id, draft=draft)
        connection.execute(
            "INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type) "
            "VALUES (?, ?, ?, 'create')",
            (commit_seq, uuid_to_blob(knowledge_id), uuid_to_blob(revision_id)),
        )
        return knowledge_id, revision_id

    def _create_claim(
        self,
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        commit_id: uuid.UUID,
        commit_seq: int,
        created_at_us: int,
        source: ChatMessage,
        result: ChatExtractionResult,
        proposal: ProposedClaim,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        claim_id = new_uuid7()
        revision_id = new_uuid7()
        provenance_id = new_uuid7()
        draft = ClaimDraft(
            claim_kind=proposal.claim_kind,
            statement=proposal.statement,
            epistemic_status=proposal.epistemic_status,
        )
        ClaimRepository._insert_entity(
            connection,
            claim_id=claim_id,
            actor_id=actor_id,
            created_at_us=created_at_us,
            commit_seq=commit_seq,
            reason="accepted Primary Model proposal",
        )
        ClaimRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            claim_id=claim_id,
            revision_id=revision_id,
            operation="claim.create.from_model_proposal",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="explicit user acceptance of validated Primary Model proposal",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        ClaimRepository._insert_provenance_input(
            connection,
            provenance_id=provenance_id,
            input_entity_id=source.message_id,
            input_revision_id=source.revision_id,
            input_role="chat_message_source",
            ordinal=0,
        )
        ClaimRepository._insert_revision(
            connection,
            claim_id=claim_id,
            revision_id=revision_id,
            revision_no=1,
            parent_revision_id=None,
            actor_id=actor_id,
            provenance_id=provenance_id,
            commit_id=commit_id,
            created_at_us=created_at_us,
            payload_hash=_claim_payload_hash(draft),
            change_kind="create",
        )
        connection.execute(
            "INSERT INTO entity_heads (entity_id, current_revision_id, current_revision_no) "
            "VALUES (?, ?, 1)",
            (uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
        )
        connection.execute("INSERT INTO claims (claim_id) VALUES (?)", (uuid_to_blob(claim_id),))
        ClaimRepository._insert_payload(connection, revision_id=revision_id, draft=draft)
        connection.execute(
            """
            INSERT INTO claim_evidence (
                claim_id, anchor_id, message_id, evidence_entity_id,
                evidence_revision_id, evidence_role, provenance_id
            ) VALUES (?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(claim_id),
                uuid_to_blob(source.message_id),
                uuid_to_blob(source.message_id),
                uuid_to_blob(source.revision_id),
                EvidenceRole.ORIGINATES.value,
                uuid_to_blob(provenance_id),
            ),
        )
        connection.execute(
            "INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type) "
            "VALUES (?, ?, ?, 'create')",
            (commit_seq, uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
        )
        return claim_id, revision_id

    @staticmethod
    def _record_reused_knowledge(
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        created_at_us: int,
        knowledge_id: uuid.UUID,
        revision_id: uuid.UUID,
        source: ChatMessage,
        result: ChatExtractionResult,
    ) -> None:
        provenance_id = new_uuid7()
        KnowledgeRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            operation="knowledge.duplicate.reused",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="exact canonical duplicate reused after user acceptance",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        KnowledgeRepository._insert_provenance_input(
            connection,
            provenance_id=provenance_id,
            input_entity_id=source.message_id,
            input_revision_id=source.revision_id,
            input_role="chat_message_duplicate_source",
            ordinal=0,
        )

    @staticmethod
    def _record_reused_claim(
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        created_at_us: int,
        claim_id: uuid.UUID,
        revision_id: uuid.UUID,
        source: ChatMessage,
        result: ChatExtractionResult,
    ) -> None:
        provenance_id = new_uuid7()
        ClaimRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            claim_id=claim_id,
            revision_id=revision_id,
            operation="claim.duplicate.reused",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="exact canonical duplicate reused after user acceptance",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        ClaimRepository._insert_provenance_input(
            connection,
            provenance_id=provenance_id,
            input_entity_id=source.message_id,
            input_revision_id=source.revision_id,
            input_role="chat_message_duplicate_source",
            ordinal=0,
        )
        exists = connection.execute(
            """
            SELECT 1
            FROM claim_evidence
            WHERE claim_id = ?
              AND message_id = ?
              AND evidence_entity_id = ?
              AND evidence_revision_id = ?
              AND evidence_role = ?
            LIMIT 1
            """,
            (
                uuid_to_blob(claim_id),
                uuid_to_blob(source.message_id),
                uuid_to_blob(source.message_id),
                uuid_to_blob(source.revision_id),
                EvidenceRole.ORIGINATES.value,
            ),
        ).fetchone()
        if exists is None:
            connection.execute(
                """
                INSERT INTO claim_evidence (
                    claim_id, anchor_id, message_id, evidence_entity_id,
                    evidence_revision_id, evidence_role, provenance_id
                ) VALUES (?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(claim_id),
                    uuid_to_blob(source.message_id),
                    uuid_to_blob(source.message_id),
                    uuid_to_blob(source.revision_id),
                    EvidenceRole.ORIGINATES.value,
                    uuid_to_blob(provenance_id),
                ),
            )

    @staticmethod
    def _contradiction_exists(
        connection: sqlite3.Connection,
        *,
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
        result: ChatExtractionResult,
        left_claim_id: uuid.UUID,
        left_revision_id: uuid.UUID,
        right_claim_id: uuid.UUID,
        right_revision_id: uuid.UUID,
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
                operation="claim.evidence.contradicts.from_model_proposal",
                actor_id=actor_id,
                created_at_us=created_at_us,
                reason="explicit user acceptance of validated contradiction proposal",
                model_signature_id=result.model_signature.model_signature_id,
                processing_run_id=result.processing_run.processing_run_id,
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
    def _validate_snapshot(
        result: ChatExtractionResult,
        source_by_sequence: dict[int, ChatMessage],
    ) -> None:
        try:
            snapshot = json.loads(result.processing_run.input_snapshot_json)
        except json.JSONDecodeError as exc:
            raise ProposalAcceptanceError("Extraction input snapshot is invalid JSON.") from exc
        if snapshot.get("chat_id") != str(result.chat_id):
            raise ProposalAcceptanceError("Extraction snapshot belongs to another chat.")
        snapshot_messages = snapshot.get("messages")
        if not isinstance(snapshot_messages, list):
            raise ProposalAcceptanceError("Extraction snapshot has no valid message list.")
        for item in snapshot_messages:
            if not isinstance(item, dict):
                raise ProposalAcceptanceError("Extraction snapshot message is invalid.")
            sequence_no = item.get("sequence_no")
            if not isinstance(sequence_no, int) or sequence_no not in source_by_sequence:
                raise ProposalAcceptanceError("Extraction source message no longer matches chat.")
            current = source_by_sequence[sequence_no]
            if item.get("message_id") != str(current.message_id):
                raise ProposalAcceptanceError("Extraction source message identity changed.")
            if item.get("revision_id") != str(current.revision_id):
                raise ProposalAcceptanceError("Extraction source revision changed after extraction.")

    @staticmethod
    def _validate_sources(
        result: ChatExtractionResult,
        source_by_sequence: dict[int, ChatMessage],
    ) -> None:
        for knowledge_proposal in result.proposals.knowledge_units:
            source = source_by_sequence.get(knowledge_proposal.source_sequence_no)
            if source is None or source.content is None:
                raise ProposalAcceptanceError("Proposal source is unavailable.")
            if knowledge_proposal.source_quote not in source.content:
                raise ProposalAcceptanceError("Proposal source_quote is no longer grounded.")

        for claim_proposal in result.proposals.claims:
            source = source_by_sequence.get(claim_proposal.source_sequence_no)
            if source is None or source.content is None:
                raise ProposalAcceptanceError("Proposal source is unavailable.")
            if claim_proposal.source_quote not in source.content:
                raise ProposalAcceptanceError("Proposal source_quote is no longer grounded.")

    @staticmethod
    def _validate_relations(result: ChatExtractionResult) -> None:
        for relation in result.proposals.relations:
            if relation.relation_type != EvidenceRole.CONTRADICTS.value:
                raise ProposalAcceptanceError(
                    f"Unsupported canonical relation proposal: {relation.relation_type!r}."
                )
            if relation.left_type is not ProposalEntityType.CLAIM:
                raise ProposalAcceptanceError("Contradiction left side must be a Claim proposal.")
            if relation.right_type is not ProposalEntityType.CLAIM:
                raise ProposalAcceptanceError("Contradiction right side must be a Claim proposal.")
