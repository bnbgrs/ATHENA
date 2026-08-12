"""Lexical, semantic, and hybrid retrieval over Derived SourceChunks."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import struct
import unicodedata
import uuid
from dataclasses import dataclass

from athena.common.time import utc_now_us
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.source.chunk_store import SourceChunkRecord, SourceChunkStore
from athena.source.chunking_service import SourceChunkingService
from athena.storage.database import SQLiteDatabase


class ArchiveSearchError(RuntimeError):
    """Raised when reconstructible archive retrieval cannot be used safely."""


@dataclass(frozen=True, slots=True)
class ArchiveSearchResult:
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunk_index: int
    chunking_profile_id: uuid.UUID
    start_anchor_value: int
    end_anchor_value: int
    content_hash: bytes
    build_signature: bytes
    source_name: str | None
    source_uri: str | None
    snippet: str
    text: str
    score: float

    @property
    def stable_anchor_key(self) -> tuple[uuid.UUID, int, int, bytes]:
        """Stable inputs from which a durable text SourceAnchor can be materialized."""
        return (
            self.representation_id,
            self.start_anchor_value,
            self.end_anchor_value,
            self.content_hash,
        )


@dataclass(frozen=True, slots=True)
class ArchiveSemanticSearchResult:
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunk_index: int
    chunking_profile_id: uuid.UUID
    start_anchor_value: int
    end_anchor_value: int
    content_hash: bytes
    build_signature: bytes
    source_name: str | None
    source_uri: str | None
    text: str
    similarity: float


@dataclass(frozen=True, slots=True)
class ArchiveHybridSearchResult:
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunk_index: int
    chunking_profile_id: uuid.UUID
    start_anchor_value: int
    end_anchor_value: int
    content_hash: bytes
    build_signature: bytes
    source_name: str | None
    source_uri: str | None
    text: str
    score: float
    lexical_score: float
    semantic_score: float


@dataclass(frozen=True, slots=True)
class ArchiveEmbeddingIndexStatus:
    model_id: str
    indexed_chunk_generation: int
    current_chunk_generation: int
    dimensions: int
    document_count: int
    rebuilt_at_us: int

    @property
    def current(self) -> bool:
        return self.indexed_chunk_generation == self.current_chunk_generation


class ArchiveSearchService:
    """FTS5 archive retrieval whose final text is verified against retained evidence."""

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        chunk_store: SourceChunkStore,
        source_chunks: SourceChunkingService,
    ) -> None:
        self.database = database
        self.chunk_store = chunk_store
        self.source_chunks = source_chunks

    def rebuild(self) -> int:
        return self.chunk_store.rebuild_archive_fts()

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        source_id: uuid.UUID | None = None,
        representation_id: uuid.UUID | None = None,
    ) -> tuple[ArchiveSearchResult, ...]:
        if not 1 <= limit <= 200:
            raise ArchiveSearchError("Archive search limit must be between 1 and 200.")
        fts_query = _safe_fts_query(query)
        candidate_limit = min(1000, max(80, limit * 8))

        with self.chunk_store.connect() as connection:
            state = connection.execute(
                """
                SELECT chunk_generation, fts_generation
                FROM archive_search_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            if state is None:
                raise ArchiveSearchError("Derived archive search state is missing.")
            if int(state["fts_generation"]) != int(state["chunk_generation"]):
                raise ArchiveSearchError(
                    "Archive FTS is stale relative to SourceChunks; rebuild required."
                )

            clauses = ["fts_archive MATCH ?"]
            parameters: list[object] = [fts_query]
            if source_id is not None:
                clauses.append("source_id = ?")
                parameters.append(source_id.hex)
            if representation_id is not None:
                clauses.append("representation_id = ?")
                parameters.append(representation_id.hex)
            parameters.append(candidate_limit)
            sql = f"""
                SELECT
                    chunk_id, source_id, representation_id, chunk_index,
                    chunking_profile_id, start_anchor_value, end_anchor_value,
                    content_hash, build_signature, body,
                    snippet(fts_archive, 9, '[', ']', ' … ', 18) AS snippet,
                    -bm25(fts_archive, 0.0, 0.0, 0.0, 0.0, 0.0,
                          0.0, 0.0, 0.0, 1.0) AS score
                FROM fts_archive
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    bm25(fts_archive, 0.0, 0.0, 0.0, 0.0, 0.0,
                         0.0, 0.0, 0.0, 1.0) ASC,
                    chunk_id ASC
                LIMIT ?
            """
            try:
                rows = connection.execute(sql, tuple(parameters)).fetchall()
            except sqlite3.OperationalError as exc:
                raise ArchiveSearchError("SQLite rejected the archive FTS query.") from exc

        results: list[ArchiveSearchResult] = []
        for row in rows:
            chunk_id = _uuid_from_hex(str(row["chunk_id"]))
            chunk = self.source_chunks.verify(chunk_id)
            _verify_fts_row(row, chunk)
            metadata = self._visible_source_metadata(chunk)
            if metadata is None:
                continue
            source_name, source_uri = metadata
            results.append(
                ArchiveSearchResult(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    representation_id=chunk.representation_id,
                    chunk_index=chunk.chunk_index,
                    chunking_profile_id=chunk.chunking_profile_id,
                    start_anchor_value=chunk.start_anchor_value,
                    end_anchor_value=chunk.end_anchor_value,
                    content_hash=chunk.content_hash,
                    build_signature=chunk.build_signature,
                    source_name=source_name,
                    source_uri=source_uri,
                    snippet=str(row["snippet"]),
                    text=chunk.chunk_text,
                    score=float(row["score"]),
                )
            )
            if len(results) >= limit:
                break
        return tuple(results)

    def visible_chunk(self, chunk_id: uuid.UUID) -> tuple[SourceChunkRecord, str | None, str | None] | None:
        chunk = self.source_chunks.verify(chunk_id)
        metadata = self._visible_source_metadata(chunk)
        if metadata is None:
            return None
        return chunk, metadata[0], metadata[1]

    def _visible_source_metadata(
        self,
        chunk: SourceChunkRecord,
    ) -> tuple[str | None, str | None] | None:
        row = self.database.connection.execute(
            """
            SELECT
                s.original_name,
                s.source_uri,
                s.lifecycle_state AS source_state,
                sr.retention_state,
                se.lifecycle_state AS source_entity_state,
                re.lifecycle_state AS representation_entity_state
            FROM source_representations AS sr
            JOIN sources AS s
              ON s.source_id = sr.source_id
            JOIN entity_registry AS se
              ON se.entity_id = s.source_id
            JOIN entity_registry AS re
              ON re.entity_id = sr.representation_id
            WHERE sr.representation_id = ?
              AND sr.source_id = ?
            """,
            (chunk.representation_id.bytes, chunk.source_id.bytes),
        ).fetchone()
        if row is None:
            raise ArchiveSearchError(
                "Derived SourceChunk references missing authoritative Source metadata."
            )
        if str(row["source_entity_state"]) != "active":
            return None
        if str(row["representation_entity_state"]) != "active":
            return None
        if str(row["source_state"]) not in {"ready", "partial"}:
            return None
        if str(row["retention_state"]) != "retained":
            return None
        return (
            None if row["original_name"] is None else str(row["original_name"]),
            None if row["source_uri"] is None else str(row["source_uri"]),
        )


class ArchiveSemanticSearchService:
    """Model-scoped semantic vectors for current Derived SourceChunks."""

    def __init__(
        self,
        *,
        lexical: ArchiveSearchService,
        provider: LMStudioEmbeddingProvider,
        batch_size: int = 32,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")
        self.lexical = lexical
        self.chunk_store = lexical.chunk_store
        self.provider = provider
        self.batch_size = batch_size

    def status(self, model_id: str) -> ArchiveEmbeddingIndexStatus | None:
        normalized_model_id = _require_model_id(model_id)
        storage_model_id = _storage_model_id(normalized_model_id)
        current_generation = self.chunk_store.current_generation()
        with self.chunk_store.connect() as connection:
            row = connection.execute(
                """
                SELECT indexed_chunk_generation, dimensions, document_count, rebuilt_at_us
                FROM archive_embedding_state
                WHERE model_id = ?
                """,
                (storage_model_id,),
            ).fetchone()
        if row is None:
            return None
        return ArchiveEmbeddingIndexStatus(
            model_id=normalized_model_id,
            indexed_chunk_generation=int(row["indexed_chunk_generation"]),
            current_chunk_generation=current_generation,
            dimensions=int(row["dimensions"]),
            document_count=int(row["document_count"]),
            rebuilt_at_us=int(row["rebuilt_at_us"]),
        )

    def rebuild(self, model_id: str) -> ArchiveEmbeddingIndexStatus:
        normalized_model_id = _require_model_id(model_id)
        storage_model_id = _storage_model_id(normalized_model_id)
        generation = self.chunk_store.current_generation()

        with self.chunk_store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = _generation_from_connection(connection)
                if current != generation:
                    raise ArchiveSearchError("SourceChunks changed before archive embedding rebuild.")
                connection.execute(
                    """
                    DELETE FROM archive_embeddings
                    WHERE model_id = ? AND indexed_chunk_generation = ?
                    """,
                    (storage_model_id, generation),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

        dimensions: int | None = None
        document_count = 0
        with self.chunk_store.connect() as connection:
            cursor = connection.execute(
                """
                SELECT chunk_id
                FROM source_chunks
                ORDER BY representation_id, chunking_profile_id, chunk_index, chunk_id
                """
            )
            while True:
                rows = cursor.fetchmany(self.batch_size)
                if not rows:
                    break
                visible: list[tuple[SourceChunkRecord, str]] = []
                for row in rows:
                    chunk_id = uuid.UUID(bytes=bytes(row["chunk_id"]))
                    loaded = self.lexical.visible_chunk(chunk_id)
                    if loaded is None:
                        continue
                    chunk, _source_name, _source_uri = loaded
                    visible.append((chunk, chunk.chunk_text))
                if not visible:
                    continue

                vectors = self.provider.embed(
                    model_id=normalized_model_id,
                    texts=[
                        _prepare_document_text(normalized_model_id, text)
                        for _chunk, text in visible
                    ],
                )
                if len(vectors) != len(visible):
                    raise ArchiveSearchError(
                        "Embedding provider returned the wrong number of archive vectors."
                    )
                normalized_vectors: list[tuple[float, ...]] = []
                for vector in vectors:
                    normalized = _normalize_vector(vector)
                    if dimensions is None:
                        dimensions = len(normalized)
                    elif len(normalized) != dimensions:
                        raise ArchiveSearchError(
                            "Embedding model returned inconsistent archive dimensions."
                        )
                    normalized_vectors.append(normalized)

                with self.chunk_store.connect() as writer:
                    writer.execute("BEGIN IMMEDIATE")
                    try:
                        if _generation_from_connection(writer) != generation:
                            raise ArchiveSearchError(
                                "SourceChunks changed during archive embedding rebuild; retry required."
                            )
                        assert dimensions is not None
                        writer.executemany(
                            """
                            INSERT OR REPLACE INTO archive_embeddings (
                                chunk_id, model_id, indexed_chunk_generation,
                                dimensions, vector_blob, text_sha256, created_at_us
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                (
                                    chunk.chunk_id.bytes,
                                    storage_model_id,
                                    generation,
                                    dimensions,
                                    _pack_vector(vector),
                                    hashlib.sha256(text.encode("utf-8")).digest(),
                                    utc_now_us(),
                                )
                                for (chunk, text), vector in zip(
                                    visible, normalized_vectors, strict=True
                                )
                            ),
                        )
                        writer.execute("COMMIT")
                    except BaseException:
                        if writer.in_transaction:
                            writer.execute("ROLLBACK")
                        raise
                document_count += len(visible)

        persisted_dimensions = dimensions or 1
        with self.chunk_store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if _generation_from_connection(connection) != generation:
                    raise ArchiveSearchError(
                        "SourceChunks changed before archive embedding index commit; retry required."
                    )
                connection.execute(
                    """
                    INSERT INTO archive_embedding_state (
                        model_id, indexed_chunk_generation, dimensions,
                        document_count, rebuilt_at_us
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(model_id) DO UPDATE SET
                        indexed_chunk_generation = excluded.indexed_chunk_generation,
                        dimensions = excluded.dimensions,
                        document_count = excluded.document_count,
                        rebuilt_at_us = excluded.rebuilt_at_us
                    """,
                    (
                        storage_model_id,
                        generation,
                        persisted_dimensions,
                        document_count,
                        utc_now_us(),
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM archive_embeddings
                    WHERE model_id = ? AND indexed_chunk_generation <> ?
                    """,
                    (storage_model_id, generation),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

        status = self.status(normalized_model_id)
        if status is None:
            raise ArchiveSearchError("Archive embedding index state was not persisted.")
        return status

    def ensure_current(self, model_id: str) -> ArchiveEmbeddingIndexStatus:
        status = self.status(model_id)
        if status is not None and status.current:
            return status
        return self.rebuild(model_id)

    def search(
        self,
        query: str,
        *,
        model_id: str,
        limit: int = 50,
        source_id: uuid.UUID | None = None,
        representation_id: uuid.UUID | None = None,
    ) -> tuple[ArchiveSemanticSearchResult, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ArchiveSearchError("Archive semantic query must not be empty.")
        if not 1 <= limit <= 500:
            raise ArchiveSearchError("Archive semantic limit must be between 1 and 500.")
        normalized_model_id = _require_model_id(model_id)
        status = self.ensure_current(normalized_model_id)
        if status.document_count == 0:
            return ()

        query_vectors = self.provider.embed(
            model_id=normalized_model_id,
            texts=[_prepare_query_text(normalized_model_id, normalized_query)],
        )
        if len(query_vectors) != 1:
            raise ArchiveSearchError("Embedding provider did not return one archive query vector.")
        query_vector = _normalize_vector(query_vectors[0])
        if len(query_vector) != status.dimensions:
            raise ArchiveSearchError(
                "Archive query embedding dimensions differ from persisted index."
            )
        storage_model_id = _storage_model_id(normalized_model_id)

        clauses = [
            "e.model_id = ?",
            "e.indexed_chunk_generation = ?",
        ]
        parameters: list[object] = [storage_model_id, status.indexed_chunk_generation]
        if source_id is not None:
            clauses.append("c.source_id = ?")
            parameters.append(source_id.bytes)
        if representation_id is not None:
            clauses.append("c.representation_id = ?")
            parameters.append(representation_id.bytes)

        with self.chunk_store.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.chunk_id, e.vector_blob, e.text_sha256, e.dimensions
                FROM archive_embeddings AS e
                JOIN source_chunks AS c ON c.chunk_id = e.chunk_id
                WHERE {' AND '.join(clauses)}
                ORDER BY c.representation_id, c.chunk_index, c.chunk_id
                """,
                tuple(parameters),
            ).fetchall()

        results: list[ArchiveSemanticSearchResult] = []
        for row in rows:
            chunk_id = uuid.UUID(bytes=bytes(row["chunk_id"]))
            loaded = self.lexical.visible_chunk(chunk_id)
            if loaded is None:
                continue
            chunk, source_name, source_uri = loaded
            if int(row["dimensions"]) != status.dimensions:
                raise ArchiveSearchError(
                    "Persisted archive embedding dimensions disagree with index state."
                )
            if bytes(row["text_sha256"]) != chunk.content_hash:
                raise ArchiveSearchError(
                    "Persisted archive embedding hash disagrees with verified SourceChunk."
                )
            vector = _unpack_vector(bytes(row["vector_blob"]), status.dimensions)
            similarity = math.fsum(
                left * right for left, right in zip(query_vector, vector, strict=True)
            )
            results.append(
                ArchiveSemanticSearchResult(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    representation_id=chunk.representation_id,
                    chunk_index=chunk.chunk_index,
                    chunking_profile_id=chunk.chunking_profile_id,
                    start_anchor_value=chunk.start_anchor_value,
                    end_anchor_value=chunk.end_anchor_value,
                    content_hash=chunk.content_hash,
                    build_signature=chunk.build_signature,
                    source_name=source_name,
                    source_uri=source_uri,
                    text=chunk.chunk_text,
                    similarity=max(-1.0, min(1.0, similarity)),
                )
            )

        if self.chunk_store.current_generation() != status.indexed_chunk_generation:
            raise ArchiveSearchError(
                "SourceChunks changed during archive semantic search; retry required."
            )
        results.sort(
            key=lambda item: (-item.similarity, item.source_id.hex, item.chunk_index, item.chunk_id.hex)
        )
        return tuple(results[:limit])


class ArchiveHybridRetrievalService:
    """Fuse archive FTS and semantic candidates without promoting chunk authority."""

    def __init__(
        self,
        lexical: ArchiveSearchService,
        semantic: ArchiveSemanticSearchService,
    ) -> None:
        self.lexical = lexical
        self.semantic = semantic

    def search(
        self,
        query: str,
        *,
        model_id: str,
        limit: int = 20,
        source_id: uuid.UUID | None = None,
        representation_id: uuid.UUID | None = None,
    ) -> tuple[ArchiveHybridSearchResult, ...]:
        if not 1 <= limit <= 200:
            raise ArchiveSearchError("Archive hybrid limit must be between 1 and 200.")
        candidate_limit = min(500, max(80, limit * 8))
        lexical = self.lexical.search(
            query,
            limit=min(200, candidate_limit),
            source_id=source_id,
            representation_id=representation_id,
        )
        semantic = self.semantic.search(
            query,
            model_id=model_id,
            limit=candidate_limit,
            source_id=source_id,
            representation_id=representation_id,
        )

        lexical_scores = [item.score for item in lexical]
        lex_min = min(lexical_scores, default=0.0)
        lex_max = max(lexical_scores, default=0.0)
        semantic_scores = [item.similarity for item in semantic]
        sem_min = min(semantic_scores, default=0.0)
        sem_max = max(semantic_scores, default=0.0)

        candidates: dict[uuid.UUID, _ArchiveCandidate] = {}
        for lexical_item in lexical:
            candidates[lexical_item.chunk_id] = _ArchiveCandidate.from_lexical(
                lexical_item,
                lexical_score=_normalize_range(lexical_item.score, lex_min, lex_max),
            )
        for semantic_item in semantic:
            semantic_score = _normalize_range(
                semantic_item.similarity, sem_min, sem_max
            )
            existing = candidates.get(semantic_item.chunk_id)
            if existing is None:
                candidates[semantic_item.chunk_id] = _ArchiveCandidate.from_semantic(
                    semantic_item,
                    semantic_score=semantic_score,
                )
            else:
                existing.semantic_score = max(existing.semantic_score, semantic_score)

        scored = [_candidate_to_result(item) for item in candidates.values()]
        return _diversify_archive(scored, limit=limit)


@dataclass(slots=True)
class _ArchiveCandidate:
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunk_index: int
    chunking_profile_id: uuid.UUID
    start_anchor_value: int
    end_anchor_value: int
    content_hash: bytes
    build_signature: bytes
    source_name: str | None
    source_uri: str | None
    text: str
    lexical_score: float
    semantic_score: float

    @classmethod
    def from_lexical(
        cls,
        item: ArchiveSearchResult,
        *,
        lexical_score: float,
    ) -> _ArchiveCandidate:
        return cls(
            chunk_id=item.chunk_id,
            source_id=item.source_id,
            representation_id=item.representation_id,
            chunk_index=item.chunk_index,
            chunking_profile_id=item.chunking_profile_id,
            start_anchor_value=item.start_anchor_value,
            end_anchor_value=item.end_anchor_value,
            content_hash=item.content_hash,
            build_signature=item.build_signature,
            source_name=item.source_name,
            source_uri=item.source_uri,
            text=item.text,
            lexical_score=lexical_score,
            semantic_score=0.0,
        )

    @classmethod
    def from_semantic(
        cls,
        item: ArchiveSemanticSearchResult,
        *,
        semantic_score: float,
    ) -> _ArchiveCandidate:
        return cls(
            chunk_id=item.chunk_id,
            source_id=item.source_id,
            representation_id=item.representation_id,
            chunk_index=item.chunk_index,
            chunking_profile_id=item.chunking_profile_id,
            start_anchor_value=item.start_anchor_value,
            end_anchor_value=item.end_anchor_value,
            content_hash=item.content_hash,
            build_signature=item.build_signature,
            source_name=item.source_name,
            source_uri=item.source_uri,
            text=item.text,
            lexical_score=0.0,
            semantic_score=semantic_score,
        )


def _candidate_to_result(candidate: _ArchiveCandidate) -> ArchiveHybridSearchResult:
    score = candidate.lexical_score * 0.52 + candidate.semantic_score * 0.48
    return ArchiveHybridSearchResult(
        chunk_id=candidate.chunk_id,
        source_id=candidate.source_id,
        representation_id=candidate.representation_id,
        chunk_index=candidate.chunk_index,
        chunking_profile_id=candidate.chunking_profile_id,
        start_anchor_value=candidate.start_anchor_value,
        end_anchor_value=candidate.end_anchor_value,
        content_hash=candidate.content_hash,
        build_signature=candidate.build_signature,
        source_name=candidate.source_name,
        source_uri=candidate.source_uri,
        text=candidate.text,
        score=score,
        lexical_score=candidate.lexical_score,
        semantic_score=candidate.semantic_score,
    )


def _diversify_archive(
    scored: list[ArchiveHybridSearchResult],
    *,
    limit: int,
) -> tuple[ArchiveHybridSearchResult, ...]:
    remaining = sorted(
        scored,
        key=lambda item: (-item.score, item.source_id.hex, item.chunk_index, item.chunk_id.hex),
    )
    selected: list[ArchiveHybridSearchResult] = []
    while remaining and len(selected) < limit:
        best_index = 0
        best_key: tuple[float, float, str] | None = None
        for index, candidate in enumerate(remaining):
            penalty = _archive_diversity_penalty(candidate, selected)
            key = (candidate.score - penalty, candidate.score, candidate.chunk_id.hex)
            if best_key is None or key > best_key:
                best_key = key
                best_index = index
        chosen = remaining.pop(best_index)
        penalty = _archive_diversity_penalty(chosen, selected)
        if penalty:
            chosen = ArchiveHybridSearchResult(
                chunk_id=chosen.chunk_id,
                source_id=chosen.source_id,
                representation_id=chosen.representation_id,
                chunk_index=chosen.chunk_index,
                chunking_profile_id=chosen.chunking_profile_id,
                start_anchor_value=chosen.start_anchor_value,
                end_anchor_value=chosen.end_anchor_value,
                content_hash=chosen.content_hash,
                build_signature=chosen.build_signature,
                source_name=chosen.source_name,
                source_uri=chosen.source_uri,
                text=chosen.text,
                score=max(0.0, chosen.score - penalty),
                lexical_score=chosen.lexical_score,
                semantic_score=chosen.semantic_score,
            )
        selected.append(chosen)
    return tuple(selected)


def _archive_diversity_penalty(
    candidate: ArchiveHybridSearchResult,
    selected: list[ArchiveHybridSearchResult],
) -> float:
    same_source = sum(1 for prior in selected if prior.source_id == candidate.source_id)
    source_penalty = min(0.16, same_source * 0.06)
    candidate_tokens = _tokens(candidate.text)
    similarity = max(
        (_jaccard(candidate_tokens, _tokens(prior.text)) for prior in selected),
        default=0.0,
    )
    similarity_penalty = 0.08 * similarity if similarity >= 0.88 else 0.0
    return source_penalty + similarity_penalty



def _verify_fts_row(row: sqlite3.Row, chunk: SourceChunkRecord) -> None:
    expected = {
        "chunk_id": chunk.chunk_id.hex,
        "source_id": chunk.source_id.hex,
        "representation_id": chunk.representation_id.hex,
        "chunk_index": str(chunk.chunk_index),
        "chunking_profile_id": chunk.chunking_profile_id.hex,
        "start_anchor_value": str(chunk.start_anchor_value),
        "end_anchor_value": str(chunk.end_anchor_value),
        "content_hash": chunk.content_hash.hex(),
        "build_signature": chunk.build_signature.hex(),
        "body": chunk.chunk_text,
    }
    for field, value in expected.items():
        if str(row[field]) != value:
            raise ArchiveSearchError(
                f"Archive FTS disagrees with verified SourceChunk field {field}."
            )

def _safe_fts_query(query: str) -> str:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        raise ArchiveSearchError("Archive search query must contain a letter or digit.")
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _require_model_id(model_id: str) -> str:
    normalized = model_id.strip()
    if not normalized:
        raise ArchiveSearchError("Embedding model id must not be empty.")
    return normalized


def _embedding_profile(model_id: str) -> str:
    if "nomic-embed-text" in model_id.casefold():
        return "nomic-rag-v1"
    return "raw-rag-v1"


def _storage_model_id(model_id: str) -> str:
    return f"{_require_model_id(model_id)}::athena-profile={_embedding_profile(model_id)}"


def _prepare_document_text(model_id: str, text: str) -> str:
    if _embedding_profile(model_id) == "nomic-rag-v1":
        return f"search_document: {text}"
    return text


def _prepare_query_text(model_id: str, text: str) -> str:
    if _embedding_profile(model_id) == "nomic-rag-v1":
        return f"search_query: {text}"
    return text


def _normalize_vector(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(math.fsum(component * component for component in vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ArchiveSearchError("Archive embedding vector has zero or invalid magnitude.")
    return tuple(component / norm for component in vector)


def _pack_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
    expected = dimensions * 4
    if len(blob) != expected:
        raise ArchiveSearchError("Persisted archive embedding vector has invalid length.")
    return tuple(struct.unpack(f"<{dimensions}f", blob))


def _generation_from_connection(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT chunk_generation FROM archive_search_state WHERE singleton_id = 1"
    ).fetchone()
    if row is None:
        raise ArchiveSearchError("Derived archive search state is missing.")
    return int(row["chunk_generation"])


def _uuid_from_hex(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(hex=value)
    except ValueError as exc:
        raise ArchiveSearchError("Archive FTS contains an invalid UUID.") from exc


def _normalize_range(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 1.0
    return min(1.0, max(0.0, (value - minimum) / (maximum - minimum)))


def _tokens(text: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return frozenset(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
