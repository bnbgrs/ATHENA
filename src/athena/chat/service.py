"""Application-facing chat use cases for Vertical Slice 1."""

from __future__ import annotations

import uuid

from athena.chat.models import ChatMessage, ChatSummary, ChatThread, MessageType
from athena.chat.repository import ChatRepository


class EmptyMessageError(ValueError):
    """Raised when a text-only Vertical Slice 1 message has no content."""


class ChatService:
    """Small use-case layer between the Core/CLI and chat persistence."""

    _LOCAL_USER_NAME = "Local User"

    def __init__(self, repository: ChatRepository) -> None:
        self.repository = repository

    def ensure_local_user(self) -> uuid.UUID:
        """Return the stable local user actor, creating it on first use."""
        actor_id = self.repository.find_active_actor(
            actor_type="user",
            display_name=self._LOCAL_USER_NAME,
        )
        if actor_id is not None:
            return actor_id

        return self.repository.create_actor(
            actor_type="user",
            display_name=self._LOCAL_USER_NAME,
        )

    def create_chat(self) -> uuid.UUID:
        user_id = self.ensure_local_user()
        return self.repository.create_chat(actor_id=user_id)

    def add_user_message(self, *, chat_id: uuid.UUID, content: str) -> ChatMessage:
        if not content.strip():
            raise EmptyMessageError("A chat message must contain non-whitespace text.")

        user_id = self.ensure_local_user()
        return self.repository.append_message(
            chat_id=chat_id,
            actor_id=user_id,
            message_type=MessageType.USER,
            content=content,
        )


    def ensure_primary_model(self, *, provider_id: str, model_id: str) -> uuid.UUID:
        """Return a stable primary-model actor for one backend model."""
        display_name = f"{provider_id}:{model_id}"
        actor_id = self.repository.find_active_actor(
            actor_type="primary_model",
            display_name=display_name,
        )
        if actor_id is not None:
            return actor_id

        return self.repository.create_actor(
            actor_type="primary_model",
            display_name=display_name,
        )

    def add_assistant_message(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        provider_id: str,
        model_id: str,
    ) -> ChatMessage:
        if not content.strip():
            raise EmptyMessageError("An assistant message must contain non-whitespace text.")

        actor_id = self.ensure_primary_model(
            provider_id=provider_id,
            model_id=model_id,
        )
        return self.repository.append_message(
            chat_id=chat_id,
            actor_id=actor_id,
            message_type=MessageType.ASSISTANT,
            content=content,
        )

    def load_chat(self, chat_id: uuid.UUID) -> ChatThread:
        return self.repository.load_chat(chat_id)

    def list_chats(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatSummary, ...]:
        return self.repository.list_chats(
            limit=limit,
            offset=offset,
        )
