"""Canonical domain types for ATHENA Personal Memory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class MemoryKind(str, Enum):
    """Core Personal-Memory kinds from the Beta specification."""

    RESPONSE_STYLE = "response_style"
    LANGUAGE_PREFERENCE = "language_preference"
    DETAIL_PREFERENCE = "detail_preference"
    WORKFLOW_PREFERENCE = "workflow_preference"
    MODEL_PREFERENCE = "model_preference"
    TOOL_PREFERENCE = "tool_preference"
    RECURRING_SETTING = "recurring_setting"
    INTERACTION_PREFERENCE = "interaction_preference"
    OTHER = "other"


class MemoryScopeKind(str, Enum):
    """Supported Personal-Memory scope classes."""

    GLOBAL = "global"
    PROJECT = "project"
    WORKFLOW = "workflow"
    CLIENT = "client"


class MemoryLearningMode(str, Enum):
    """How one Personal-Memory revision entered the canonical store."""

    EXPLICIT_USER = "explicit_user"
    MODEL_INFERRED = "model_inferred"
    IMPORTED = "imported"


class MemorySensitivity(str, Enum):
    """Protection classification for Personal Memory."""

    NORMAL = "normal"
    SENSITIVE = "sensitive"
    PROTECTED = "protected"


@dataclass(frozen=True, slots=True)
class PersonalMemoryDraft:
    """Unprotected Personal-Memory payload for one immutable revision."""

    memory_kind: MemoryKind
    content: str
    scope_kind: MemoryScopeKind = MemoryScopeKind.GLOBAL
    scope_entity_id: uuid.UUID | None = None
    learning_mode: MemoryLearningMode = MemoryLearningMode.EXPLICIT_USER
    sensitivity: MemorySensitivity = MemorySensitivity.NORMAL
    confidence: float | None = None
    last_confirmed_at_us: int | None = None

    def __post_init__(self) -> None:
        normalized = self.content.strip()
        if not normalized:
            raise ValueError("Personal Memory content must not be empty.")
        object.__setattr__(self, "content", normalized)

        if self.scope_kind is MemoryScopeKind.GLOBAL:
            if self.scope_entity_id is not None:
                raise ValueError("Global Personal Memory must not have scope_entity_id.")
        elif self.scope_entity_id is None:
            raise ValueError("Scoped Personal Memory requires scope_entity_id.")

        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Personal Memory confidence must be between 0 and 1.")
        if self.learning_mode is MemoryLearningMode.EXPLICIT_USER and self.confidence is not None:
            raise ValueError("Explicit user Personal Memory must not invent model confidence.")
        if self.last_confirmed_at_us is not None and self.last_confirmed_at_us < 0:
            raise ValueError("last_confirmed_at_us must not be negative.")


@dataclass(frozen=True, slots=True)
class PersonalMemoryRevision:
    memory_id: uuid.UUID
    revision_id: uuid.UUID
    revision_no: int
    created_at_us: int
    created_by_actor_id: uuid.UUID
    provenance_id: uuid.UUID
    payload: PersonalMemoryDraft

    def __post_init__(self) -> None:
        if self.revision_no < 1:
            raise ValueError("revision_no must be at least 1.")


@dataclass(frozen=True, slots=True)
class PersonalMemorySnapshot:
    """Current state of one stable Personal-Memory entity."""

    memory_id: uuid.UUID
    lifecycle_state: str
    revision: PersonalMemoryRevision


@dataclass(frozen=True, slots=True)
class PersonalMemoryResetResult:
    """Result of one explicit bulk reset operation."""

    commit_id: uuid.UUID | None
    deleted_count: int
