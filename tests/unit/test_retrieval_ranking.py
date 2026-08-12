from __future__ import annotations

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.claim_service import ClaimService
from athena.knowledge.models import ClaimKind, KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import KnowledgeService
from athena.retrieval.ranking import RetrievalRankingService
from athena.retrieval.search import LocalSearchService, SearchEntityType
from athena.storage.database import SQLiteDatabase


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    knowledge = KnowledgeService(KnowledgeRepository(database), chat)
    claims = ClaimService(ClaimRepository(database), chat)
    search = LocalSearchService(database)
    ranking = RetrievalRankingService(search)
    return database, chat, knowledge, claims, ranking


def test_exact_cross_type_duplicates_are_consolidated_with_knowledge_preferred(tmp_path) -> None:
    database, chat, knowledge, claims, ranking = _services(tmp_path)
    try:
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Berlin ist die Hauptstadt von Deutschland.",
        )
        knowledge_revision = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
            title="Hauptstadt",
        )
        claims.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
        )

        results = ranking.search("Berlin Hauptstadt")
        matching = [
            item
            for item in results
            if "Hauptstadt" in item.text
        ]
        assert len(matching) == 1
        result = matching[0]
        assert result.entity_type is SearchEntityType.KNOWLEDGE
        assert result.entity_id == knowledge_revision.knowledge_id
        assert result.duplicate_count == 2
        assert len(result.duplicate_entity_ids) == 2
    finally:
        database.stop()


def test_near_but_opposite_text_is_not_collapsed(tmp_path) -> None:
    database, chat, knowledge, _claims, ranking = _services(tmp_path)
    try:
        first_chat = chat.create_chat()
        first = chat.add_user_message(
            chat_id=first_chat,
            content="Der Nahverkehr in Berlin ist zuverlässig.",
        )
        knowledge.promote_chat_message(
            chat_id=first_chat,
            sequence_no=first.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        second_chat = chat.create_chat()
        second = chat.add_user_message(
            chat_id=second_chat,
            content="Der Nahverkehr in Berlin ist unzuverlässig.",
        )
        knowledge.promote_chat_message(
            chat_id=second_chat,
            sequence_no=second.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        results = ranking.search("Nahverkehr Berlin", entity_type=SearchEntityType.KNOWLEDGE)
        texts = {item.text for item in results}
        assert "Der Nahverkehr in Berlin ist zuverlässig." in texts
        assert "Der Nahverkehr in Berlin ist unzuverlässig." in texts
    finally:
        database.stop()


def test_authority_prefers_knowledge_when_lexical_match_is_equal(tmp_path) -> None:
    database, chat, knowledge, _claims, ranking = _services(tmp_path)
    try:
        knowledge_chat = chat.create_chat()
        message = chat.add_user_message(
            chat_id=knowledge_chat,
            content="Jupiter besitzt den Großen Roten Fleck.",
        )
        knowledge.promote_chat_message(
            chat_id=knowledge_chat,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        raw_chat = chat.create_chat()
        chat.add_user_message(
            chat_id=raw_chat,
            content="Jupiter besitzt den Großen Roten Fleck und ist sichtbar.",
        )

        results = ranking.search("Jupiter Fleck")
        assert results
        assert results[0].entity_type is SearchEntityType.KNOWLEDGE
        assert results[0].authority_score == 1.0
    finally:
        database.stop()


def test_exact_duplicate_group_preserves_claim_contradiction_signal(tmp_path) -> None:
    database, chat, knowledge, claims, ranking = _services(tmp_path)
    try:
        first_chat = chat.create_chat()
        first = chat.add_user_message(
            chat_id=first_chat,
            content="Berlin ist meistens zuverlässig.",
        )
        first_knowledge = knowledge.promote_chat_message(
            chat_id=first_chat,
            sequence_no=first.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )
        first_claim = claims.promote_chat_message(
            chat_id=first_chat,
            sequence_no=first.sequence_no,
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
        )

        second_chat = chat.create_chat()
        second = chat.add_user_message(
            chat_id=second_chat,
            content="Berlin ist meistens unzuverlässig.",
        )
        second_claim = claims.promote_chat_message(
            chat_id=second_chat,
            sequence_no=second.sequence_no,
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
        )

        claims.mark_contradiction(
            left_claim_id=first_claim.claim_id,
            right_claim_id=second_claim.claim_id,
        )

        results = ranking.search("Berlin zuverlässig")
        matching = [
            item
            for item in results
            if item.entity_id == first_knowledge.knowledge_id
        ]
        assert len(matching) == 1
        assert matching[0].entity_type is SearchEntityType.KNOWLEDGE
        assert matching[0].contradiction_count == 1
        assert matching[0].duplicate_count >= 1
    finally:
        database.stop()
