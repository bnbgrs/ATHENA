"""Retrieval-augmented persistent chat orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.generation import ChatGenerationResult, ChatGenerationService
from athena.chat.grounding import (
    GroundingContract,
    GroundingEvidenceRef,
    render_grounding_instructions,
)
from athena.memory.models import MemoryScopeKind
from athena.memory.service import PersonalMemoryService
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.domain import ModelInfo
from athena.retrieval.context import (
    ContextBuilderError,
    ContextBuilderService,
    ContextBundle,
    estimate_tokens,
)
from athena.retrieval.evidence import MemoryEvidencePolicy, MemoryEvidenceSelection
from athena.retrieval.hybrid import HybridRetrievalService

_MIN_CONTEXT_BUDGET = 128
_MAX_CONTEXT_BUDGET = 64_000
_MAX_CONTEXT_ITEMS = 100
_MAX_MEMORY_ITEMS = 100
_DEFAULT_OUTPUT_RESERVE = 2048
_DEFAULT_SAFETY_MARGIN = 256
_MESSAGE_WRAPPER_ESTIMATE = 6


@dataclass(frozen=True, slots=True)
class ContextBudgetReport:
    """Deterministic accounting for one memory-augmented chat model call."""

    effective_context_limit: int
    estimated_input_tokens: int
    context_tokens: int
    output_reserve: int
    safety_margin: int
    estimated_total_tokens: int


@dataclass(frozen=True, slots=True)
class MemoryChatGenerationResult:
    """One completed chat turn plus the ephemeral retrieval context used."""

    generation: ChatGenerationResult
    context: ContextBundle
    embedding_model: ModelInfo
    evidence_selection: MemoryEvidenceSelection
    budget: ContextBudgetReport


class MemoryAugmentedChatService:
    """Retrieve typed local evidence and Personal Memory before Primary Model use.

    Retrieval happens before the new user message is persisted. This prevents
    the current query from entering the search index and being retrieved as its
    own evidence. Personal Memory is supplied separately as USER PREFERENCE data.
    The current user message remains the authoritative user instruction for the
    call and is never replaced by memory.
    """

    def __init__(
        self,
        *,
        chat_generation: ChatGenerationService,
        embedding_provider: LMStudioEmbeddingProvider,
        hybrid_retrieval: HybridRetrievalService,
        context_builder: ContextBuilderService,
        evidence_policy: MemoryEvidencePolicy,
        personal_memory: PersonalMemoryService,
    ) -> None:
        self.chat_generation = chat_generation
        self.embedding_provider = embedding_provider
        self.hybrid_retrieval = hybrid_retrieval
        self.context_builder = context_builder
        self.evidence_policy = evidence_policy
        self.personal_memory = personal_memory

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        max_context_tokens: int = 1200,
        max_context_items: int = 8,
        max_memory_items: int = 8,
        memory_scope_kind: MemoryScopeKind | None = None,
        memory_scope_entity_id: uuid.UUID | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = _DEFAULT_OUTPUT_RESERVE,
        safety_margin: int = _DEFAULT_SAFETY_MARGIN,
        allow_model_prior: bool = True,
        on_delta: Callable[[str], None] | None = None,
    ) -> MemoryChatGenerationResult:
        self._validate_request(
            max_context_tokens=max_context_tokens,
            max_context_items=max_context_items,
            max_memory_items=max_memory_items,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
        )

        # Resolve the actual Primary Model before retrieval so the Context Builder
        # can budget against the loaded runtime context and the generation can be
        # pinned to that exact model ID.
        model = self.chat_generation.select_model(requested_model_id)
        context_limit = self._resolve_context_limit(
            model=model,
            requested_limit=effective_context_limit,
        )
        thread = self.chat_generation.chat.load_chat(chat_id)
        fixed_input_tokens = _estimate_conversation_input(thread.messages, content)
        available_for_context = (
            context_limit - fixed_input_tokens - output_reserve - safety_margin
        )
        if available_for_context < _MIN_CONTEXT_BUDGET:
            raise ContextBuilderError(
                "Current conversation plus output reserve and safety margin leave "
                "insufficient room for a bounded ATHENA context."
            )
        context_budget = min(max_context_tokens, available_for_context)

        memories = self.personal_memory.context_candidates(
            scope_kind=memory_scope_kind,
            scope_entity_id=memory_scope_entity_id,
            limit=max(32, max_memory_items),
        )

        embedding_model = self.embedding_provider.resolve_model(
            requested_embedding_model_id
        )
        candidate_limit = min(200, max(40, max_context_items * 8))
        results = self.hybrid_retrieval.search(
            content,
            model_id=embedding_model.backend_model_id,
            limit=candidate_limit,
        )
        evidence_selection = self.evidence_policy.classify(results)

        context: ContextBundle | None = None
        grounding_contract: GroundingContract | None = None
        estimated_input_tokens = 0

        # The grounding wrapper size depends on the exact selected CTX refs. Build,
        # account, and shrink deterministically until the full request fits.
        for _ in range(8):
            context = self.context_builder.build_from_hybrid(
                query=content,
                results=evidence_selection.results,
                personal_memory=memories,
                max_estimated_tokens=context_budget,
                max_items=max_context_items,
                max_memory_items=max_memory_items,
            )
            grounding_contract = self._grounding_contract(
                context=context,
                evidence_selection=evidence_selection,
                allow_model_prior=allow_model_prior,
            )
            system_text = render_grounding_instructions(grounding_contract) + context.rendered_text
            estimated_input_tokens = fixed_input_tokens + estimate_tokens(system_text)
            total = estimated_input_tokens + output_reserve + safety_margin
            if total <= context_limit:
                break
            overflow = total - context_limit
            next_budget = context_budget - overflow - 8
            if next_budget < _MIN_CONTEXT_BUDGET:
                raise ContextBuilderError(
                    "Context cannot be reduced enough to preserve output reserve and "
                    "safety margin for the active model context."
                )
            context_budget = next_budget
        else:
            raise RuntimeError("Context Builder budget convergence failed.")

        assert context is not None
        assert grounding_contract is not None
        budget_report = ContextBudgetReport(
            effective_context_limit=context_limit,
            estimated_input_tokens=estimated_input_tokens,
            context_tokens=context.estimated_tokens,
            output_reserve=output_reserve,
            safety_margin=safety_margin,
            estimated_total_tokens=(
                estimated_input_tokens + output_reserve + safety_margin
            ),
        )
        if budget_report.estimated_total_tokens > context_limit:
            raise RuntimeError("ATHENA attempted to exceed the active context budget.")

        generation = self.chat_generation.send_message(
            chat_id=chat_id,
            content=content,
            requested_model_id=model.backend_model_id,
            on_delta=on_delta,
            retrieved_context=context.rendered_text,
            grounding_contract=grounding_contract,
            max_output_tokens=output_reserve,
            reasoning_mode="off",
        )
        return MemoryChatGenerationResult(
            generation=generation,
            context=context,
            embedding_model=embedding_model,
            evidence_selection=evidence_selection,
            budget=budget_report,
        )

    @staticmethod
    def _validate_request(
        *,
        max_context_tokens: int,
        max_context_items: int,
        max_memory_items: int,
        output_reserve: int,
        safety_margin: int,
    ) -> None:
        if not _MIN_CONTEXT_BUDGET <= max_context_tokens <= _MAX_CONTEXT_BUDGET:
            raise ContextBuilderError(
                "Context token budget must be between 128 and 64000."
            )
        if not 1 <= max_context_items <= _MAX_CONTEXT_ITEMS:
            raise ContextBuilderError("Context max-items must be between 1 and 100.")
        if not 0 <= max_memory_items <= _MAX_MEMORY_ITEMS:
            raise ContextBuilderError(
                "Context max-memory-items must be between 0 and 100."
            )
        if output_reserve < 1:
            raise ContextBuilderError("Output reserve must be positive.")
        if safety_margin < 0:
            raise ContextBuilderError("Safety margin must not be negative.")

    @staticmethod
    def _resolve_context_limit(
        *,
        model: ModelInfo,
        requested_limit: int | None,
    ) -> int:
        reported_effective = model.loaded_context_length
        if requested_limit is None:
            if reported_effective is None:
                raise ContextBuilderError(
                    "Active model did not report its loaded runtime context; provide an "
                    "explicit effective context limit instead of assuming the model maximum."
                )
            return reported_effective
        if requested_limit < 1:
            raise ContextBuilderError("Effective context limit must be positive.")
        if model.context_capacity is not None and requested_limit > model.context_capacity:
            raise ContextBuilderError(
                "Requested effective context limit exceeds the model maximum capacity."
            )
        if (
            model.loaded_context_length is not None
            and requested_limit > model.loaded_context_length
        ):
            raise ContextBuilderError(
                "Requested effective context limit exceeds the currently loaded "
                "LM Studio context."
            )
        return requested_limit

    @staticmethod
    def _grounding_contract(
        *,
        context: ContextBundle,
        evidence_selection: MemoryEvidenceSelection,
        allow_model_prior: bool,
    ) -> GroundingContract:
        evidence_refs: list[GroundingEvidenceRef] = []
        for item in context.items:
            classification = evidence_selection.classification_for(
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                revision_id=item.revision_id,
            )
            evidence_refs.append(
                GroundingEvidenceRef(
                    context_id=item.context_id,
                    entity_type=item.entity_type.value,
                    entity_id=item.entity_id,
                    revision_id=item.revision_id,
                    evidence_class=classification.evidence_class,
                )
            )
        return GroundingContract(
            evidence_refs=tuple(evidence_refs),
            allow_model_prior=allow_model_prior,
        )


def _estimate_conversation_input(messages: tuple[object, ...], current_content: str) -> int:
    """Conservatively estimate existing history plus the unmodified current user turn."""
    total = estimate_tokens(current_content) + _MESSAGE_WRAPPER_ESTIMATE
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            total += estimate_tokens(content) + _MESSAGE_WRAPPER_ESTIMATE
    return total
