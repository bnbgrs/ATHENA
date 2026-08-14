from __future__ import annotations

from dataclasses import dataclass

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.models import KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import KnowledgeService
from athena.retrieval.search import SearchEntityType
from athena.retrieval.semantic import LocalSemanticSearchService
from athena.storage.database import SQLiteDatabase


@dataclass
class FakeEmbeddingProvider:
    calls: int = 0

    def embed(self, *, model_id: str, texts):
        self.calls += 1
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


def test_semantic_search_finds_nonlexical_related_document(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(KnowledgeRepository(database), chat)
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Berlin ist der Regierungssitz Deutschlands.",
        )
        revision = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        provider = FakeEmbeddingProvider()
        semantic = LocalSemanticSearchService(database, provider, batch_size=2)
        results = semantic.search(
            "Hauptstadt Deutschland",
            model_id="fake-embed",
            limit=10,
        )
        assert results
        assert results[0].entity_id == revision.knowledge_id
        assert results[0].entity_type is SearchEntityType.KNOWLEDGE
        assert results[0].similarity > 0.0
        status = semantic.status("fake-embed")
        assert status is not None
        assert status.current
        assert status.document_count >= 2
    finally:
        database.stop()


def test_semantic_index_rebuilds_after_canonical_change(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(KnowledgeRepository(database), chat)
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Jupiter ist sichtbar.",
        )
        revision = knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )
        provider = FakeEmbeddingProvider()
        semantic = LocalSemanticSearchService(database, provider)
        first = semantic.ensure_current("fake-embed")
        knowledge.revise(
            knowledge_id=revision.knowledge_id,
            body="Berlin ist der Regierungssitz Deutschlands.",
        )
        second = semantic.ensure_current("fake-embed")
        assert second.indexed_commit_seq > first.indexed_commit_seq
        assert provider.calls >= 2
    finally:
        database.stop()


def test_empty_semantic_index_returns_no_results(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        provider = FakeEmbeddingProvider()
        semantic = LocalSemanticSearchService(database, provider)
        results = semantic.search(
            "anything",
            model_id="fake-embed",
            limit=10,
        )
        assert results == ()
        status = semantic.status("fake-embed")
        assert status is not None
        assert status.document_count == 0
    finally:
        database.stop()



@dataclass
class RecordingEmbeddingProvider:
    inputs: list[tuple[str, ...]]

    def embed(self, *, model_id: str, texts):
        captured = tuple(texts)
        self.inputs.append(captured)
        return tuple((1.0, 0.0, 0.0) for _ in captured)


def test_nomic_retrieval_uses_required_task_prefixes(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(KnowledgeRepository(database), chat)
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Berlin ist der Regierungssitz Deutschlands.",
        )
        knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        provider = RecordingEmbeddingProvider(inputs=[])
        semantic = LocalSemanticSearchService(database, provider)
        semantic.search(
            "Hauptstadt Deutschlands",
            model_id="text-embedding-nomic-embed-text-v1.5",
            limit=10,
        )

        flattened = [text for batch in provider.inputs for text in batch]
        assert any(text.startswith("search_document: ") for text in flattened)
        assert any(text.startswith("search_query: ") for text in flattened)
    finally:
        database.stop()


def test_semantic_documents_exclude_internal_assistant_provenance_manifest(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
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
        provider = RecordingEmbeddingProvider(inputs=[])
        semantic = LocalSemanticSearchService(database, provider)

        semantic.rebuild("fake-embed")

        flattened = [text for batch in provider.inputs for text in batch]
        document_inputs = [text for text in flattened if "Berlin" in text]
        assert document_inputs
        assert all("ATHENA_PROVENANCE" not in text for text in document_inputs)
    finally:
        database.stop()


def test_hnsw_sidecar_rebuilds_from_persisted_vectors_without_reembedding(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    try:
        chat = ChatService(ChatRepository(database))
        knowledge = KnowledgeService(KnowledgeRepository(database), chat)
        chat_id = chat.create_chat()
        message = chat.add_user_message(
            chat_id=chat_id,
            content="Berlin ist der Regierungssitz Deutschlands.",
        )
        knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )
        provider = FakeEmbeddingProvider()
        semantic = LocalSemanticSearchService(database, provider)
        semantic.rebuild("fake-embed")
        calls_after_embedding_rebuild = provider.calls

        for path in semantic.hnsw.root.glob("*"):
            path.unlink()

        missing = semantic.status("fake-embed")
        assert missing is not None
        assert not missing.hnsw_ready
        assert not missing.current

        restored = semantic.ensure_current("fake-embed")
        assert restored.current
        assert restored.hnsw_ready
        assert provider.calls == calls_after_embedding_rebuild
    finally:
        database.stop()
