"""Explicit user acceptance of source-analysis Knowledge/Claim proposals."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.claim_repository import ClaimRepository, _claim_payload_hash
from athena.knowledge.deduplication import (
    CanonicalDeduplicationService,
    DedupAction,
    DedupDecision,
    DeduplicationPlan,
)
from athena.knowledge.extraction_models import (
    ProposalEntityType,
    ProposedClaim,
    ProposedKnowledgeUnit,
)
from athena.knowledge.models import ClaimDraft, EvidenceRole, KnowledgeUnitDraft
from athena.knowledge.repository import KnowledgeRepository, _knowledge_payload_hash
from athena.knowledge.review_service import ReviewService
from athena.knowledge.source_extraction import (
    HIERARCHICAL_LEGACY_PROMPT_TEMPLATE_VERSIONS,
    HIERARCHICAL_PIPELINE_VERSION,
    HIERARCHICAL_PROMPT_TEMPLATE_ID,
    HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
    PIPELINE_VERSION,
    PROMPT_TEMPLATE_ID,
    PROMPT_TEMPLATE_VERSION,
    SourceAnalysisExtractionResult,
    SourceExtractionEvidence,
    SourceExtractionSnapshotNotFoundError,
    SourceExtractionSnapshotRepository,
)
from athena.source.analysis_models import AnalysisStage
from athena.source.analysis_repository import SourceAnalysisRepository
from athena.source.anchor_service import SourceAnchorService
from athena.storage.database import SQLiteDatabase


class SourceProposalAcceptanceError(ValueError):
    """Raised when a source-derived proposal set cannot be safely committed."""


@dataclass(frozen=True, slots=True)
class SourceProposalAcceptanceResult:
    processing_run_id: uuid.UUID
    commit_id: uuid.UUID
    knowledge_ids: tuple[uuid.UUID, ...]
    claim_ids: tuple[uuid.UUID, ...]
    knowledge_created_ids: tuple[uuid.UUID, ...]
    claim_created_ids: tuple[uuid.UUID, ...]
    knowledge_reused_ids: tuple[uuid.UUID, ...]
    claim_reused_ids: tuple[uuid.UUID, ...]
    contradiction_review_ids: tuple[uuid.UUID, ...]


class SourceProposalAcceptanceService:
    """Atomically promote frozen, grounded source-analysis proposals after user approval."""

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chat: ChatService,
        analyses: SourceAnalysisRepository,
        anchors: SourceAnchorService,
        reviews: ReviewService,
        snapshots: SourceExtractionSnapshotRepository,
    ) -> None:
        self.database = database
        self.chat = chat
        self.analyses = analyses
        self.anchors = anchors
        self.reviews = reviews
        self.snapshots = snapshots

    def preflight(self, result: SourceAnalysisExtractionResult) -> DeduplicationPlan:
        self._validate_result(result)
        if result.proposals.merge_candidates:
            raise SourceProposalAcceptanceError(
                "Source extractor returned merge candidates without canonical context."
            )
        return CanonicalDeduplicationService.plan(self.database.connection, result)

    def accept_all(
        self,
        result: SourceAnalysisExtractionResult,
        *,
        expected_plan: DeduplicationPlan | None = None,
        keep_separate_near_duplicates: bool = False,
    ) -> SourceProposalAcceptanceResult:
        self._validate_result(result)
        if result.proposals.merge_candidates:
            raise SourceProposalAcceptanceError(
                "Source extractor returned unresolved merge candidates."
            )
        actor_id = self.chat.ensure_local_user()
        commit_id = new_uuid7()
        created_at_us = utc_now_us()
        evidence_by_sequence = {item.sequence_no: item for item in result.evidence}

        knowledge_ids: list[uuid.UUID] = []
        knowledge_revision_ids: list[uuid.UUID] = []
        claim_ids: list[uuid.UUID] = []
        claim_revision_ids: list[uuid.UUID] = []
        knowledge_created: list[uuid.UUID] = []
        claim_created: list[uuid.UUID] = []
        knowledge_reused: list[uuid.UUID] = []
        claim_reused: list[uuid.UUID] = []
        contradiction_reviews: list[uuid.UUID] = []

        with self.database.write_transaction() as connection:
            current_plan = CanonicalDeduplicationService.plan(connection, result)
            if expected_plan is not None and current_plan != expected_plan:
                raise SourceProposalAcceptanceError(
                    "Canonical state changed after deduplication preflight; review proposals again."
                )
            if current_plan.has_unresolved_merge_candidates and not keep_separate_near_duplicates:
                raise SourceProposalAcceptanceError(
                    "Possible near-duplicates require an explicit keep-separate decision before acceptance."
                )

            KnowledgeRepository._require_active_actor(connection, actor_id)
            commit_reason = "explicit user acceptance of grounded source-analysis proposals"
            if keep_separate_near_duplicates and current_plan.merge_candidates:
                commit_reason += "; explicit user decision to keep surfaced near-duplicates separate"
            commit_seq = KnowledgeRepository._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="source_analysis.proposal_set.accept",
                committed_at_us=created_at_us,
                reason=commit_reason,
            )

            for index, knowledge_proposal in enumerate(result.proposals.knowledge_units):
                evidence = evidence_by_sequence[knowledge_proposal.source_sequence_no]
                decision = current_plan.knowledge[index]
                if decision.action is DedupAction.CREATE:
                    knowledge_id, revision_id = self._create_knowledge(
                        connection=connection,
                        actor_id=actor_id,
                        commit_id=commit_id,
                        commit_seq=commit_seq,
                        created_at_us=created_at_us,
                        evidence=evidence,
                        result=result,
                        proposal=knowledge_proposal,
                    )
                    knowledge_created.append(knowledge_id)
                else:
                    knowledge_id, revision_id = self._resolve_reused(
                        decision,
                        knowledge_ids,
                        knowledge_revision_ids,
                    )
                    self._record_reused_knowledge(
                        connection=connection,
                        actor_id=actor_id,
                        created_at_us=created_at_us,
                        knowledge_id=knowledge_id,
                        revision_id=revision_id,
                        evidence=evidence,
                        result=result,
                    )
                    knowledge_reused.append(knowledge_id)
                knowledge_ids.append(knowledge_id)
                knowledge_revision_ids.append(revision_id)

            for index, claim_proposal in enumerate(result.proposals.claims):
                evidence = evidence_by_sequence[claim_proposal.source_sequence_no]
                decision = current_plan.claims[index]
                if decision.action is DedupAction.CREATE:
                    claim_id, revision_id = self._create_claim(
                        connection=connection,
                        actor_id=actor_id,
                        commit_id=commit_id,
                        commit_seq=commit_seq,
                        created_at_us=created_at_us,
                        evidence=evidence,
                        result=result,
                        proposal=claim_proposal,
                    )
                    claim_created.append(claim_id)
                else:
                    claim_id, revision_id = self._resolve_reused(
                        decision,
                        claim_ids,
                        claim_revision_ids,
                    )
                    self._record_reused_claim(
                        connection=connection,
                        actor_id=actor_id,
                        created_at_us=created_at_us,
                        claim_id=claim_id,
                        revision_id=revision_id,
                        evidence=evidence,
                        result=result,
                    )
                    claim_reused.append(claim_id)
                claim_ids.append(claim_id)
                claim_revision_ids.append(revision_id)

            for relation in result.proposals.relations:
                if relation.relation_type != EvidenceRole.CONTRADICTS.value:
                    raise SourceProposalAcceptanceError(
                        f"Unsupported canonical relation proposal: {relation.relation_type!r}."
                    )
                if relation.left_type is not ProposalEntityType.CLAIM or relation.right_type is not ProposalEntityType.CLAIM:
                    raise SourceProposalAcceptanceError(
                        "Source contradiction relations must reference Claim proposals."
                    )
                left_id = claim_ids[relation.left_index]
                right_id = claim_ids[relation.right_index]
                if left_id == right_id:
                    raise SourceProposalAcceptanceError(
                        "Deduplication collapsed both sides of a contradiction to one Claim."
                    )
                if self._contradiction_exists(connection, left_id, right_id):
                    continue
                review_id = self.reviews.enqueue_contradiction(
                    connection,
                    processing_run_id=result.processing_run.processing_run_id,
                    model_signature_id=result.model_signature.model_signature_id,
                    left_entity_id=left_id,
                    left_revision_id=claim_revision_ids[relation.left_index],
                    right_entity_id=right_id,
                    right_revision_id=claim_revision_ids[relation.right_index],
                    confidence=relation.confidence,
                    reason=(
                        "Primary Model source-analysis contradiction requires review; "
                        "model confidence is not an authorization signal"
                    ),
                    created_at_us=created_at_us,
                )
                contradiction_reviews.append(review_id)

        return SourceProposalAcceptanceResult(
            processing_run_id=result.processing_run.processing_run_id,
            commit_id=commit_id,
            knowledge_ids=tuple(knowledge_ids),
            claim_ids=tuple(claim_ids),
            knowledge_created_ids=tuple(knowledge_created),
            claim_created_ids=tuple(claim_created),
            knowledge_reused_ids=tuple(knowledge_reused),
            claim_reused_ids=tuple(claim_reused),
            contradiction_review_ids=tuple(contradiction_reviews),
        )

    def _validate_result(self, result: SourceAnalysisExtractionResult) -> None:
        if result.processing_run.status != "succeeded":
            raise SourceProposalAcceptanceError(
                "Only succeeded source extraction runs can be accepted."
            )
        if result.processing_run.run_type != "source_knowledge_extraction":
            raise SourceProposalAcceptanceError("ProcessingRun is not a source extraction run.")
        valid_identities = {
            (
                PIPELINE_VERSION,
                PROMPT_TEMPLATE_ID,
                PROMPT_TEMPLATE_VERSION,
            ),
            (
                HIERARCHICAL_PIPELINE_VERSION,
                HIERARCHICAL_PROMPT_TEMPLATE_ID,
                HIERARCHICAL_PROMPT_TEMPLATE_VERSION,
            ),
            *(
                (
                    HIERARCHICAL_PIPELINE_VERSION,
                    HIERARCHICAL_PROMPT_TEMPLATE_ID,
                    version,
                )
                for version in HIERARCHICAL_LEGACY_PROMPT_TEMPLATE_VERSIONS
            ),
        }
        identity = (
            result.processing_run.pipeline_version,
            result.processing_run.prompt_template_id,
            result.processing_run.prompt_template_version,
        )
        if identity not in valid_identities:
            raise SourceProposalAcceptanceError("Source extraction pipeline version changed.")
        if result.processing_run.model_signature_id != result.model_signature.model_signature_id:
            raise SourceProposalAcceptanceError("Source extraction run/model signature mismatch.")
        self._validate_run_snapshot(result)
        try:
            frozen = self.snapshots.load(result.processing_run.processing_run_id)
        except SourceExtractionSnapshotNotFoundError as exc:
            raise SourceProposalAcceptanceError(
                "Source extraction has no valid frozen proposal snapshot."
            ) from exc
        if (
            frozen.analysis_id != result.analysis_id
            or frozen.final_artifact_id != result.final_artifact_id
            or frozen.source_id != result.source_id
            or frozen.representation_id != result.representation_id
            or frozen.model_signature != result.model_signature
            or frozen.processing_run != result.processing_run
            or frozen.evidence != result.evidence
            or frozen.proposals != result.proposals
        ):
            raise SourceProposalAcceptanceError(
                "Displayed source proposal set no longer matches its frozen validated snapshot."
            )
        analysis = self.analyses.get_analysis(result.analysis_id)
        if analysis.state.value != "completed" or analysis.final_artifact_id != result.final_artifact_id:
            raise SourceProposalAcceptanceError("Source analysis Final Artifact changed or is incomplete.")
        final = self.analyses.get_artifact(result.final_artifact_id)
        if final.artifact_kind is not AnalysisStage.FINAL or final.analysis_id != result.analysis_id:
            raise SourceProposalAcceptanceError("Frozen source extraction references an invalid Final Artifact.")
        expected_anchor_ids = set(self.analyses.source_anchor_ids_for_artifact(result.final_artifact_id))
        if not expected_anchor_ids:
            raise SourceProposalAcceptanceError("Final Artifact has no SourceAnchor provenance.")
        seen_sequences: set[int] = set()
        evidence_by_sequence: dict[int, SourceExtractionEvidence] = {}
        for evidence in result.evidence:
            if evidence.sequence_no < 1 or evidence.sequence_no in seen_sequences:
                raise SourceProposalAcceptanceError("Frozen source evidence sequence is invalid.")
            seen_sequences.add(evidence.sequence_no)
            evidence_by_sequence[evidence.sequence_no] = evidence
            anchor = self.anchors.verify(evidence.anchor_id)
            if anchor.anchor_id not in expected_anchor_ids:
                raise SourceProposalAcceptanceError("Frozen source evidence is outside Final provenance.")
            if anchor.source_id != result.source_id or anchor.representation_id != result.representation_id:
                raise SourceProposalAcceptanceError("Frozen source evidence crossed pinned source scope.")
            if anchor.quoted_hash != evidence.quoted_hash:
                raise SourceProposalAcceptanceError("Frozen SourceAnchor hash changed.")
        if {item.anchor_id for item in result.evidence} != expected_anchor_ids:
            raise SourceProposalAcceptanceError(
                "Frozen source evidence no longer matches complete Final provenance."
            )
        if set(evidence_by_sequence) != set(range(1, len(result.evidence) + 1)):
            raise SourceProposalAcceptanceError("Frozen source evidence sequence must be contiguous.")
        for knowledge_proposal in result.proposals.knowledge_units:
            proposal_evidence = evidence_by_sequence.get(knowledge_proposal.source_sequence_no)
            if proposal_evidence is None:
                raise SourceProposalAcceptanceError(
                    "Proposal references no frozen SourceAnchor evidence."
                )
            text = self.anchors.read_text(proposal_evidence.anchor_id)
            if knowledge_proposal.source_quote not in text:
                raise SourceProposalAcceptanceError(
                    "Proposal source_quote no longer matches SourceAnchor text."
                )
        for claim_proposal in result.proposals.claims:
            proposal_evidence = evidence_by_sequence.get(claim_proposal.source_sequence_no)
            if proposal_evidence is None:
                raise SourceProposalAcceptanceError(
                    "Proposal references no frozen SourceAnchor evidence."
                )
            text = self.anchors.read_text(proposal_evidence.anchor_id)
            if claim_proposal.source_quote not in text:
                raise SourceProposalAcceptanceError(
                    "Proposal source_quote no longer matches SourceAnchor text."
                )


    @staticmethod
    def _validate_run_snapshot(result: SourceAnalysisExtractionResult) -> None:
        try:
            snapshot = json.loads(result.processing_run.input_snapshot_json)
        except json.JSONDecodeError as exc:
            raise SourceProposalAcceptanceError(
                "Source extraction ProcessingRun snapshot is invalid JSON."
            ) from exc
        if not isinstance(snapshot, dict):
            raise SourceProposalAcceptanceError(
                "Source extraction ProcessingRun snapshot is invalid."
            )
        expected_identity = {
            "analysis_id": str(result.analysis_id),
            "final_artifact_id": str(result.final_artifact_id),
            "source_id": str(result.source_id),
            "representation_id": str(result.representation_id),
        }
        for key, expected in expected_identity.items():
            if snapshot.get(key) != expected:
                raise SourceProposalAcceptanceError(
                    f"Source extraction ProcessingRun snapshot mismatch: {key}."
                )
        raw_evidence = snapshot.get("evidence")
        if not isinstance(raw_evidence, list):
            raise SourceProposalAcceptanceError(
                "Source extraction ProcessingRun snapshot has no valid evidence list."
            )
        expected_evidence = [
            {
                "sequence_no": item.sequence_no,
                "anchor_id": str(item.anchor_id),
                "quoted_hash": item.quoted_hash.hex(),
            }
            for item in result.evidence
        ]
        if raw_evidence != expected_evidence:
            raise SourceProposalAcceptanceError(
                "Source extraction ProcessingRun evidence snapshot changed."
            )

    @staticmethod
    def _resolve_reused(
        decision: DedupDecision,
        resolved_ids: list[uuid.UUID],
        resolved_revision_ids: list[uuid.UUID],
    ) -> tuple[uuid.UUID, uuid.UUID]:
        if decision.action is DedupAction.REUSE_CANONICAL:
            if decision.existing_entity_id is None or decision.existing_revision_id is None:
                raise SourceProposalAcceptanceError("Canonical reuse decision is incomplete.")
            return decision.existing_entity_id, decision.existing_revision_id
        if decision.action is DedupAction.REUSE_PROPOSAL:
            prior = decision.duplicate_of_proposal_index
            if prior is None or prior >= len(resolved_ids):
                raise SourceProposalAcceptanceError("Proposal reuse decision is invalid.")
            return resolved_ids[prior], resolved_revision_ids[prior]
        raise SourceProposalAcceptanceError("CREATE decision cannot be resolved as reuse.")

    @staticmethod
    def _insert_anchor_provenance_input(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        anchor_id: uuid.UUID,
        input_role: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO provenance_inputs (
                provenance_id, input_entity_id, input_revision_id, input_role, ordinal
            ) VALUES (?, ?, NULL, ?, 0)
            """,
            (uuid_to_blob(provenance_id), uuid_to_blob(anchor_id), input_role),
        )

    @staticmethod
    def _insert_analysis_origin(
        connection: sqlite3.Connection,
        *,
        provenance_id: uuid.UUID,
        result: SourceAnalysisExtractionResult,
        created_at_us: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO source_analysis_knowledge_origins (
                provenance_id, analysis_id, final_artifact_id, extraction_run_id, created_at_us
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid_to_blob(provenance_id),
                uuid_to_blob(result.analysis_id),
                uuid_to_blob(result.final_artifact_id),
                uuid_to_blob(result.processing_run.processing_run_id),
                created_at_us,
            ),
        )

    def _create_knowledge(
        self,
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        commit_id: uuid.UUID,
        commit_seq: int,
        created_at_us: int,
        evidence: SourceExtractionEvidence,
        result: SourceAnalysisExtractionResult,
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
            reason="accepted grounded source-analysis proposal",
        )
        KnowledgeRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            operation="knowledge.create.from_source_analysis",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="explicit user acceptance of grounded source-analysis proposal",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        self._insert_anchor_provenance_input(
            connection,
            provenance_id=provenance_id,
            anchor_id=evidence.anchor_id,
            input_role="source_anchor_evidence",
        )
        self._insert_analysis_origin(
            connection,
            provenance_id=provenance_id,
            result=result,
            created_at_us=created_at_us,
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
            "INSERT INTO entity_heads (entity_id, current_revision_id, current_revision_no) VALUES (?, ?, 1)",
            (uuid_to_blob(knowledge_id), uuid_to_blob(revision_id)),
        )
        connection.execute(
            "INSERT INTO knowledge_units (knowledge_id) VALUES (?)",
            (uuid_to_blob(knowledge_id),),
        )
        KnowledgeRepository._insert_payload(connection, revision_id=revision_id, draft=draft)
        connection.execute(
            "INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type) VALUES (?, ?, ?, 'create')",
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
        evidence: SourceExtractionEvidence,
        result: SourceAnalysisExtractionResult,
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
            reason="accepted grounded source-analysis proposal",
        )
        ClaimRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            claim_id=claim_id,
            revision_id=revision_id,
            operation="claim.create.from_source_analysis",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="explicit user acceptance of grounded source-analysis proposal",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        self._insert_anchor_provenance_input(
            connection,
            provenance_id=provenance_id,
            anchor_id=evidence.anchor_id,
            input_role="source_anchor_evidence",
        )
        self._insert_analysis_origin(
            connection,
            provenance_id=provenance_id,
            result=result,
            created_at_us=created_at_us,
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
            "INSERT INTO entity_heads (entity_id, current_revision_id, current_revision_no) VALUES (?, ?, 1)",
            (uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
        )
        connection.execute("INSERT INTO claims (claim_id) VALUES (?)", (uuid_to_blob(claim_id),))
        ClaimRepository._insert_payload(connection, revision_id=revision_id, draft=draft)
        connection.execute(
            """
            INSERT INTO claim_evidence (
                claim_id, anchor_id, message_id, evidence_entity_id,
                evidence_revision_id, evidence_role, provenance_id
            ) VALUES (?, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                uuid_to_blob(claim_id),
                uuid_to_blob(evidence.anchor_id),
                EvidenceRole.ORIGINATES.value,
                uuid_to_blob(provenance_id),
            ),
        )
        connection.execute(
            "INSERT INTO commit_changes (commit_seq, entity_id, revision_id, change_type) VALUES (?, ?, ?, 'create')",
            (commit_seq, uuid_to_blob(claim_id), uuid_to_blob(revision_id)),
        )
        return claim_id, revision_id

    def _record_reused_knowledge(
        self,
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        created_at_us: int,
        knowledge_id: uuid.UUID,
        revision_id: uuid.UUID,
        evidence: SourceExtractionEvidence,
        result: SourceAnalysisExtractionResult,
    ) -> None:
        provenance_id = new_uuid7()
        KnowledgeRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            knowledge_id=knowledge_id,
            revision_id=revision_id,
            operation="knowledge.duplicate.reused.from_source_analysis",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="exact canonical duplicate reused after user acceptance",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        self._insert_anchor_provenance_input(
            connection,
            provenance_id=provenance_id,
            anchor_id=evidence.anchor_id,
            input_role="source_anchor_duplicate_evidence",
        )
        self._insert_analysis_origin(
            connection,
            provenance_id=provenance_id,
            result=result,
            created_at_us=created_at_us,
        )

    def _record_reused_claim(
        self,
        *,
        connection: sqlite3.Connection,
        actor_id: uuid.UUID,
        created_at_us: int,
        claim_id: uuid.UUID,
        revision_id: uuid.UUID,
        evidence: SourceExtractionEvidence,
        result: SourceAnalysisExtractionResult,
    ) -> None:
        provenance_id = new_uuid7()
        ClaimRepository._insert_provenance(
            connection,
            provenance_id=provenance_id,
            claim_id=claim_id,
            revision_id=revision_id,
            operation="claim.duplicate.reused.from_source_analysis",
            actor_id=actor_id,
            created_at_us=created_at_us,
            reason="exact canonical duplicate reused after user acceptance",
            model_signature_id=result.model_signature.model_signature_id,
            processing_run_id=result.processing_run.processing_run_id,
        )
        self._insert_anchor_provenance_input(
            connection,
            provenance_id=provenance_id,
            anchor_id=evidence.anchor_id,
            input_role="source_anchor_duplicate_evidence",
        )
        self._insert_analysis_origin(
            connection,
            provenance_id=provenance_id,
            result=result,
            created_at_us=created_at_us,
        )
        exists = connection.execute(
            """
            SELECT 1 FROM claim_evidence
            WHERE claim_id = ? AND anchor_id = ? AND evidence_role = ?
            LIMIT 1
            """,
            (
                uuid_to_blob(claim_id),
                uuid_to_blob(evidence.anchor_id),
                EvidenceRole.ORIGINATES.value,
            ),
        ).fetchone()
        if exists is None:
            connection.execute(
                """
                INSERT INTO claim_evidence (
                    claim_id, anchor_id, message_id, evidence_entity_id,
                    evidence_revision_id, evidence_role, provenance_id
                ) VALUES (?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    uuid_to_blob(claim_id),
                    uuid_to_blob(evidence.anchor_id),
                    EvidenceRole.ORIGINATES.value,
                    uuid_to_blob(provenance_id),
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
              AND evidence_role = 'contradicts'
            LIMIT 1
            """,
            (uuid_to_blob(left_claim_id), uuid_to_blob(right_claim_id)),
        ).fetchone()
        return row is not None
