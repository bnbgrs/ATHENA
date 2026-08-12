"""Explicit user acceptance of validated Primary Model extraction proposals."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from athena.chat.models import ChatMessage
from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.claim_repository import ClaimRepository, _claim_payload_hash
from athena.knowledge.extraction_models import (
    ChatExtractionResult,
    ProposalEntityType,
)
from athena.knowledge.models import ClaimDraft, EvidenceRole, KnowledgeUnitDraft
from athena.knowledge.repository import KnowledgeRepository, _knowledge_payload_hash
from athena.storage.database import SQLiteDatabase


class ProposalAcceptanceError(ValueError):
    """Raised when a proposal set cannot be safely committed."""


@dataclass(frozen=True, slots=True)
class ProposalAcceptanceResult:
    processing_run_id: uuid.UUID
    commit_id: uuid.UUID
    knowledge_ids: tuple[uuid.UUID, ...]
    claim_ids: tuple[uuid.UUID, ...]
    contradiction_pairs: tuple[tuple[uuid.UUID, uuid.UUID], ...]


class ProposalAcceptanceService:
    """Atomically commit one already-validated extraction result after user approval."""

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chat: ChatService,
        knowledge: KnowledgeRepository,
        claims: ClaimRepository,
    ) -> None:
        self.database = database
        self.chat = chat
        self.knowledge = knowledge
        self.claims = claims

    def accept_all(self, result: ChatExtractionResult) -> ProposalAcceptanceResult:
        """Commit the exact displayed proposal set in one SQLite transaction."""
        if result.processing_run.status != "succeeded":
            raise ProposalAcceptanceError("Only succeeded extraction runs can be accepted.")
        if result.processing_run.model_signature_id != result.model_signature.model_signature_id:
            raise ProposalAcceptanceError("Extraction run/model signature mismatch.")
        if result.processing_run.processing_run_id is None:
            raise ProposalAcceptanceError("Extraction result has no processing run.")
        if result.proposals.merge_candidates:
            raise ProposalAcceptanceError(
                "Proposal sets with unresolved merge candidates cannot be accepted wholesale."
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
        claim_ids: list[uuid.UUID] = []
        claim_revision_ids: list[uuid.UUID] = []
        contradiction_pairs: list[tuple[uuid.UUID, uuid.UUID]] = []

        with self.database.write_transaction() as connection:
            KnowledgeRepository._require_active_actor(connection, actor_id)
            commit_seq = KnowledgeRepository._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="knowledge.proposal_set.accept",
                committed_at_us=created_at_us,
                reason=(
                    "explicit user acceptance of validated Primary Model extraction proposals"
                ),
            )

            for knowledge_proposal in result.proposals.knowledge_units:
                source = source_by_sequence[knowledge_proposal.source_sequence_no]
                knowledge_id = new_uuid7()
                revision_id = new_uuid7()
                provenance_id = new_uuid7()
                knowledge_draft = KnowledgeUnitDraft(
                    knowledge_kind=knowledge_proposal.knowledge_kind,
                    title=knowledge_proposal.title,
                    body=knowledge_proposal.body,
                    epistemic_status=knowledge_proposal.epistemic_status,
                )
                KnowledgeRepository._require_source_revision(
                    connection,
                    entity_id=source.message_id,
                    revision_id=source.revision_id,
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
                    payload_hash=_knowledge_payload_hash(knowledge_draft),
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
                KnowledgeRepository._insert_payload(
                    connection,
                    revision_id=revision_id,
                    draft=knowledge_draft,
                )
                connection.execute(
                    "INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type) "
                    "VALUES (?, ?, ?, 'create')",
                    (commit_seq, uuid_to_blob(knowledge_id), uuid_to_blob(revision_id)),
                )
                knowledge_ids.append(knowledge_id)

            for claim_proposal in result.proposals.claims:
                source = source_by_sequence[claim_proposal.source_sequence_no]
                claim_id = new_uuid7()
                revision_id = new_uuid7()
                provenance_id = new_uuid7()
                claim_draft = ClaimDraft(
                    claim_kind=claim_proposal.claim_kind,
                    statement=claim_proposal.statement,
                    epistemic_status=claim_proposal.epistemic_status,
                )
                ClaimRepository._require_source_revision(
                    connection,
                    entity_id=source.message_id,
                    revision_id=source.revision_id,
                )
                ClaimRepository._require_chat_message(connection, source.message_id)
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
                    payload_hash=_claim_payload_hash(claim_draft),
                    change_kind="create",
                )
                connection.execute(
                    "INSERT INTO entity_heads (entity_id, current_revision_id, current_revision_no) "
                    "VALUES (?, ?, 1)",
                    (uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
                )
                connection.execute(
                    "INSERT INTO claims (claim_id) VALUES (?)",
                    (uuid_to_blob(claim_id),),
                )
                ClaimRepository._insert_payload(connection, revision_id=revision_id, draft=claim_draft)
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
                claim_ids.append(claim_id)
                claim_revision_ids.append(revision_id)

            for relation in result.proposals.relations:
                if relation.relation_type != EvidenceRole.CONTRADICTS.value:
                    continue
                left_claim_id = claim_ids[relation.left_index]
                right_claim_id = claim_ids[relation.right_index]
                left_revision_id = claim_revision_ids[relation.left_index]
                right_revision_id = claim_revision_ids[relation.right_index]
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
                contradiction_pairs.append((left_claim_id, right_claim_id))

        return ProposalAcceptanceResult(
            processing_run_id=result.processing_run.processing_run_id,
            commit_id=commit_id,
            knowledge_ids=tuple(knowledge_ids),
            claim_ids=tuple(claim_ids),
            contradiction_pairs=tuple(contradiction_pairs),
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
