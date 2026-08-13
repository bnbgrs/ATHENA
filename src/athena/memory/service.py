"""Application-facing explicit-user Personal Memory use cases."""

from __future__ import annotations

import uuid

from athena.chat.service import ChatService
from athena.common.time import utc_now_us
from athena.memory.models import (
    MemoryKind,
    MemoryLearningMode,
    MemoryScopeKind,
    MemorySensitivity,
    PersonalMemoryDraft,
    PersonalMemoryResetResult,
    PersonalMemoryRevision,
    PersonalMemorySnapshot,
)
from athena.memory.repository import PersonalMemoryRepository


class PersonalMemoryService:
    """Direct-user Personal Memory operations; no model is called in this slice."""

    def __init__(self, repository: PersonalMemoryRepository, chat: ChatService) -> None:
        self.repository = repository
        self.chat = chat

    def remember(
        self,
        *,
        content: str,
        memory_kind: MemoryKind = MemoryKind.OTHER,
        scope_kind: MemoryScopeKind = MemoryScopeKind.GLOBAL,
        scope_entity_id: uuid.UUID | None = None,
        sensitivity: MemorySensitivity = MemorySensitivity.NORMAL,
    ) -> PersonalMemoryRevision:
        actor_id = self.chat.ensure_local_user()
        return self.repository.create(
            actor_id=actor_id,
            draft=PersonalMemoryDraft(
                memory_kind=memory_kind,
                content=content,
                scope_kind=scope_kind,
                scope_entity_id=scope_entity_id,
                learning_mode=MemoryLearningMode.EXPLICIT_USER,
                sensitivity=sensitivity,
                confidence=None,
                last_confirmed_at_us=utc_now_us(),
            ),
            reason="explicit user Personal Memory write",
        )

    def revise(
        self,
        *,
        memory_id: uuid.UUID,
        content: str,
        memory_kind: MemoryKind | None = None,
        scope_kind: MemoryScopeKind | None = None,
        scope_entity_id: uuid.UUID | None = None,
        sensitivity: MemorySensitivity | None = None,
    ) -> PersonalMemoryRevision:
        current = self.repository.load_current(memory_id)
        payload = current.revision.payload
        resolved_scope_kind = scope_kind or payload.scope_kind
        if scope_kind is None:
            resolved_scope_entity_id = (
                scope_entity_id if scope_entity_id is not None else payload.scope_entity_id
            )
        elif resolved_scope_kind is MemoryScopeKind.GLOBAL:
            resolved_scope_entity_id = None
        else:
            resolved_scope_entity_id = scope_entity_id

        actor_id = self.chat.ensure_local_user()
        return self.repository.revise(
            actor_id=actor_id,
            memory_id=memory_id,
            expected_revision_id=current.revision.revision_id,
            draft=PersonalMemoryDraft(
                memory_kind=memory_kind or payload.memory_kind,
                content=content,
                scope_kind=resolved_scope_kind,
                scope_entity_id=resolved_scope_entity_id,
                learning_mode=MemoryLearningMode.EXPLICIT_USER,
                sensitivity=sensitivity or payload.sensitivity,
                confidence=None,
                last_confirmed_at_us=utc_now_us(),
            ),
            reason="direct user Personal Memory revision",
        )

    def confirm(self, memory_id: uuid.UUID) -> PersonalMemoryRevision:
        current = self.repository.load_current(memory_id)
        payload = current.revision.payload
        actor_id = self.chat.ensure_local_user()
        return self.repository.revise(
            actor_id=actor_id,
            memory_id=memory_id,
            expected_revision_id=current.revision.revision_id,
            draft=PersonalMemoryDraft(
                memory_kind=payload.memory_kind,
                content=payload.content,
                scope_kind=payload.scope_kind,
                scope_entity_id=payload.scope_entity_id,
                learning_mode=MemoryLearningMode.EXPLICIT_USER,
                sensitivity=payload.sensitivity,
                confidence=None,
                last_confirmed_at_us=utc_now_us(),
            ),
            reason="explicit user Personal Memory confirmation",
            operation="personal_memory.confirm",
            change_kind="confirm",
        )

    def disable(self, memory_id: uuid.UUID) -> uuid.UUID | None:
        return self.repository.set_lifecycle_state(
            actor_id=self.chat.ensure_local_user(),
            memory_id=memory_id,
            lifecycle_state="inactive",
            reason="explicit user Personal Memory disable",
        )

    def enable(self, memory_id: uuid.UUID) -> uuid.UUID | None:
        return self.repository.set_lifecycle_state(
            actor_id=self.chat.ensure_local_user(),
            memory_id=memory_id,
            lifecycle_state="active",
            reason="explicit user Personal Memory enable",
        )

    def delete(self, memory_id: uuid.UUID) -> uuid.UUID | None:
        return self.repository.set_lifecycle_state(
            actor_id=self.chat.ensure_local_user(),
            memory_id=memory_id,
            lifecycle_state="deleted",
            reason="explicit user Personal Memory delete",
        )

    def reset(self) -> PersonalMemoryResetResult:
        return self.repository.reset_all(
            actor_id=self.chat.ensure_local_user(),
            reason="explicit user Personal Memory bulk reset",
        )

    def load(self, memory_id: uuid.UUID) -> PersonalMemorySnapshot:
        return self.repository.load_current(memory_id)

    def list(
        self,
        *,
        limit: int = 50,
        include_inactive: bool = False,
    ) -> tuple[PersonalMemorySnapshot, ...]:
        return self.repository.list_current(
            limit=limit,
            include_inactive=include_inactive,
        )

    def history(self, memory_id: uuid.UUID) -> tuple[PersonalMemoryRevision, ...]:
        return self.repository.list_revisions(memory_id)
