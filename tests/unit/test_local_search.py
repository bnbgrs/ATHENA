from __future__ import annotations

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.claim_repository import ClaimRepository
from athena.knowledge.claim_service import ClaimService
from athena.knowledge.models import ClaimKind, KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import KnowledgeService
from athena.retrieval.search import LocalSearchService, SearchEntityType, SearchError
from athena.storage.database import SQLiteDatabase


def _services(tmp_path):
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    knowledge = KnowledgeService(KnowledgeRepository(database), chat)
    claims = ClaimService(ClaimRepository(database), chat)
    search = LocalSearchService(database)
    return database, chat, knowledge, claims, search


def test_search_indexes_current_knowledge_claim_and_chat_heads(tmp_path) -> None:
    database, chat, knowledge, claims, search = _services(tmp_path)
    try:
        chat_id = chat.create_chat()
        chat.add_user_message(
            chat_id=chat_id,
            content="Die Sternwarte auf dem Hügel beobachtet Jupiter jede Nacht.",
        )
        knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=1,
            knowledge_kind=KnowledgeKind.FACT,
            title="Lokale Sternwarte",
        )
        claims.promote_chat_message(
            chat_id=chat_id,
            sequence_no=1,
            claim_kind=ClaimKind.FACTUAL_ASSERTION,
        )

        results = search.search("Jupiter")
        assert {item.entity_type for item in results} == {
            SearchEntityType.KNOWLEDGE,
            SearchEntityType.CLAIM,
            SearchEntityType.CHAT_MESSAGE,
        }
        assert all("Jupiter" in item.snippet for item in results)
        assert search.indexed_commit_seq() > 0
    finally:
        database.stop()


def test_search_rebuilds_after_current_knowledge_revision_changes(tmp_path) -> None:
    database, chat, knowledge, _claims, search = _services(tmp_path)
    try:
        chat_id = chat.create_chat()
        chat.add_user_message(chat_id=chat_id, content="Mars ist heute sichtbar.")
        revision = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=1,
            knowledge_kind=KnowledgeKind.FACT,
        )
        assert any(
            item.entity_type is SearchEntityType.KNOWLEDGE
            for item in search.search("Mars")
        )

        knowledge.revise(
            knowledge_id=revision.knowledge_id,
            body="Venus ist heute sichtbar.",
        )
        assert not any(
            item.entity_type is SearchEntityType.KNOWLEDGE
            for item in search.search("Mars", entity_type=SearchEntityType.KNOWLEDGE)
        )
        venus = search.search("Venus", entity_type=SearchEntityType.KNOWLEDGE)
        assert len(venus) == 1
        assert venus[0].entity_id == revision.knowledge_id
    finally:
        database.stop()


def test_search_type_filter_and_safe_query_validation(tmp_path) -> None:
    database, chat, _knowledge, _claims, search = _services(tmp_path)
    try:
        chat_id = chat.create_chat()
        chat.add_user_message(chat_id=chat_id, content="Alpha Beta Gamma")
        results = search.search(
            'Alpha OR "malformed',
            entity_type=SearchEntityType.CHAT_MESSAGE,
        )
        assert len(results) == 1
        assert results[0].entity_type is SearchEntityType.CHAT_MESSAGE

        try:
            search.search("---")
        except SearchError:
            pass
        else:
            raise AssertionError("punctuation-only search must fail")
    finally:
        database.stop()


def test_search_projection_excludes_internal_assistant_provenance_manifest(tmp_path) -> None:
    database, chat, _knowledge, _claims, search = _services(tmp_path)
    try:
        chat_id = chat.create_chat()
        chat.add_assistant_message(
            chat_id=chat_id,
            content=(
                "Berlin ist die Hauptstadt. [MODEL-PRIOR]\n\n"
                'ATHENA_PROVENANCE {"athena_provenance_version":2,"evidence":[]}'
            ),
            provider_id="lm_studio",
            model_id="primary",
        )

        results = search.search(
            "Berlin",
            entity_type=SearchEntityType.CHAT_MESSAGE,
        )

        assert len(results) == 1
        assert results[0].text == "Berlin ist die Hauptstadt. [MODEL-PRIOR]"
        assert "ATHENA_PROVENANCE" not in results[0].text
        assert search.search(
            "athena provenance version",
            entity_type=SearchEntityType.CHAT_MESSAGE,
        ) == ()
    finally:
        database.stop()
