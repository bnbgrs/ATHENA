"""Retrieval-augmented persistent chat orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.generation import ChatGenerationResult, ChatGenerationService
from athena.chat.grounding import GroundingContract, GroundingEvidenceRef
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.domain import ModelInfo
from athena.retrieval.context import (
    ContextBuilderError,
    ContextBuilderService,
    ContextBundle,
)
from athena.retrieval.evidence import MemoryEvidencePolicy, MemoryEvidenceSelection
from athena.retrieval.hybrid import HybridRetrievalService


@dataclass(frozen=True, slots=True)
class MemoryChatGenerationResult:
    """One completed chat turn plus the ephemeral retrieval context used."""

    generation: ChatGenerationResult
    context: ContextBundle
    embedding_model: ModelInfo
    evidence_selection: MemoryEvidenceSelection


class MemoryAugmentedChatService:
    """Retrieve typed local evidence, build context, then call the Primary Model.

    Retrieval happens before the new user message is persisted. This prevents
    the current query from entering the search index and being retrieved as its
    own evidence. The rendered context is ephemeral model input only; canonical
    chat persistence remains user/assistant messages.

    Retrieval result types stay distinct: canonical Knowledge/Claims, direct
    user statements, and conversation records are all available to the model,
    but the grounding contract prevents them from being silently conflated.
    """

    def __init__(
        self,
        *,
        chat_generation: ChatGenerationService,
        embedding_provider: LMStudioEmbeddingProvider,
        hybrid_retrieval: HybridRetrievalService,
        context_builder: ContextBuilderService,
        evidence_policy: MemoryEvidencePolicy,
    ) -> None:
        self.chat_generation = chat_generation
        self.embedding_provider = embedding_provider
        self.hybrid_retrieval = hybrid_retrieval
        self.context_builder = context_builder
        self.evidence_policy = evidence_policy

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        max_context_tokens: int = 1200,
        max_context_items: int = 8,
        allow_model_prior: bool = True,
        on_delta: Callable[[str], None] | None = None,
    ) -> MemoryChatGenerationResult:
        if not 128 <= max_context_tokens <= 64_000:
            raise ContextBuilderError(
                "Context token budget must be between 128 and 64000."
            )
        if not 1 <= max_context_items <= 100:
            raise ContextBuilderError(
                "Context max-items must be between 1 and 100."
            )

        # Resolve and retrieve before ChatGenerationService persists the new
        # user message. This is an intentional anti-self-retrieval boundary.
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
        context = self.context_builder.build_from_hybrid(
            query=content,
            results=evidence_selection.results,
            max_estimated_tokens=max_context_tokens,
            max_items=max_context_items,
        )

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

        grounding_contract = GroundingContract(
            evidence_refs=tuple(evidence_refs),
            allow_model_prior=allow_model_prior,
        )
        generation = self.chat_generation.send_message(
            chat_id=chat_id,
            content=content,
            requested_model_id=requested_model_id,
            on_delta=on_delta,
            retrieved_context=context.rendered_text,
            grounding_contract=grounding_contract,
        )
        return MemoryChatGenerationResult(
            generation=generation,
            context=context,
            embedding_model=embedding_model,
            evidence_selection=evidence_selection,
        )
