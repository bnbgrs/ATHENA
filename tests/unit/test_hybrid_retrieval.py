from __future__ import annotations

from dataclasses import dataclass

import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.models import KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import KnowledgeService
from athena.model.adapters.lm_studio import ModelProviderError
from athena.retrieval.degradation import SemanticRetrievalUnavailableError
from athena.retrieval.hybrid import HybridRetrievalService
from athena.retrieval.ranking import RetrievalRankingService
from athena.retrieval.search import LocalSearchService, SearchEntityType
from athena.retrieval.semantic import LocalSemanticSearchService
from athena.storage.database import SQLiteDatabase


@dataclass
class FakeEmbeddingProvider:
    def embed(self, *, model_id: str, texts):
        vectors = []
        for text in texts:
            lowered = text.casefold()
            vectors.append(
                (
                    1.0 if "hauptstadt" in lowered or "regierungssitz" in lowered else 0.0,
                    1.0 if "berlin" in lowered else 0.0,
                    1.0 if "jupiter" in lowered else 0.0,
                )
            )
        return tuple(vectors)


@dataclass
class StableEmbeddingProvider:
    """Return valid deterministic vectors for index setup only."""

    calls: int = 0

    def embed(self, *, model_id: str, texts):
        del model_id
        captured = tuple(texts)
        self.calls += 1
        return tuple(
            (1.0, 0.0, 0.0)
            for _ in captured
        )


def test_hybrid_retrieval_adds_semantic_only_candidate(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(KnowledgeRepository(database), chat)

        berlin_chat = chat.create_chat()
        message = chat.add_user_message(
            chat_id=berlin_chat,
            content="Berlin ist der Regierungssitz Deutschlands.",
        )
        berlin = knowledge.promote_chat_message(
            chat_id=berlin_chat,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        other_chat = chat.create_chat()
        other = chat.add_user_message(
            chat_id=other_chat,
            content="Jupiter besitzt einen großen Sturm.",
        )
        knowledge.promote_chat_message(
            chat_id=other_chat,
            sequence_no=other.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        lexical = RetrievalRankingService(LocalSearchService(database))
        semantic = LocalSemanticSearchService(database, FakeEmbeddingProvider())
        semantic.rebuild("fake-embed")
        hybrid = HybridRetrievalService(lexical, semantic)

        results = hybrid.search(
            "Hauptstadt",
            model_id="fake-embed",
            limit=10,
        )
        assert any(item.entity_id == berlin.knowledge_id for item in results)
        berlin_result = next(
            item for item in results if item.entity_id == berlin.knowledge_id
        )
        assert berlin_result.semantic_score > 0.0
        assert berlin_result.entity_type is SearchEntityType.KNOWLEDGE
    finally:
        database.stop()



def test_hybrid_duplicate_count_does_not_double_count_same_entities(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(KnowledgeRepository(database), chat)

        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Berlin ist die Hauptstadt von Deutschland.",
        )
        knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        lexical = RetrievalRankingService(LocalSearchService(database))
        semantic = LocalSemanticSearchService(database, FakeEmbeddingProvider())
        semantic.rebuild("fake-embed")
        hybrid = HybridRetrievalService(lexical, semantic)

        lexical_results = lexical.search("Berlin")
        lexical_berlin = next(
            item
            for item in lexical_results
            if item.text == "Berlin ist die Hauptstadt von Deutschland."
        )
        hybrid_results = hybrid.search(
            "Berlin",
            model_id="fake-embed",
            limit=10,
        )
        hybrid_berlin = next(
            item
            for item in hybrid_results
            if item.text == "Berlin ist die Hauptstadt von Deutschland."
        )
        assert hybrid_berlin.duplicate_count == lexical_berlin.duplicate_count
    finally:
        database.stop()


@dataclass
class FailingEmbeddingProvider:
    def embed(self, *, model_id: str, texts):
        del model_id, texts
        raise ModelProviderError("synthetic embedding outage")


def test_hybrid_retrieval_exposes_safe_lexical_fallback_after_semantic_outage(
    tmp_path,
) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(
            KnowledgeRepository(database),
            chat,
        )

        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Project Borealis has assigned code 2202.",
        )
        promoted = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        lexical = RetrievalRankingService(
            LocalSearchService(database)
        )
        semantic = LocalSemanticSearchService(
            database,
            StableEmbeddingProvider(),
        )
        semantic.rebuild("broken-embed")

        # Keep this as a real query-time embedding outage rather than merely
        # exercising the absent-index branch.
        semantic.provider = FailingEmbeddingProvider()

        hybrid = HybridRetrievalService(
            lexical,
            semantic,
        )

        with pytest.raises(
            SemanticRetrievalUnavailableError,
            match="knowledge_semantic_unavailable",
        ):
            hybrid.search(
                "Borealis code",
                model_id="broken-embed",
                limit=10,
            )

        fallback = hybrid.search_lexical(
            "Borealis code",
            limit=10,
        )

        assert fallback
        result = next(
            item
            for item in fallback
            if item.entity_id == promoted.knowledge_id
        )
        assert result.lexical_score > 0.0
        assert result.semantic_score == 0.0
    finally:
        database.stop()

def test_hybrid_exposes_stale_semantic_state_and_lexical_fallback(
    tmp_path,
) -> None:
    database = SQLiteDatabase(
        tmp_path / "athena.db"
    )
    database.start()

    try:
        chat = ChatService(
            ChatRepository(database)
        )
        knowledge = KnowledgeService(
            KnowledgeRepository(database),
            chat,
        )

        chat_id = chat.create_chat()

        message = chat.add_user_message(
            chat_id=chat_id,
            content="Project Borealis has assigned code 4404.",
        )

        promoted = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        lexical = RetrievalRankingService(
            LocalSearchService(database)
        )

        semantic = LocalSemanticSearchService(
            database,
            StableEmbeddingProvider(),
        )

        semantic.rebuild("fake-embed")

        hybrid_service = HybridRetrievalService(
            lexical,
            semantic,
        )

        knowledge.revise(
            knowledge_id=promoted.knowledge_id,
            body="Project Borealis has assigned code 5505.",
        )

        with pytest.raises(
            SemanticRetrievalUnavailableError,
            match="knowledge_semantic_unavailable",
        ):
            hybrid_service.search(
                "Borealis code",
                model_id="fake-embed",
                limit=10,
            )

        fallback = hybrid_service.search_lexical(
            "Borealis code",
            limit=10,
        )

        assert fallback

        result = next(
            item
            for item in fallback
            if item.entity_id == promoted.knowledge_id
        )

        assert result.lexical_score > 0.0
        assert result.semantic_score == 0.0
        assert "5505" in result.text

    finally:
        database.stop()
