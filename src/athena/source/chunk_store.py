"""Reconstructible SourceChunk persistence in the Derived State search store."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us

_DERIVED_APPLICATION_ID = 1_096_042_564  # ASCII-ish ATHD
_DERIVED_SCHEMA_VERSION = 4


class SourceChunkNotFoundError(LookupError):
    """Raised when a derived SourceChunk no longer exists."""


class SourceChunkStoreError(RuntimeError):
    """Raised when the reconstructible SourceChunk store is invalid."""


@dataclass(frozen=True, slots=True)
class SourceChunkPlanRecord:
    """One deterministic planned chunk in reconstructible Derived State."""

    chunk_index: int
    start_anchor_value: int
    end_anchor_value: int
    start_byte_offset: int
    end_byte_offset: int
    content_hash: bytes


@dataclass(frozen=True, slots=True)
class StagedSourceChunkRecord:
    """One unpublished chunk prepared by a durable large-source job."""

    chunk_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunk_index: int
    chunking_profile_id: uuid.UUID
    start_anchor_value: int
    end_anchor_value: int
    content_hash: bytes
    build_signature: bytes
    chunk_text: str
    created_at_us: int


@dataclass(frozen=True, slots=True)
class StagedSourceChunkBuildRecord:
    """Metadata for one unpublished deterministic SourceChunk build."""

    source_id: uuid.UUID
    representation_id: uuid.UUID
    chunking_profile_id: uuid.UUID
    build_signature: bytes
    representation_hash: bytes
    total_chunks: int
    created_at_us: int


@dataclass(frozen=True, slots=True)
class CurrentSourceChunkBuildRecord:
    """Published SourceChunk build metadata."""

    representation_id: uuid.UUID
    chunking_profile_id: uuid.UUID
    build_signature: bytes
    processing_run_id: uuid.UUID
    created_at_us: int
    chunk_count: int


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
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                representation_hex = representation_id.hex
                profile_hex = chunking_profile_id.hex
                connection.execute(
                    """
                    DELETE FROM fts_archive
                    WHERE representation_id = ? AND chunking_profile_id = ?
                    """,
                    (representation_hex, profile_hex),
                )
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
                connection.executemany(
                    """
                    INSERT INTO fts_archive (
                        chunk_id, source_id, representation_id, chunk_index,
                        chunking_profile_id, start_anchor_value, end_anchor_value,
                        content_hash, build_signature, body
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            chunk.chunk_id.hex,
                            chunk.source_id.hex,
                            chunk.representation_id.hex,
                            str(chunk.chunk_index),
                            chunk.chunking_profile_id.hex,
                            str(chunk.start_anchor_value),
                            str(chunk.end_anchor_value),
                            chunk.content_hash.hex(),
                            chunk.build_signature.hex(),
                            chunk.chunk_text,
                        )
                        for chunk in chunks
                    ),
                )
                connection.execute(
                    """
                    UPDATE archive_search_state
                    SET chunk_generation = chunk_generation + 1,
                        fts_generation = chunk_generation + 1,
                        updated_at_us = ?
                    WHERE singleton_id = 1
                    """,
                    (utc_now_us(),),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def prepare_staged_build(
        self,
        *,
        source_id: uuid.UUID,
        representation_id: uuid.UUID,
        chunking_profile_id: uuid.UUID,
        build_signature: bytes,
        representation_hash: bytes,
        plan: tuple[SourceChunkPlanRecord, ...],
        created_at_us: int,
    ) -> StagedSourceChunkBuildRecord:
        """Persist an unpublished deterministic plan without changing visible chunks."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT * FROM source_chunk_staging_builds
                    WHERE representation_id = ? AND chunking_profile_id = ?
                    """,
                    (uuid_to_blob(representation_id), uuid_to_blob(chunking_profile_id)),
                ).fetchone()
                if existing is not None and bytes(existing["build_signature"]) == build_signature:
                    compatible = (
                        uuid_from_blob(existing["source_id"]) == source_id
                        and bytes(existing["representation_hash"]) == representation_hash
                        and int(existing["total_chunks"]) == len(plan)
                    )
                    if not compatible:
                        raise SourceChunkStoreError(
                            "Existing staged build metadata disagrees with the deterministic plan."
                        )
                    plan_count = int(
                        connection.execute(
                            "SELECT count(*) FROM source_chunk_staging_plan WHERE build_signature = ?",
                            (build_signature,),
                        ).fetchone()[0]
                    )
                    if plan_count == len(plan):
                        connection.execute("COMMIT")
                        return _staged_build_from_row(existing)
                    connection.execute(
                        "DELETE FROM source_chunk_staging_plan WHERE build_signature = ?",
                        (build_signature,),
                    )
                else:
                    if existing is not None:
                        old_signature = bytes(existing["build_signature"])
                        connection.execute(
                            "DELETE FROM source_chunk_staging_chunks WHERE build_signature = ?",
                            (old_signature,),
                        )
                        connection.execute(
                            "DELETE FROM source_chunk_staging_plan WHERE build_signature = ?",
                            (old_signature,),
                        )
                        connection.execute(
                            "DELETE FROM source_chunk_staging_builds WHERE build_signature = ?",
                            (old_signature,),
                        )
                    connection.execute(
                        """
                        INSERT INTO source_chunk_staging_builds (
                            source_id, representation_id, chunking_profile_id,
                            build_signature, representation_hash, total_chunks, created_at_us
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            uuid_to_blob(source_id),
                            uuid_to_blob(representation_id),
                            uuid_to_blob(chunking_profile_id),
                            build_signature,
                            representation_hash,
                            len(plan),
                            created_at_us,
                        ),
                    )
                connection.executemany(
                    """
                    INSERT INTO source_chunk_staging_plan (
                        build_signature, chunk_index, start_anchor_value,
                        end_anchor_value, start_byte_offset, end_byte_offset, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            build_signature,
                            item.chunk_index,
                            item.start_anchor_value,
                            item.end_anchor_value,
                            item.start_byte_offset,
                            item.end_byte_offset,
                            item.content_hash,
                        )
                        for item in plan
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM source_chunk_staging_builds WHERE build_signature = ?",
                    (build_signature,),
                ).fetchone()
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        if row is None:
            raise SourceChunkStoreError("Staged SourceChunk build disappeared during prepare.")
        return _staged_build_from_row(row)

    def get_staged_build(self, build_signature: bytes) -> StagedSourceChunkBuildRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_chunk_staging_builds WHERE build_signature = ?",
                (build_signature,),
            ).fetchone()
        if row is None:
            raise SourceChunkNotFoundError("Staged SourceChunk build not found.")
        return _staged_build_from_row(row)

    def list_staged_plan(
        self,
        build_signature: bytes,
        *,
        start_index: int,
        limit: int,
    ) -> tuple[SourceChunkPlanRecord, ...]:
        if start_index < 0 or limit <= 0:
            raise ValueError("Staged plan range is invalid.")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM source_chunk_staging_plan
                WHERE build_signature = ? AND chunk_index >= ?
                ORDER BY chunk_index
                LIMIT ?
                """,
                (build_signature, start_index, limit),
            ).fetchall()
        return tuple(_plan_from_row(row) for row in rows)

    def stage_chunk_batch(
        self,
        *,
        build_signature: bytes,
        start_index: int,
        chunks: tuple[StagedSourceChunkRecord, ...],
    ) -> int:
        """Atomically replace one *unconfirmed* staged batch and return its end index."""
        if start_index < 0:
            raise ValueError("Staged chunk start_index must not be negative.")
        expected_indexes = tuple(range(start_index, start_index + len(chunks)))
        if tuple(item.chunk_index for item in chunks) != expected_indexes:
            raise SourceChunkStoreError("Staged chunk batch indexes are not contiguous.")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                build = connection.execute(
                    "SELECT * FROM source_chunk_staging_builds WHERE build_signature = ?",
                    (build_signature,),
                ).fetchone()
                if build is None:
                    raise SourceChunkNotFoundError("Staged SourceChunk build not found.")
                end_index = start_index + len(chunks)
                if end_index > int(build["total_chunks"]):
                    raise SourceChunkStoreError("Staged batch exceeds the deterministic plan.")
                # Rows at/after the durable checkpoint are not confirmed. Replacing
                # this exact batch makes crash-after-commit-before-checkpoint idempotent.
                connection.execute(
                    """
                    DELETE FROM source_chunk_staging_chunks
                    WHERE build_signature = ? AND chunk_index >= ? AND chunk_index < ?
                    """,
                    (build_signature, start_index, end_index),
                )
                connection.executemany(
                    """
                    INSERT INTO source_chunk_staging_chunks (
                        build_signature, chunk_index, chunk_id, source_id,
                        representation_id, chunking_profile_id, start_anchor_value,
                        end_anchor_value, content_hash, chunk_text, created_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            build_signature,
                            item.chunk_index,
                            uuid_to_blob(item.chunk_id),
                            uuid_to_blob(item.source_id),
                            uuid_to_blob(item.representation_id),
                            uuid_to_blob(item.chunking_profile_id),
                            item.start_anchor_value,
                            item.end_anchor_value,
                            item.content_hash,
                            item.chunk_text,
                            item.created_at_us,
                        )
                        for item in chunks
                    ),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return start_index + len(chunks)

    def iter_staged_chunks(
        self,
        build_signature: bytes,
    ) -> Iterator[StagedSourceChunkRecord]:
        """Stream unpublished staged chunks in deterministic order."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM source_chunk_staging_chunks
                WHERE build_signature = ?
                ORDER BY chunk_index
                """,
                (build_signature,),
            )
            for row in cursor:
                yield _staged_chunk_from_row(row)

    def staged_prefix_count(self, build_signature: bytes, end_index: int) -> int:
        if end_index < 0:
            raise ValueError("Staged prefix end_index must not be negative.")
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT count(*) AS n FROM source_chunk_staging_chunks
                WHERE build_signature = ? AND chunk_index < ?
                """,
                (build_signature, end_index),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def staged_chunk_count(self, build_signature: bytes) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS n FROM source_chunk_staging_chunks WHERE build_signature = ?",
                (build_signature,),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def discard_staged_build(self, build_signature: bytes) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM source_chunk_staging_chunks WHERE build_signature = ?",
                    (build_signature,),
                )
                connection.execute(
                    "DELETE FROM source_chunk_staging_plan WHERE build_signature = ?",
                    (build_signature,),
                )
                connection.execute(
                    "DELETE FROM source_chunk_staging_builds WHERE build_signature = ?",
                    (build_signature,),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def publish_staged_build(
        self,
        *,
        build_signature: bytes,
        processing_run_id: uuid.UUID,
        created_at_us: int,
    ) -> int:
        """Atomically publish a complete staged build and advance Derived generations once."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                build = connection.execute(
                    "SELECT * FROM source_chunk_staging_builds WHERE build_signature = ?",
                    (build_signature,),
                ).fetchone()
                if build is None:
                    raise SourceChunkNotFoundError("Staged SourceChunk build not found.")
                representation_id = uuid_from_blob(build["representation_id"])
                profile_id = uuid_from_blob(build["chunking_profile_id"])
                source_id = uuid_from_blob(build["source_id"])
                total_chunks = int(build["total_chunks"])
                stats = connection.execute(
                    """
                    SELECT count(*) AS n, min(chunk_index) AS lo, max(chunk_index) AS hi
                    FROM source_chunk_staging_chunks WHERE build_signature = ?
                    """,
                    (build_signature,),
                ).fetchone()
                count = int(stats["n"])
                if count != total_chunks:
                    raise SourceChunkStoreError(
                        f"Staged build is incomplete ({count}/{total_chunks} chunks)."
                    )
                if total_chunks and (int(stats["lo"]) != 0 or int(stats["hi"]) != total_chunks - 1):
                    raise SourceChunkStoreError("Staged build indexes are not contiguous.")
                mismatch = connection.execute(
                    """
                    SELECT 1 FROM source_chunk_staging_chunks
                    WHERE build_signature = ? AND (
                        source_id != ? OR representation_id != ? OR chunking_profile_id != ?
                    ) LIMIT 1
                    """,
                    (
                        build_signature,
                        uuid_to_blob(source_id),
                        uuid_to_blob(representation_id),
                        uuid_to_blob(profile_id),
                    ),
                ).fetchone()
                if mismatch is not None:
                    raise SourceChunkStoreError("Staged chunks disagree with staged build metadata.")

                connection.execute(
                    "DELETE FROM fts_archive WHERE representation_id = ? AND chunking_profile_id = ?",
                    (representation_id.hex, profile_id.hex),
                )
                connection.execute(
                    "DELETE FROM source_chunks WHERE representation_id = ? AND chunking_profile_id = ?",
                    (uuid_to_blob(representation_id), uuid_to_blob(profile_id)),
                )
                connection.execute(
                    "DELETE FROM source_chunk_builds WHERE representation_id = ? AND chunking_profile_id = ?",
                    (uuid_to_blob(representation_id), uuid_to_blob(profile_id)),
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
                        uuid_to_blob(profile_id),
                        build_signature,
                        uuid_to_blob(processing_run_id),
                        created_at_us,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO source_chunks (
                        chunk_id, source_id, representation_id, chunk_index,
                        chunking_profile_id, anchor_id, start_anchor_value,
                        end_anchor_value, content_hash, processing_run_id,
                        build_signature, chunk_text, created_at_us
                    )
                    SELECT chunk_id, source_id, representation_id, chunk_index,
                           chunking_profile_id, NULL, start_anchor_value,
                           end_anchor_value, content_hash, ?, build_signature,
                           chunk_text, created_at_us
                    FROM source_chunk_staging_chunks
                    WHERE build_signature = ?
                    ORDER BY chunk_index
                    """,
                    (uuid_to_blob(processing_run_id), build_signature),
                )
                connection.execute(
                    """
                    INSERT INTO fts_archive (
                        chunk_id, source_id, representation_id, chunk_index,
                        chunking_profile_id, start_anchor_value, end_anchor_value,
                        content_hash, build_signature, body
                    )
                    SELECT lower(hex(chunk_id)), lower(hex(source_id)),
                           lower(hex(representation_id)), CAST(chunk_index AS TEXT),
                           lower(hex(chunking_profile_id)),
                           CAST(start_anchor_value AS TEXT), CAST(end_anchor_value AS TEXT),
                           lower(hex(content_hash)), lower(hex(build_signature)), chunk_text
                    FROM source_chunk_staging_chunks
                    WHERE build_signature = ?
                    ORDER BY chunk_index
                    """,
                    (build_signature,),
                )
                connection.execute(
                    """
                    UPDATE archive_search_state
                    SET chunk_generation = chunk_generation + 1,
                        fts_generation = chunk_generation + 1,
                        updated_at_us = ?
                    WHERE singleton_id = 1
                    """,
                    (utc_now_us(),),
                )
                connection.execute(
                    "DELETE FROM source_chunk_staging_chunks WHERE build_signature = ?",
                    (build_signature,),
                )
                connection.execute(
                    "DELETE FROM source_chunk_staging_plan WHERE build_signature = ?",
                    (build_signature,),
                )
                connection.execute(
                    "DELETE FROM source_chunk_staging_builds WHERE build_signature = ?",
                    (build_signature,),
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return total_chunks

    def current_build(
        self,
        representation_id: uuid.UUID,
        chunking_profile_id: uuid.UUID,
    ) -> CurrentSourceChunkBuildRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT b.*, count(c.chunk_id) AS chunk_count
                FROM source_chunk_builds AS b
                LEFT JOIN source_chunks AS c
                  ON c.representation_id = b.representation_id
                 AND c.chunking_profile_id = b.chunking_profile_id
                WHERE b.representation_id = ? AND b.chunking_profile_id = ?
                GROUP BY b.representation_id, b.chunking_profile_id
                """,
                (uuid_to_blob(representation_id), uuid_to_blob(chunking_profile_id)),
            ).fetchone()
        return _current_build_from_row(row) if row is not None else None

    def iter_for_representation(
        self,
        representation_id: uuid.UUID,
        *,
        chunking_profile_id: uuid.UUID,
    ) -> Iterator[SourceChunkRecord]:
        """Stream current chunks in index order without a 5000-row materialization cap."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM source_chunks
                WHERE representation_id = ? AND chunking_profile_id = ?
                ORDER BY chunk_index, chunk_id
                """,
                (uuid_to_blob(representation_id), uuid_to_blob(chunking_profile_id)),
            )
            for row in cursor:
                yield _chunk_from_row(row)

    def get(self, chunk_id: uuid.UUID) -> SourceChunkRecord:
        with self.connect() as connection:
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
        with self.connect() as connection:
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
        with self.connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS n FROM source_chunks WHERE representation_id = ?",
                (uuid_to_blob(representation_id),),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def set_anchor_hint(self, chunk_id: uuid.UUID, anchor_id: uuid.UUID) -> None:
        """Attach a non-authoritative durable-anchor hint to one current chunk."""
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE source_chunks SET anchor_id = ? WHERE chunk_id = ?",
                (uuid_to_blob(anchor_id), uuid_to_blob(chunk_id)),
            )
        if cursor.rowcount != 1:
            raise SourceChunkNotFoundError(f"SourceChunk {chunk_id} not found.")

    def current_generation(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT chunk_generation
                FROM archive_search_state
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            raise SourceChunkStoreError("Derived archive search state is missing.")
        return int(row["chunk_generation"])

    def rebuild_archive_fts(self) -> int:
        """Reconstruct archive FTS from current SourceChunks without changing chunks."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM fts_archive")
                connection.execute(
                    """
                    INSERT INTO fts_archive (
                        chunk_id, source_id, representation_id, chunk_index,
                        chunking_profile_id, start_anchor_value, end_anchor_value,
                        content_hash, build_signature, body
                    )
                    SELECT
                        lower(hex(chunk_id)), lower(hex(source_id)),
                        lower(hex(representation_id)), CAST(chunk_index AS TEXT),
                        lower(hex(chunking_profile_id)),
                        CAST(start_anchor_value AS TEXT),
                        CAST(end_anchor_value AS TEXT),
                        lower(hex(content_hash)), lower(hex(build_signature)), chunk_text
                    FROM source_chunks
                    ORDER BY representation_id, chunking_profile_id, chunk_index, chunk_id
                    """
                )
                connection.execute(
                    """
                    UPDATE archive_search_state
                    SET fts_generation = chunk_generation,
                        updated_at_us = ?
                    WHERE singleton_id = 1
                    """,
                    (utc_now_us(),),
                )
                row = connection.execute(
                    "SELECT count(*) AS n FROM fts_archive"
                ).fetchone()
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        if row is None:
            raise SourceChunkStoreError("Archive FTS row count failed.")
        return int(row["n"])

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open the reconstructible search store with schema validation."""
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
    if user_version not in {0, 1, 2, 3, _DERIVED_SCHEMA_VERSION}:
        raise SourceChunkStoreError("Derived search.db schema version is unsupported.")

    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    if user_version == 0:
        _create_schema_v4(connection)
    elif user_version == 1:
        _migrate_v1_to_v2(connection)
        _migrate_v2_to_v3(connection)
        _migrate_v3_to_v4(connection)
    elif user_version == 2:
        _migrate_v2_to_v3(connection)
        _migrate_v3_to_v4(connection)
    elif user_version == 3:
        _migrate_v3_to_v4(connection)


def _create_schema_v4(connection: sqlite3.Connection) -> None:
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
        CREATE VIRTUAL TABLE fts_archive USING fts5(
            chunk_id UNINDEXED,
            source_id UNINDEXED,
            representation_id UNINDEXED,
            chunk_index UNINDEXED,
            chunking_profile_id UNINDEXED,
            start_anchor_value UNINDEXED,
            end_anchor_value UNINDEXED,
            content_hash UNINDEXED,
            build_signature UNINDEXED,
            body,
            tokenize = 'unicode61 remove_diacritics 2'
        );
        CREATE TABLE archive_search_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            chunk_generation INTEGER NOT NULL CHECK(chunk_generation >= 0),
            fts_generation INTEGER NOT NULL CHECK(fts_generation >= 0),
            updated_at_us INTEGER NOT NULL
        );
        INSERT INTO archive_search_state (
            singleton_id, chunk_generation, fts_generation, updated_at_us
        ) VALUES (1, 0, 0, 0);
        CREATE TABLE archive_embeddings (
            chunk_id BLOB(16) NOT NULL CHECK(length(chunk_id) = 16),
            model_id TEXT NOT NULL,
            indexed_chunk_generation INTEGER NOT NULL CHECK(indexed_chunk_generation >= 0),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            vector_blob BLOB NOT NULL,
            text_sha256 BLOB(32) NOT NULL CHECK(length(text_sha256) = 32),
            created_at_us INTEGER NOT NULL,
            PRIMARY KEY(chunk_id, model_id, indexed_chunk_generation)
        ) WITHOUT ROWID;
        CREATE INDEX idx_archive_embeddings_model_generation
            ON archive_embeddings(model_id, indexed_chunk_generation);
        CREATE TABLE archive_embedding_state (
            model_id TEXT PRIMARY KEY,
            indexed_chunk_generation INTEGER NOT NULL CHECK(indexed_chunk_generation >= 0),
            indexed_visibility_commit_seq INTEGER NOT NULL DEFAULT -1
                CHECK(indexed_visibility_commit_seq >= -1),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            document_count INTEGER NOT NULL CHECK(document_count >= 0),
            rebuilt_at_us INTEGER NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE source_chunk_staging_builds (
            build_signature BLOB(32) PRIMARY KEY CHECK(length(build_signature) = 32),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            chunking_profile_id BLOB(16) NOT NULL CHECK(length(chunking_profile_id) = 16),
            representation_hash BLOB(32) NOT NULL CHECK(length(representation_hash) = 32),
            total_chunks INTEGER NOT NULL CHECK(total_chunks >= 0),
            created_at_us INTEGER NOT NULL,
            UNIQUE(representation_id, chunking_profile_id)
        ) WITHOUT ROWID;
        CREATE TABLE source_chunk_staging_plan (
            build_signature BLOB(32) NOT NULL CHECK(length(build_signature) = 32),
            chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
            start_anchor_value INTEGER NOT NULL CHECK(start_anchor_value >= 0),
            end_anchor_value INTEGER NOT NULL CHECK(end_anchor_value >= start_anchor_value),
            start_byte_offset INTEGER NOT NULL CHECK(start_byte_offset >= 0),
            end_byte_offset INTEGER NOT NULL CHECK(end_byte_offset >= start_byte_offset),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            PRIMARY KEY(build_signature, chunk_index)
        ) WITHOUT ROWID;
        CREATE TABLE source_chunk_staging_chunks (
            build_signature BLOB(32) NOT NULL CHECK(length(build_signature) = 32),
            chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
            chunk_id BLOB(16) NOT NULL UNIQUE CHECK(length(chunk_id) = 16),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            chunking_profile_id BLOB(16) NOT NULL CHECK(length(chunking_profile_id) = 16),
            start_anchor_value INTEGER NOT NULL CHECK(start_anchor_value >= 0),
            end_anchor_value INTEGER NOT NULL CHECK(end_anchor_value >= start_anchor_value),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            chunk_text TEXT NOT NULL,
            created_at_us INTEGER NOT NULL,
            PRIMARY KEY(build_signature, chunk_index)
        ) WITHOUT ROWID;
        PRAGMA user_version = {_DERIVED_SCHEMA_VERSION};
        COMMIT;
        """
    )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        BEGIN IMMEDIATE;
        CREATE VIRTUAL TABLE fts_archive USING fts5(
            chunk_id UNINDEXED,
            source_id UNINDEXED,
            representation_id UNINDEXED,
            chunk_index UNINDEXED,
            chunking_profile_id UNINDEXED,
            start_anchor_value UNINDEXED,
            end_anchor_value UNINDEXED,
            content_hash UNINDEXED,
            build_signature UNINDEXED,
            body,
            tokenize = 'unicode61 remove_diacritics 2'
        );
        INSERT INTO fts_archive (
            chunk_id, source_id, representation_id, chunk_index,
            chunking_profile_id, start_anchor_value, end_anchor_value,
            content_hash, build_signature, body
        )
        SELECT
            lower(hex(chunk_id)), lower(hex(source_id)), lower(hex(representation_id)),
            CAST(chunk_index AS TEXT), lower(hex(chunking_profile_id)),
            CAST(start_anchor_value AS TEXT), CAST(end_anchor_value AS TEXT),
            lower(hex(content_hash)), lower(hex(build_signature)), chunk_text
        FROM source_chunks
        ORDER BY representation_id, chunking_profile_id, chunk_index, chunk_id;
        CREATE TABLE archive_search_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            chunk_generation INTEGER NOT NULL CHECK(chunk_generation >= 0),
            fts_generation INTEGER NOT NULL CHECK(fts_generation >= 0),
            updated_at_us INTEGER NOT NULL
        );
        INSERT INTO archive_search_state (
            singleton_id, chunk_generation, fts_generation, updated_at_us
        )
        SELECT 1,
               CASE WHEN EXISTS(SELECT 1 FROM source_chunks) THEN 1 ELSE 0 END,
               CASE WHEN EXISTS(SELECT 1 FROM source_chunks) THEN 1 ELSE 0 END,
               0;
        CREATE TABLE archive_embeddings (
            chunk_id BLOB(16) NOT NULL CHECK(length(chunk_id) = 16),
            model_id TEXT NOT NULL,
            indexed_chunk_generation INTEGER NOT NULL CHECK(indexed_chunk_generation >= 0),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            vector_blob BLOB NOT NULL,
            text_sha256 BLOB(32) NOT NULL CHECK(length(text_sha256) = 32),
            created_at_us INTEGER NOT NULL,
            PRIMARY KEY(chunk_id, model_id, indexed_chunk_generation)
        ) WITHOUT ROWID;
        CREATE INDEX idx_archive_embeddings_model_generation
            ON archive_embeddings(model_id, indexed_chunk_generation);
        CREATE TABLE archive_embedding_state (
            model_id TEXT PRIMARY KEY,
            indexed_chunk_generation INTEGER NOT NULL CHECK(indexed_chunk_generation >= 0),
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            document_count INTEGER NOT NULL CHECK(document_count >= 0),
            rebuilt_at_us INTEGER NOT NULL
        ) WITHOUT ROWID;
        PRAGMA user_version = 2;
        COMMIT;
        """
    )




def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        BEGIN IMMEDIATE;
        CREATE TABLE source_chunk_staging_builds (
            build_signature BLOB(32) PRIMARY KEY CHECK(length(build_signature) = 32),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            chunking_profile_id BLOB(16) NOT NULL CHECK(length(chunking_profile_id) = 16),
            representation_hash BLOB(32) NOT NULL CHECK(length(representation_hash) = 32),
            total_chunks INTEGER NOT NULL CHECK(total_chunks >= 0),
            created_at_us INTEGER NOT NULL,
            UNIQUE(representation_id, chunking_profile_id)
        ) WITHOUT ROWID;
        CREATE TABLE source_chunk_staging_plan (
            build_signature BLOB(32) NOT NULL CHECK(length(build_signature) = 32),
            chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
            start_anchor_value INTEGER NOT NULL CHECK(start_anchor_value >= 0),
            end_anchor_value INTEGER NOT NULL CHECK(end_anchor_value >= start_anchor_value),
            start_byte_offset INTEGER NOT NULL CHECK(start_byte_offset >= 0),
            end_byte_offset INTEGER NOT NULL CHECK(end_byte_offset >= start_byte_offset),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            PRIMARY KEY(build_signature, chunk_index)
        ) WITHOUT ROWID;
        CREATE TABLE source_chunk_staging_chunks (
            build_signature BLOB(32) NOT NULL CHECK(length(build_signature) = 32),
            chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
            chunk_id BLOB(16) NOT NULL UNIQUE CHECK(length(chunk_id) = 16),
            source_id BLOB(16) NOT NULL CHECK(length(source_id) = 16),
            representation_id BLOB(16) NOT NULL CHECK(length(representation_id) = 16),
            chunking_profile_id BLOB(16) NOT NULL CHECK(length(chunking_profile_id) = 16),
            start_anchor_value INTEGER NOT NULL CHECK(start_anchor_value >= 0),
            end_anchor_value INTEGER NOT NULL CHECK(end_anchor_value >= start_anchor_value),
            content_hash BLOB(32) NOT NULL CHECK(length(content_hash) = 32),
            chunk_text TEXT NOT NULL,
            created_at_us INTEGER NOT NULL,
            PRIMARY KEY(build_signature, chunk_index)
        ) WITHOUT ROWID;
        PRAGMA user_version = 3;
        COMMIT;
        """
    )

def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        BEGIN IMMEDIATE;
        ALTER TABLE archive_embedding_state
            ADD COLUMN indexed_visibility_commit_seq INTEGER NOT NULL
            DEFAULT -1
            CHECK(indexed_visibility_commit_seq >= -1);
        PRAGMA user_version = 4;
        COMMIT;
        """
    )


def _plan_from_row(row: sqlite3.Row) -> SourceChunkPlanRecord:
    return SourceChunkPlanRecord(
        chunk_index=int(row["chunk_index"]),
        start_anchor_value=int(row["start_anchor_value"]),
        end_anchor_value=int(row["end_anchor_value"]),
        start_byte_offset=int(row["start_byte_offset"]),
        end_byte_offset=int(row["end_byte_offset"]),
        content_hash=bytes(row["content_hash"]),
    )


def _staged_build_from_row(row: sqlite3.Row) -> StagedSourceChunkBuildRecord:
    return StagedSourceChunkBuildRecord(
        source_id=uuid_from_blob(row["source_id"]),
        representation_id=uuid_from_blob(row["representation_id"]),
        chunking_profile_id=uuid_from_blob(row["chunking_profile_id"]),
        build_signature=bytes(row["build_signature"]),
        representation_hash=bytes(row["representation_hash"]),
        total_chunks=int(row["total_chunks"]),
        created_at_us=int(row["created_at_us"]),
    )


def _staged_chunk_from_row(row: sqlite3.Row) -> StagedSourceChunkRecord:
    return StagedSourceChunkRecord(
        chunk_id=uuid_from_blob(row["chunk_id"]),
        source_id=uuid_from_blob(row["source_id"]),
        representation_id=uuid_from_blob(row["representation_id"]),
        chunk_index=int(row["chunk_index"]),
        chunking_profile_id=uuid_from_blob(row["chunking_profile_id"]),
        start_anchor_value=int(row["start_anchor_value"]),
        end_anchor_value=int(row["end_anchor_value"]),
        content_hash=bytes(row["content_hash"]),
        build_signature=bytes(row["build_signature"]),
        chunk_text=str(row["chunk_text"]),
        created_at_us=int(row["created_at_us"]),
    )


def _current_build_from_row(row: sqlite3.Row) -> CurrentSourceChunkBuildRecord:
    return CurrentSourceChunkBuildRecord(
        representation_id=uuid_from_blob(row["representation_id"]),
        chunking_profile_id=uuid_from_blob(row["chunking_profile_id"]),
        build_signature=bytes(row["build_signature"]),
        processing_run_id=uuid_from_blob(row["processing_run_id"]),
        created_at_us=int(row["created_at_us"]),
        chunk_count=int(row["chunk_count"]),
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
