"""Explicit user promotion of immutable ResearchResult findings into canonical knowledge."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from athena.chat.service import ChatService
from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.knowledge.claim_repository import ClaimRepository, _claim_payload_hash
from athena.knowledge.deduplication import (
    CanonicalDeduplicationService,
    DedupAction,
)
from athena.knowledge.extraction_models import (
    ExtractionProposalSet,
    ProposedClaim,
    ProposedKnowledgeUnit,
)
from athena.knowledge.models import (
    ClaimDraft,
    ClaimKind,
    EpistemicStatus,
    EvidenceRole,
    KnowledgeKind,
    KnowledgeUnitDraft,
)
from athena.knowledge.repository import KnowledgeRepository, _knowledge_payload_hash
from athena.research.repository import ResearchRepository
from athena.source.analysis_models import AnalysisStage, SourceAnalysisState
from athena.source.analysis_repository import SourceAnalysisRepository
from athena.source.anchor_service import SourceAnchorService
from athena.storage.database import SQLiteDatabase


class ResearchPromotionError(ValueError):
    """Raised when a ResearchResult cannot be promoted safely."""


class ResearchProposalType(str, Enum):
    KNOWLEDGE = "knowledge"
    CLAIM = "claim"
    CONTRADICTION = "contradiction"


class ResearchProposalState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ResearchProposalRecord:
    proposal_id: uuid.UUID
    proposal_set_id: uuid.UUID
    ordinal: int
    proposal_type: ResearchProposalType
    payload_json: str
    evidence_kind: str
    evidence_ordinal: int | None
    source_analysis_artifact_ids_json: str
    state: ResearchProposalState
    accepted_entity_id: uuid.UUID | None
    accepted_revision_id: uuid.UUID | None
    created_at_us: int
    decided_at_us: int | None


@dataclass(frozen=True, slots=True)
class ResearchProposalSetRecord:
    proposal_set_id: uuid.UUID
    result_id: uuid.UUID
    result_content_hash: bytes
    state: str
    created_at_us: int
    updated_at_us: int


@dataclass(frozen=True, slots=True)
class ResearchPromotionAcceptance:
    proposal_id: uuid.UUID
    entity_id: uuid.UUID
    revision_id: uuid.UUID
    commit_id: uuid.UUID


class ResearchPromotionService:
    """Freeze deterministic proposals and require explicit user acceptance."""

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chat: ChatService,
        research: ResearchRepository,
        source_analyses: SourceAnalysisRepository,
        anchors: SourceAnchorService,
    ) -> None:
        self.database = database
        self.chat = chat
        self.research = research
        self.source_analyses = source_analyses
        self.anchors = anchors

    def result_view(self, identifier: uuid.UUID) -> dict[str, Any]:
        row = self.database.connection.execute(
            """
            SELECT rr.*, rs.job_id, rs.query_text, rs.state AS scope_state
            FROM research_results AS rr
            JOIN research_scopes AS rs ON rs.scope_id = rr.scope_id
            WHERE rr.result_id = ? OR rr.scope_id = ? OR rs.job_id = ?
            """,
            (uuid_to_blob(identifier), uuid_to_blob(identifier), uuid_to_blob(identifier)),
        ).fetchone()
        if row is None:
            raise ResearchPromotionError(f"No ResearchResult matches {identifier}.")
        content = _json_object(str(row["content_json"]), "ResearchResult content")
        evidence: dict[str, list[dict[str, Any]]] = {
            "findings": [],
            "contradictions": [],
        }
        if row["final_artifact_id"] is not None:
            final_artifact_id = uuid_from_blob(bytes(row["final_artifact_id"]))
            for key, output_kind in (
                ("findings", "finding"),
                ("contradictions", "contradiction"),
            ):
                values = _string_list(content.get(key), key)
                for output_ordinal, text in enumerate(values):
                    artifact_ids = tuple(
                        self.research.source_analysis_artifact_ids_for_synthesis_output(
                            final_artifact_id,
                            output_kind=output_kind,
                            output_ordinal=output_ordinal,
                        )
                    )
                    anchor_ids: set[uuid.UUID] = set()
                    source_ids: set[uuid.UUID] = set()
                    for artifact_id in artifact_ids:
                        artifact = self.source_analyses.get_artifact(artifact_id)
                        analysis = self.source_analyses.get_analysis(artifact.analysis_id)
                        source_ids.add(analysis.source_id)
                        for anchor_id in (
                            self.source_analyses.source_anchor_ids_for_artifact(
                                artifact_id
                            )
                        ):
                            anchor = self.anchors.verify(anchor_id)
                            if anchor.source_id != analysis.source_id:
                                raise ResearchPromotionError(
                                    "ResearchResult provenance crossed SourceAnalysis source scope."
                                )
                            anchor_ids.add(anchor_id)
                    evidence[key].append(
                        {
                            "ordinal": output_ordinal,
                            "text": text,
                            "source_analysis_artifact_ids": [
                                str(item) for item in artifact_ids
                            ],
                            "source_anchor_ids": [
                                str(item) for item in sorted(anchor_ids, key=str)
                            ],
                            "source_ids": [
                                str(item) for item in sorted(source_ids, key=str)
                            ],
                        }
                    )
        return {
            "result_id": str(uuid_from_blob(bytes(row["result_id"]))),
            "scope_id": str(uuid_from_blob(bytes(row["scope_id"]))),
            "job_id": str(uuid_from_blob(bytes(row["job_id"]))),
            "query": str(row["query_text"]),
            "scope_state": str(row["scope_state"]),
            "snapshot_commit_seq": int(row["snapshot_commit_seq"]),
            "coverage": {
                "candidate_total": int(row["candidate_total"]),
                "processed_count": int(row["processed_count"]),
                "successful_count": int(row["successful_count"]),
                "irrelevant_count": int(row["irrelevant_count"]),
                "failed_count": int(row["failed_count"]),
                "unavailable_count": int(row["unavailable_count"]),
                "excluded_count": int(row["excluded_count"]),
                "coverage_ratio": float(row["coverage_ratio"]),
            },
            "problem_sources": json.loads(str(row["problem_sources_json"])),
            "content": content,
            "evidence": evidence,
        }

    def create_proposals(self, result_id: uuid.UUID) -> ResearchProposalSetRecord:
        existing = self._get_set_for_result(result_id)
        if existing is not None:
            return existing

        result = self._result_row(result_id)
        if str(result["scope_state"]) != "completed":
            raise ResearchPromotionError("Only a completed ResearchScope can create proposals.")
        if int(result["successful_count"]) < 1 or result["final_artifact_id"] is None:
            raise ResearchPromotionError(
                "ResearchResult has no successful evidence-backed final artifact to promote."
            )

        content_json = str(result["content_json"])
        expected_hash = bytes(result["content_hash"])
        if hashlib.sha256(content_json.encode("utf-8")).digest() != expected_hash:
            raise ResearchPromotionError("ResearchResult content hash verification failed.")
        content = _json_object(content_json, "ResearchResult content")
        summary = _string_value(content.get("summary"), "summary")
        findings = _string_list(content.get("findings"), "findings")
        contradictions = _string_list(content.get("contradictions"), "contradictions")

        final_artifact_id = uuid_from_blob(bytes(result["final_artifact_id"]))
        all_source_artifacts = tuple(
            self.research.source_analysis_artifact_ids_for_synthesis_artifact(
                final_artifact_id
            )
        )
        if not all_source_artifacts:
            raise ResearchPromotionError(
                "Final Research synthesis has no recursive SourceAnalysis provenance."
            )
        if result["model_signature_id"] is None:
            raise ResearchPromotionError(
                "Evidence-backed ResearchResult has no pinned ModelSignature."
            )
        self._verify_source_artifact_lineage(
            tuple(sorted(set(all_source_artifacts), key=lambda item: item.bytes)),
            expected_model_signature_id=uuid_from_blob(
                bytes(result["model_signature_id"])
            ),
        )

        now_us = utc_now_us()
        proposal_set_id = new_uuid7()
        scope_id = uuid_from_blob(bytes(result["scope_id"]))
        scope = self.research.get_scope(scope_id)
        summary_status = (
            EpistemicStatus.DISPUTED
            if contradictions
            else EpistemicStatus.SUPPORTED
        )
        finding_status = (
            EpistemicStatus.UNCERTAIN
            if contradictions
            else EpistemicStatus.SUPPORTED
        )
        rows: list[
            tuple[
                ResearchProposalType,
                dict[str, Any],
                str,
                int | None,
                tuple[uuid.UUID, ...],
            ]
        ] = [
            (
                ResearchProposalType.KNOWLEDGE,
                {
                    "knowledge_kind": KnowledgeKind.SUMMARY.value,
                    "title": _research_title(scope.query_text),
                    "body": summary,
                    "epistemic_status": summary_status.value,
                },
                "summary",
                None,
                all_source_artifacts,
            )
        ]

        for ordinal, text in enumerate(findings):
            evidence = tuple(
                self.research.source_analysis_artifact_ids_for_synthesis_output(
                    final_artifact_id,
                    output_kind="finding",
                    output_ordinal=ordinal,
                )
            )
            if not evidence:
                raise ResearchPromotionError(
                    f"Finding {ordinal} has no durable Research synthesis evidence."
                )
            rows.append(
                (
                    ResearchProposalType.CLAIM,
                    {
                        "claim_kind": ClaimKind.OBSERVATION.value,
                        "statement": text,
                        "epistemic_status": finding_status.value,
                    },
                    "finding",
                    ordinal,
                    evidence,
                )
            )

        for ordinal, text in enumerate(contradictions):
            evidence = tuple(
                self.research.source_analysis_artifact_ids_for_synthesis_output(
                    final_artifact_id,
                    output_kind="contradiction",
                    output_ordinal=ordinal,
                )
            )
            if len(set(evidence)) < 2:
                raise ResearchPromotionError(
                    f"Contradiction {ordinal} is not backed by at least two source analyses."
                )
            rows.append(
                (
                    ResearchProposalType.CONTRADICTION,
                    {"text": text},
                    "contradiction",
                    ordinal,
                    evidence,
                )
            )

        with self.database.write_transaction() as connection:
            race = connection.execute(
                "SELECT * FROM research_promotion_sets WHERE result_id = ?",
                (uuid_to_blob(result_id),),
            ).fetchone()
            if race is not None:
                return _set_from_row(race)

            connection.execute(
                """
                INSERT INTO research_promotion_sets (
                    proposal_set_id, result_id, result_content_hash, state,
                    created_at_us, updated_at_us
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (
                    uuid_to_blob(proposal_set_id),
                    uuid_to_blob(result_id),
                    expected_hash,
                    now_us,
                    now_us,
                ),
            )
            for ordinal, item in enumerate(rows):
                proposal_type, payload, evidence_kind, evidence_ordinal, artifact_ids = item
                connection.execute(
                    """
                    INSERT INTO research_promotion_items (
                        proposal_id, proposal_set_id, ordinal, proposal_type,
                        payload_json, evidence_kind, evidence_ordinal,
                        source_analysis_artifact_ids_json, state,
                        accepted_entity_id, accepted_revision_id,
                        created_at_us, decided_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, NULL)
                    """,
                    (
                        uuid_to_blob(new_uuid7()),
                        uuid_to_blob(proposal_set_id),
                        ordinal,
                        proposal_type.value,
                        _canonical_json(payload),
                        evidence_kind,
                        evidence_ordinal,
                        _uuid_array_json(tuple(sorted(set(artifact_ids), key=lambda item: item.bytes))),
                        now_us,
                    ),
                )
        return self.get_set(proposal_set_id)

    def get_set(self, proposal_set_id: uuid.UUID) -> ResearchProposalSetRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_promotion_sets WHERE proposal_set_id = ?",
            (uuid_to_blob(proposal_set_id),),
        ).fetchone()
        if row is None:
            raise ResearchPromotionError(f"Research proposal set {proposal_set_id} not found.")
        return _set_from_row(row)

    def proposals_for_result(self, result_id: uuid.UUID) -> tuple[ResearchProposalRecord, ...]:
        proposal_set = self._get_set_for_result(result_id)
        if proposal_set is None:
            return ()
        return self.list_proposals(proposal_set.proposal_set_id)

    def list_proposals(
        self,
        proposal_set_id: uuid.UUID,
    ) -> tuple[ResearchProposalRecord, ...]:
        rows = self.database.connection.execute(
            """
            SELECT * FROM research_promotion_items
            WHERE proposal_set_id = ?
            ORDER BY ordinal
            """,
            (uuid_to_blob(proposal_set_id),),
        ).fetchall()
        return tuple(_proposal_from_row(row) for row in rows)

    def accept(
        self,
        proposal_id: uuid.UUID,
        *,
        keep_separate_near_duplicates: bool = False,
    ) -> ResearchPromotionAcceptance:
        actor_id = self.chat.ensure_local_user()
        proposal = self._proposal(proposal_id)
        if proposal.state is ResearchProposalState.ACCEPTED:
            if (
                proposal.accepted_entity_id is None
                or proposal.accepted_revision_id is None
            ):
                raise ResearchPromotionError(
                    "Accepted Research proposal lost its canonical identity."
                )
            origin = self.database.connection.execute(
                """
                SELECT acceptance_commit_id
                FROM research_knowledge_origins
                WHERE proposal_id = ?
                """,
                (uuid_to_blob(proposal_id),),
            ).fetchone()
            if origin is None:
                raise ResearchPromotionError(
                    "Accepted Research proposal lost its acceptance provenance."
                )
            return ResearchPromotionAcceptance(
                proposal_id=proposal_id,
                entity_id=proposal.accepted_entity_id,
                revision_id=proposal.accepted_revision_id,
                commit_id=uuid_from_blob(bytes(origin["acceptance_commit_id"])),
            )
        if proposal.proposal_type is ResearchProposalType.CONTRADICTION:
            raise ResearchPromotionError(
                "Contradiction proposals are review-only; reject/acknowledge them instead "
                "of silently canonicalizing one side."
            )
        if proposal.state is not ResearchProposalState.PENDING:
            raise ResearchPromotionError("Only a pending Research proposal can be accepted.")

        proposal_set = self.get_set(proposal.proposal_set_id)
        result = self._result_row(proposal_set.result_id)
        if bytes(result["content_hash"]) != proposal_set.result_content_hash:
            raise ResearchPromotionError("ResearchResult changed after proposal freeze.")
        if str(result["scope_state"]) != "completed":
            raise ResearchPromotionError("ResearchScope is no longer completed.")
        final_artifact_id = (
            uuid_from_blob(bytes(result["final_artifact_id"]))
            if result["final_artifact_id"] is not None
            else None
        )
        if final_artifact_id is None:
            raise ResearchPromotionError("Research proposal lost its final synthesis artifact.")

        expected_payload, expected_artifact_ids = self._expected_proposal(
            proposal=proposal,
            result=result,
        )
        stored_artifact_ids = tuple(
            sorted(
                _uuid_array(
                    proposal.source_analysis_artifact_ids_json,
                    "source_analysis_artifact_ids_json",
                ),
                key=lambda item: item.bytes,
            )
        )
        if stored_artifact_ids != expected_artifact_ids:
            raise ResearchPromotionError(
                "Frozen Research proposal evidence changed after proposal creation."
            )
        if _canonical_json(expected_payload) != proposal.payload_json:
            raise ResearchPromotionError(
                "Frozen Research proposal payload changed after proposal creation."
            )
        artifact_ids = expected_artifact_ids
        if not artifact_ids:
            raise ResearchPromotionError("Research proposal has no SourceAnalysis evidence.")
        if result["model_signature_id"] is None:
            raise ResearchPromotionError(
                "Evidence-backed ResearchResult has no pinned ModelSignature."
            )
        result_model_signature_id = uuid_from_blob(bytes(result["model_signature_id"]))
        anchor_ids, source_ids = self._verify_source_artifact_lineage(
            artifact_ids,
            expected_model_signature_id=result_model_signature_id,
        )

        created_at_us = utc_now_us()
        commit_id = new_uuid7()
        provenance_id = new_uuid7()
        run_row = self.database.connection.execute(
            """
            SELECT artifact.processing_run_id, run.status, run.model_signature_id
            FROM research_synthesis_artifacts AS artifact
            JOIN processing_runs AS run
              ON run.processing_run_id = artifact.processing_run_id
            WHERE artifact.artifact_id = ?
            """,
            (uuid_to_blob(final_artifact_id),),
        ).fetchone()
        if run_row is None or str(run_row["status"]) != "succeeded":
            raise ResearchPromotionError(
                "Research FINAL synthesis ProcessingRun is absent or not succeeded."
            )
        if (
            run_row["model_signature_id"] is None
            or uuid_from_blob(bytes(run_row["model_signature_id"]))
            != result_model_signature_id
        ):
            raise ResearchPromotionError(
                "ResearchResult ModelSignature disagrees with FINAL synthesis run."
            )
        processing_run_id = uuid_from_blob(bytes(run_row["processing_run_id"]))

        payload = expected_payload
        with self.database.write_transaction() as connection:
            current = connection.execute(
                "SELECT * FROM research_promotion_items WHERE proposal_id = ?",
                (uuid_to_blob(proposal_id),),
            ).fetchone()
            if (
                current is None
                or _proposal_from_row(current) != proposal
                or str(current["state"]) != "pending"
            ):
                raise ResearchPromotionError(
                    "Research proposal content/state changed before acceptance."
                )
            # Re-run immutable artifact/anchor verification while the canonical
            # write transaction is already fenced. This closes the review/write
            # TOCTOU boundary: no stale or changed evidence can be promoted.
            verified_anchor_ids, verified_source_ids = self._verify_source_artifact_lineage(
                artifact_ids,
                expected_model_signature_id=result_model_signature_id,
            )
            if verified_anchor_ids != anchor_ids or verified_source_ids != source_ids:
                raise ResearchPromotionError(
                    "Research proposal provenance changed at the acceptance boundary."
                )
            KnowledgeRepository._require_active_actor(connection, actor_id)
            dedup = CanonicalDeduplicationService.plan(
                connection,
                _ResearchDedupCarrier(_dedup_proposals(proposal.proposal_type, payload)),
            )
            decision = (
                dedup.knowledge[0]
                if proposal.proposal_type is ResearchProposalType.KNOWLEDGE
                else dedup.claims[0]
            )
            if dedup.merge_candidates and not keep_separate_near_duplicates:
                candidates = ", ".join(
                    str(item.existing_entity_id) for item in dedup.merge_candidates
                )
                raise ResearchPromotionError(
                    "Research proposal has possible canonical near-duplicates; "
                    "review before accepting, or explicitly keep separate: " + candidates
                )
            reused = decision.action is DedupAction.REUSE_CANONICAL
            if decision.action is DedupAction.REUSE_PROPOSAL:
                raise ResearchPromotionError(
                    "Single Research proposal deduplication returned invalid proposal reuse."
                )
            if reused:
                if (
                    decision.existing_entity_id is None
                    or decision.existing_revision_id is None
                ):
                    raise ResearchPromotionError(
                        "Canonical Research duplicate reuse decision is incomplete."
                    )
                entity_id = decision.existing_entity_id
                revision_id = decision.existing_revision_id
            else:
                entity_id = new_uuid7()
                revision_id = new_uuid7()

            commit_seq = KnowledgeRepository._insert_commit(
                connection,
                commit_id=commit_id,
                actor_id=actor_id,
                operation_type="research.proposal.accept",
                committed_at_us=created_at_us,
                reason="explicit user acceptance of frozen ResearchResult proposal",
            )
            if proposal.proposal_type is ResearchProposalType.KNOWLEDGE:
                knowledge_draft = KnowledgeUnitDraft(
                    knowledge_kind=KnowledgeKind(_required_string(payload, "knowledge_kind")),
                    title=_optional_string(payload, "title"),
                    body=_required_string(payload, "body"),
                    epistemic_status=EpistemicStatus(
                        _required_string(payload, "epistemic_status")
                    ),
                )
                if not reused:
                    KnowledgeRepository._insert_entity(
                        connection,
                        knowledge_id=entity_id,
                        actor_id=actor_id,
                        created_at_us=created_at_us,
                        commit_seq=commit_seq,
                        reason="research proposal acceptance",
                    )
                KnowledgeRepository._insert_provenance(
                    connection,
                    provenance_id=provenance_id,
                    knowledge_id=entity_id,
                    revision_id=revision_id,
                    operation=(
                        "knowledge.duplicate.reused.from_research"
                        if reused
                        else "research.proposal.accept"
                    ),
                    actor_id=actor_id,
                    created_at_us=created_at_us,
                    reason=(
                        "exact canonical duplicate reused after explicit Research acceptance"
                        if reused
                        else "explicit user acceptance of ResearchResult proposal"
                    ),
                    model_signature_id=result_model_signature_id,
                    processing_run_id=processing_run_id,
                )
                if not reused:
                    KnowledgeRepository._insert_revision(
                        connection,
                        knowledge_id=entity_id,
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
                        """
                        INSERT INTO entity_heads (
                            entity_id, current_revision_id, current_revision_no
                        ) VALUES (?, ?, 1)
                        """,
                        (uuid_to_blob(entity_id), uuid_to_blob(revision_id)),
                    )
                    connection.execute(
                        "INSERT INTO knowledge_units (knowledge_id) VALUES (?)",
                        (uuid_to_blob(entity_id),),
                    )
                    KnowledgeRepository._insert_payload(
                        connection,
                        revision_id=revision_id,
                        draft=knowledge_draft,
                    )
            else:
                claim_draft = ClaimDraft(
                    claim_kind=ClaimKind(_required_string(payload, "claim_kind")),
                    statement=_required_string(payload, "statement"),
                    epistemic_status=EpistemicStatus(
                        _required_string(payload, "epistemic_status")
                    ),
                )
                if not reused:
                    ClaimRepository._insert_entity(
                        connection,
                        claim_id=entity_id,
                        actor_id=actor_id,
                        created_at_us=created_at_us,
                        commit_seq=commit_seq,
                        reason="research proposal acceptance",
                    )
                ClaimRepository._insert_provenance(
                    connection,
                    provenance_id=provenance_id,
                    claim_id=entity_id,
                    revision_id=revision_id,
                    operation=(
                        "claim.duplicate.reused.from_research"
                        if reused
                        else "research.proposal.accept"
                    ),
                    actor_id=actor_id,
                    created_at_us=created_at_us,
                    reason=(
                        "exact canonical duplicate reused after explicit Research acceptance"
                        if reused
                        else "explicit user acceptance of ResearchResult proposal"
                    ),
                    model_signature_id=result_model_signature_id,
                    processing_run_id=processing_run_id,
                )
                if not reused:
                    ClaimRepository._insert_revision(
                        connection,
                        claim_id=entity_id,
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
                        """
                        INSERT INTO entity_heads (
                            entity_id, current_revision_id, current_revision_no
                        ) VALUES (?, ?, 1)
                        """,
                        (uuid_to_blob(entity_id), uuid_to_blob(revision_id)),
                    )
                    connection.execute(
                        "INSERT INTO claims (claim_id) VALUES (?)",
                        (uuid_to_blob(entity_id),),
                    )
                    ClaimRepository._insert_payload(
                        connection,
                        revision_id=revision_id,
                        draft=claim_draft,
                    )
                for anchor_id in sorted(anchor_ids, key=str):
                    exists = connection.execute(
                        """
                        SELECT 1 FROM claim_evidence
                        WHERE claim_id = ? AND anchor_id = ? AND evidence_role = ?
                        LIMIT 1
                        """,
                        (
                            uuid_to_blob(entity_id),
                            uuid_to_blob(anchor_id),
                            EvidenceRole.ORIGINATES.value,
                        ),
                    ).fetchone()
                    if exists is None:
                        connection.execute(
                            """
                            INSERT INTO claim_evidence (
                                claim_id, anchor_id, message_id,
                                evidence_entity_id, evidence_revision_id,
                                evidence_role, provenance_id
                            ) VALUES (?, ?, NULL, NULL, NULL, ?, ?)
                            """,
                            (
                                uuid_to_blob(entity_id),
                                uuid_to_blob(anchor_id),
                                EvidenceRole.ORIGINATES.value,
                                uuid_to_blob(provenance_id),
                            ),
                        )

            for input_ordinal, anchor_id in enumerate(
                sorted(anchor_ids, key=lambda item: item.bytes)
            ):
                connection.execute(
                    """
                    INSERT INTO provenance_inputs (
                        provenance_id, input_entity_id, input_revision_id,
                        input_role, ordinal
                    ) VALUES (?, ?, NULL, 'research_source_anchor_origin', ?)
                    """,
                    (
                        uuid_to_blob(provenance_id),
                        uuid_to_blob(anchor_id),
                        input_ordinal,
                    ),
                )

            if not reused:
                connection.execute(
                    """
                    INSERT INTO commit_changes (
                        commit_seq, entity_id, revision_id, change_type
                    ) VALUES (?, ?, ?, 'create')
                    """,
                    (commit_seq, uuid_to_blob(entity_id), uuid_to_blob(revision_id)),
                )
            connection.execute(
                """
                INSERT INTO research_knowledge_origins (
                    origin_id, subject_entity_id, subject_revision_id, result_id, proposal_id,
                    acceptance_commit_id, final_artifact_id,
                    source_analysis_artifact_ids_json,
                    source_anchor_ids_json, source_ids_json, created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(new_uuid7()),
                    uuid_to_blob(entity_id),
                    uuid_to_blob(revision_id),
                    uuid_to_blob(proposal_set.result_id),
                    uuid_to_blob(proposal_id),
                    uuid_to_blob(commit_id),
                    uuid_to_blob(final_artifact_id),
                    _uuid_array_json(tuple(sorted(set(artifact_ids), key=lambda item: item.bytes))),
                    _uuid_array_json(tuple(sorted(anchor_ids, key=str))),
                    _uuid_array_json(tuple(sorted(source_ids, key=str))),
                    created_at_us,
                ),
            )
            cursor = connection.execute(
                """
                UPDATE research_promotion_items
                SET state = 'accepted',
                    accepted_entity_id = ?,
                    accepted_revision_id = ?,
                    decided_at_us = ?
                WHERE proposal_id = ? AND state = 'pending'
                """,
                (
                    uuid_to_blob(entity_id),
                    uuid_to_blob(revision_id),
                    created_at_us,
                    uuid_to_blob(proposal_id),
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchPromotionError(
                    "Research proposal decision changed during acceptance."
                )
            self._refresh_set_state(connection, proposal.proposal_set_id, created_at_us)

        return ResearchPromotionAcceptance(
            proposal_id=proposal_id,
            entity_id=entity_id,
            revision_id=revision_id,
            commit_id=commit_id,
        )

    def reject(self, proposal_id: uuid.UUID) -> ResearchProposalRecord:
        now_us = utc_now_us()
        proposal = self._proposal(proposal_id)
        if proposal.state is ResearchProposalState.REJECTED:
            return proposal
        if proposal.state is not ResearchProposalState.PENDING:
            raise ResearchPromotionError("Only a pending Research proposal can be rejected.")
        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE research_promotion_items
                SET state = 'rejected', decided_at_us = ?
                WHERE proposal_id = ? AND state = 'pending'
                """,
                (now_us, uuid_to_blob(proposal_id)),
            )
            if cursor.rowcount != 1:
                raise ResearchPromotionError("Research proposal decision changed.")
            self._refresh_set_state(connection, proposal.proposal_set_id, now_us)
        return self._proposal(proposal_id)

    def _verify_source_artifact_lineage(
        self,
        artifact_ids: tuple[uuid.UUID, ...],
        *,
        expected_model_signature_id: uuid.UUID,
    ) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        anchor_ids: set[uuid.UUID] = set()
        source_ids: set[uuid.UUID] = set()
        for artifact_id in artifact_ids:
            artifact = self.source_analyses.get_artifact(artifact_id)
            if artifact.artifact_kind is not AnalysisStage.FINAL:
                raise ResearchPromotionError(
                    "Research promotion evidence must reference SourceAnalysis FINAL artifacts."
                )
            analysis = self.source_analyses.get_analysis(artifact.analysis_id)
            if (
                analysis.state is not SourceAnalysisState.COMPLETED
                or analysis.final_artifact_id != artifact_id
                or analysis.coverage != 1.0
            ):
                raise ResearchPromotionError(
                    "Research promotion evidence SourceAnalysis is not a complete final result."
                )
            if analysis.model_signature_id != expected_model_signature_id:
                raise ResearchPromotionError(
                    "Research promotion evidence crossed the pinned Research ModelSignature."
                )
            source_ids.add(analysis.source_id)
            artifact_anchor_ids = (
                self.source_analyses.source_anchor_ids_for_artifact(artifact_id)
            )
            if not artifact_anchor_ids:
                raise ResearchPromotionError(
                    "Research promotion SourceAnalysis FINAL artifact has no SourceAnchor provenance."
                )
            for anchor_id in artifact_anchor_ids:
                anchor = self.anchors.verify(anchor_id)
                if anchor.source_id != analysis.source_id:
                    raise ResearchPromotionError(
                        "Research proposal SourceAnchor crossed SourceAnalysis source scope."
                    )
                anchor_ids.add(anchor_id)
        if not anchor_ids:
            raise ResearchPromotionError(
                "Research proposal has no verified SourceAnchor provenance."
            )
        return anchor_ids, source_ids

    def _refresh_set_state(
        self,
        connection: sqlite3.Connection,
        proposal_set_id: uuid.UUID,
        now_us: int,
    ) -> None:
        row = connection.execute(
            """
            SELECT COUNT(*) AS pending
            FROM research_promotion_items
            WHERE proposal_set_id = ? AND state = 'pending'
            """,
            (uuid_to_blob(proposal_set_id),),
        ).fetchone()
        state = "completed" if row is not None and int(row["pending"]) == 0 else "pending"
        connection.execute(
            """
            UPDATE research_promotion_sets
            SET state = ?, updated_at_us = ?
            WHERE proposal_set_id = ?
            """,
            (state, now_us, uuid_to_blob(proposal_set_id)),
        )

    def _expected_proposal(
        self,
        *,
        proposal: ResearchProposalRecord,
        result: sqlite3.Row,
    ) -> tuple[dict[str, Any], tuple[uuid.UUID, ...]]:
        content_json = str(result["content_json"])
        if hashlib.sha256(content_json.encode("utf-8")).digest() != bytes(
            result["content_hash"]
        ):
            raise ResearchPromotionError("ResearchResult content hash verification failed.")
        content = _json_object(content_json, "ResearchResult content")
        contradictions = _string_list(content.get("contradictions"), "contradictions")
        final_artifact_id = (
            uuid_from_blob(bytes(result["final_artifact_id"]))
            if result["final_artifact_id"] is not None
            else None
        )
        if final_artifact_id is None:
            raise ResearchPromotionError("Research proposal lost its final synthesis artifact.")

        if proposal.evidence_kind == "summary":
            if (
                proposal.proposal_type is not ResearchProposalType.KNOWLEDGE
                or proposal.evidence_ordinal is not None
            ):
                raise ResearchPromotionError("Research summary proposal identity is invalid.")
            scope = self.research.get_scope(uuid_from_blob(bytes(result["scope_id"])))
            payload = {
                "knowledge_kind": KnowledgeKind.SUMMARY.value,
                "title": _research_title(scope.query_text),
                "body": _string_value(content.get("summary"), "summary"),
                "epistemic_status": (
                    EpistemicStatus.DISPUTED.value
                    if contradictions
                    else EpistemicStatus.SUPPORTED.value
                ),
            }
            artifacts = self.research.source_analysis_artifact_ids_for_synthesis_artifact(
                final_artifact_id
            )
        elif proposal.evidence_kind == "finding":
            if (
                proposal.proposal_type is not ResearchProposalType.CLAIM
                or proposal.evidence_ordinal is None
            ):
                raise ResearchPromotionError("Research finding proposal identity is invalid.")
            findings = _string_list(content.get("findings"), "findings")
            if proposal.evidence_ordinal >= len(findings):
                raise ResearchPromotionError("Research finding proposal ordinal is invalid.")
            payload = {
                "claim_kind": ClaimKind.OBSERVATION.value,
                "statement": findings[proposal.evidence_ordinal],
                "epistemic_status": (
                    EpistemicStatus.UNCERTAIN.value
                    if contradictions
                    else EpistemicStatus.SUPPORTED.value
                ),
            }
            artifacts = self.research.source_analysis_artifact_ids_for_synthesis_output(
                final_artifact_id,
                output_kind="finding",
                output_ordinal=proposal.evidence_ordinal,
            )
        elif proposal.evidence_kind == "contradiction":
            if (
                proposal.proposal_type is not ResearchProposalType.CONTRADICTION
                or proposal.evidence_ordinal is None
            ):
                raise ResearchPromotionError(
                    "Research contradiction proposal identity is invalid."
                )
            if proposal.evidence_ordinal >= len(contradictions):
                raise ResearchPromotionError(
                    "Research contradiction proposal ordinal is invalid."
                )
            payload = {"text": contradictions[proposal.evidence_ordinal]}
            artifacts = self.research.source_analysis_artifact_ids_for_synthesis_output(
                final_artifact_id,
                output_kind="contradiction",
                output_ordinal=proposal.evidence_ordinal,
            )
        else:
            raise ResearchPromotionError(
                f"Unsupported Research proposal evidence kind {proposal.evidence_kind!r}."
            )

        normalized = tuple(sorted(set(artifacts), key=lambda item: item.bytes))
        if not normalized:
            raise ResearchPromotionError("Research proposal has no durable source evidence.")
        return payload, normalized

    def _proposal(self, proposal_id: uuid.UUID) -> ResearchProposalRecord:
        row = self.database.connection.execute(
            "SELECT * FROM research_promotion_items WHERE proposal_id = ?",
            (uuid_to_blob(proposal_id),),
        ).fetchone()
        if row is None:
            raise ResearchPromotionError(f"Research proposal {proposal_id} not found.")
        return _proposal_from_row(row)

    def _get_set_for_result(
        self,
        result_id: uuid.UUID,
    ) -> ResearchProposalSetRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM research_promotion_sets WHERE result_id = ?",
            (uuid_to_blob(result_id),),
        ).fetchone()
        return None if row is None else _set_from_row(row)

    def _result_row(self, result_id: uuid.UUID) -> sqlite3.Row:
        row = self.database.connection.execute(
            """
            SELECT rr.*, rs.state AS scope_state
            FROM research_results AS rr
            JOIN research_scopes AS rs ON rs.scope_id = rr.scope_id
            WHERE rr.result_id = ?
            """,
            (uuid_to_blob(result_id),),
        ).fetchone()
        if row is None:
            raise ResearchPromotionError(f"ResearchResult {result_id} not found.")
        return cast(sqlite3.Row, row)


@dataclass(frozen=True, slots=True)
class _ResearchDedupCarrier:
    proposals: ExtractionProposalSet


def _dedup_proposals(
    proposal_type: ResearchProposalType,
    payload: dict[str, Any],
) -> ExtractionProposalSet:
    if proposal_type is ResearchProposalType.KNOWLEDGE:
        knowledge = ProposedKnowledgeUnit(
            source_sequence_no=1,
            source_quote="research-result-synthesis",
            knowledge_kind=KnowledgeKind(_required_string(payload, "knowledge_kind")),
            title=_optional_string(payload, "title"),
            body=_required_string(payload, "body"),
            epistemic_status=EpistemicStatus(
                _required_string(payload, "epistemic_status")
            ),
            confidence=1.0,
        )
        return ExtractionProposalSet(
            knowledge_units=(knowledge,),
            claims=(),
            relations=(),
            merge_candidates=(),
        )
    if proposal_type is ResearchProposalType.CLAIM:
        claim = ProposedClaim(
            source_sequence_no=1,
            source_quote="research-result-synthesis",
            claim_kind=ClaimKind(_required_string(payload, "claim_kind")),
            statement=_required_string(payload, "statement"),
            epistemic_status=EpistemicStatus(
                _required_string(payload, "epistemic_status")
            ),
            confidence=1.0,
        )
        return ExtractionProposalSet(
            knowledge_units=(),
            claims=(claim,),
            relations=(),
            merge_candidates=(),
        )
    raise ResearchPromotionError("Contradiction proposals are not canonical dedup candidates.")


def _set_from_row(row: sqlite3.Row) -> ResearchProposalSetRecord:
    return ResearchProposalSetRecord(
        proposal_set_id=uuid_from_blob(bytes(row["proposal_set_id"])),
        result_id=uuid_from_blob(bytes(row["result_id"])),
        result_content_hash=bytes(row["result_content_hash"]),
        state=str(row["state"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )


def _proposal_from_row(row: sqlite3.Row) -> ResearchProposalRecord:
    return ResearchProposalRecord(
        proposal_id=uuid_from_blob(bytes(row["proposal_id"])),
        proposal_set_id=uuid_from_blob(bytes(row["proposal_set_id"])),
        ordinal=int(row["ordinal"]),
        proposal_type=ResearchProposalType(str(row["proposal_type"])),
        payload_json=str(row["payload_json"]),
        evidence_kind=str(row["evidence_kind"]),
        evidence_ordinal=(
            int(row["evidence_ordinal"])
            if row["evidence_ordinal"] is not None
            else None
        ),
        source_analysis_artifact_ids_json=str(
            row["source_analysis_artifact_ids_json"]
        ),
        state=ResearchProposalState(str(row["state"])),
        accepted_entity_id=(
            uuid_from_blob(bytes(row["accepted_entity_id"]))
            if row["accepted_entity_id"] is not None
            else None
        ),
        accepted_revision_id=(
            uuid_from_blob(bytes(row["accepted_revision_id"]))
            if row["accepted_revision_id"] is not None
            else None
        ),
        created_at_us=int(row["created_at_us"]),
        decided_at_us=(
            int(row["decided_at_us"]) if row["decided_at_us"] is not None else None
        ),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _uuid_array_json(values: tuple[uuid.UUID, ...]) -> str:
    return _canonical_json([str(item) for item in values])


def _uuid_array(value: str, field: str) -> tuple[uuid.UUID, ...]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ResearchPromotionError(f"{field} is invalid JSON.") from exc
    if not isinstance(raw, list):
        raise ResearchPromotionError(f"{field} must be a JSON array.")
    try:
        result = tuple(uuid.UUID(item) for item in raw if isinstance(item, str))
    except ValueError as exc:
        raise ResearchPromotionError(f"{field} contains an invalid UUID.") from exc
    if len(result) != len(raw):
        raise ResearchPromotionError(f"{field} contains a non-string UUID.")
    return result


def _json_object(value: str, field: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ResearchPromotionError(f"{field} is invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ResearchPromotionError(f"{field} must be a JSON object.")
    return parsed


def _string_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchPromotionError(f"ResearchResult {field} must be non-empty text.")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ResearchPromotionError(f"ResearchResult {field} must be a string array.")
    return [item.strip() for item in value]


def _required_string(value: dict[str, Any], field: str) -> str:
    return _string_value(value.get(field), field)


def _optional_string(value: dict[str, Any], field: str) -> str | None:
    raw = value.get(field)
    if raw is None:
        return None
    return _string_value(raw, field)


def _research_title(query: str) -> str:
    normalized = " ".join(query.split())
    return f"Research: {normalized[:120]}"
