"""Application-facing use cases for canonical ATHENA Claims."""

from __future__ import annotations

import uuid

from athena.chat.models import MessageType
from athena.chat.provenance import strip_canonical_promotion_trace
from athena.chat.service import ChatService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.models import (
    ClaimDraft,
    ClaimEvidenceRef,
    ClaimKind,
    ClaimRevision,
    ClaimSnapshot,
    EpistemicStatus,
    ProvenanceInputRef,
)
from athena.knowledge.service import (
    ChatMessageSequenceError,
    UnsupportedKnowledgeSourceError,
)


class ClaimService:
    """Explicit user-driven Claim creation, revision, and contradiction linking."""

    def __init__(self, repository: ClaimRepository, chat: ChatService) -> None:
        self.repository = repository
        self.chat = chat

    def promote_chat_message(
        self,
        *,
        chat_id: uuid.UUID,
        sequence_no: int,
        claim_kind: ClaimKind,
        epistemic_status: EpistemicStatus = EpistemicStatus.ASSERTED,
        valid_from_us: int | None = None,
        valid_to_us: int | None = None,
    ) -> ClaimRevision:
        """Promote one chat-message revision to a canonical Claim.

        User-authored text remains exact at the Claim draft boundary. Assistant
        grounding annotations are removed deterministically while the original
        chat revision remains the stable provenance and evidence source.
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

        statement = message.content
        if message.message_type is MessageType.ASSISTANT:
            statement = strip_canonical_promotion_trace(statement)

        if not statement.strip():
            raise UnsupportedKnowledgeSourceError(
                "Assistant chat content contains no promotable semantic text after "
                "removing technical grounding annotations."
            )

        actor_id = self.chat.ensure_local_user()
        return self.repository.create_claim(
            actor_id=actor_id,
            draft=ClaimDraft(
                claim_kind=claim_kind,
                statement=statement,
                epistemic_status=epistemic_status,
                valid_from_us=valid_from_us,
                valid_to_us=valid_to_us,
            ),
            source_entity_id=message.message_id,
            source_revision_id=message.revision_id,
            source_message_id=message.message_id,
            input_role="chat_message_source",
            reason="explicit user claim promotion from chat",
        )

    def revise(
        self,
        *,
        claim_id: uuid.UUID,
        statement: str,
        claim_kind: ClaimKind | None = None,
        epistemic_status: EpistemicStatus | None = None,
    ) -> ClaimRevision:
        """Create a new direct-user Claim revision."""
        current = self.repository.load_current(claim_id)
        payload = current.revision.payload
        actor_id = self.chat.ensure_local_user()
        return self.repository.revise_claim(
            actor_id=actor_id,
            claim_id=claim_id,
            expected_revision_id=current.revision.revision_id,
            draft=ClaimDraft(
                claim_kind=claim_kind or payload.claim_kind,
                statement=statement,
                epistemic_status=epistemic_status or payload.epistemic_status,
                subject_entity_id=payload.subject_entity_id,
                predicate=payload.predicate,
                object_entity_id=payload.object_entity_id,
                attributed_to_entity_id=payload.attributed_to_entity_id,
                valid_from_us=payload.valid_from_us,
                valid_to_us=payload.valid_to_us,
            ),
            reason="direct user claim revision",
        )

    def mark_contradiction(
        self,
        *,
        left_claim_id: uuid.UUID,
        right_claim_id: uuid.UUID,
    ) -> tuple[ClaimEvidenceRef, ClaimEvidenceRef]:
        """Create reciprocal contradiction evidence without deleting either Claim."""
        actor_id = self.chat.ensure_local_user()
        return self.repository.link_contradiction(
            actor_id=actor_id,
            left_claim_id=left_claim_id,
            right_claim_id=right_claim_id,
            reason="explicit user-confirmed contradiction",
        )

    def load(self, claim_id: uuid.UUID) -> ClaimSnapshot:
        return self.repository.load_current(claim_id)

    def list(self, *, limit: int = 50) -> tuple[ClaimSnapshot, ...]:
        return self.repository.list_current(limit=limit)

    def history(self, claim_id: uuid.UUID) -> tuple[ClaimRevision, ...]:
        return self.repository.list_revisions(claim_id)

    def evidence(self, claim_id: uuid.UUID) -> tuple[ClaimEvidenceRef, ...]:
        return self.repository.list_evidence(claim_id)

    def provenance_inputs(
        self,
        provenance_id: uuid.UUID,
    ) -> tuple[ProvenanceInputRef, ...]:
        return self.repository.list_provenance_inputs(provenance_id)
