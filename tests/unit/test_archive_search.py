from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.model.adapters.lm_studio import ModelProviderError
from athena.retrieval.archive import (
    ArchiveHybridRetrievalService,
    ArchiveSearchError,
    ArchiveSemanticSearchService,
)
from athena.retrieval.degradation import SemanticRetrievalUnavailableError
from athena.source.chunk_store import SourceChunkStore


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
                    1.0
                    if "hauptstadt" in lowered or "regierungssitz" in lowered
                    else 0.0,
                    1.0 if "berlin" in lowered else 0.0,
                    1.0 if "jupiter" in lowered else 0.0,
                )
            )
        return tuple(vectors)


@dataclass
class RecordingEmbeddingProvider:
    inputs: list[tuple[str, ...]]

    def embed(self, *, model_id: str, texts):
        captured = tuple(texts)
        self.inputs.append(captured)
        return tuple((1.0, 0.0, 0.0) for _ in captured)


def _started_app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def _build_chunks(app: AthenaApplication, tmp_path: Path, name: str, text: str):
    original = tmp_path / name
    original.write_text(text, encoding="utf-8", newline="")
    captured = app.sources.capture_file(original)
    represented = app.source_text.build(captured.source.source_id)
    built = app.source_chunks.build_default(
        represented.result.representation.representation_id
    )
    return captured.source, represented.result.representation, built


def test_archive_lexical_search_returns_verified_stable_anchor_inputs(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        source, representation, built = _build_chunks(
            app,
            tmp_path,
            "notes.md",
            "Berlin ist die Hauptstadt Deutschlands.\n\nWeitere Notiz.\n",
        )

        results = app.archive_search.search("Berlin Hauptstadt")

        assert results
        result = results[0]
        assert result.chunk_id == built.chunks[0].chunk_id
        assert result.source_id == source.source_id
        assert result.representation_id == representation.representation_id
        assert result.start_anchor_value == 0
        assert result.end_anchor_value == len(result.text)
        assert result.stable_anchor_key == (
            representation.representation_id,
            result.start_anchor_value,
            result.end_anchor_value,
            result.content_hash,
        )
        assert result.source_name == "notes.md"
        assert "Berlin" in result.snippet
        # Archive chunks stay out of the canonical/chat FTS path until durable
        # SourceAnchor grounding is available.
        assert app.search.search("Weitere") == ()
    finally:
        app.stop()


def test_archive_search_rebuild_changes_chunk_id_but_preserves_anchor_inputs(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        _source, representation, first = _build_chunks(
            app,
            tmp_path,
            "rebuild.txt",
            "Alpha Berlin Beta\n",
        )
        before = app.archive_search.search("Berlin")[0]
        second = app.source_chunks.build_default(representation.representation_id)
        after = app.archive_search.search("Berlin")[0]

        assert first.chunks[0].chunk_id != second.chunks[0].chunk_id
        assert before.chunk_id != after.chunk_id
        assert before.stable_anchor_key == after.stable_anchor_key
        assert before.build_signature == after.build_signature
    finally:
        app.stop()


def test_archive_search_filters_by_source_and_representation(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        source_a, representation_a, _ = _build_chunks(
            app, tmp_path, "a.txt", "Berlin alpha\n"
        )
        source_b, representation_b, _ = _build_chunks(
            app, tmp_path, "b.txt", "Berlin beta\n"
        )

        source_results = app.archive_search.search(
            "Berlin", source_id=source_a.source_id
        )
        representation_results = app.archive_search.search(
            "Berlin", representation_id=representation_b.representation_id
        )

        assert {item.source_id for item in source_results} == {source_a.source_id}
        assert {item.representation_id for item in representation_results} == {
            representation_b.representation_id
        }
        assert all(item.source_id != source_b.source_id for item in source_results)
        assert representation_a.representation_id != representation_b.representation_id
    finally:
        app.stop()


def test_archive_search_fails_closed_when_fts_body_is_tampered(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        _source, _representation, built = _build_chunks(
            app, tmp_path, "tamper.txt", "Berlin original evidence\n"
        )
        chunk = built.chunks[0]
        with app.source_chunk_store.connect() as connection:
            connection.execute(
                "UPDATE fts_archive SET body = 'Berlin tampered evidence' WHERE chunk_id = ?",
                (chunk.chunk_id.hex,),
            )

        with pytest.raises(ArchiveSearchError, match="FTS disagrees"):
            app.archive_search.search("Berlin")
    finally:
        app.stop()


def test_archive_semantic_search_finds_nonlexical_related_chunk(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        source, _representation, _ = _build_chunks(
            app,
            tmp_path,
            "semantic.txt",
            "Berlin ist der Regierungssitz Deutschlands.\n",
        )
        provider = FakeEmbeddingProvider()
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
            batch_size=2,
        )
        semantic.rebuild("fake-embed")

        results = semantic.search("Hauptstadt", model_id="fake-embed", limit=10)

        assert results
        assert results[0].source_id == source.source_id
        assert results[0].similarity > 0.0
        status = semantic.status("fake-embed")
        assert status is not None and status.current
        assert status.document_count == 1
    finally:
        app.stop()


def test_archive_embedding_index_becomes_stale_after_chunk_rebuild(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        _source, representation, _ = _build_chunks(
            app, tmp_path, "stale.txt", "Berlin Regierungssitz\n"
        )
        provider = FakeEmbeddingProvider()
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )
        first = semantic.rebuild("fake-embed")

        app.source_chunks.build_default(representation.representation_id)
        stale = semantic.status("fake-embed")
        assert stale is not None
        assert not stale.current
        assert stale.current_chunk_generation > first.indexed_chunk_generation

        calls_before_search = provider.calls

        with pytest.raises(
            ArchiveSearchError,
            match="stale",
        ):
            semantic.search(
                "Berlin",
                model_id="fake-embed",
                limit=10,
            )

        assert provider.calls == calls_before_search

        second = semantic.ensure_current("fake-embed")
        assert second.current
        assert second.indexed_chunk_generation > first.indexed_chunk_generation
        assert provider.calls > calls_before_search
    finally:
        app.stop()


def test_archive_nomic_embeddings_use_document_and_query_prefixes(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        _build_chunks(app, tmp_path, "nomic.txt", "Berlin text\n")
        provider = RecordingEmbeddingProvider(inputs=[])
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )
        semantic.rebuild(
            "text-embedding-nomic-embed-text-v1.5"
        )

        semantic.search(
            "Hauptstadt",
            model_id="text-embedding-nomic-embed-text-v1.5",
            limit=10,
        )

        flattened = [text for batch in provider.inputs for text in batch]
        assert any(text.startswith("search_document: ") for text in flattened)
        assert any(text.startswith("search_query: ") for text in flattened)
    finally:
        app.stop()


def test_archive_hybrid_can_return_semantic_only_candidate(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        source, _representation, _ = _build_chunks(
            app,
            tmp_path,
            "hybrid.txt",
            "Berlin ist der Regierungssitz Deutschlands.\n",
        )
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=FakeEmbeddingProvider(),
        )
        semantic.rebuild("fake-embed")
        hybrid = ArchiveHybridRetrievalService(app.archive_search, semantic)

        results = hybrid.search("Hauptstadt", model_id="fake-embed", limit=10)

        assert results
        berlin = next(item for item in results if item.source_id == source.source_id)
        assert berlin.lexical_score == 0.0
        assert berlin.semantic_score > 0.0
    finally:
        app.stop()


def test_derived_v1_store_migrates_and_backfills_archive_fts(tmp_path) -> None:
    derived_root = tmp_path / "derived"
    derived_root.mkdir(parents=True)
    path = derived_root / "search.db"
    connection = sqlite3.connect(path, autocommit=True)
    connection.executescript(
        """
        PRAGMA application_id = 1096042564;
        CREATE TABLE source_chunk_builds (
            representation_id BLOB(16) NOT NULL,
            chunking_profile_id BLOB(16) NOT NULL,
            build_signature BLOB(32) NOT NULL,
            processing_run_id BLOB(16) NOT NULL,
            created_at_us INTEGER NOT NULL,
            PRIMARY KEY(representation_id, chunking_profile_id)
        ) WITHOUT ROWID;
        CREATE TABLE source_chunks (
            chunk_id BLOB(16) PRIMARY KEY,
            source_id BLOB(16) NOT NULL,
            representation_id BLOB(16) NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunking_profile_id BLOB(16) NOT NULL,
            anchor_id BLOB(16) NULL,
            start_anchor_value INTEGER NOT NULL,
            end_anchor_value INTEGER NOT NULL,
            content_hash BLOB(32) NOT NULL,
            processing_run_id BLOB(16) NOT NULL,
            build_signature BLOB(32) NOT NULL,
            chunk_text TEXT NOT NULL,
            created_at_us INTEGER NOT NULL,
            UNIQUE(representation_id, chunking_profile_id, chunk_index)
        ) WITHOUT ROWID;
        CREATE INDEX idx_source_chunks_representation
            ON source_chunks(representation_id, chunk_index);
        CREATE INDEX idx_source_chunks_source
            ON source_chunks(source_id, representation_id);
        PRAGMA user_version = 1;
        """
    )
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    representation_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    run_id = uuid.uuid4()
    text = "legacy Berlin chunk"
    digest = hashlib.sha256(text.encode()).digest()
    connection.execute(
        """
        INSERT INTO source_chunks (
            chunk_id, source_id, representation_id, chunk_index,
            chunking_profile_id, anchor_id, start_anchor_value,
            end_anchor_value, content_hash, processing_run_id,
            build_signature, chunk_text, created_at_us
        ) VALUES (?, ?, ?, 0, ?, NULL, 0, ?, ?, ?, ?, ?, 1)
        """,
        (
            chunk_id.bytes,
            source_id.bytes,
            representation_id.bytes,
            profile_id.bytes,
            len(text),
            digest,
            run_id.bytes,
            b"b" * 32,
            text,
        ),
    )
    connection.close()

    store = SourceChunkStore(derived_root)
    with store.connect() as migrated:
        assert int(migrated.execute("PRAGMA user_version").fetchone()[0]) == 4
        columns = {
            str(row["name"])
            for row in migrated.execute(
                "PRAGMA table_info('archive_embedding_state')"
            ).fetchall()
        }
        assert "indexed_visibility_commit_seq" in columns
        row = migrated.execute(
            "SELECT chunk_id, body FROM fts_archive WHERE fts_archive MATCH 'Berlin'"
        ).fetchone()
        assert row is not None
        assert row["chunk_id"] == chunk_id.hex
        assert row["body"] == text
        state = migrated.execute(
            "SELECT chunk_generation, fts_generation FROM archive_search_state"
        ).fetchone()
        assert tuple(state) == (1, 1)


def test_archive_hnsw_sidecar_rebuilds_without_reembedding(tmp_path) -> None:
    app = _started_app(tmp_path)
    try:
        _build_chunks(
            app,
            tmp_path,
            "archive-hnsw.txt",
            "Berlin ist der Regierungssitz Deutschlands.\n",
        )
        provider = FakeEmbeddingProvider()
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )
        semantic.rebuild("fake-embed")
        calls_after_embedding_rebuild = provider.calls

        for path in semantic.hnsw.root.glob("*"):
            path.unlink()

        missing = semantic.status("fake-embed")
        assert missing is not None
        assert not missing.hnsw_ready
        assert not missing.current

        with pytest.raises(
            ArchiveSearchError,
            match="HNSW",
        ):
            semantic.search(
                "Berlin",
                model_id="fake-embed",
                limit=10,
            )

        assert provider.calls == calls_after_embedding_rebuild

        still_missing = semantic.status("fake-embed")
        assert still_missing is not None
        assert not still_missing.hnsw_ready

        restored = semantic.ensure_current("fake-embed")
        assert restored.current
        assert restored.hnsw_ready
        assert provider.calls == calls_after_embedding_rebuild
    finally:
        app.stop()


@dataclass
class FailingArchiveEmbeddingProvider:
    def embed(self, *, model_id: str, texts):
        del model_id, texts
        raise ModelProviderError("synthetic archive embedding outage")


def test_archive_hybrid_degrades_only_after_verified_lexical_path_succeeds(
    tmp_path,
) -> None:
    app = _started_app(tmp_path)
    try:
        source, _representation, _built = _build_chunks(
            app,
            tmp_path,
            "fallback.txt",
            "Project Borealis has assigned code 3303.\n",
        )
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=RecordingEmbeddingProvider(inputs=[]),
        )
        semantic.rebuild("broken-embed")

        # Establish a valid index first, then simulate only query-time
        # provider failure. This keeps provider outage distinct from the new
        # absent/stale-index contract.
        semantic.provider = FailingArchiveEmbeddingProvider()

        hybrid = ArchiveHybridRetrievalService(
            app.archive_search,
            semantic,
        )

        with pytest.raises(
            SemanticRetrievalUnavailableError,
            match="archive_semantic_unavailable",
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
            if item.source_id == source.source_id
        )
        assert result.lexical_score > 0.0
        assert result.semantic_score == 0.0
    finally:
        app.stop()

def test_archive_semantic_search_absent_index_requires_explicit_rebuild(
    tmp_path,
) -> None:
    app = _started_app(tmp_path)

    try:
        _build_chunks(
            app,
            tmp_path,
            "archive-absent.txt",
            "Berlin archive evidence.\n",
        )

        provider = FakeEmbeddingProvider()

        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )

        with pytest.raises(
            ArchiveSearchError,
            match="absent",
        ):
            semantic.search(
                "Berlin",
                model_id="fake-embed",
                limit=10,
            )

        assert provider.calls == 0
        assert semantic.status("fake-embed") is None

    finally:
        app.stop()


def test_archive_embedding_visibility_change_marks_index_stale_and_rebuilds(
    tmp_path,
) -> None:
    app = _started_app(tmp_path)
    try:
        source_a, _representation_a, built_a = _build_chunks(
            app,
            tmp_path,
            "visibility-a.txt",
            "Berlin visibility alpha.\n",
        )
        source_b, _representation_b, built_b = _build_chunks(
            app,
            tmp_path,
            "visibility-b.txt",
            "Berlin visibility beta.\n",
        )
        provider = FakeEmbeddingProvider()
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
            batch_size=2,
        )
        published = semantic.rebuild("fake-embed")
        assert published.current
        assert published.document_count == (
            len(built_a.chunks) + len(built_b.chunks)
        )

        generation_before = app.source_chunk_store.current_generation()
        preview = app.lifecycle_deletion.preview(source_a.source_id)
        app.lifecycle_deletion.delete(
            source_a.source_id,
            preview_digest=preview.preview_digest,
        )
        assert app.source_chunk_store.current_generation() == generation_before

        stale = semantic.status("fake-embed")
        assert stale is not None
        assert not stale.current
        assert (
            stale.current_visibility_commit_seq
            > stale.indexed_visibility_commit_seq
        )

        calls_before_search = provider.calls
        with pytest.raises(
            ArchiveSearchError,
            match="stale",
        ):
            semantic.search(
                "Berlin",
                model_id="fake-embed",
                limit=10,
            )
        assert provider.calls == calls_before_search

        calls_before_repair = provider.calls
        repaired = semantic.ensure_current("fake-embed")
        assert repaired.current
        assert provider.calls == calls_before_repair
        assert repaired.document_count == len(built_b.chunks)
        assert (
            repaired.indexed_visibility_commit_seq
            == repaired.current_visibility_commit_seq
        )

        results = semantic.search(
            "Berlin",
            model_id="fake-embed",
            limit=10,
        )
        assert results
        assert {item.source_id for item in results} == {
            source_b.source_id
        }

        with app.source_chunk_store.connect() as connection:
            persisted = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM archive_embeddings
                    WHERE model_id LIKE ?
                      AND indexed_chunk_generation = ?
                    """,
                    (
                        "fake-embed::%",
                        repaired.indexed_chunk_generation,
                    ),
                ).fetchone()[0]
            )
        assert persisted == repaired.document_count
    finally:
        app.stop()


def test_archive_embedding_visibility_watermark_ignores_non_source_commits(
    tmp_path,
) -> None:
    app = _started_app(tmp_path)
    try:
        _build_chunks(
            app,
            tmp_path,
            "visibility-unrelated.txt",
            "Berlin remains visible across unrelated commits.\n",
        )
        provider = FakeEmbeddingProvider()
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )
        published = semantic.rebuild("fake-embed")
        assert published.current

        generation_before = app.source_chunk_store.current_generation()
        visibility_before = published.current_visibility_commit_seq
        provider_calls_before = provider.calls

        chat_id = app.chat.create_chat()
        app.chat.add_user_message(
            chat_id=chat_id,
            content="Unrelated canonical chat commit.",
        )

        assert (
            app.source_chunk_store.current_generation()
            == generation_before
        )

        after = semantic.status("fake-embed")
        assert after is not None
        assert after.current
        assert (
            after.current_visibility_commit_seq
            == visibility_before
        )
        assert (
            after.indexed_visibility_commit_seq
            == visibility_before
        )

        ensured = semantic.ensure_current("fake-embed")
        assert ensured.current
        assert provider.calls == provider_calls_before
    finally:
        app.stop()


def test_v3_archive_embedding_state_migrates_visibility_watermark_fail_closed(
    tmp_path,
) -> None:
    derived_root = tmp_path / "derived-v3"
    derived_root.mkdir(parents=True)
    path = derived_root / "search.db"

    connection = sqlite3.connect(path, autocommit=True)
    connection.executescript(
        """
        PRAGMA application_id = 1096042564;

        CREATE TABLE archive_embedding_state (
            model_id TEXT PRIMARY KEY,
            indexed_chunk_generation INTEGER NOT NULL
                CHECK(indexed_chunk_generation >= 0),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            document_count INTEGER NOT NULL
                CHECK(document_count >= 0),
            rebuilt_at_us INTEGER NOT NULL
        ) WITHOUT ROWID;

        INSERT INTO archive_embedding_state (
            model_id,
            indexed_chunk_generation,
            dimensions,
            document_count,
            rebuilt_at_us
        ) VALUES (
            'legacy-v3-model',
            7,
            3,
            2,
            123
        );

        PRAGMA user_version = 3;
        """
    )
    connection.close()

    store = SourceChunkStore(derived_root)

    with store.connect() as migrated:
        assert (
            int(
                migrated.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            )
            == 4
        )

        row = migrated.execute(
            """
            SELECT
                indexed_chunk_generation,
                indexed_visibility_commit_seq,
                dimensions,
                document_count
            FROM archive_embedding_state
            WHERE model_id = 'legacy-v3-model'
            """
        ).fetchone()

        assert row is not None
        assert tuple(row) == (7, -1, 3, 2)

def test_archive_embedding_snapshot_rejects_derived_source_id_mismatch(
    tmp_path,
) -> None:
    app = _started_app(tmp_path)
    try:
        source, representation, built = _build_chunks(
            app,
            tmp_path,
            "source-id-mismatch.txt",
            "Berlin source identity must remain canonical.\n",
        )
        assert built.chunks

        wrong_source_id = uuid.uuid4()
        assert wrong_source_id != source.source_id

        with app.source_chunk_store.connect() as connection:
            connection.execute(
                """
                UPDATE source_chunks
                SET source_id = ?
                WHERE representation_id = ?
                """,
                (
                    wrong_source_id.bytes,
                    representation.representation_id.bytes,
                ),
            )

        provider = FakeEmbeddingProvider()
        semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )

        with pytest.raises(
            ArchiveSearchError,
            match="source_id",
        ):
            semantic.rebuild("fake-embed")

        assert provider.calls == 0
    finally:
        app.stop()
