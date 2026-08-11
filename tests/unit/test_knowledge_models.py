import uuid

import pytest

from athena.knowledge.models import (
    ClaimDraft,
    ClaimEvidenceRef,
    ClaimKind,
    EpistemicStatus,
    EvidenceRole,
    KnowledgeKind,
    KnowledgeUnitDraft,
)


def test_knowledge_unit_draft_normalizes_text() -> None:
    draft = KnowledgeUnitDraft(
        knowledge_kind=KnowledgeKind.DECISION,
        title="  Storage decision  ",
        body="  SQLite stays local.  ",
        epistemic_status=EpistemicStatus.ASSERTED,
    )

    assert draft.title == "Storage decision"
    assert draft.body == "SQLite stays local."


def test_knowledge_unit_draft_rejects_invalid_temporal_range() -> None:
    with pytest.raises(ValueError, match="valid_to_us"):
        KnowledgeUnitDraft(
            knowledge_kind=KnowledgeKind.EVENT,
            body="A bounded event.",
            valid_from_us=20,
            valid_to_us=10,
        )


def test_claim_draft_requires_statement() -> None:
    with pytest.raises(ValueError, match="statement"):
        ClaimDraft(
            claim_kind=ClaimKind.USER_STATEMENT,
            statement="   ",
        )


def test_attributed_opinion_requires_attribution() -> None:
    with pytest.raises(ValueError, match="attributed_to_entity_id"):
        ClaimDraft(
            claim_kind=ClaimKind.ATTRIBUTED_OPINION,
            statement="Source A considers X problematic.",
        )


def test_claim_evidence_requires_concrete_reference() -> None:
    with pytest.raises(ValueError, match="concrete evidence"):
        ClaimEvidenceRef(
            evidence_role=EvidenceRole.SUPPORTS,
            provenance_id=uuid.uuid4(),
        )


def test_claim_evidence_accepts_chat_message_reference() -> None:
    message_id = uuid.uuid4()
    evidence = ClaimEvidenceRef(
        evidence_role=EvidenceRole.ORIGINATES,
        provenance_id=uuid.uuid4(),
        message_id=message_id,
    )

    assert evidence.message_id == message_id
