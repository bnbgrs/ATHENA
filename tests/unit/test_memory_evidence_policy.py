from __future__ import annotations

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.retrieval.evidence import EvidenceClass, MemoryEvidencePolicy
from athena.retrieval.hybrid import HybridSearchResult
from athena.retrieval.search import SearchEntityType
from athena.storage.database import SQLiteDatabase


def _hybrid_result(*, entity_type, entity_id, revision_id, text):
    return HybridSearchResult(
        entity_id=entity_id,
        revision_id=revision_id,
        entity_type=entity_type,
        title=None,
        text=text,
        score=0.9,
        lexical_score=0.8,
        semantic_score=0.9,
        authority_score=0.8,
        contradiction_count=0,
        duplicate_count=0,
    )


def test_policy_distinguishes_user_and_assistant_chat_records(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        chat_id = chat.create_chat()
        user = chat.add_user_message(chat_id=chat_id, content="Mein Auto ist ein Volvo.")
        assistant = chat.add_assistant_message(
            chat_id=chat_id,
            content="Berlin ist seit 1990 Hauptstadt.",
            provider_id="test",
            model_id="primary",
        )

        policy = MemoryEvidencePolicy(database)
        selection = policy.classify(
            (
                _hybrid_result(
                    entity_type=SearchEntityType.CHAT_MESSAGE,
                    entity_id=user.message_id,
                    revision_id=user.revision_id,
                    text=user.content or "",
                ),
                _hybrid_result(
                    entity_type=SearchEntityType.CHAT_MESSAGE,
                    entity_id=assistant.message_id,
                    revision_id=assistant.revision_id,
                    text=assistant.content or "",
                ),
            )
        )

        assert selection.policy_id == "typed-provenance-v1"
        assert selection.classifications[0].evidence_class is EvidenceClass.USER_STATEMENT
        assert selection.classifications[0].message_type == "user"
        assert (
            selection.classifications[1].evidence_class
            is EvidenceClass.CONVERSATION_RECORD
        )
        assert selection.classifications[1].message_type == "assistant"
        assert selection.results[0].text == "Mein Auto ist ein Volvo."
        assert selection.results[1].text == "Berlin ist seit 1990 Hauptstadt."
    finally:
        database.stop()


def test_policy_keeps_knowledge_and_claims_canonical(tmp_path) -> None:
    import uuid

    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        knowledge = _hybrid_result(
            entity_type=SearchEntityType.KNOWLEDGE,
            entity_id=uuid.uuid4(),
            revision_id=uuid.uuid4(),
            text="Berlin ist die Hauptstadt von Deutschland.",
        )
        claim = _hybrid_result(
            entity_type=SearchEntityType.CLAIM,
            entity_id=uuid.uuid4(),
            revision_id=uuid.uuid4(),
            text="München ist die Hauptstadt von Deutschland.",
        )

        selection = MemoryEvidencePolicy(database).classify((knowledge, claim))

        assert tuple(item.evidence_class for item in selection.classifications) == (
            EvidenceClass.CANONICAL,
            EvidenceClass.CANONICAL,
        )
        assert selection.counts == ((EvidenceClass.CANONICAL, 2),)
    finally:
        database.stop()
