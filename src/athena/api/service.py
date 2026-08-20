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
    HealthResponse,
    ModelResponse,
    ProviderHealthResponse,
)
from athena.chat.models import ChatMessage, ChatSummary, ChatThread
from athena.chat.service import ChatService
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
    ) -> object: ...


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
    ) -> None:
        self._health = health
        self._chat = chat
        self._model_provider = model_provider
        self._direct_chat = direct_chat

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
    ) -> ChatThreadResponse:
        if self._direct_chat is None:
            raise RuntimeError("Direct chat is unavailable in this Core process.")
        parsed_chat_id = uuid.UUID(chat_id)
        self._direct_chat.send_message(
            chat_id=parsed_chat_id,
            content=content,
            requested_model_id=requested_model_id,
        )
        return _chat_thread(self._chat.load_chat(parsed_chat_id))

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
    return ChatMessageResponse(
        message_id=str(message.message_id),
        chat_id=str(message.chat_id),
        sequence_no=message.sequence_no,
        message_type=message.message_type.value,
        actor_id=None if message.actor_id is None else str(message.actor_id),
        created_at_us=message.created_at_us,
        revision_id=str(message.revision_id),
        content=message.content,
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
