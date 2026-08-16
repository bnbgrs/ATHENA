"""Application-facing use cases for canonical ATHENA KnowledgeUnits."""

from __future__ import annotations

import uuid

from athena.chat.models import MessageType
from athena.chat.provenance import strip_canonical_promotion_trace
from athena.chat.service import ChatService
from athena.knowledge.models import (
    EpistemicStatus,
    KnowledgeKind,
    KnowledgeUnitDraft,
    KnowledgeUnitRevision,
    KnowledgeUnitSnapshot,
    ProvenanceInputRef,
)
from athena.knowledge.repository import KnowledgeRepository


class ChatMessageSequenceError(LookupError):
    """Raised when a chat does not contain the requested message sequence."""


class UnsupportedKnowledgeSourceError(ValueError):
    """Raised when a source message cannot safely become canonical Knowledge."""


class KnowledgeService:
    """Explicit user-driven Knowledge creation and revision use cases."""

    def __init__(self, repository: KnowledgeRepository, chat: ChatService) -> None:
        self.repository = repository
        self.chat = chat

    def promote_chat_message(
        self,
        *,
        chat_id: uuid.UUID,
        sequence_no: int,
        knowledge_kind: KnowledgeKind,
        title: str | None = None,
        epistemic_status: EpistemicStatus = EpistemicStatus.ASSERTED,
    ) -> KnowledgeUnitRevision:
        """Promote one chat message via an explicit user semantic commit.

        No model interprets or rewrites the message in this use case. User-authored
        text remains exact at the Knowledge draft boundary. Assistant-authored text
        is projected deterministically without ephemeral grounding annotations.
        The stable original message revision remains provenance input ordinal 0.
        """
        if sequence_no < 1:
            raise ChatMessageSequenceError("Chat message sequence must be at least 1.")

        thread = self.chat.load_chat(chat_id)
        message = next(
            (item for item in thread.messages if item.sequence_no == sequence_no),
            None,
        )
        if message is None:
            raise ChatMessageSequenceError(
                f"Chat {chat_id} has no message with sequence {sequence_no}."
            )
        if message.content is None:
            raise UnsupportedKnowledgeSourceError(
                "Protected chat content cannot be promoted through the unprotected VS2 path."
            )

        body = message.content
        if message.message_type is MessageType.ASSISTANT:
            body = strip_canonical_promotion_trace(body)

        if not body.strip():
            raise UnsupportedKnowledgeSourceError(
                "Assistant chat content contains no promotable semantic text after "
                "removing technical grounding annotations."
            )

        actor_id = self.chat.ensure_local_user()
        return self.repository.create_knowledge_unit(
            actor_id=actor_id,
            draft=KnowledgeUnitDraft(
                knowledge_kind=knowledge_kind,
                title=title,
                body=body,
                epistemic_status=epistemic_status,
            ),
            source_entity_id=message.message_id,
            source_revision_id=message.revision_id,
            input_role="chat_message_source",
            reason="explicit user promotion from chat",
        )

    def revise(
        self,
        *,
        knowledge_id: uuid.UUID,
        body: str,
        title: str | None = None,
        knowledge_kind: KnowledgeKind | None = None,
        epistemic_status: EpistemicStatus | None = None,
    ) -> KnowledgeUnitRevision:
        """Create a new direct-user revision without inventing model provenance."""
        current = self.repository.load_current(knowledge_id)
        current_payload = current.revision.payload
        actor_id = self.chat.ensure_local_user()
        return self.repository.revise_knowledge_unit(
            actor_id=actor_id,
            knowledge_id=knowledge_id,
            expected_revision_id=current.revision.revision_id,
            draft=KnowledgeUnitDraft(
                knowledge_kind=knowledge_kind or current_payload.knowledge_kind,
                title=title if title is not None else current_payload.title,
                body=body,
                valid_from_us=current_payload.valid_from_us,
                valid_to_us=current_payload.valid_to_us,
                epistemic_status=epistemic_status or current_payload.epistemic_status,
            ),
            reason="direct user revision",
        )

    def load(self, knowledge_id: uuid.UUID) -> KnowledgeUnitSnapshot:
        return self.repository.load_current(knowledge_id)

    def list(self, *, limit: int = 50) -> tuple[KnowledgeUnitSnapshot, ...]:
        return self.repository.list_current(limit=limit)

    def history(self, knowledge_id: uuid.UUID) -> tuple[KnowledgeUnitRevision, ...]:
        return self.repository.list_revisions(knowledge_id)

    def provenance_inputs(
        self,
        provenance_id: uuid.UUID,
    ) -> tuple[ProvenanceInputRef, ...]:
        return self.repository.list_provenance_inputs(provenance_id)
