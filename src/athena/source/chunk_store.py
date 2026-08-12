"""Reconstructible SourceChunk persistence in the Derived State search store."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from athena.common.ids import uuid_from_blob, uuid_to_blob

_DERIVED_APPLICATION_ID = 1_096_042_564  # ASCII-ish ATHD
_DERIVED_SCHEMA_VERSION = 1


class SourceChunkNotFoundError(LookupError):
    """Raised when a derived SourceChunk no longer exists."""


class SourceChunkStoreError(RuntimeError):
    """Raised when the reconstructible SourceChunk store is invalid."""


@dataclass(frozen=True, slots=True)
class SourceChunkRecord:
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunk_index: int
    chunking_profile_id: uuid.UUID
    start_anchor_value: int
    end_anchor_value: int
    content_hash: bytes
    processing_run_id: uuid.UUID
    build_signature: bytes
    chunk_text: str
    created_at_us: int

    @property
    def uri(self) -> str:
        return f"derived://chunk/{self.chunk_id}"


class SourceChunkStore:
    """Own a physically separate reconstructible SQLite store for SourceChunks."""

    def __init__(self, derived_root: Path) -> None:
        self.path = derived_root / "search.db"

    def replace_build(
        self,
        *,
        representation_id: uuid.UUID,
        chunking_profile_id: uuid.UUID,
        build_signature: bytes,
        processing_run_id: uuid.UUID,
        created_at_us: int,
        chunks: tuple[SourceChunkRecord, ...],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    DELETE FROM source_chunks
                    WHERE representation_id = ? AND chunking_profile_id = ?
                    """,
                    (uuid_to_blob(representation_id), uuid_to_blob(chunking_profile_id)),
                )
                connection.execute(
                    """
                    DELETE FROM source_chunk_builds
                    WHERE representation_id = ? AND chunking_profile_id = ?
                    """,
                    (uuid_to_blob(representation_id), uuid_to_blob(chunking_profile_id)),
                )
                connection.execute(
                    """
                    INSERT INTO source_chunk_builds (
                        representation_id, chunking_profile_id, build_signature,
                        processing_run_id, created_at_us
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(representation_id),
                        uuid_to_blob(chunking_profile_id),
                        build_signature,
                        uuid_to_blob(processing_run_id),
                        created_at_us,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO source_chunks (
                        chunk_id, source_id, representation_id, chunk_index,
                        chunking_profile_id, anchor_id, start_anchor_value,
                        end_anchor_value, content_hash, processing_run_id,
                        build_signature, chunk_text, created_at_us
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            uuid_to_blob(chunk.chunk_id),
                            uuid_to_blob(chunk.source_id),
                            uuid_to_blob(chunk.representation_id),
                            chunk.chunk_index,
                            uuid_to_blob(chunk.chunking_profile_id),
                            chunk.start_anchor_value,
                            chunk.end_anchor_value,
                            chunk.content_hash,
                            uuid_to_blob(chunk.processing_run_id),
                            chunk.build_signature,
                            chunk.chunk_text,
                            chunk.created_at_us,
                        )
                        for chunk in chunks
                    ),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get(self, chunk_id: uuid.UUID) -> SourceChunkRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_chunks WHERE chunk_id = ?",
                (uuid_to_blob(chunk_id),),
            ).fetchone()
        if row is None:
            raise SourceChunkNotFoundError(f"SourceChunk {chunk_id} not found.")
        return _chunk_from_row(row)

    def list_for_representation(
        self,
        representation_id: uuid.UUID,
        *,
        limit: int = 500,
    ) -> tuple[SourceChunkRecord, ...]:
        if not 1 <= limit <= 5000:
            raise ValueError("Chunk list limit must be between 1 and 5000.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM source_chunks
                WHERE representation_id = ?
                ORDER BY chunk_index, chunk_id
                LIMIT ?
                """,
                (uuid_to_blob(representation_id), limit),
            ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def count_for_representation(self, representation_id: uuid.UUID) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS n FROM source_chunks WHERE representation_id = ?",
                (uuid_to_blob(representation_id),),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0, autocommit=True)
        connection.row_factory = sqlite3.Row
        try:
            _initialize(connection)
            yield connection
        finally:
            connection.close()


def _initialize(connection: sqlite3.Connection) -> None:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id not in {0, _DERIVED_APPLICATION_ID}:
        raise SourceChunkStoreError("Derived search.db application_id is not ATHENA.")
    user_tables = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    )
    if application_id == 0 and user_tables:
        raise SourceChunkStoreError(
            "Refusing to adopt a non-empty derived search.db without ATHENA application_id."
        )
    if user_version not in {0, _DERIVED_SCHEMA_VERSION}:
        raise SourceChunkStoreError("Derived search.db schema version is unsupported.")

    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    if user_version == 0:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;
            PRAGMA application_id = {_DERIVED_APPLICATION_ID};
            CREATE TABLE source_chunk_builds (
                representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
                chunking_profile_id BLOB(16) NOT NULL CHECK(length(chunking_profile_id) = 16),
                build_signature BLOB(32) NOT NULL CHECK(length(build_signature) = 32),
                processing_run_id BLOB(16) NOT NULL CHECK(length(processing_run_id) = 16),
                created_at_us INTEGER NOT NULL,
                PRIMARY KEY(representation_id, chunking_profile_id)
            ) WITHOUT ROWID;
            CREATE TABLE source_chunks (
                chunk_id BLOB(16) PRIMARY KEY CHECK(length(chunk_id) = 16),
                source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
                representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
                chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
                chunking_profile_id BLOB(16) NOT NULL CHECK(length(chunking_profile_id) = 16),
                anchor_id BLOB(16) NULL CHECK(anchor_id IS NULL OR length(anchor_id) = 16),
                start_anchor_value INTEGER NOT NULL CHECK(start_anchor_value >= 0),
                end_anchor_value INTEGER NOT NULL CHECK(end_anchor_value >= start_anchor_value),
                content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
                processing_run_id BLOB(16) NOT NULL CHECK(length(processing_run_id) = 16),
                build_signature BLOB(32) NOT NULL CHECK(length(build_signature) = 32),
                chunk_text TEXT NOT NULL,
                created_at_us INTEGER NOT NULL,
                UNIQUE(representation_id, chunking_profile_id, chunk_index)
            ) WITHOUT ROWID;
            CREATE INDEX idx_source_chunks_representation
                ON source_chunks(representation_id, chunk_index);
            CREATE INDEX idx_source_chunks_source
                ON source_chunks(source_id, representation_id);
            PRAGMA user_version = {_DERIVED_SCHEMA_VERSION};
            COMMIT;
            """
        )


def _chunk_from_row(row: sqlite3.Row) -> SourceChunkRecord:
    return SourceChunkRecord(
        chunk_id=uuid_from_blob(row["chunk_id"]),
        source_id=uuid_from_blob(row["source_id"]),
        representation_id=uuid_from_blob(row["representation_id"]),
        chunk_index=int(row["chunk_index"]),
        chunking_profile_id=uuid_from_blob(row["chunking_profile_id"]),
        start_anchor_value=int(row["start_anchor_value"]),
        end_anchor_value=int(row["end_anchor_value"]),
        content_hash=bytes(row["content_hash"]),
        processing_run_id=uuid_from_blob(row["processing_run_id"]),
        build_signature=bytes(row["build_signature"]),
        chunk_text=str(row["chunk_text"]),
        created_at_us=int(row["created_at_us"]),
    )
