"""Grounded chat over imported Raw Archive sources."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.generation import ChatGenerationResult, ChatGenerationService
from athena.chat.grounding import GroundingContract, GroundingEvidenceRef
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.model.domain import ModelInfo
from athena.retrieval.archive import ArchiveHybridRetrievalService
from athena.retrieval.context import ContextBuilderError
from athena.retrieval.evidence import EvidenceClass
from athena.retrieval.source_context import SourceContextBuilderService, SourceContextBundle


@dataclass(frozen=True, slots=True)
class SourceGroundedChatResult:
    """One completed chat turn plus the ephemeral source context used."""

    generation: ChatGenerationResult
    context: SourceContextBundle
    embedding_model: ModelInfo


class SourceGroundedChatService:
    """Retrieve archive evidence, materialize SourceAnchors, and ground a reply.

    Retrieval and SourceAnchor materialization happen before the new user
    message is persisted. The model sees persistent ``anchor_id`` values and
    source ranges only; Derived ``chunk_id`` values never cross this boundary.
    """

    def __init__(
        self,
        *,
        chat_generation: ChatGenerationService,
        embedding_provider: LMStudioEmbeddingProvider,
        archive_retrieval: ArchiveHybridRetrievalService,
        context_builder: SourceContextBuilderService,
    ) -> None:
        self.chat_generation = chat_generation
        self.embedding_provider = embedding_provider
        self.archive_retrieval = archive_retrieval
        self.context_builder = context_builder

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
    ) -> SourceGroundedChatResult:
        if not 128 <= max_context_tokens <= 64_000:
            raise ContextBuilderError(
                "Context token budget must be between 128 and 64000."
            )
        if not 1 <= max_context_items <= 100:
            raise ContextBuilderError(
                "Context max-items must be between 1 and 100."
            )

        embedding_model = self.embedding_provider.resolve_model(
            requested_embedding_model_id
        )
        candidate_limit = min(200, max(40, max_context_items * 8))
        results = self.archive_retrieval.search(
            content,
            model_id=embedding_model.backend_model_id,
            limit=candidate_limit,
        )
        context = self.context_builder.build_from_hybrid(
            query=content,
            results=results,
            max_estimated_tokens=max_context_tokens,
            max_items=max_context_items,
        )

        evidence_refs = tuple(
            GroundingEvidenceRef(
                context_id=item.context_id,
                entity_type="source_anchor",
                entity_id=item.anchor_id,
                revision_id=None,
                evidence_class=EvidenceClass.SOURCE,
                source_id=item.source_id,
                representation_id=item.representation_id,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                quoted_hash=item.quoted_hash,
            )
            for item in context.items
        )
        grounding_contract = GroundingContract(
            evidence_refs=evidence_refs,
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
        return SourceGroundedChatResult(
            generation=generation,
            context=context,
            embedding_model=embedding_model,
        )
