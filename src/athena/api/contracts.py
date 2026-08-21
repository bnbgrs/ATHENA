"""Versioned transport-neutral contracts exposed to ATHENA clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import cast

# Python 3.12 does not expose a stdlib JsonValue alias. Keep the public
# contracts explicit and serializable without leaking domain objects.
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

API_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ApiContract:
    """Mixin for immutable client DTOs with a JSON-safe representation."""

    def to_dict(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], _json_safe(asdict(self)))


def _json_safe(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("API contract dictionaries require string keys.")
            result[key] = _json_safe(item)
        return result
    raise TypeError(f"Unsupported API contract value: {type(value).__name__}.")


@dataclass(frozen=True, slots=True)
class HealthResponse(ApiContract):
    api_version: str
    core_status: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class CapabilitiesResponse(ApiContract):
    api_version: str
    features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatSummaryResponse(ApiContract):
    chat_id: str
    started_at_us: int
    ended_at_us: int | None
    archive_mode: str
    lifecycle_state: str
    message_count: int


@dataclass(frozen=True, slots=True)
class ChatMessageResponse(ApiContract):
    message_id: str
    chat_id: str
    sequence_no: int
    message_type: str
    actor_id: str | None
    created_at_us: int
    revision_id: str
    content: str | None
    content_format: str | None


@dataclass(frozen=True, slots=True)
class ChatThreadResponse(ApiContract):
    chat_id: str
    started_at_us: int
    ended_at_us: int | None
    archive_mode: str
    lifecycle_state: str
    messages: tuple[ChatMessageResponse, ...]


@dataclass(frozen=True, slots=True)
class GroundedEvidenceResponse(ApiContract):
    """One typed CTX evidence item behind a grounded assistant answer."""

    context_id: str
    evidence_class: str
    entity_type: str
    entity_id: str
    revision_id: str | None
    title: str | None
    text: str
    cited: bool
    epistemic_status: str | None
    source_id: str | None
    representation_id: str | None
    source_name: str | None
    source_uri: str | None
    start_offset: int | None
    end_offset: int | None
    page_start: int | None
    page_end: int | None
    quoted_sha256: str | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class GroundedMemoryResponse(ApiContract):
    """Personal Memory kept distinct from factual evidence."""

    context_id: str
    memory_id: str
    revision_id: str
    memory_kind: str
    scope_kind: str
    scope_entity_id: str | None
    content: str


@dataclass(frozen=True, slots=True)
class GroundingResponse(ApiContract):
    """Deterministic grounding validation result for one answer."""

    cited_context_ids: tuple[str, ...]
    canonical_context_ids: tuple[str, ...]
    user_statement_context_ids: tuple[str, ...]
    conversation_context_ids: tuple[str, ...]
    source_context_ids: tuple[str, ...]
    research_context_ids: tuple[str, ...]
    news_context_ids: tuple[str, ...]
    invalid_context_ids: tuple[str, ...]
    uses_inference: bool
    uses_model_prior: bool
    uses_unknown: bool
    has_provenance_marker: bool


@dataclass(frozen=True, slots=True)
class GroundedChatResponse(ApiContract):
    """Persisted thread plus structured evidence for one grounded turn."""

    thread: ChatThreadResponse
    assistant_text: str
    evidence: tuple[GroundedEvidenceResponse, ...]
    personal_memory: tuple[GroundedMemoryResponse, ...]
    grounding: GroundingResponse
    processing_run_id: str
    model_id: str
    embedding_model_id: str | None


@dataclass(frozen=True, slots=True)
class RememberedChatMessageResponse(ApiContract):
    chat_id: str
    message_id: str
    message_revision_id: str
    memory_id: str
    memory_revision_id: str
    content: str


@dataclass(frozen=True, slots=True)
class KnowledgeUnitProposalResponse(ApiContract):
    proposal_index: int
    source_sequence_no: int
    source_quote: str
    knowledge_kind: str
    title: str | None
    body: str
    epistemic_status: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ClaimProposalResponse(ApiContract):
    proposal_index: int
    source_sequence_no: int
    source_quote: str
    claim_kind: str
    statement: str
    epistemic_status: str
    confidence: float


@dataclass(frozen=True, slots=True)
class RelationProposalResponse(ApiContract):
    relation_index: int
    left_type: str
    left_index: int
    relation_type: str
    right_type: str
    right_index: int
    confidence: float


@dataclass(frozen=True, slots=True)
class ExtractorMergeCandidateResponse(ApiContract):
    candidate_index: int
    proposal_type: str
    proposal_index: int
    reason: str
    confidence: float


@dataclass(frozen=True, slots=True)
class MessageKnowledgeExtractionResponse(ApiContract):
    chat_id: str
    message_id: str
    message_revision_id: str
    processing_run_id: str
    model_id: str
    model_signature_id: str
    knowledge_units: tuple[KnowledgeUnitProposalResponse, ...]
    claims: tuple[ClaimProposalResponse, ...]
    relations: tuple[RelationProposalResponse, ...]
    extractor_merge_candidates: tuple[ExtractorMergeCandidateResponse, ...]


@dataclass(frozen=True, slots=True)
class DedupDecisionResponse(ApiContract):
    proposal_type: str
    proposal_index: int
    action: str
    existing_entity_id: str | None
    existing_revision_id: str | None
    duplicate_of_proposal_index: int | None


@dataclass(frozen=True, slots=True)
class CanonicalMergeReviewResponse(ApiContract):
    candidate_index: int
    review_id: str
    proposal_type: str
    proposal_index: int
    existing_entity_id: str
    existing_revision_id: str
    similarity: float
    reason: str


@dataclass(frozen=True, slots=True)
class KnowledgeReviewResponse(ApiContract):
    processing_run_id: str
    model_signature_id: str
    ready_to_accept: bool
    blocked_reason: str | None
    preflight_digest: str | None
    knowledge_decisions: tuple[DedupDecisionResponse, ...]
    claim_decisions: tuple[DedupDecisionResponse, ...]
    canonical_merge_candidates: tuple[CanonicalMergeReviewResponse, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeMergeReviewResponse(ApiContract):
    review_id: str
    status: str
    proposal_type: str
    proposal_index: int
    source_entity_id: str
    source_revision_id: str
    proposal_text: str
    proposal_kind: str
    proposal_epistemic_status: str
    similarity: float
    decision: str | None
    existing_entity_id: str
    existing_revision_id: str


@dataclass(frozen=True, slots=True)
class DeletionDependencyResponse(ApiContract):
    relation: str
    count: int
    dependent_entity_id: str | None
    dependent_entity_type: str | None


@dataclass(frozen=True, slots=True)
class DeletionPreviewResponse(ApiContract):
    entity_id: str
    entity_type: str
    lifecycle_state: str
    dependencies: tuple[DeletionDependencyResponse, ...]
    preview_digest: str


@dataclass(frozen=True, slots=True)
class DeletionResultResponse(ApiContract):
    entity_id: str
    entity_type: str
    commit_id: str
    deleted_entity_ids: tuple[str, ...]
    preview_digest: str


@dataclass(frozen=True, slots=True)
class ProviderHealthResponse(ApiContract):
    provider: str
    status: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class ModelResponse(ApiContract):
    provider: str
    backend_model_id: str
    display_name: str
    model_type: str
    context_capacity: int | None
    quantization: str | None
    loaded: bool
    vision: bool | None
    trained_for_tool_use: bool | None
    loaded_context_length: int | None
