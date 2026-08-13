"""Deterministic canonical deduplication and conservative merge-candidate detection."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from typing import Protocol

from athena.common.ids import uuid_from_blob
from athena.knowledge.extraction_models import ExtractionProposalSet, ProposalEntityType


class ExtractionProposalCarrier(Protocol):
    """Minimal result contract required by canonical deduplication."""

    @property
    def proposals(self) -> ExtractionProposalSet:
        """Return the immutable proposal set exposed by an extraction result."""
        ...


class DedupAction(str, Enum):
    """Action for one proposal after canonical deduplication preflight."""

    CREATE = "create"
    REUSE_CANONICAL = "reuse_canonical"
    REUSE_PROPOSAL = "reuse_proposal"


@dataclass(frozen=True, slots=True)
class DedupDecision:
    proposal_type: ProposalEntityType
    proposal_index: int
    action: DedupAction
    existing_entity_id: uuid.UUID | None = None
    existing_revision_id: uuid.UUID | None = None
    duplicate_of_proposal_index: int | None = None


@dataclass(frozen=True, slots=True)
class CanonicalMergeCandidate:
    proposal_type: ProposalEntityType
    proposal_index: int
    existing_entity_id: uuid.UUID
    existing_revision_id: uuid.UUID
    similarity: float
    reason: str


@dataclass(frozen=True, slots=True)
class DeduplicationPlan:
    knowledge: tuple[DedupDecision, ...]
    claims: tuple[DedupDecision, ...]
    merge_candidates: tuple[CanonicalMergeCandidate, ...]

    @property
    def has_unresolved_merge_candidates(self) -> bool:
        return bool(self.merge_candidates)


_PUNCT_OR_SYMBOL = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_semantic_text(value: str) -> str:
    """Normalize harmless textual variation without changing word identity."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = _PUNCT_OR_SYMBOL.sub(" ", value)
    return _SPACE.sub(" ", value).strip()


def _text_similarity(left: str, right: str) -> float:
    left_n = normalize_semantic_text(left)
    right_n = normalize_semantic_text(right)
    if not left_n or not right_n:
        return 0.0
    if left_n == right_n:
        return 1.0
    sequence = SequenceMatcher(a=left_n, b=right_n, autojunk=False).ratio()
    left_tokens = set(left_n.split())
    right_tokens = set(right_n.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return max(sequence, jaccard)


class CanonicalDeduplicationService:
    """Build a fail-closed deduplication plan against current canonical state."""

    NEAR_DUPLICATE_THRESHOLD = 0.93

    @classmethod
    def plan(
        cls,
        connection: sqlite3.Connection,
        result: ExtractionProposalCarrier,
    ) -> DeduplicationPlan:
        knowledge_rows = cls._knowledge_rows(connection)
        claim_rows = cls._claim_rows(connection)

        knowledge_decisions: list[DedupDecision] = []
        claim_decisions: list[DedupDecision] = []
        merge_candidates: list[CanonicalMergeCandidate] = []

        prior_knowledge: list[tuple[int, str, str, str]] = []
        for index, knowledge_proposal in enumerate(result.proposals.knowledge_units):
            exact = next(
                (
                    row
                    for row in knowledge_rows
                    if row["knowledge_kind"] == knowledge_proposal.knowledge_kind.value
                    and row["epistemic_status"] == knowledge_proposal.epistemic_status.value
                    and normalize_semantic_text(str(row["body"]))
                    == normalize_semantic_text(knowledge_proposal.body)
                    and row["valid_from_us"] is None
                    and row["valid_to_us"] is None
                ),
                None,
            )
            if exact is not None:
                knowledge_decisions.append(
                    DedupDecision(
                        proposal_type=ProposalEntityType.KNOWLEDGE,
                        proposal_index=index,
                        action=DedupAction.REUSE_CANONICAL,
                        existing_entity_id=uuid_from_blob(bytes(exact["entity_id"])),
                        existing_revision_id=uuid_from_blob(bytes(exact["revision_id"])),
                    )
                )
                prior_knowledge.append(
                    (
                        index,
                        knowledge_proposal.knowledge_kind.value,
                        knowledge_proposal.epistemic_status.value,
                        knowledge_proposal.body,
                    )
                )
                continue

            prior_exact = next(
                (
                    prior_index
                    for prior_index, kind, status, body in prior_knowledge
                    if kind == knowledge_proposal.knowledge_kind.value
                    and status == knowledge_proposal.epistemic_status.value
                    and normalize_semantic_text(body) == normalize_semantic_text(knowledge_proposal.body)
                ),
                None,
            )
            if prior_exact is not None:
                knowledge_decisions.append(
                    DedupDecision(
                        proposal_type=ProposalEntityType.KNOWLEDGE,
                        proposal_index=index,
                        action=DedupAction.REUSE_PROPOSAL,
                        duplicate_of_proposal_index=prior_exact,
                    )
                )
                prior_knowledge.append(
                    (
                        index,
                        knowledge_proposal.knowledge_kind.value,
                        knowledge_proposal.epistemic_status.value,
                        knowledge_proposal.body,
                    )
                )
                continue

            knowledge_decisions.append(
                DedupDecision(
                    proposal_type=ProposalEntityType.KNOWLEDGE,
                    proposal_index=index,
                    action=DedupAction.CREATE,
                )
            )
            prior_knowledge.append(
                (
                    index,
                    knowledge_proposal.knowledge_kind.value,
                    knowledge_proposal.epistemic_status.value,
                    knowledge_proposal.body,
                )
            )

            for row in knowledge_rows:
                if row["knowledge_kind"] != knowledge_proposal.knowledge_kind.value:
                    continue
                similarity = _text_similarity(knowledge_proposal.body, str(row["body"]))
                if cls.NEAR_DUPLICATE_THRESHOLD <= similarity < 1.0:
                    merge_candidates.append(
                        CanonicalMergeCandidate(
                            proposal_type=ProposalEntityType.KNOWLEDGE,
                            proposal_index=index,
                            existing_entity_id=uuid_from_blob(bytes(row["entity_id"])),
                            existing_revision_id=uuid_from_blob(bytes(row["revision_id"])),
                            similarity=similarity,
                            reason="possible textual near-duplicate of canonical Knowledge",
                        )
                    )

        contradicted_pairs = {
            tuple(sorted((relation.left_index, relation.right_index)))
            for relation in result.proposals.relations
            if relation.relation_type == "contradicts"
            and relation.left_type is ProposalEntityType.CLAIM
            and relation.right_type is ProposalEntityType.CLAIM
        }

        prior_claims: list[tuple[int, str, str, str]] = []
        for index, claim_proposal in enumerate(result.proposals.claims):
            exact = next(
                (
                    row
                    for row in claim_rows
                    if row["claim_kind"] == claim_proposal.claim_kind.value
                    and row["epistemic_status"] == claim_proposal.epistemic_status.value
                    and normalize_semantic_text(str(row["statement"]))
                    == normalize_semantic_text(claim_proposal.statement)
                    and row["valid_from_us"] is None
                    and row["valid_to_us"] is None
                    and row["subject_entity_id"] is None
                    and row["object_entity_id"] is None
                    and row["attributed_to_entity_id"] is None
                    and row["predicate"] is None
                ),
                None,
            )
            if exact is not None:
                claim_decisions.append(
                    DedupDecision(
                        proposal_type=ProposalEntityType.CLAIM,
                        proposal_index=index,
                        action=DedupAction.REUSE_CANONICAL,
                        existing_entity_id=uuid_from_blob(bytes(exact["entity_id"])),
                        existing_revision_id=uuid_from_blob(bytes(exact["revision_id"])),
                    )
                )
                prior_claims.append(
                    (
                        index,
                        claim_proposal.claim_kind.value,
                        claim_proposal.epistemic_status.value,
                        claim_proposal.statement,
                    )
                )
                continue

            prior_exact = next(
                (
                    prior_index
                    for prior_index, kind, status, statement in prior_claims
                    if kind == claim_proposal.claim_kind.value
                    and status == claim_proposal.epistemic_status.value
                    and normalize_semantic_text(statement)
                    == normalize_semantic_text(claim_proposal.statement)
                ),
                None,
            )
            if prior_exact is not None:
                claim_decisions.append(
                    DedupDecision(
                        proposal_type=ProposalEntityType.CLAIM,
                        proposal_index=index,
                        action=DedupAction.REUSE_PROPOSAL,
                        duplicate_of_proposal_index=prior_exact,
                    )
                )
                prior_claims.append(
                    (
                        index,
                        claim_proposal.claim_kind.value,
                        claim_proposal.epistemic_status.value,
                        claim_proposal.statement,
                    )
                )
                continue

            claim_decisions.append(
                DedupDecision(
                    proposal_type=ProposalEntityType.CLAIM,
                    proposal_index=index,
                    action=DedupAction.CREATE,
                )
            )

            for row in claim_rows:
                if row["claim_kind"] != claim_proposal.claim_kind.value:
                    continue
                similarity = _text_similarity(claim_proposal.statement, str(row["statement"]))
                if cls.NEAR_DUPLICATE_THRESHOLD <= similarity < 1.0:
                    merge_candidates.append(
                        CanonicalMergeCandidate(
                            proposal_type=ProposalEntityType.CLAIM,
                            proposal_index=index,
                            existing_entity_id=uuid_from_blob(bytes(row["entity_id"])),
                            existing_revision_id=uuid_from_blob(bytes(row["revision_id"])),
                            similarity=similarity,
                            reason="possible textual near-duplicate of canonical Claim",
                        )
                    )

            for prior_index, kind, _status, statement in prior_claims:
                if kind != claim_proposal.claim_kind.value:
                    continue
                if tuple(sorted((prior_index, index))) in contradicted_pairs:
                    continue
                similarity = _text_similarity(claim_proposal.statement, statement)
                if cls.NEAR_DUPLICATE_THRESHOLD <= similarity < 1.0:
                    # There is no canonical entity yet, so this is deliberately not auto-merged.
                    # The duplicate is surfaced by blocking acceptance through the extractor's
                    # own merge-candidate path in a later semantic merge step.
                    pass

            prior_claims.append(
                (
                    index,
                    claim_proposal.claim_kind.value,
                    claim_proposal.epistemic_status.value,
                    claim_proposal.statement,
                )
            )

        # Stable deterministic order and at most one candidate per proposal/entity pair.
        unique: dict[tuple[str, int, uuid.UUID], CanonicalMergeCandidate] = {}
        for candidate in merge_candidates:
            key = (
                candidate.proposal_type.value,
                candidate.proposal_index,
                candidate.existing_entity_id,
            )
            previous = unique.get(key)
            if previous is None or candidate.similarity > previous.similarity:
                unique[key] = candidate

        ordered = tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.proposal_type.value,
                    item.proposal_index,
                    -item.similarity,
                    str(item.existing_entity_id),
                ),
            )
        )
        return DeduplicationPlan(
            knowledge=tuple(knowledge_decisions),
            claims=tuple(claim_decisions),
            merge_candidates=ordered,
        )

    @staticmethod
    def _knowledge_rows(connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                """
                SELECT
                    k.knowledge_id AS entity_id,
                    h.current_revision_id AS revision_id,
                    kr.knowledge_kind,
                    kr.body,
                    kr.valid_from_us,
                    kr.valid_to_us,
                    kr.epistemic_status
                FROM knowledge_units AS k
                JOIN entity_registry AS e ON e.entity_id = k.knowledge_id
                JOIN entity_heads AS h ON h.entity_id = k.knowledge_id
                JOIN knowledge_unit_revisions AS kr ON kr.revision_id = h.current_revision_id
                WHERE e.lifecycle_state = 'active'
                """
            ).fetchall()
        )

    @staticmethod
    def _claim_rows(connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                """
                SELECT
                    c.claim_id AS entity_id,
                    h.current_revision_id AS revision_id,
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
                JOIN claim_revisions AS cr ON cr.revision_id = h.current_revision_id
                WHERE e.lifecycle_state = 'active'
                """
            ).fetchall()
        )
