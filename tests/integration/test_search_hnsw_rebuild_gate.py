from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.knowledge.models import KnowledgeKind
from athena.retrieval.archive import ArchiveSemanticSearchService
from athena.retrieval.semantic import LocalSemanticSearchService


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


def _authoritative_snapshot(app: AthenaApplication) -> tuple[tuple[object, ...], ...]:
    connection = app.database.connection
    queries = (
        "SELECT hex(knowledge_id) FROM knowledge_units ORDER BY knowledge_id",
        "SELECT hex(entity_id), hex(current_revision_id) FROM entity_heads ORDER BY entity_id",
        "SELECT hex(revision_id), body FROM knowledge_unit_revisions ORDER BY revision_id",
        "SELECT hex(claim_id) FROM claims ORDER BY claim_id",
        "SELECT hex(source_id), hex(blob_id), lifecycle_state FROM sources ORDER BY source_id",
        "SELECT hex(blob_id), byte_length, hex(integrity_sha256) FROM blob_records ORDER BY blob_id",
    )
    snapshot: list[tuple[object, ...]] = []
    for query in queries:
        rows = connection.execute(query).fetchall()
        snapshot.append(tuple(tuple(row) for row in rows))
    return tuple(snapshot)


def test_destructive_fts_hnsw_rebuild_preserves_authoritative_state(tmp_path: Path) -> None:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    try:
        chat_id = app.chat.create_chat()
        message = app.chat.add_user_message(
            chat_id=chat_id,
            content="Berlin ist der Regierungssitz Deutschlands.",
        )
        knowledge = app.knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.FACT,
        )

        source_path = tmp_path / "source.txt"
        source_path.write_text(
            "Berlin ist der Regierungssitz Deutschlands.\n",
            encoding="utf-8",
        )
        captured = app.sources.capture_file(source_path)
        represented = app.source_text.build(captured.source.source_id)
        app.source_chunks.build_default(
            represented.result.representation.representation_id
        )

        provider = FakeEmbeddingProvider()
        semantic = LocalSemanticSearchService(
            app.database,
            provider,
            hnsw_root=app.paths.derived_root / "hnsw",
        )
        archive_semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )

        app.search.rebuild()
        semantic.rebuild("fake-embed")
        app.archive_search.rebuild()
        archive_semantic.rebuild("fake-embed")
        assert semantic.search("Hauptstadt", model_id="fake-embed")[0].entity_id == knowledge.knowledge_id
        assert archive_semantic.search("Hauptstadt", model_id="fake-embed")

        before = _authoritative_snapshot(app)
        initial_status = semantic.status("fake-embed")
        assert initial_status is not None
        canonical_commit_seq = initial_status.current_commit_seq
        chunk_generation = app.source_chunk_store.current_generation()

        with app.database.write_transaction() as connection:
            connection.execute("DELETE FROM search_fts")
            connection.execute(
                "UPDATE search_index_state SET indexed_commit_seq = 0 WHERE singleton_id = 1"
            )
            connection.execute("DELETE FROM search_embeddings")
            connection.execute("DELETE FROM search_embedding_state")

        with app.source_chunk_store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM fts_archive")
                connection.execute(
                    "UPDATE archive_search_state SET fts_generation = 0 WHERE singleton_id = 1"
                )
                connection.execute("DELETE FROM archive_embeddings")
                connection.execute("DELETE FROM archive_embedding_state")
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

        hnsw_root = app.paths.derived_root / "hnsw"
        for path in hnsw_root.glob("*"):
            path.unlink()

        assert app.search.rebuild() > 0
        canonical_status = semantic.rebuild("fake-embed")
        assert app.archive_search.rebuild() > 0
        archive_status = archive_semantic.rebuild("fake-embed")

        after = _authoritative_snapshot(app)
        assert after == before
        assert canonical_status.current
        assert canonical_status.hnsw_ready
        assert canonical_status.current_commit_seq == canonical_commit_seq
        assert archive_status.current
        assert archive_status.hnsw_ready
        assert archive_status.indexed_chunk_generation == chunk_generation
        assert semantic.search("Hauptstadt", model_id="fake-embed")[0].entity_id == knowledge.knowledge_id
        assert archive_semantic.search("Hauptstadt", model_id="fake-embed")
        assert tuple(hnsw_root.glob("*.usearch"))
        assert tuple(hnsw_root.glob("*.refs"))
    finally:
        app.stop()
