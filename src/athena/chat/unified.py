"""Unified local chat over ATHENA memory/knowledge and Raw Archive evidence."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.direct import (
    _estimate_persisted_messages,
    _prior_chat_sections,
    _resolve_context_limit,
    _select_recent_conversation_window,
)
from athena.chat.generation import (
    GROUNDING_RETRY_POLICY,
    ChatGenerationResult,
    ChatGenerationService,
)
from athena.chat.grounding import (
    GroundingContract,
    GroundingEvidenceRef,
    render_grounding_instructions,
)
from athena.chat.provenance import strip_turn_local_grounding_markers
from athena.memory.models import MemoryScopeKind
from athena.memory.service import PersonalMemoryService
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.retrieval.archive import ArchiveHybridRetrievalService
from athena.retrieval.context import (
    ContextBuilderError,
    ContextBuilderService,
    ContextBundle,
    estimate_tokens,
)
from athena.retrieval.context_package import (
    ContextIncludedRef,
    ContextPackage,
    ContextPackageBudget,
    ContextPackageService,
    ContextSection,
    ContextTokenEstimates,
    ExcludedCandidateSummary,
)
from athena.retrieval.degradation import (
    LEXICAL_FALLBACK_RETRIEVAL_MODE,
    SemanticRetrievalUnavailableError,
    resolve_embedding_model_for_retrieval,
)
from athena.retrieval.evidence import (
    EvidenceClass,
    MemoryEvidencePolicy,
    MemoryEvidenceSelection,
)
from athena.retrieval.hybrid import HybridRetrievalService, HybridSearchResult
from athena.retrieval.search import SearchEntityType
from athena.retrieval.source_context import (
    SourceContextBuilderService,
    SourceContextBundle,
)

_MIN_CONTEXT_BUDGET = 128
_MAX_CONTEXT_BUDGET = 64_000
_MAX_CONTEXT_ITEMS = 100
_MAX_MEMORY_ITEMS = 100
_DEFAULT_RECENT_CONVERSATION_TURNS = 8
_MAX_RECENT_CONVERSATION_TURNS = 100
_DEFAULT_OUTPUT_RESERVE = 2048
_DEFAULT_SAFETY_MARGIN = 256
_MESSAGE_WRAPPER_ESTIMATE = 6
_GROUNDING_REF_TOKEN_RESERVE = 12
_EPISTEMIC_GROUNDING_VERSION = 1
_EPISTEMIC_ITEM_TOKEN_RESERVE = 64
_CONTEXTUAL_RETRIEVAL_POLICY_VERSION = 1
_CONTEXTUAL_RETRIEVAL_MAX_TOKENS = 10
_CONTEXTUAL_RETRIEVAL_MAX_PREVIOUS_CHARS = 2000

_CONTEXTUAL_REFERENCE_TOKENS = frozenset(
    {
        "about",
        "beide",
        "beiden",
        "both",
        "davon",
        "das",
        "dem",
        "den",
        "der",
        "die",
        "dies",
        "diese",
        "dieser",
        "dieses",
        "that",
        "them",
        "these",
        "this",
        "those",
        "welche",
        "welcher",
        "welches",
        "which",
        "warum",
        "why",
        "richtig",
        "stimmt",
        "true",
        "correct",
        "right",
    }
)

_CONTEXTUAL_NON_TOPIC_TOKENS = frozenset(
    {
        "about",
        "also",
        "am",
        "an",
        "and",
        "are",
        "beide",
        "beiden",
        "both",
        "correct",
        "da",
        "das",
        "davon",
        "dem",
        "den",
        "der",
        "die",
        "dies",
        "diese",
        "dieser",
        "dieses",
        "do",
        "does",
        "es",
        "etwas",
        "genau",
        "gilt",
        "ihr",
        "ihre",
        "in",
        "is",
        "ist",
        "it",
        "mit",
        "noch",
        "nun",
        "oder",
        "one",
        "right",
        "richtig",
        "sind",
        "so",
        "stimmt",
        "that",
        "the",
        "them",
        "then",
        "these",
        "this",
        "those",
        "true",
        "und",
        "von",
        "warum",
        "was",
        "welche",
        "welcher",
        "welches",
        "what",
        "which",
        "why",
        "wie",
        "wieso",
        "woher",
        "zu",
    }
)

_EPISTEMIC_INTERPRETATION = (
    "ATHENA EPISTEMIC INTERPRETATION\n"
    "Canonical means stored/accepted in ATHENA; it does not mean independently "
    "verified truth.\n"
    "The epistemic status `asserted` means an assertion is stored. It is not the "
    "same as `supported`, verified, confirmed, or secured fact.\n"
    "A positive contradiction_count is an explicit conflict signal, not a truth "
    "score and not evidence that either side is superior.\n"
    "Preserve the exact epistemic status of retrieved canonical evidence in your "
    "reasoning.\n"
    "Do not describe asserted-only evidence as verified, confirmed, secured, "
    "established, or otherwise independently validated unless another valid cited "
    "source supports that.\n"
    "When local canonical evidence conflicts and the retrieved evidence cannot "
    "resolve which side is factually correct, state that ATHENA's local evidence "
    "is unresolved.\n"
    "If the grounding contract allows model prior and the user asks for a factual "
    "resolution, you may add a clearly separate resolution based on model prior, "
    "marked [MODEL-PRIOR].\n"
    "Never attribute a model-prior resolution to ATHENA's local canonical evidence.\n"
)

_RESPONSE_LANGUAGE_POLICY_VERSION = 1
_RESPONSE_LANGUAGE_INSTRUCTION = (
    "ATHENA RESPONSE LANGUAGE\n"
    "Respond in the same natural language as the current user message unless "
    "the user explicitly requests another language.\n"
    "For a short or language-ambiguous follow-up, continue the natural language "
    "of the preceding user turn unless the user explicitly requests a switch.\n"
    "Do not switch languages merely because system instructions, retrieved "
    "evidence, source material, citations, or model-prior knowledge use another "
    "language.\n"
)


@dataclass(frozen=True, slots=True)
class UnifiedLocalBudgetReport:
    effective_context_limit: int
    memory_context_budget: int
    source_context_budget: int
    estimated_input_tokens: int
    context_tokens: int
    output_reserve: int
    safety_margin: int
    estimated_total_tokens: int


@dataclass(frozen=True, slots=True)
class UnifiedLocalChatResult:
    """One model call grounded in typed local memory and Raw Archive evidence."""

    generation: ChatGenerationResult
    memory_context: ContextBundle
    source_context: SourceContextBundle
    context_package: ContextPackage
    processing_run: ProcessingRun
    embedding_model: ModelInfo | None
    evidence_selection: MemoryEvidenceSelection
    budget: UnifiedLocalBudgetReport


def _query_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in re.findall(
            r"\w+",
            unicodedata.normalize("NFKC", value),
            flags=re.UNICODE,
        )
    )


def _resolve_contextual_retrieval_query(
    *,
    content: str,
    recent_messages: tuple[object, ...],
) -> tuple[str, str]:
    normalized = content.strip()
    tokens = _query_tokens(normalized)
    if (
        not tokens
        or len(tokens) > _CONTEXTUAL_RETRIEVAL_MAX_TOKENS
        or not any(
            token in _CONTEXTUAL_REFERENCE_TOKENS
            for token in tokens
        )
        or any(
            token not in _CONTEXTUAL_NON_TOPIC_TOKENS
            for token in tokens
        )
    ):
        return normalized, "current_message"

    previous_user_content: str | None = None
    for message in reversed(recent_messages):
        message_type = getattr(message, "message_type", None)
        message_content = getattr(message, "content", None)
        if (
            getattr(message_type, "value", None) == "user"
            and isinstance(message_content, str)
            and message_content.strip()
        ):
            previous_user_content = strip_turn_local_grounding_markers(
                message_content
            ).strip()
            break

    if (
        previous_user_content is None
        or len(previous_user_content)
        > _CONTEXTUAL_RETRIEVAL_MAX_PREVIOUS_CHARS
    ):
        return normalized, "current_message"

    return (
        previous_user_content + "\n" + normalized,
        "previous_user_plus_current",
    )


def _render_epistemic_context(
    *,
    memory_context: ContextBundle,
    evidence_selection: MemoryEvidenceSelection,
) -> str:
    items: list[dict[str, object]] = []

    for context_item in memory_context.items:
        classification = evidence_selection.classification_for(
            entity_type=context_item.entity_type,
            entity_id=context_item.entity_id,
            revision_id=context_item.revision_id,
        )
        if classification.evidence_class is not EvidenceClass.CANONICAL:
            raise RuntimeError(
                "Unified epistemic overlay received non-canonical evidence."
            )

        status = (
            "unknown"
            if classification.epistemic_status is None
            else classification.epistemic_status.value
        )
        items.append(
            {
                "context_id": context_item.context_id,
                "entity_type": context_item.entity_type.value,
                "epistemic_status": status,
                "contradiction_count": context_item.contradiction_count,
                "duplicate_count": context_item.duplicate_count,
            }
        )

    payload = {
        "athena_epistemic_context_version": _EPISTEMIC_GROUNDING_VERSION,
        "canonical_means_stored_not_verified": True,
        "asserted_means_asserted_not_verified": True,
        "contradiction_count_is_conflict_signal_not_truth_score": True,
        "items": items,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )


def _canonical_text_key(value: str) -> str:
    """Normalize canonical text consistently with HybridRetrievalService."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        character if character.isalnum() else " "
        for character in normalized
    )
    return " ".join(normalized.split())


def _merge_canonical_results(
    knowledge_results: tuple[HybridSearchResult, ...],
    claim_results: tuple[HybridSearchResult, ...],
    *,
    limit: int,
) -> tuple[HybridSearchResult, ...]:
    """Merge Knowledge + Claim retrieval without duplicate semantic statements.

    Hybrid retrieval consolidates duplicates inside one entity-type query. Unified
    retrieval performs separate typed queries so chat records cannot crowd out
    canonical evidence; this helper performs the corresponding cross-type exact
    consolidation.

    When a KnowledgeUnit and Claim contain the same normalized text, prefer the
    higher-authority representative while retaining the strongest retrieval score
    and contradiction metadata.
    """

    if not 1 <= limit <= 200:
        raise ValueError(
            "Canonical merge limit must be between 1 and 200."
        )

    by_text: dict[str, HybridSearchResult] = {}

    for item in (*knowledge_results, *claim_results):
        if item.entity_type not in {
            SearchEntityType.KNOWLEDGE,
            SearchEntityType.CLAIM,
        }:
            raise ValueError(
                "Canonical merge received a non-canonical search result."
            )

        key = _canonical_text_key(item.text)

        current = by_text.get(key)

        if current is None:
            by_text[key] = item
            continue

        representative = max(
            (current, item),
            key=lambda candidate: (
                candidate.authority_score,
                candidate.lexical_score,
                candidate.semantic_score,
                candidate.score,
                candidate.entity_type is SearchEntityType.KNOWLEDGE,
                candidate.entity_id.hex,
            ),
        )

        by_text[key] = HybridSearchResult(
            entity_id=representative.entity_id,
            revision_id=representative.revision_id,
            entity_type=representative.entity_type,
            title=representative.title,
            text=representative.text,
            score=max(current.score, item.score),
            lexical_score=max(
                current.lexical_score,
                item.lexical_score,
            ),
            semantic_score=max(
                current.semantic_score,
                item.semantic_score,
            ),
            authority_score=representative.authority_score,
            contradiction_count=max(
                current.contradiction_count,
                item.contradiction_count,
            ),
            duplicate_count=(
                current.duplicate_count
                + item.duplicate_count
                + 1
            ),
        )

    ordered = sorted(
        by_text.values(),
        key=lambda item: (
            -item.score,
            -item.authority_score,
            item.entity_type.value,
            item.entity_id.hex,
        ),
    )

    return tuple(ordered[:limit])


class UnifiedLocalChatService:
    """Compose mature local retrieval domains into one grounded ContextPackage."""

    def __init__(
        self,
        *,
        chat_generation: ChatGenerationService,
        embedding_provider: LMStudioEmbeddingProvider,
        hybrid_retrieval: HybridRetrievalService,
        memory_context_builder: ContextBuilderService,
        evidence_policy: MemoryEvidencePolicy,
        personal_memory: PersonalMemoryService,
        archive_retrieval: ArchiveHybridRetrievalService,
        source_context_builder: SourceContextBuilderService,
        context_packages: ContextPackageService,
        model_runs: ModelRunRepository,
    ) -> None:
        self.chat_generation = chat_generation
        self.embedding_provider = embedding_provider
        self.hybrid_retrieval = hybrid_retrieval
        self.memory_context_builder = memory_context_builder
        self.evidence_policy = evidence_policy
        self.personal_memory = personal_memory
        self.archive_retrieval = archive_retrieval
        self.source_context_builder = source_context_builder
        self.context_packages = context_packages
        self.model_runs = model_runs

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        retrieval_query: str | None = None,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        max_memory_context_tokens: int = 1200,
        max_memory_context_items: int = 8,
        max_memory_items: int = 8,
        max_source_context_tokens: int = 1200,
        max_source_context_items: int = 8,
        max_recent_conversation_turns: int = _DEFAULT_RECENT_CONVERSATION_TURNS,
        memory_scope_kind: MemoryScopeKind | None = None,
        memory_scope_entity_id: uuid.UUID | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = _DEFAULT_OUTPUT_RESERVE,
        safety_margin: int = _DEFAULT_SAFETY_MARGIN,
        temperature: float | None = None,
        reasoning_mode: str | None = "off",
        allow_model_prior: bool = True,
        on_delta: Callable[[str], None] | None = None,
    ) -> UnifiedLocalChatResult:
        self._validate_request(
            max_memory_context_tokens=max_memory_context_tokens,
            max_memory_context_items=max_memory_context_items,
            max_memory_items=max_memory_items,
            max_source_context_tokens=max_source_context_tokens,
            max_source_context_items=max_source_context_items,
            max_recent_conversation_turns=max_recent_conversation_turns,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
        )
        if temperature is not None and not 0.0 <= temperature <= 2.0:
            raise ContextBuilderError(
                "Temperature must be between 0.0 and 2.0."
            )
        if reasoning_mode not in {None, "off"}:
            raise ContextBuilderError(
                "Reasoning mode must be None or 'off'."
            )

        search_query = content
        retrieval_query_mode = "current_message"
        if retrieval_query is not None:
            search_query = retrieval_query.strip()
            if not search_query:
                raise ContextBuilderError(
                    "Retrieval query override must not be empty."
                )
            retrieval_query_mode = "explicit_override"

        model = self.chat_generation.select_model(requested_model_id)
        context_limit = _resolve_context_limit(
            model=model,
            requested_limit=effective_context_limit,
        )
        embedding_resolution = resolve_embedding_model_for_retrieval(
            self.embedding_provider,
            requested_embedding_model_id,
        )
        embedding_model = embedding_resolution.model
        source_retrieval_mode = embedding_resolution.mode
        source_retrieval_warning = embedding_resolution.warning
        memory_retrieval_mode = embedding_resolution.mode
        memory_retrieval_warning = embedding_resolution.warning

        # This first history read is budget planning only. The authoritative
        # history is loaded again after SourceAnchor materialization and pinning.
        preflight_thread = self.chat_generation.chat.load_chat(chat_id)
        preflight_recent = _select_recent_conversation_window(
            preflight_thread.messages,
            max_turns=max_recent_conversation_turns,
            include_assistant=False,
        )
        if retrieval_query is None:
            search_query, retrieval_query_mode = (
                _resolve_contextual_retrieval_query(
                    content=content,
                    recent_messages=preflight_recent,
                )
            )
        preflight_conversation_tokens = _estimate_persisted_messages(
            preflight_recent
        )
        current_user_tokens = estimate_tokens(content) + _MESSAGE_WRAPPER_ESTIMATE
        grounding_reserve = (
            estimate_tokens(
                render_grounding_instructions(
                    GroundingContract(
                        evidence_refs=(),
                        allow_model_prior=allow_model_prior,
                    )
                )
            )
            + estimate_tokens(_EPISTEMIC_INTERPRETATION)
            + estimate_tokens(_RESPONSE_LANGUAGE_INSTRUCTION)
            + max_memory_context_items
            * _EPISTEMIC_ITEM_TOKEN_RESERVE
            + (
                max_memory_context_items
                + max_source_context_items
            )
            * _GROUNDING_REF_TOKEN_RESERVE
        )

        available_payload_tokens = (
            context_limit
            - preflight_conversation_tokens
            - current_user_tokens
            - output_reserve
            - safety_margin
            - grounding_reserve
        )
        if available_payload_tokens < 2 * _MIN_CONTEXT_BUDGET:
            raise ContextBuilderError(
                "Conversation, current input, grounding instructions, output "
                "reserve and safety margin leave insufficient room for both "
                "local retrieval domains."
            )

        memory_context_budget = min(
            max_memory_context_tokens,
            available_payload_tokens - _MIN_CONTEXT_BUDGET,
        )
        source_context_budget = min(
            max_source_context_tokens,
            available_payload_tokens - memory_context_budget,
        )
        if source_context_budget < _MIN_CONTEXT_BUDGET:
            source_context_budget = _MIN_CONTEXT_BUDGET
            memory_context_budget = min(
                max_memory_context_tokens,
                available_payload_tokens - source_context_budget,
            )
        if memory_context_budget < _MIN_CONTEXT_BUDGET:
            raise ContextBuilderError(
                "Unified local retrieval could not reserve the minimum "
                "deterministic budget for Memory/Knowledge."
            )

        source_candidate_limit = min(
            200,
            max(40, max_source_context_items * 8),
        )
        if embedding_model is None:
            source_results = self.archive_retrieval.search_lexical(
                search_query,
                limit=source_candidate_limit,
            )
        else:
            try:
                source_results = self.archive_retrieval.search(
                    search_query,
                    model_id=embedding_model.backend_model_id,
                    limit=source_candidate_limit,
                )
            except SemanticRetrievalUnavailableError as exc:
                source_retrieval_mode = LEXICAL_FALLBACK_RETRIEVAL_MODE
                source_retrieval_warning = exc.reason_code
                source_results = self.archive_retrieval.search_lexical(
                    search_query,
                    limit=source_candidate_limit,
                )
        source_context = self.source_context_builder.build_from_hybrid(
            query=content,
            results=source_results,
            max_estimated_tokens=source_context_budget,
            max_items=max_source_context_items,
        )
        self.source_context_builder.verify_bundle(source_context)

        # SourceAnchor materialization is durable state. Pin only after it has
        # completed, then perform canonical/Memory retrieval under that pin.
        retrieval_snapshot_commit_seq = self.context_packages.current_commit_seq()

        thread = self.chat_generation.chat.load_chat(chat_id)
        recent_messages = _select_recent_conversation_window(
            thread.messages,
            max_turns=max_recent_conversation_turns,
            include_assistant=False,
        )
        prior_sections, prior_refs = _prior_chat_sections(recent_messages)
        conversation_tokens = _estimate_persisted_messages(recent_messages)

        memories = self.personal_memory.context_candidates(
            scope_kind=memory_scope_kind,
            scope_entity_id=memory_scope_entity_id,
            limit=max(32, max_memory_items),
        )
        memory_candidate_limit = min(
            200,
            max(40, max_memory_context_items * 8),
        )

        # Unified Local Context v1 deliberately composes:
        #
        #   - Personal Memory preferences/details
        #   - Canonical Knowledge / Claims
        #   - Raw Archive Source evidence
        #
        # Historical chat messages remain available through the existing
        # Memory Chat path and, later, through an adaptive retrieval planner.
        # They must not compete with Canonical Knowledge for the bounded
        # Knowledge portion of an explicitly combined --memory --sources turn.
        if embedding_model is None:
            knowledge_results = self.hybrid_retrieval.search_lexical(
                search_query,
                limit=memory_candidate_limit,
                entity_type=SearchEntityType.KNOWLEDGE,
            )
            claim_results = self.hybrid_retrieval.search_lexical(
                search_query,
                limit=memory_candidate_limit,
                entity_type=SearchEntityType.CLAIM,
            )
        else:
            try:
                knowledge_results = self.hybrid_retrieval.search(
                    search_query,
                    model_id=embedding_model.backend_model_id,
                    limit=memory_candidate_limit,
                    entity_type=SearchEntityType.KNOWLEDGE,
                )
                claim_results = self.hybrid_retrieval.search(
                    search_query,
                    model_id=embedding_model.backend_model_id,
                    limit=memory_candidate_limit,
                    entity_type=SearchEntityType.CLAIM,
                )
            except SemanticRetrievalUnavailableError as exc:
                # Recompute both canonical types lexically. Do not leave one
                # half of a single domain on semantic ranking and the other
                # half on lexical ranking.
                memory_retrieval_mode = LEXICAL_FALLBACK_RETRIEVAL_MODE
                memory_retrieval_warning = exc.reason_code
                knowledge_results = self.hybrid_retrieval.search_lexical(
                    search_query,
                    limit=memory_candidate_limit,
                    entity_type=SearchEntityType.KNOWLEDGE,
                )
                claim_results = self.hybrid_retrieval.search_lexical(
                    search_query,
                    limit=memory_candidate_limit,
                    entity_type=SearchEntityType.CLAIM,
                )
        memory_results = _merge_canonical_results(
            knowledge_results,
            claim_results,
            limit=memory_candidate_limit,
        )

        retrieval_warnings = tuple(
            dict.fromkeys(
                warning
                for warning in (
                    memory_retrieval_warning,
                    source_retrieval_warning,
                )
                if warning is not None
            )
        )

        evidence_selection = self.evidence_policy.classify(memory_results)

        if any(
            classification.evidence_class is not EvidenceClass.CANONICAL
            for classification in evidence_selection.classifications
        ):
            raise RuntimeError(
                "Unified canonical retrieval admitted a non-canonical "
                "Memory/Knowledge evidence class."
            )

        memory_context = self.memory_context_builder.build_from_hybrid(
            query=content,
            results=evidence_selection.results,
            personal_memory=memories,
            max_estimated_tokens=memory_context_budget,
            max_items=max_memory_context_items,
            max_memory_items=max_memory_items,
        )
        epistemic_context = _render_epistemic_context(
            memory_context=memory_context,
            evidence_selection=evidence_selection,
        )

        # Memory/Knowledge owns CTX-001..N. Rebase only the ephemeral labels of
        # Raw Archive items. Durable SourceAnchor identity is unchanged.
        source_context = self.source_context_builder.rebase_context_ids(
            source_context,
            start_index=len(memory_context.items) + 1,
        )

        grounding_contract = self._grounding_contract(
            memory_context=memory_context,
            source_context=source_context,
            evidence_selection=evidence_selection,
            allow_model_prior=allow_model_prior,
        )
        system_text = (
            render_grounding_instructions(grounding_contract)
            + _EPISTEMIC_INTERPRETATION
            + _RESPONSE_LANGUAGE_INSTRUCTION
            + "\nATHENA CANONICAL EPISTEMIC METADATA\n"
            + epistemic_context
            + "\n\nATHENA LOCAL MEMORY / KNOWLEDGE CONTEXT\n"
            + memory_context.rendered_text
            + "\n\nATHENA RAW ARCHIVE CONTEXT\n"
            + source_context.rendered_text
        )
        system_tokens = estimate_tokens(system_text)
        estimated_input_tokens = (
            conversation_tokens + current_user_tokens + system_tokens
        )
        estimated_total_tokens = (
            estimated_input_tokens + output_reserve + safety_margin
        )
        if estimated_total_tokens > context_limit:
            raise ContextBuilderError(
                "Unified local ContextPackage exceeds the active model context "
                "after exact deterministic accounting."
            )

        self.context_packages.assert_snapshot_current(
            retrieval_snapshot_commit_seq,
            phase="post-unified-local-context-build",
        )

        context_configuration = {
            "context_package_version": 1,
            "mode": "unified_local_chat",
            "effective_context_limit": context_limit,
            "memory_context_budget": memory_context_budget,
            "source_context_budget": source_context_budget,
            "max_memory_context_items": max_memory_context_items,
            "max_memory_items": max_memory_items,
            "max_source_context_items": max_source_context_items,
            "max_recent_conversation_turns": max_recent_conversation_turns,
            "safety_margin": safety_margin,
            "conversation_history_policy": "grounded_user_only",
            "grounding_retry_policy": GROUNDING_RETRY_POLICY,
            "embedding_model_id": (
                None
                if embedding_model is None
                else embedding_model.backend_model_id
            ),
            "memory_retrieval_mode": memory_retrieval_mode,
            "source_retrieval_mode": source_retrieval_mode,
            "retrieval_warnings": retrieval_warnings,
            "evidence_policy_id": evidence_selection.policy_id,
            "epistemic_grounding_version": (
                _EPISTEMIC_GROUNDING_VERSION
            ),
            "response_language_policy_version": (
                _RESPONSE_LANGUAGE_POLICY_VERSION
            ),
            "retrieval_query_policy_version": (
                _CONTEXTUAL_RETRIEVAL_POLICY_VERSION
            ),
            "retrieval_query_mode": retrieval_query_mode,
            "allow_model_prior": allow_model_prior,
        }
        generation_parameters: dict[str, object] = {
            "max_output_tokens": output_reserve,
            "reasoning_mode": reasoning_mode,
        }
        if temperature is not None:
            generation_parameters["temperature"] = temperature
        signature = self.model_runs.get_or_create_signature(
            model=model,
            generation_parameters=generation_parameters,
            context_configuration=context_configuration,
        )

        # Persist the current user input only after retrieval so it cannot
        # retrieve itself. Exactly one new commit is allowed.
        user_message = self.chat_generation.chat.add_user_message(
            chat_id=chat_id,
            content=content,
        )
        package_snapshot_commit_seq = self.context_packages.assert_user_commit_follows(
            retrieval_snapshot_commit_seq,
            user_message,
        )

        system_refs = self._system_package_refs(
            memory_context=memory_context,
            source_context=source_context,
        )
        current_ref = ContextIncludedRef(
            ref_id="CURRENT-USER",
            entity_type="chat_message",
            entity_id=user_message.message_id,
            revision_id=user_message.revision_id,
        )
        sections = (
            ContextSection(
                name="unified_local_context",
                role="system",
                content=system_text,
                included_ref_ids=tuple(item.ref_id for item in system_refs),
            ),
            *prior_sections,
            ContextSection(
                name="current_user",
                role="user",
                content=content,
                included_ref_ids=(current_ref.ref_id,),
            ),
        )

        retrieval_candidate_count = (
            len(evidence_selection.results) + len(source_results)
        )
        retrieval_included_count = (
            len(memory_context.items) + len(source_context.items)
        )

        package = self.context_packages.build_from_sections(
            model_signature=signature,
            budget=ContextPackageBudget(
                effective_context_limit=context_limit,
                context_budget=memory_context_budget + source_context_budget,
                output_reserve=output_reserve,
                safety_margin=safety_margin,
            ),
            sections=sections,
            included_refs=(*system_refs, *prior_refs, current_ref),
            excluded_candidate_summary=ExcludedCandidateSummary(
                retrieval_candidate_count=retrieval_candidate_count,
                retrieval_included_count=retrieval_included_count,
                retrieval_excluded_count=(
                    retrieval_candidate_count - retrieval_included_count
                ),
                memory_candidate_count=len(memories),
                memory_included_count=len(memory_context.memory_items),
                memory_excluded_count=(
                    len(memories) - len(memory_context.memory_items)
                ),
                conversation_candidate_count=len(thread.messages),
                conversation_included_count=len(recent_messages),
                conversation_excluded_count=(
                    len(thread.messages) - len(recent_messages)
                ),
            ),
            token_estimates=ContextTokenEstimates(
                conversation_tokens=conversation_tokens,
                current_user_tokens=current_user_tokens,
                system_tokens=system_tokens,
                context_tokens=(
                    memory_context.estimated_tokens
                    + source_context.estimated_tokens
                ),
                estimated_input_tokens=estimated_input_tokens,
                estimated_total_tokens=estimated_total_tokens,
            ),
            snapshot_commit_seq=package_snapshot_commit_seq,
        )

        if user_message.actor_id is None:
            raise RuntimeError(
                "Persisted user message has no actor for ProcessingRun."
            )

        run_snapshot = package.run_snapshot()
        if retrieval_query is not None:
            run_snapshot = {
                **run_snapshot,
                "retrieval_query_override": search_query,
            }

        processing_run = self.model_runs.start_run(
            run_type="chat.unified_local_context_package",
            trigger_actor_id=user_message.actor_id,
            pipeline_version="unified-local-chat-context-package-v1",
            input_snapshot=run_snapshot,
            configuration=context_configuration,
            model_signature_id=signature.model_signature_id,
            prompt_template_id="unified-local-grounding",
            prompt_template_version="1",
        )

        def before_provider() -> None:
            self.context_packages.assert_snapshot_current(
                package.snapshot_commit_seq,
                phase="immediately-before-primary-model-call",
            )
            self.source_context_builder.verify_bundle(source_context)

        try:
            generation = self.chat_generation.send_context_package(
                chat_id=chat_id,
                user_message=user_message,
                context_package=package,
                on_delta=on_delta,
                grounding_contract=grounding_contract,
                on_before_provider_call=before_provider,
            )
        except KeyboardInterrupt:
            self.model_runs.finish_run(
                processing_run.processing_run_id,
                status="cancelled",
            )
            raise
        except Exception as exc:
            self.model_runs.finish_run(
                processing_run.processing_run_id,
                status="failed",
                error_detail=f"{type(exc).__name__}: {exc}"[:4000],
            )
            raise

        processing_run = self.model_runs.finish_run(
            processing_run.processing_run_id,
            status="succeeded",
        )

        return UnifiedLocalChatResult(
            generation=generation,
            memory_context=memory_context,
            source_context=source_context,
            context_package=package,
            processing_run=processing_run,
            embedding_model=embedding_model,
            evidence_selection=evidence_selection,
            budget=UnifiedLocalBudgetReport(
                effective_context_limit=context_limit,
                memory_context_budget=memory_context_budget,
                source_context_budget=source_context_budget,
                estimated_input_tokens=estimated_input_tokens,
                context_tokens=(
                    memory_context.estimated_tokens
                    + source_context.estimated_tokens
                ),
                output_reserve=output_reserve,
                safety_margin=safety_margin,
                estimated_total_tokens=estimated_total_tokens,
            ),
        )
    @staticmethod
    def _system_package_refs(
        *,
        memory_context: ContextBundle,
        source_context: SourceContextBundle,
    ) -> tuple[ContextIncludedRef, ...]:
        refs: list[ContextIncludedRef] = []

        for memory in memory_context.memory_items:
            refs.append(
                ContextIncludedRef(
                    ref_id=memory.context_id,
                    entity_type="personal_memory",
                    entity_id=memory.memory_id,
                    revision_id=memory.revision_id,
                )
            )

        for context_item in memory_context.items:
            refs.append(
                ContextIncludedRef(
                    ref_id=context_item.context_id,
                    entity_type=context_item.entity_type.value,
                    entity_id=context_item.entity_id,
                    revision_id=context_item.revision_id,
                )
            )

        for source_item in source_context.items:
            refs.append(
                ContextIncludedRef(
                    ref_id=source_item.context_id,
                    entity_type="source_anchor",
                    entity_id=source_item.anchor_id,
                    revision_id=None,
                )
            )

        return tuple(refs)

    @staticmethod
    def _grounding_contract(
        *,
        memory_context: ContextBundle,
        source_context: SourceContextBundle,
        evidence_selection: MemoryEvidenceSelection,
        allow_model_prior: bool,
    ) -> GroundingContract:
        refs: list[GroundingEvidenceRef] = []

        for context_item in memory_context.items:
            classification = evidence_selection.classification_for(
                entity_type=context_item.entity_type,
                entity_id=context_item.entity_id,
                revision_id=context_item.revision_id,
            )
            refs.append(
                GroundingEvidenceRef(
                    context_id=context_item.context_id,
                    entity_type=context_item.entity_type.value,
                    entity_id=context_item.entity_id,
                    revision_id=context_item.revision_id,
                    evidence_class=classification.evidence_class,
                )
            )

        for source_item in source_context.items:
            refs.append(
                GroundingEvidenceRef(
                    context_id=source_item.context_id,
                    entity_type="source_anchor",
                    entity_id=source_item.anchor_id,
                    revision_id=None,
                    evidence_class=EvidenceClass.SOURCE,
                    source_id=source_item.source_id,
                    representation_id=source_item.representation_id,
                    start_offset=source_item.start_offset,
                    end_offset=source_item.end_offset,
                    quoted_hash=source_item.quoted_hash,
                )
            )

        return GroundingContract(
            evidence_refs=tuple(refs),
            allow_model_prior=allow_model_prior,
        )

    @staticmethod
    def _validate_request(
        *,
        max_memory_context_tokens: int,
        max_memory_context_items: int,
        max_memory_items: int,
        max_source_context_tokens: int,
        max_source_context_items: int,
        max_recent_conversation_turns: int,
        output_reserve: int,
        safety_margin: int,
    ) -> None:
        for label, value in (
            ("Memory context token budget", max_memory_context_tokens),
            ("Source context token budget", max_source_context_tokens),
        ):
            if not _MIN_CONTEXT_BUDGET <= value <= _MAX_CONTEXT_BUDGET:
                raise ContextBuilderError(
                    f"{label} must be between 128 and 64000."
                )

        for label, value in (
            ("Memory context max-items", max_memory_context_items),
            ("Source context max-items", max_source_context_items),
        ):
            if not 1 <= value <= _MAX_CONTEXT_ITEMS:
                raise ContextBuilderError(
                    f"{label} must be between 1 and 100."
                )

        if not 0 <= max_memory_items <= _MAX_MEMORY_ITEMS:
            raise ContextBuilderError(
                "Context max-memory-items must be between 0 and 100."
            )
        if not (
            1
            <= max_recent_conversation_turns
            <= _MAX_RECENT_CONVERSATION_TURNS
        ):
            raise ContextBuilderError(
                "Recent conversation turns must be between 1 and 100."
            )
        if output_reserve < 1:
            raise ContextBuilderError("Output reserve must be positive.")
        if safety_margin < 0:
            raise ContextBuilderError("Safety margin must not be negative.")
