"""Application-facing explicit-user Personal Memory use cases."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from athena.chat.models import ChatMessage
from athena.chat.service import ChatService
from athena.common.time import utc_now_us
from athena.memory.explicit_command import (
    ExplicitMemoryIntent,
    parse_explicit_personal_memory_command,
)
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


@dataclass(frozen=True, slots=True)
class ExplicitMemoryCommandWrite:
    """One locally handled explicit Memory command from persistent chat."""

    intent: ExplicitMemoryIntent
    user_message: ChatMessage
    memory_revision: PersonalMemoryRevision


class PersonalMemoryService:
    """Direct-user Personal Memory operations; no model is called in this slice."""

    def __init__(self, repository: PersonalMemoryRepository, chat: ChatService) -> None:
        self.repository = repository
        self.chat = chat
        self._deletion_sync_callback: Callable[[], object] | None = None

    def set_deletion_sync_callback(
        self,
        callback: Callable[[], object] | None,
    ) -> None:
        """Configure best-effort post-commit deletion propagation."""
        self._deletion_sync_callback = callback

    def _sync_deletion_targets(self) -> None:
        callback = self._deletion_sync_callback

        if callback is not None:
            callback()

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

    def remember_explicit_chat_command(
        self,
        *,
        chat_id: uuid.UUID,
        content: str,
        scope_kind: MemoryScopeKind | None = None,
        scope_entity_id: uuid.UUID | None = None,
    ) -> ExplicitMemoryCommandWrite | None:
        """Handle one unambiguous Personal Memory command without a model call."""
        intent = parse_explicit_personal_memory_command(
            content,
            scope_kind=scope_kind,
            scope_entity_id=scope_entity_id,
        )
        if intent is None:
            return None

        # Validate the target chat before creating durable Memory.
        self.chat.load_chat(chat_id)
        user_message = self.chat.add_user_message(chat_id=chat_id, content=content)
        revision = self.remember(
            content=intent.memory_content,
            memory_kind=intent.memory_kind,
            scope_kind=intent.scope_kind,
            scope_entity_id=intent.scope_entity_id,
            sensitivity=MemorySensitivity.NORMAL,
        )
        return ExplicitMemoryCommandWrite(
            intent=intent,
            user_message=user_message,
            memory_revision=revision,
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
        commit_id = self.repository.set_lifecycle_state(
            actor_id=self.chat.ensure_local_user(),
            memory_id=memory_id,
            lifecycle_state="deleted",
            reason="explicit user Personal Memory delete",
        )
        self._sync_deletion_targets()
        return commit_id

    def reset(self) -> PersonalMemoryResetResult:
        result = self.repository.reset_all(
            actor_id=self.chat.ensure_local_user(),
            reason="explicit user Personal Memory bulk reset",
        )
        self._sync_deletion_targets()
        return result

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

    def context_candidates(
        self,
        *,
        scope_kind: MemoryScopeKind | None = None,
        scope_entity_id: uuid.UUID | None = None,
        limit: int = 32,
    ) -> tuple[PersonalMemorySnapshot, ...]:
        """Return deterministic active Memory candidates for one model call.

        Global core collaboration preferences are eligible everywhere. Scoped
        entries are eligible only for an exact current scope match. Protected
        entries cannot exist in the v1 plaintext repository, so this method never
        silently unlocks protected content.
        """
        if not 1 <= limit <= 100:
            raise ValueError("Personal Memory context limit must be between 1 and 100.")
        if scope_kind is None and scope_entity_id is not None:
            raise ValueError("scope_entity_id requires scope_kind.")
        if scope_kind is MemoryScopeKind.GLOBAL and scope_entity_id is not None:
            raise ValueError("Global context scope must not have scope_entity_id.")
        if scope_kind is not None and scope_kind is not MemoryScopeKind.GLOBAL:
            if scope_entity_id is None:
                raise ValueError("Scoped context requires scope_entity_id.")

        snapshots = self.repository.list_current(limit=500, include_inactive=False)
        core_kinds = {
            MemoryKind.RESPONSE_STYLE,
            MemoryKind.LANGUAGE_PREFERENCE,
            MemoryKind.DETAIL_PREFERENCE,
            MemoryKind.INTERACTION_PREFERENCE,
        }

        def priority(snapshot: PersonalMemorySnapshot) -> tuple[int, int, str]:
            payload = snapshot.revision.payload
            if payload.scope_kind is MemoryScopeKind.GLOBAL and payload.memory_kind in core_kinds:
                tier = 0
            elif (
                scope_kind is not None
                and scope_kind is not MemoryScopeKind.GLOBAL
                and payload.scope_kind is scope_kind
                and payload.scope_entity_id == scope_entity_id
            ):
                tier = 1
            elif payload.scope_kind is MemoryScopeKind.GLOBAL:
                tier = 2
            else:
                tier = 3
            return (tier, -snapshot.revision.created_at_us, str(snapshot.memory_id))

        eligible = []
        for snapshot in snapshots:
            payload = snapshot.revision.payload
            if payload.scope_kind is MemoryScopeKind.GLOBAL:
                eligible.append(snapshot)
                continue
            if (
                scope_kind is not None
                and scope_kind is not MemoryScopeKind.GLOBAL
                and payload.scope_kind is scope_kind
                and payload.scope_entity_id == scope_entity_id
            ):
                eligible.append(snapshot)

        return tuple(sorted(eligible, key=priority)[:limit])
