"""Transport-neutral v1 API facade over existing ATHENA domain services."""

from __future__ import annotations

import uuid
from typing import Protocol

from athena.api.contracts import (
    API_VERSION,
    CapabilitiesResponse,
    ChatMessageResponse,
    ChatSummaryResponse,
    ChatThreadResponse,
    DeletionDependencyResponse,
    DeletionPreviewResponse,
    DeletionResultResponse,
    GroundedChatResponse,
    GroundedEvidenceResponse,
    GroundedMemoryResponse,
    GroundingResponse,
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.chat.models import ChatMessage, ChatSummary, ChatThread
from athena.chat.provenance import strip_durable_provenance_manifest
from athena.chat.service import ChatService
from athena.chat.unified import UnifiedLocalChatResult
from athena.lifecycle.service import (
    DeletionPreview,
    DeletionResult,
    LifecycleDeletionService,
)
from athena.model.domain import ModelInfo
from athena.model.ports import ModelDiscoveryProvider
from athena.observability.health import HealthService


class DirectChatSender(Protocol):
    """Minimal direct-chat orchestration boundary used by the API."""

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = 2048,
        temperature: float | None = None,
        reasoning_mode: str | None = "off",
    ) -> object: ...

class UnifiedLocalChatSender(Protocol):
    """Minimal Unified Local orchestration boundary used by the API."""

    def send_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        effective_context_limit: int | None = None,
        output_reserve: int = 2048,
        temperature: float | None = None,
        reasoning_mode: str | None = "off",
    ) -> UnifiedLocalChatResult: ...

class CoreApiFacade:
    """Stable client boundary used by desktop and future transports.

    The facade deliberately exposes DTOs instead of repositories, SQLite rows,
    provider payloads, or other implementation details. HTTP/ASGI can be added
    around this boundary without changing domain services.
    """

    _FEATURES = (
        "health",
        "capabilities",
        "chat.read",
        "chat.create",
        "models.read",
    )

    def __init__(
        self,
        *,
        health: HealthService,
        chat: ChatService,
        model_provider: ModelDiscoveryProvider,
        direct_chat: DirectChatSender | None = None,
        lifecycle_deletion: LifecycleDeletionService | None = None,
    ) -> None:
        self._health = health
        self._chat = chat
        self._model_provider = model_provider
        self._direct_chat = direct_chat
        self._lifecycle_deletion = lifecycle_deletion
        self._unified_local_chat: UnifiedLocalChatSender | None = None

    def attach_unified_local_chat(
        self,
        sender: UnifiedLocalChatSender,
    ) -> None:
        """Attach Unified Local chat exactly once after app construction."""

        if self._unified_local_chat is not None:
            raise RuntimeError(
                "Unified Local chat is already attached to the Core API."
            )
        self._unified_local_chat = sender

    def health(self) -> HealthResponse:
        snapshot = self._health.snapshot()
        return HealthResponse(
            api_version=API_VERSION,
            core_status=snapshot.status.value,
            detail=snapshot.detail,
        )

    def capabilities(self) -> CapabilitiesResponse:
        features: tuple[str, ...] = self._FEATURES
        if self._direct_chat is not None:
            features = (*features, "chat.send.direct")
        if self._unified_local_chat is not None:
            features = (*features, "chat.send.unified_local")
        if self._lifecycle_deletion is not None:
            features = (*features, "chat.delete")
        return CapabilitiesResponse(
            api_version=API_VERSION,
            features=features,
        )

    def list_chats(self, *, limit: int = 50) -> tuple[ChatSummaryResponse, ...]:
        return tuple(_chat_summary(summary) for summary in self._chat.list_chats(limit=limit))

    def create_chat(self) -> ChatThreadResponse:
        chat_id = self._chat.create_chat()
        return _chat_thread(self._chat.load_chat(chat_id))

    def load_chat(self, chat_id: str) -> ChatThreadResponse:
        parsed_chat_id = uuid.UUID(chat_id)
        return _chat_thread(self._chat.load_chat(parsed_chat_id))

    def send_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        requested_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> ChatThreadResponse:
        if self._direct_chat is None:
            raise RuntimeError("Direct chat is unavailable in this Core process.")
        parsed_chat_id = uuid.UUID(chat_id)
        if (
            effective_context_limit is None
            and max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            self._direct_chat.send_message(
                chat_id=parsed_chat_id,
                content=content,
                requested_model_id=requested_model_id,
            )
        elif (
            max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            self._direct_chat.send_message(
                chat_id=parsed_chat_id,
                content=content,
                requested_model_id=requested_model_id,
                effective_context_limit=effective_context_limit,
            )
        else:
            self._direct_chat.send_message(
                chat_id=parsed_chat_id,
                content=content,
                requested_model_id=requested_model_id,
                effective_context_limit=effective_context_limit,
                output_reserve=(
                    2048 if max_output_tokens is None else max_output_tokens
                ),
                temperature=temperature,
                reasoning_mode=(None if thinking_enabled is True else "off"),
            )
        return _chat_thread(self._chat.load_chat(parsed_chat_id))
    def send_unified_local_chat_message(
        self,
        chat_id: str,
        *,
        content: str,
        requested_model_id: str | None = None,
        requested_embedding_model_id: str | None = None,
        effective_context_limit: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        thinking_enabled: bool | None = None,
    ) -> GroundedChatResponse:
        if self._unified_local_chat is None:
            raise RuntimeError(
                "Unified Local chat is unavailable in this Core process."
            )
        parsed_chat_id = uuid.UUID(chat_id)
        if (
            effective_context_limit is None
            and max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            result = self._unified_local_chat.send_message(
                chat_id=parsed_chat_id,
                content=content,
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
            )
        elif (
            max_output_tokens is None
            and temperature is None
            and thinking_enabled is None
        ):
            result = self._unified_local_chat.send_message(
                chat_id=parsed_chat_id,
                content=content,
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
                effective_context_limit=effective_context_limit,
            )
        else:
            result = self._unified_local_chat.send_message(
                chat_id=parsed_chat_id,
                content=content,
                requested_model_id=requested_model_id,
                requested_embedding_model_id=requested_embedding_model_id,
                effective_context_limit=effective_context_limit,
                output_reserve=(
                    2048 if max_output_tokens is None else max_output_tokens
                ),
                temperature=temperature,
                reasoning_mode=(None if thinking_enabled is True else "off"),
            )
        return _grounded_chat_response(
            result,
            self._chat.load_chat(parsed_chat_id),
        )

    def preview_chat_deletion(self, chat_id: str) -> DeletionPreviewResponse:
        if self._lifecycle_deletion is None:
            raise RuntimeError("Chat deletion is unavailable in this Core process.")
        parsed_chat_id = uuid.UUID(chat_id)
        preview = self._lifecycle_deletion.preview(parsed_chat_id)
        if preview.entity_type != "chat":
            raise RuntimeError("Deletion preview resolved a non-chat entity.")
        return _deletion_preview(preview)

    def delete_chat(
        self,
        chat_id: str,
        *,
        preview_digest: str,
    ) -> DeletionResultResponse:
        if self._lifecycle_deletion is None:
            raise RuntimeError("Chat deletion is unavailable in this Core process.")
        parsed_chat_id = uuid.UUID(chat_id)
        result = self._lifecycle_deletion.delete(
            parsed_chat_id,
            preview_digest=preview_digest,
        )
        if result.entity_type != "chat":
            raise RuntimeError("Deletion result resolved a non-chat entity.")
        return _deletion_result(result)

    def provider_health(self) -> ProviderHealthResponse:
        snapshot = self._model_provider.health()
        return ProviderHealthResponse(
            provider=self._model_provider.provider_id,
            status=snapshot.status.value,
            detail=snapshot.detail,
        )

    def list_models(self) -> tuple[ModelResponse, ...]:
        return tuple(_model(model) for model in self._model_provider.discover_models())


def _chat_summary(summary: ChatSummary) -> ChatSummaryResponse:
    return ChatSummaryResponse(
        chat_id=str(summary.chat_id),
        started_at_us=summary.started_at_us,
        ended_at_us=summary.ended_at_us,
        archive_mode=summary.archive_mode,
        lifecycle_state=summary.lifecycle_state,
        message_count=summary.message_count,
    )


def _chat_message(message: ChatMessage) -> ChatMessageResponse:
    content = message.content
    if (
        message.message_type.value == "assistant"
        and content is not None
    ):
        content = strip_durable_provenance_manifest(content)

    return ChatMessageResponse(
        message_id=str(message.message_id),
        chat_id=str(message.chat_id),
        sequence_no=message.sequence_no,
        message_type=message.message_type.value,
        actor_id=None if message.actor_id is None else str(message.actor_id),
        created_at_us=message.created_at_us,
        revision_id=str(message.revision_id),
        content=content,
        content_format=message.content_format,
    )


def _chat_thread(thread: ChatThread) -> ChatThreadResponse:
    return ChatThreadResponse(
        chat_id=str(thread.chat_id),
        started_at_us=thread.started_at_us,
        ended_at_us=thread.ended_at_us,
        archive_mode=thread.archive_mode,
        lifecycle_state=thread.lifecycle_state,
        messages=tuple(_chat_message(message) for message in thread.messages),
    )


def _grounded_chat_response(
    result: UnifiedLocalChatResult,
    thread: ChatThread,
) -> GroundedChatResponse:
    report = result.generation.grounding_report
    if report is None:
        raise RuntimeError(
            "Unified Local chat completed without a grounding report."
        )
    if report.invalid_context_ids:
        raise RuntimeError(
            "Unified Local chat produced invalid grounding references."
        )

    assistant = result.generation.assistant_message
    if assistant.chat_id != thread.chat_id:
        raise RuntimeError(
            "Grounded assistant message belongs to another chat."
        )
    if assistant.content is None:
        raise RuntimeError(
            "Grounded assistant message has no persisted content."
        )
    if not any(
        item.message_id == assistant.message_id
        and item.revision_id == assistant.revision_id
        for item in thread.messages
    ):
        raise RuntimeError(
            "Grounded assistant message is missing from persisted chat."
        )

    assistant_text = strip_durable_provenance_manifest(
        assistant.content
    ).strip()
    if not assistant_text:
        raise RuntimeError(
            "Grounded assistant display projection must not be blank."
        )

    cited_context_ids = tuple(report.cited_context_ids)
    cited = set(cited_context_ids)
    if len(cited) != len(cited_context_ids):
        raise RuntimeError(
            "Grounding report contains duplicate cited context IDs."
        )

    evidence: list[GroundedEvidenceResponse] = []

    for context_item in result.memory_context.items:
        classification = result.evidence_selection.classification_for(
            entity_type=context_item.entity_type,
            entity_id=context_item.entity_id,
            revision_id=context_item.revision_id,
        )
        evidence.append(
            GroundedEvidenceResponse(
                context_id=context_item.context_id,
                evidence_class=classification.evidence_class.value,
                entity_type=context_item.entity_type.value,
                entity_id=str(context_item.entity_id),
                revision_id=str(context_item.revision_id),
                title=context_item.title,
                text=context_item.text,
                cited=context_item.context_id in cited,
                epistemic_status=(
                    None
                    if classification.epistemic_status is None
                    else classification.epistemic_status.value
                ),
                source_id=None,
                representation_id=None,
                source_name=None,
                source_uri=None,
                start_offset=None,
                end_offset=None,
                page_start=None,
                page_end=None,
                quoted_sha256=None,
                truncated=context_item.truncated,
            )
        )

    for source_item in result.source_context.items:
        evidence.append(
            GroundedEvidenceResponse(
                context_id=source_item.context_id,
                evidence_class="source",
                entity_type="source_anchor",
                entity_id=str(source_item.anchor_id),
                revision_id=None,
                title=source_item.source_name,
                text=source_item.text,
                cited=source_item.context_id in cited,
                epistemic_status=None,
                source_id=str(source_item.source_id),
                representation_id=str(source_item.representation_id),
                source_name=source_item.source_name,
                source_uri=source_item.source_uri,
                start_offset=source_item.start_offset,
                end_offset=source_item.end_offset,
                page_start=source_item.page_start,
                page_end=source_item.page_end,
                quoted_sha256=source_item.quoted_hash.hex(),
                truncated=source_item.truncated,
            )
        )

    evidence_ids = tuple(item.context_id for item in evidence)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise RuntimeError(
            "Unified Local chat produced duplicate evidence context IDs."
        )
    if not cited.issubset(evidence_ids):
        raise RuntimeError(
            "Grounding report cites evidence missing from transport output."
        )

    evidence_class_by_id = {
        item.context_id: item.evidence_class
        for item in evidence
    }
    typed_groups = (
        (report.canonical_context_ids, "canonical"),
        (report.user_statement_context_ids, "user_statement"),
        (report.conversation_context_ids, "conversation_record"),
        (report.source_context_ids, "source"),
        (report.research_context_ids, "research"),
        (report.news_context_ids, "news"),
    )
    for context_ids, expected_class in typed_groups:
        for context_id in context_ids:
            if evidence_class_by_id.get(context_id) != expected_class:
                raise RuntimeError(
                    "Grounding evidence class disagrees with transport evidence."
                )

    return GroundedChatResponse(
        thread=_chat_thread(thread),
        assistant_text=assistant_text,
        evidence=tuple(evidence),
        personal_memory=tuple(
            GroundedMemoryResponse(
                context_id=item.context_id,
                memory_id=str(item.memory_id),
                revision_id=str(item.revision_id),
                memory_kind=item.memory_kind,
                scope_kind=item.scope_kind,
                scope_entity_id=(
                    None
                    if item.scope_entity_id is None
                    else str(item.scope_entity_id)
                ),
                content=item.content,
            )
            for item in result.memory_context.memory_items
        ),
        grounding=GroundingResponse(
            cited_context_ids=cited_context_ids,
            canonical_context_ids=tuple(
                report.canonical_context_ids
            ),
            user_statement_context_ids=tuple(
                report.user_statement_context_ids
            ),
            conversation_context_ids=tuple(
                report.conversation_context_ids
            ),
            source_context_ids=tuple(report.source_context_ids),
            research_context_ids=tuple(
                report.research_context_ids
            ),
            news_context_ids=tuple(report.news_context_ids),
            invalid_context_ids=tuple(
                report.invalid_context_ids
            ),
            uses_inference=report.uses_inference,
            uses_model_prior=report.uses_model_prior,
            uses_unknown=report.uses_unknown,
            has_provenance_marker=report.has_provenance_marker,
        ),
        processing_run_id=str(
            result.processing_run.processing_run_id
        ),
        model_id=result.generation.model.backend_model_id,
        embedding_model_id=(
            None
            if result.embedding_model is None
            else result.embedding_model.backend_model_id
        ),
    )



def _deletion_preview(preview: DeletionPreview) -> DeletionPreviewResponse:
    return DeletionPreviewResponse(
        entity_id=str(preview.entity_id),
        entity_type=preview.entity_type,
        lifecycle_state=preview.lifecycle_state,
        dependencies=tuple(
            DeletionDependencyResponse(
                relation=item.relation,
                count=item.count,
                dependent_entity_id=(
                    None
                    if item.dependent_entity_id is None
                    else str(item.dependent_entity_id)
                ),
                dependent_entity_type=item.dependent_entity_type,
            )
            for item in preview.dependencies
        ),
        preview_digest=preview.preview_digest,
    )


def _deletion_result(result: DeletionResult) -> DeletionResultResponse:
    return DeletionResultResponse(
        entity_id=str(result.entity_id),
        entity_type=result.entity_type,
        commit_id=str(result.commit_id),
        deleted_entity_ids=tuple(str(item) for item in result.deleted_entity_ids),
        preview_digest=result.preview_digest,
    )


def _model(model: ModelInfo) -> ModelResponse:
    return ModelResponse(
        provider=model.provider,
        backend_model_id=model.backend_model_id,
        display_name=model.display_name,
        model_type=model.model_type,
        context_capacity=model.context_capacity,
        quantization=model.quantization,
        loaded=model.loaded,
        vision=model.vision,
        trained_for_tool_use=model.trained_for_tool_use,
        loaded_context_length=model.loaded_context_length,
    )
