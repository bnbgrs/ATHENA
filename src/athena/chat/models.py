"""Persistent chat domain models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class MessageType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    SYSTEM_EVENT = "system_event"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    message_id: uuid.UUID
    chat_id: uuid.UUID
    sequence_no: int
    message_type: MessageType
    actor_id: uuid.UUID | None
    created_at_us: int
    revision_id: uuid.UUID
    content: str | None
    content_format: str | None


@dataclass(frozen=True, slots=True)
class ChatThread:
    chat_id: uuid.UUID
    started_at_us: int
    ended_at_us: int | None
    archive_mode: str
    lifecycle_state: str
    messages: tuple[ChatMessage, ...]


@dataclass(frozen=True, slots=True)
class ChatSummary:
    chat_id: uuid.UUID
    started_at_us: int
    ended_at_us: int | None
    archive_mode: str
    lifecycle_state: str
    message_count: int
