"""Canonical domain types for ATHENA Knowledge and Claims."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class KnowledgeKind(str, Enum):
    """Core v1 Knowledge kinds; storage remains text-extensible."""

    CONCEPT = "concept"
    FACT = "fact"
    DECISION = "decision"
    GOAL = "goal"
    IDEA = "idea"
    EXPERIENCE = "experience"
    PROCEDURE = "procedure"
    EVENT = "event"
    PROJECT_KNOWLEDGE = "project_knowledge"
    SUMMARY = "summary"
    OTHER = "other"


class ClaimKind(str, Enum):
    """Core v1 Claim kinds."""

    FACTUAL_ASSERTION = "factual_assertion"
    ATTRIBUTED_OPINION = "attributed_opinion"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    INTENTION = "intention"
    DEFINITION = "definition"
    OBSERVATION = "observation"
    EVENT_ASSERTION = "event_assertion"
    USER_STATEMENT = "user_statement"
    OTHER = "other"


class EpistemicStatus(str, Enum):
    """Versionable epistemic state; deliberately not a truth boolean."""

    ASSERTED = "asserted"
    SUPPORTED = "supported"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"


class EvidenceRole(str, Enum):
    """Semantic role of an evidence link."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    MENTIONS = "mentions"
    CONTEXTUALIZES = "contextualizes"
    ORIGINATES = "originates"


def _validate_temporal_range(valid_from_us: int | None, valid_to_us: int | None) -> None:
    if valid_from_us is not None and valid_to_us is not None and valid_to_us < valid_from_us:
        raise ValueError("valid_to_us must be greater than or equal to valid_from_us.")


def _require_meaningful_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


@dataclass(frozen=True, slots=True)
class KnowledgeUnitDraft:
    """Unprotected canonical KnowledgeUnit content proposed for one revision."""

    knowledge_kind: KnowledgeKind
    body: str
    title: str | None = None
    valid_from_us: int | None = None
    valid_to_us: int | None = None
    epistemic_status: EpistemicStatus = EpistemicStatus.ASSERTED

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", _require_meaningful_text(self.body, field_name="body"))
        if self.title is not None:
            title = self.title.strip()
            object.__setattr__(self, "title", title or None)
        _validate_temporal_range(self.valid_from_us, self.valid_to_us)


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    """Unprotected Claim content proposed for one canonical revision."""

    claim_kind: ClaimKind
    statement: str
    epistemic_status: EpistemicStatus = EpistemicStatus.ASSERTED
    subject_entity_id: uuid.UUID | None = None
    predicate: str | None = None
    object_entity_id: uuid.UUID | None = None
    attributed_to_entity_id: uuid.UUID | None = None
    valid_from_us: int | None = None
    valid_to_us: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "statement",
            _require_meaningful_text(self.statement, field_name="statement"),
        )
        if self.predicate is not None:
            predicate = self.predicate.strip()
            object.__setattr__(self, "predicate", predicate or None)
        _validate_temporal_range(self.valid_from_us, self.valid_to_us)

        if self.claim_kind is ClaimKind.ATTRIBUTED_OPINION and self.attributed_to_entity_id is None:
            raise ValueError("Attributed opinions require attributed_to_entity_id.")


@dataclass(frozen=True, slots=True)
class KnowledgeUnitRevision:
    knowledge_id: uuid.UUID
    revision_id: uuid.UUID
    revision_no: int
    created_at_us: int
    created_by_actor_id: uuid.UUID
    provenance_id: uuid.UUID
    payload: KnowledgeUnitDraft

    def __post_init__(self) -> None:
        if self.revision_no < 1:
            raise ValueError("revision_no must be at least 1.")


@dataclass(frozen=True, slots=True)
class KnowledgeUnitSnapshot:
    """Current canonical state of one stable KnowledgeUnit entity."""

    knowledge_id: uuid.UUID
    lifecycle_state: str
    revision: KnowledgeUnitRevision


@dataclass(frozen=True, slots=True)
class ProvenanceInputRef:
    """Stable input reference that explains one semantic revision."""

    provenance_id: uuid.UUID
    input_entity_id: uuid.UUID
    input_revision_id: uuid.UUID | None
    input_role: str
    ordinal: int

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ordinal must not be negative.")
        object.__setattr__(
            self,
            "input_role",
            _require_meaningful_text(self.input_role, field_name="input_role"),
        )


@dataclass(frozen=True, slots=True)
class ClaimRevision:
    claim_id: uuid.UUID
    revision_id: uuid.UUID
    revision_no: int
    created_at_us: int
    created_by_actor_id: uuid.UUID
    provenance_id: uuid.UUID
    payload: ClaimDraft

    def __post_init__(self) -> None:
        if self.revision_no < 1:
            raise ValueError("revision_no must be at least 1.")


@dataclass(frozen=True, slots=True)
class ClaimSnapshot:
    """Current canonical state of one stable Claim entity."""

    claim_id: uuid.UUID
    lifecycle_state: str
    revision: ClaimRevision


@dataclass(frozen=True, slots=True)
class ClaimEvidenceRef:
    """One concrete evidence reference for a Claim."""

    evidence_role: EvidenceRole
    provenance_id: uuid.UUID
    anchor_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    evidence_entity_id: uuid.UUID | None = None
    evidence_revision_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not any(
            (
                self.anchor_id,
                self.message_id,
                self.evidence_entity_id,
                self.evidence_revision_id,
            )
        ):
            raise ValueError("Claim evidence requires at least one concrete evidence reference.")
