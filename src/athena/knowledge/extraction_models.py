"""Structured proposal types for Primary Model knowledge extraction."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Any, TypeVar

from athena.knowledge.models import ClaimKind, EpistemicStatus, KnowledgeKind
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelSignature, ProcessingRun

EnumT = TypeVar("EnumT", bound=Enum)


class ExtractionValidationError(ValueError):
    """Raised when model output does not satisfy ATHENA's extraction contract."""


class ProposalEntityType(str, Enum):
    KNOWLEDGE = "knowledge"
    CLAIM = "claim"


class ClaimPairRelationship(str, Enum):
    CONTRADICTS = "contradicts"
    COMPATIBLE_OR_UNKNOWN = "compatible_or_unknown"


@dataclass(frozen=True, slots=True)
class ProposedKnowledgeUnit:
    source_sequence_no: int
    source_quote: str
    knowledge_kind: KnowledgeKind
    title: str | None
    body: str
    epistemic_status: EpistemicStatus
    confidence: float


@dataclass(frozen=True, slots=True)
class ProposedClaim:
    source_sequence_no: int
    source_quote: str
    claim_kind: ClaimKind
    statement: str
    epistemic_status: EpistemicStatus
    confidence: float


@dataclass(frozen=True, slots=True)
class ProposedRelation:
    left_type: ProposalEntityType
    left_index: int
    relation_type: str
    right_type: ProposalEntityType
    right_index: int
    confidence: float


@dataclass(frozen=True, slots=True)
class MergeCandidate:
    proposal_type: ProposalEntityType
    proposal_index: int
    reason: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ClaimPairAssessment:
    left_claim_index: int
    right_claim_index: int
    relationship: ClaimPairRelationship
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class ExtractionProposalSet:
    knowledge_units: tuple[ProposedKnowledgeUnit, ...]
    claims: tuple[ProposedClaim, ...]
    relations: tuple[ProposedRelation, ...]
    merge_candidates: tuple[MergeCandidate, ...]


@dataclass(frozen=True, slots=True)
class ChatExtractionResult:
    chat_id: uuid.UUID
    model: ModelInfo
    model_signature: ModelSignature
    processing_run: ProcessingRun
    proposals: ExtractionProposalSet


EXTRACTION_SCHEMA_ID = "athena_chat_knowledge_extraction_v2"
CONTRADICTION_AUDIT_SCHEMA_ID = "athena_claim_pair_audit_v1"


def extraction_json_schema() -> dict[str, Any]:
    """Return the provider-facing JSON schema for grounded extraction proposals."""
    epistemic_values = [item.value for item in EpistemicStatus]
    knowledge_values = [item.value for item in KnowledgeKind]
    claim_values = [
        item.value
        for item in ClaimKind
        if item is not ClaimKind.ATTRIBUTED_OPINION
    ]
    entity_types = [item.value for item in ProposalEntityType]
    confidence = {"type": "number", "minimum": 0.0, "maximum": 1.0}

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "knowledge_units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_sequence_no": {"type": "integer", "minimum": 1},
                        "source_quote": {"type": "string", "minLength": 1},
                        "knowledge_kind": {"type": "string", "enum": knowledge_values},
                        "title": {"type": ["string", "null"]},
                        "body": {"type": "string", "minLength": 1},
                        "epistemic_status": {
                            "type": "string",
                            "enum": epistemic_values,
                        },
                        "confidence": confidence,
                    },
                    "required": [
                        "source_sequence_no",
                        "source_quote",
                        "knowledge_kind",
                        "title",
                        "body",
                        "epistemic_status",
                        "confidence",
                    ],
                },
            },
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_sequence_no": {"type": "integer", "minimum": 1},
                        "source_quote": {"type": "string", "minLength": 1},
                        "claim_kind": {"type": "string", "enum": claim_values},
                        "statement": {"type": "string", "minLength": 1},
                        "epistemic_status": {
                            "type": "string",
                            "enum": epistemic_values,
                        },
                        "confidence": confidence,
                    },
                    "required": [
                        "source_sequence_no",
                        "source_quote",
                        "claim_kind",
                        "statement",
                        "epistemic_status",
                        "confidence",
                    ],
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "left_type": {"type": "string", "enum": entity_types},
                        "left_index": {"type": "integer", "minimum": 0},
                        "relation_type": {"type": "string", "minLength": 1},
                        "right_type": {"type": "string", "enum": entity_types},
                        "right_index": {"type": "integer", "minimum": 0},
                        "confidence": confidence,
                    },
                    "required": [
                        "left_type",
                        "left_index",
                        "relation_type",
                        "right_type",
                        "right_index",
                        "confidence",
                    ],
                },
            },
            "merge_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "proposal_type": {"type": "string", "enum": entity_types},
                        "proposal_index": {"type": "integer", "minimum": 0},
                        "reason": {"type": "string", "minLength": 1},
                        "confidence": confidence,
                    },
                    "required": [
                        "proposal_type",
                        "proposal_index",
                        "reason",
                        "confidence",
                    ],
                },
            },
        },
        "required": ["knowledge_units", "claims", "relations", "merge_candidates"],
    }


def contradiction_audit_json_schema(*, claim_count: int) -> dict[str, Any]:
    """Require one explicit consistency assessment for every unordered claim pair."""
    if claim_count < 2:
        raise ValueError("claim_count must be at least 2 for contradiction audit.")
    confidence = {"type": "number", "minimum": 0.0, "maximum": 1.0}
    relationships = [item.value for item in ClaimPairRelationship]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "assessments": {
                "type": "array",
                "minItems": claim_count * (claim_count - 1) // 2,
                "maxItems": claim_count * (claim_count - 1) // 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "left_claim_index": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": claim_count - 1,
                        },
                        "right_claim_index": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": claim_count - 1,
                        },
                        "relationship": {"type": "string", "enum": relationships},
                        "confidence": confidence,
                        "reason": {"type": "string", "minLength": 1},
                    },
                    "required": [
                        "left_claim_index",
                        "right_claim_index",
                        "relationship",
                        "confidence",
                        "reason",
                    ],
                },
            }
        },
        "required": ["assessments"],
    }


def parse_extraction_proposals(
    payload: Mapping[str, Any],
    *,
    source_messages: Mapping[int, str],
) -> ExtractionProposalSet:
    """Independently validate provider output before any canonical write exists."""
    _require_exact_keys(
        payload,
        {"knowledge_units", "claims", "relations", "merge_candidates"},
        "extraction root",
    )
    knowledge_raw = _require_list(payload, "knowledge_units")
    claims_raw = _require_list(payload, "claims")
    relations_raw = _require_list(payload, "relations")
    merges_raw = _require_list(payload, "merge_candidates")

    knowledge = tuple(
        _parse_knowledge(item, source_messages=source_messages)
        for item in knowledge_raw
    )
    claims = tuple(_parse_claim(item, source_messages=source_messages) for item in claims_raw)
    relations = tuple(_parse_relation(item) for item in relations_raw)
    merges = tuple(_parse_merge(item) for item in merges_raw)

    proposal_set = ExtractionProposalSet(
        knowledge_units=knowledge,
        claims=claims,
        relations=relations,
        merge_candidates=merges,
    )
    _validate_proposal_references(proposal_set)
    return proposal_set


def parse_claim_pair_audit(
    payload: Mapping[str, Any],
    *,
    claim_count: int,
) -> tuple[ClaimPairAssessment, ...]:
    """Validate that every unordered claim pair received exactly one assessment."""
    if claim_count < 2:
        raise ValueError("claim_count must be at least 2 for contradiction audit.")
    _require_exact_keys(payload, {"assessments"}, "claim-pair audit root")
    raw_items = _require_list(payload, "assessments")
    assessments: list[ClaimPairAssessment] = []
    seen: set[tuple[int, int]] = set()

    for value in raw_items:
        item = _require_mapping(value, "claim-pair assessment")
        _require_exact_keys(
            item,
            {
                "left_claim_index",
                "right_claim_index",
                "relationship",
                "confidence",
                "reason",
            },
            "claim-pair assessment",
        )
        left = _nonnegative_int(item["left_claim_index"], "left_claim_index")
        right = _nonnegative_int(item["right_claim_index"], "right_claim_index")
        if left >= claim_count or right >= claim_count:
            raise ExtractionValidationError("claim-pair assessment references no claim.")
        if left >= right:
            raise ExtractionValidationError(
                "claim-pair assessment must use canonical left_claim_index < right_claim_index."
            )
        pair = (left, right)
        if pair in seen:
            raise ExtractionValidationError("claim-pair audit contains a duplicate pair.")
        seen.add(pair)
        assessments.append(
            ClaimPairAssessment(
                left_claim_index=left,
                right_claim_index=right,
                relationship=_enum_value(
                    ClaimPairRelationship,
                    item["relationship"],
                    "relationship",
                ),
                confidence=_confidence(item["confidence"]),
                reason=_text(item["reason"], "claim-pair reason"),
            )
        )

    expected = set(combinations(range(claim_count), 2))
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise ExtractionValidationError(
            f"claim-pair audit must classify every unordered pair exactly once; "
            f"missing={missing}, extra={extra}."
        )
    return tuple(assessments)


def apply_claim_pair_audit(
    proposals: ExtractionProposalSet,
    assessments: tuple[ClaimPairAssessment, ...],
) -> ExtractionProposalSet:
    """Add audited contradiction proposals without creating canonical relations."""
    relations = list(proposals.relations)
    existing = {
        (relation.left_type, relation.left_index, relation.relation_type, relation.right_type, relation.right_index)
        for relation in relations
    }
    for assessment in assessments:
        if assessment.relationship is not ClaimPairRelationship.CONTRADICTS:
            continue
        key = (
            ProposalEntityType.CLAIM,
            assessment.left_claim_index,
            "contradicts",
            ProposalEntityType.CLAIM,
            assessment.right_claim_index,
        )
        if key in existing:
            continue
        relations.append(
            ProposedRelation(
                left_type=ProposalEntityType.CLAIM,
                left_index=assessment.left_claim_index,
                relation_type="contradicts",
                right_type=ProposalEntityType.CLAIM,
                right_index=assessment.right_claim_index,
                confidence=assessment.confidence,
            )
        )
        existing.add(key)
    return ExtractionProposalSet(
        knowledge_units=proposals.knowledge_units,
        claims=proposals.claims,
        relations=tuple(relations),
        merge_candidates=proposals.merge_candidates,
    )


def _parse_knowledge(
    value: object,
    *,
    source_messages: Mapping[int, str],
) -> ProposedKnowledgeUnit:
    item = _require_mapping(value, "knowledge proposal")
    _require_exact_keys(
        item,
        {
            "source_sequence_no",
            "source_quote",
            "knowledge_kind",
            "title",
            "body",
            "epistemic_status",
            "confidence",
        },
        "knowledge proposal",
    )
    source_sequence_no = _source_sequence(item, set(source_messages))
    title_raw = item["title"]
    if title_raw is not None and not isinstance(title_raw, str):
        raise ExtractionValidationError("knowledge title must be text or null.")
    title = title_raw.strip() if isinstance(title_raw, str) else None
    if title == "":
        title = None
    return ProposedKnowledgeUnit(
        source_sequence_no=source_sequence_no,
        source_quote=_source_quote(item, source_sequence_no, source_messages),
        knowledge_kind=_enum_value(KnowledgeKind, item["knowledge_kind"], "knowledge_kind"),
        title=title,
        body=_text(item["body"], "knowledge body"),
        epistemic_status=_enum_value(
            EpistemicStatus,
            item["epistemic_status"],
            "epistemic_status",
        ),
        confidence=_confidence(item["confidence"]),
    )


def _parse_claim(
    value: object,
    *,
    source_messages: Mapping[int, str],
) -> ProposedClaim:
    item = _require_mapping(value, "claim proposal")
    _require_exact_keys(
        item,
        {
            "source_sequence_no",
            "source_quote",
            "claim_kind",
            "statement",
            "epistemic_status",
            "confidence",
        },
        "claim proposal",
    )
    source_sequence_no = _source_sequence(item, set(source_messages))
    claim_kind = _enum_value(ClaimKind, item["claim_kind"], "claim_kind")
    if claim_kind is ClaimKind.ATTRIBUTED_OPINION:
        raise ExtractionValidationError(
            "attributed_opinion is unavailable to Primary Model extraction until "
            "ATHENA can bind and independently validate an attributed entity."
        )
    return ProposedClaim(
        source_sequence_no=source_sequence_no,
        source_quote=_source_quote(item, source_sequence_no, source_messages),
        claim_kind=claim_kind,
        statement=_text(item["statement"], "claim statement"),
        epistemic_status=_enum_value(
            EpistemicStatus,
            item["epistemic_status"],
            "epistemic_status",
        ),
        confidence=_confidence(item["confidence"]),
    )


def _parse_relation(value: object) -> ProposedRelation:
    item = _require_mapping(value, "relation proposal")
    _require_exact_keys(
        item,
        {
            "left_type",
            "left_index",
            "relation_type",
            "right_type",
            "right_index",
            "confidence",
        },
        "relation proposal",
    )
    return ProposedRelation(
        left_type=_enum_value(ProposalEntityType, item["left_type"], "left_type"),
        left_index=_nonnegative_int(item["left_index"], "left_index"),
        relation_type=_text(item["relation_type"], "relation_type"),
        right_type=_enum_value(ProposalEntityType, item["right_type"], "right_type"),
        right_index=_nonnegative_int(item["right_index"], "right_index"),
        confidence=_confidence(item["confidence"]),
    )


def _parse_merge(value: object) -> MergeCandidate:
    item = _require_mapping(value, "merge candidate")
    _require_exact_keys(
        item,
        {"proposal_type", "proposal_index", "reason", "confidence"},
        "merge candidate",
    )
    return MergeCandidate(
        proposal_type=_enum_value(ProposalEntityType, item["proposal_type"], "proposal_type"),
        proposal_index=_nonnegative_int(item["proposal_index"], "proposal_index"),
        reason=_text(item["reason"], "merge reason"),
        confidence=_confidence(item["confidence"]),
    )


def _validate_proposal_references(proposals: ExtractionProposalSet) -> None:
    def count(entity_type: ProposalEntityType) -> int:
        if entity_type is ProposalEntityType.KNOWLEDGE:
            return len(proposals.knowledge_units)
        return len(proposals.claims)

    for relation in proposals.relations:
        if relation.left_index >= count(relation.left_type):
            raise ExtractionValidationError("relation left_index references no proposal.")
        if relation.right_index >= count(relation.right_type):
            raise ExtractionValidationError("relation right_index references no proposal.")
        if relation.left_type is relation.right_type and relation.left_index == relation.right_index:
            raise ExtractionValidationError("relation cannot reference the same proposal twice.")

    for candidate in proposals.merge_candidates:
        if candidate.proposal_index >= count(candidate.proposal_type):
            raise ExtractionValidationError("merge candidate references no proposal.")


def _source_sequence(item: Mapping[str, Any], valid_source_sequences: set[int]) -> int:
    sequence = _positive_int(item["source_sequence_no"], "source_sequence_no")
    if sequence not in valid_source_sequences:
        raise ExtractionValidationError(
            f"source_sequence_no {sequence} does not exist in the supplied chat snapshot."
        )
    return sequence


def _source_quote(
    item: Mapping[str, Any],
    sequence: int,
    source_messages: Mapping[int, str],
) -> str:
    quote = _text(item["source_quote"], "source_quote")
    source = source_messages[sequence]
    if quote not in source:
        raise ExtractionValidationError(
            f"source_quote for sequence {sequence} is not an exact contiguous quote "
            "from the cited chat message."
        )
    return quote


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtractionValidationError(f"{label} must be an object.")
    return value


def _require_list(mapping: Mapping[str, Any], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise ExtractionValidationError(f"{key} must be an array.")
    return value


def _require_exact_keys(
    mapping: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(mapping)
    if actual != expected:
        raise ExtractionValidationError(
            f"{label} keys must be exactly {sorted(expected)!r}; got {sorted(actual)!r}."
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ExtractionValidationError(f"{label} must be text.")
    normalized = value.strip()
    if not normalized:
        raise ExtractionValidationError(f"{label} must not be empty.")
    return normalized


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ExtractionValidationError(f"{label} must be a positive integer.")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExtractionValidationError(f"{label} must be a non-negative integer.")
    return value


def _confidence(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ExtractionValidationError("confidence must be numeric.")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ExtractionValidationError("confidence must be between 0.0 and 1.0.")
    return result


def _enum_value(enum_type: type[EnumT], value: object, label: str) -> EnumT:
    if not isinstance(value, str):
        raise ExtractionValidationError(f"{label} must be text.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ExtractionValidationError(
            f"Invalid {label} {value!r}; expected one of: {allowed}."
        ) from exc
