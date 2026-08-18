"""Reconstructible local semantic retrieval using infrastructure embeddings."""

from __future__ import annotations

import hashlib
import math
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path

from athena.common.ids import uuid_to_blob
from athena.common.time import utc_now_us
from athena.model.adapters.lm_studio_embeddings import LMStudioEmbeddingProvider
from athena.retrieval.hnsw import HnswIndexError, HnswIndexStore
from athena.retrieval.search import (
    SearchEntityType,
    current_search_projection_commit_seq,
)
from athena.storage.database import SQLiteDatabase

_SEMANTIC_TYPE_PRIORITY = {
    SearchEntityType.KNOWLEDGE: 0,
    SearchEntityType.CLAIM: 1,
    SearchEntityType.CHAT_MESSAGE: 2,
}

class SemanticSearchError(RuntimeError):
    """Raised when the semantic derived index cannot be used safely."""


@dataclass(frozen=True, slots=True)
class EmbeddingIndexStatus:
    model_id: str
    indexed_commit_seq: int
    current_commit_seq: int
    dimensions: int
    document_count: int
    rebuilt_at_us: int
    hnsw_ready: bool

    @property
    def current(self) -> bool:
        return self.indexed_commit_seq >= self.current_commit_seq and self.hnsw_ready


@dataclass(frozen=True, slots=True)
class SemanticSearchResult:
    entity_id: uuid.UUID
    revision_id: uuid.UUID
    entity_type: SearchEntityType
    title: str | None
    text: str
    similarity: float
    contradiction_count: int


class LocalSemanticSearchService:
    """Maintain and query model-scoped semantic vectors as Derived State."""

    def __init__(
        self,
        database: SQLiteDatabase,
        provider: LMStudioEmbeddingProvider,
        *,
        batch_size: int = 32,
        hnsw_root: Path | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")
        self.database = database
        self.provider = provider
        self.batch_size = batch_size
        self.hnsw = HnswIndexStore(
            hnsw_root or (self.database.path.parent / "hnsw"),
            namespace="knowledge",
            reference_size=33,
        )

    def status(self, model_id: str) -> EmbeddingIndexStatus | None:
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            raise SemanticSearchError("Embedding model id must not be empty.")
        storage_model_id = _storage_model_id(normalized_model_id)
        row = self.database.connection.execute(
            """
            SELECT
                indexed_commit_seq,
                dimensions,
                document_count,
                rebuilt_at_us
            FROM search_embedding_state
            WHERE model_id = ?
            """,
            (storage_model_id,),
        ).fetchone()
        if row is None:
            return None
        indexed_commit_seq = int(row["indexed_commit_seq"])
        dimensions = int(row["dimensions"])
        document_count = int(row["document_count"])
        return EmbeddingIndexStatus(
            model_id=normalized_model_id,
            indexed_commit_seq=indexed_commit_seq,
            current_commit_seq=current_search_projection_commit_seq(self.database.connection),
            dimensions=dimensions,
            document_count=document_count,
            rebuilt_at_us=int(row["rebuilt_at_us"]),
            hnsw_ready=self.hnsw.ready(
                model_id=storage_model_id,
                snapshot=indexed_commit_seq,
                dimensions=dimensions,
                document_count=document_count,
            ),
        )

    def rebuild(self, model_id: str) -> EmbeddingIndexStatus:
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            raise SemanticSearchError("Embedding model id must not be empty.")
        storage_model_id = _storage_model_id(normalized_model_id)

        # Make FTS current first because it defines the allowed current,
        # unprotected document set for both lexical and semantic retrieval.
        #
        # The external embedding call must never be allowed to publish vectors
        # for an older FTS snapshot under a newer canonical commit watermark.
        # Acquire a short writer lock after the normal FTS freshness check and
        # capture the FTS rows plus canonical watermark atomically. If another
        # canonical writer won the race between _ensure_fts_current() and this
        # lock, repeat until both watermarks describe the same snapshot.
        while True:
            self._ensure_fts_current()
            with self.database.write_transaction() as connection:
                current_commit_seq = current_search_projection_commit_seq(connection)
                state = connection.execute(
                    """
                    SELECT indexed_commit_seq
                    FROM search_index_state
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                if state is None:
                    raise SemanticSearchError("Search index state is missing.")
                if int(state["indexed_commit_seq"]) < current_commit_seq:
                    continue
                source_rows = connection.execute(
                    """
                    SELECT entity_type, entity_id, revision_id, title, body
                    FROM search_fts
                    ORDER BY entity_type, entity_id, revision_id
                    """
                ).fetchall()
            break

        documents = [
            (
                SearchEntityType(str(row["entity_type"])),
                _uuid_from_hex(str(row["entity_id"])),
                _uuid_from_hex(str(row["revision_id"])),
                None if row["title"] in {None, ""} else str(row["title"]),
                str(row["body"]),
            )
            for row in source_rows
        ]

        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(documents), self.batch_size):
            batch = documents[start : start + self.batch_size]
            batch_vectors = self.provider.embed(
                model_id=normalized_model_id,
                texts=[
                    _prepare_document_text(normalized_model_id, document[4])
                    for document in batch
                ],
            )
            vectors.extend(batch_vectors)

        dimensions = 1
        if vectors:
            dimensions = len(vectors[0])
            if dimensions <= 0:
                raise SemanticSearchError("Embedding vectors must not be empty.")
            if any(len(vector) != dimensions for vector in vectors):
                raise SemanticSearchError(
                    "Embedding model returned inconsistent dimensions."
                )

        normalized_vectors = [_normalize_vector(vector) for vector in vectors]

        with self.database.write_transaction() as connection:
            # Fail closed if canonical state changed while external embedding
            # generation was running.
            if current_search_projection_commit_seq(connection) != current_commit_seq:
                raise SemanticSearchError(
                    "Canonical state changed during embedding rebuild; retry required."
                )

            connection.execute(
                "DELETE FROM search_embeddings WHERE model_id IN (?, ?)",
                (storage_model_id, normalized_model_id),
            )
            connection.execute(
                "DELETE FROM search_embedding_state WHERE model_id = ?",
                (normalized_model_id,),
            )
            for document, vector in zip(documents, normalized_vectors, strict=True):
                entity_type, entity_id, revision_id, _title, text = document
                connection.execute(
                    """
                    INSERT INTO search_embeddings (
                        entity_type,
                        entity_id,
                        revision_id,
                        model_id,
                        dimensions,
                        vector_blob,
                        text_sha256,
                        created_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_type.value,
                        uuid_to_blob(entity_id),
                        uuid_to_blob(revision_id),
                        storage_model_id,
                        dimensions,
                        _pack_vector(vector),
                        hashlib.sha256(text.encode("utf-8")).digest(),
                        utc_now_us(),
                    ),
                )

            connection.execute(
                """
                INSERT INTO search_embedding_state (
                    model_id,
                    indexed_commit_seq,
                    dimensions,
                    document_count,
                    rebuilt_at_us
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    indexed_commit_seq = excluded.indexed_commit_seq,
                    dimensions = excluded.dimensions,
                    document_count = excluded.document_count,
                    rebuilt_at_us = excluded.rebuilt_at_us
                """,
                (
                    storage_model_id,
                    current_commit_seq,
                    dimensions,
                    len(documents),
                    utc_now_us(),
                ),
            )

        try:
            self._rebuild_hnsw_from_persisted(
                normalized_model_id,
                snapshot=current_commit_seq,
                dimensions=dimensions,
                document_count=len(documents),
            )
        except HnswIndexError as exc:
            raise SemanticSearchError(str(exc)) from exc

        status = self.status(normalized_model_id)
        if status is None or not status.current:
            raise SemanticSearchError("Embedding/HNSW index state was not published.")
        return status

    def ensure_current(self, model_id: str) -> EmbeddingIndexStatus:
        normalized_model_id = model_id.strip()
        status = self.status(normalized_model_id)
        current_commit_seq = current_search_projection_commit_seq(self.database.connection)
        if status is None or status.indexed_commit_seq < current_commit_seq:
            return self.rebuild(normalized_model_id)
        if not status.hnsw_ready:
            try:
                self._rebuild_hnsw_from_persisted(
                    normalized_model_id,
                    snapshot=status.indexed_commit_seq,
                    dimensions=status.dimensions,
                    document_count=status.document_count,
                )
            except HnswIndexError as exc:
                raise SemanticSearchError(str(exc)) from exc
            status = self.status(normalized_model_id)
            if status is None or not status.current:
                raise SemanticSearchError("HNSW sidecar rebuild did not become current.")
        return status

    def search(
        self,
        query: str,
        *,
        model_id: str,
        limit: int = 50,
    ) -> tuple[SemanticSearchResult, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            raise SemanticSearchError("Semantic query must not be empty.")
        if not 1 <= limit <= 500:
            raise SemanticSearchError("Semantic search limit must be between 1 and 500.")

        status = self.status(model_id)
        if status is None:
            raise SemanticSearchError(
                "Semantic index is absent; explicit rebuild required."
            )
        if status.indexed_commit_seq < status.current_commit_seq:
            raise SemanticSearchError(
                "Semantic index is stale; explicit rebuild required."
            )
        if not status.hnsw_ready:
            raise SemanticSearchError(
                "Semantic HNSW sidecar is unavailable; "
                "explicit maintenance required."
            )
        if status.document_count == 0:
            return ()

        storage_model_id = _storage_model_id(model_id)
        query_vectors = self.provider.embed(
            model_id=model_id,
            texts=[_prepare_query_text(model_id, normalized_query)],
        )
        if len(query_vectors) != 1:
            raise SemanticSearchError("Embedding provider did not return one query vector.")
        query_vector = _normalize_vector(query_vectors[0])
        if len(query_vector) != status.dimensions:
            raise SemanticSearchError(
                "Query embedding dimensions differ from the persisted index."
            )

        candidate_limit = min(status.document_count, max(limit, min(500, limit * 4)))
        try:
            matches = self.hnsw.search(
                query_vector,
                model_id=storage_model_id,
                snapshot=status.indexed_commit_seq,
                dimensions=status.dimensions,
                document_count=status.document_count,
                limit=candidate_limit,
            )
        except HnswIndexError as exc:
            raise SemanticSearchError(str(exc)) from exc

        results: list[SemanticSearchResult] = []
        for match in matches:
            entity_type, entity_id, revision_id = _decode_reference(match.reference)
            row = self.database.connection.execute(
                """
                SELECT
                    e.vector_blob,
                    NULLIF(f.title, '') AS title,
                    f.body,
                    CASE
                        WHEN e.entity_type = 'claim' THEN (
                            SELECT count(*)
                            FROM claim_evidence AS ce
                            WHERE ce.claim_id = e.entity_id
                              AND ce.evidence_role = 'contradicts'
                        )
                        ELSE 0
                    END AS contradiction_count
                FROM search_embeddings AS e
                JOIN search_fts AS f
                  ON lower(hex(e.entity_id)) = f.entity_id
                 AND lower(hex(e.revision_id)) = f.revision_id
                 AND e.entity_type = f.entity_type
                WHERE e.model_id = ?
                  AND e.entity_type = ?
                  AND e.entity_id = ?
                  AND e.revision_id = ?
                """,
                (
                    storage_model_id,
                    entity_type.value,
                    uuid_to_blob(entity_id),
                    uuid_to_blob(revision_id),
                ),
            ).fetchone()
            if row is None:
                raise SemanticSearchError(
                    "HNSW candidate references missing persisted embedding state."
                )
            vector = _unpack_vector(bytes(row["vector_blob"]), status.dimensions)
            similarity = math.fsum(
                left * right for left, right in zip(query_vector, vector, strict=True)
            )
            results.append(
                SemanticSearchResult(
                    entity_id=entity_id,
                    revision_id=revision_id,
                    entity_type=entity_type,
                    title=None if row["title"] is None else str(row["title"]),
                    text=str(row["body"]),
                    similarity=max(-1.0, min(1.0, similarity)),
                    contradiction_count=int(row["contradiction_count"]),
                )
            )

        results.sort(
            key=lambda item: (
                -item.similarity,
                _SEMANTIC_TYPE_PRIORITY[item.entity_type],
                item.entity_id.hex,
            )
        )
        return tuple(results[:limit])

    def _rebuild_hnsw_from_persisted(
        self,
        model_id: str,
        *,
        snapshot: int,
        dimensions: int,
        document_count: int,
    ) -> None:
        storage_model_id = _storage_model_id(model_id)
        rows = self.database.connection.execute(
            """
            SELECT entity_type, entity_id, revision_id, vector_blob
            FROM search_embeddings
            WHERE model_id = ?
            ORDER BY entity_type, entity_id, revision_id
            """,
            (storage_model_id,),
        ).fetchall()
        if len(rows) != document_count:
            raise SemanticSearchError(
                "Persisted embedding count disagrees with semantic index state."
            )
        entries = tuple(
            (
                _encode_reference(
                    SearchEntityType(str(row["entity_type"])),
                    uuid.UUID(bytes=bytes(row["entity_id"])),
                    uuid.UUID(bytes=bytes(row["revision_id"])),
                ),
                _unpack_vector(bytes(row["vector_blob"]), dimensions),
            )
            for row in rows
        )
        self.hnsw.build(
            model_id=storage_model_id,
            snapshot=snapshot,
            dimensions=dimensions,
            entries=entries,
        )

    def _ensure_fts_current(self) -> None:
        # Reuse the same commit watermark contract without duplicating the FTS
        # implementation. Import locally to avoid a construction cycle.
        from athena.retrieval.search import LocalSearchService

        LocalSearchService(self.database)._ensure_current()

_REFERENCE_TYPE_CODE = {
    SearchEntityType.KNOWLEDGE: 1,
    SearchEntityType.CLAIM: 2,
    SearchEntityType.CHAT_MESSAGE: 3,
}
_REFERENCE_CODE_TYPE = {value: key for key, value in _REFERENCE_TYPE_CODE.items()}


def _encode_reference(
    entity_type: SearchEntityType,
    entity_id: uuid.UUID,
    revision_id: uuid.UUID,
) -> bytes:
    return bytes((_REFERENCE_TYPE_CODE[entity_type],)) + entity_id.bytes + revision_id.bytes


def _decode_reference(value: bytes) -> tuple[SearchEntityType, uuid.UUID, uuid.UUID]:
    if len(value) != 33:
        raise SemanticSearchError("HNSW semantic reference has an invalid length.")
    try:
        entity_type = _REFERENCE_CODE_TYPE[value[0]]
    except KeyError as exc:
        raise SemanticSearchError("HNSW semantic reference has an invalid entity type.") from exc
    return entity_type, uuid.UUID(bytes=value[1:17]), uuid.UUID(bytes=value[17:33])


def _embedding_profile(model_id: str) -> str:
    normalized = model_id.casefold()
    if "nomic-embed-text" in normalized:
        return "nomic-rag-v1"
    return "raw-rag-v1"


def _storage_model_id(model_id: str) -> str:
    normalized = model_id.strip()
    if not normalized:
        raise SemanticSearchError("Embedding model id must not be empty.")
    return f"{normalized}::athena-profile={_embedding_profile(normalized)}"


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
        raise SemanticSearchError("Embedding vector has zero or invalid magnitude.")
    return tuple(component / norm for component in vector)


def _pack_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
    expected = dimensions * 4
    if len(blob) != expected:
        raise SemanticSearchError("Persisted embedding vector has invalid length.")
    return tuple(struct.unpack(f"<{dimensions}f", blob))


def _uuid_from_hex(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(hex=value)
    except ValueError as exc:
        raise SemanticSearchError("FTS index contains an invalid UUID.") from exc
