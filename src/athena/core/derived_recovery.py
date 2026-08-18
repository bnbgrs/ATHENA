"""Read-only diagnosis and gated reconstruction of ATHENA Derived State."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import struct
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from athena.storage.recovery import inspect_database_read_only
from athena.storage.schema import SCHEMA_VERSION

# search.db is reconstructible Derived State, but it may contain durable,
# unpublished chunk staging. Recovery therefore validates the existing file
# read-only and never deletes/recreates an invalid store implicitly.
_DERIVED_APPLICATION_ID = 1_096_042_564
_DERIVED_SCHEMA_VERSION = 4

_HNSW_FORMAT_VERSION = 1
_KNOWLEDGE_HNSW_NAMESPACE = "knowledge"
_ARCHIVE_HNSW_NAMESPACE = "archive"
_KNOWLEDGE_REFERENCE_SIZE = 33
_ARCHIVE_REFERENCE_SIZE = 16

_REFERENCE_TYPE_CODE = {
    "knowledge": 1,
    "claim": 2,
    "chat_message": 3,
}


class DerivedRecoveryError(RuntimeError):
    """A reconstructible recovery operation could not complete safely."""


class DerivedRecoveryRequiredError(DerivedRecoveryError):
    """Derived State requires a broader recovery action than the requested fix."""


class DerivedLayerStatus(str, Enum):
    """Read-only classification of one Derived State layer."""

    MISSING = "missing"
    CURRENT = "current"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class DerivedIndexReport:
    """Payload-free state of one generation/watermark-backed index."""

    status: DerivedLayerStatus
    current_snapshot: int | None
    indexed_snapshot: int | None
    source_document_count: int | None
    indexed_document_count: int | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class DerivedEmbeddingReport:
    """Payload-free diagnosis for one storage-scoped embedding model."""

    storage_model_id: str
    published: bool
    indexed_snapshot: int | None
    current_snapshot: int
    dimensions: int | None
    document_count: int | None
    persisted_document_count: int
    unpublished_document_count: int
    persisted_valid: bool
    embeddings_current: bool
    hnsw_files_plausible: bool
    embedding_rebuild_required: bool
    hnsw_rebuild_required: bool


@dataclass(frozen=True, slots=True)
class DerivedRecoveryReport:
    """Read-only recovery diagnosis without loading model/runtime services."""

    canonical_integrity_confirmed: bool
    normal_writes_allowed: bool
    protected_scopes_locked: bool
    canonical_fts: DerivedIndexReport
    archive_store_status: DerivedLayerStatus
    archive_fts: DerivedIndexReport
    archive_staged_build_count: int | None
    archive_staged_chunk_count: int | None
    archive_hidden_chunk_count: int | None
    canonical_embeddings: tuple[DerivedEmbeddingReport, ...]
    archive_embeddings: tuple[DerivedEmbeddingReport, ...]
    detail: str | None


@dataclass(frozen=True, slots=True)
class _ArchiveInspection:
    store_status: DerivedLayerStatus
    fts: DerivedIndexReport
    staged_build_count: int | None
    staged_chunk_count: int | None
    hidden_chunk_count: int | None
    embeddings: tuple[DerivedEmbeddingReport, ...]
    detail: str | None


class DerivedRecoveryService:
    """Diagnose Derived State read-only and perform explicit safe rebuilds."""

    def __init__(
        self,
        *,
        database_path: Path,
        derived_root: Path,
    ) -> None:
        self.database_path = database_path.expanduser().resolve(strict=False)
        self.derived_root = derived_root.expanduser().resolve(strict=False)
        self.archive_database_path = self.derived_root / "search.db"
        self.hnsw_root = self.derived_root / "hnsw"

    def inspect(self) -> DerivedRecoveryReport:
        """Inspect canonical and derived indexes without intentional writes."""

        preflight = inspect_database_read_only(self.database_path)

        if not preflight.exists:
            raise DerivedRecoveryRequiredError(
                "Derived recovery requires an existing canonical ATHENA database."
            )

        if preflight.schema_version != SCHEMA_VERSION:
            raise DerivedRecoveryRequiredError(
                "Derived recovery requires the current canonical schema; "
                "recovery mode must not perform an implicit migration."
            )

        with _open_read_only(self.database_path) as canonical:
            canonical_fts = _inspect_canonical_fts(canonical)
            visible_pairs = _visible_representation_pairs(canonical)
            archive_visibility_commit_seq = (
                _archive_visibility_commit_seq(canonical)
            )
            canonical_embeddings = _inspect_canonical_embeddings(
                canonical,
                canonical_fts=canonical_fts,
                hnsw_root=self.hnsw_root,
            )

            archive = _inspect_archive(
                self.archive_database_path,
                hnsw_root=self.hnsw_root,
                visible_pairs=visible_pairs,
                current_visibility_commit_seq=(
                    archive_visibility_commit_seq
                ),
            )

        return DerivedRecoveryReport(
            canonical_integrity_confirmed=True,
            normal_writes_allowed=False,
            protected_scopes_locked=True,
            canonical_fts=canonical_fts,
            archive_store_status=archive.store_status,
            archive_fts=archive.fts,
            archive_staged_build_count=archive.staged_build_count,
            archive_staged_chunk_count=archive.staged_chunk_count,
            archive_hidden_chunk_count=archive.hidden_chunk_count,
            canonical_embeddings=canonical_embeddings,
            archive_embeddings=archive.embeddings,
            detail=archive.detail,
        )

    def rebuild_canonical_fts(self) -> int:
        """Rebuild only canonical-db FTS after canonical integrity is proven."""

        before = self.inspect()

        if before.canonical_fts.status is DerivedLayerStatus.INVALID:
            raise DerivedRecoveryRequiredError(
                "Canonical FTS structure is invalid; refusing a content-only rebuild."
            )

        from athena.retrieval.search import LocalSearchService
        from athena.storage.database import SQLiteDatabase

        database = SQLiteDatabase(self.database_path)
        started = False

        try:
            database.start()
            started = True
            indexed = LocalSearchService(database).rebuild()
        finally:
            if started:
                database.stop()

        after = self.inspect()

        if after.canonical_fts.status is not DerivedLayerStatus.CURRENT:
            raise DerivedRecoveryError(
                "Canonical FTS rebuild did not become current."
            )

        return indexed

    def rebuild_archive_fts(self) -> int:
        """Rebuild archive FTS only from an already valid SourceChunk store."""

        before = self.inspect()

        if before.archive_store_status is DerivedLayerStatus.MISSING:
            raise DerivedRecoveryRequiredError(
                "Derived search.db is missing; FTS-only recovery cannot "
                "reconstruct SourceChunks."
            )

        if before.archive_store_status is DerivedLayerStatus.INVALID:
            raise DerivedRecoveryRequiredError(
                "Derived search.db is invalid; refusing to delete or recreate "
                "possible unpublished chunk staging."
            )

        if before.archive_store_status is DerivedLayerStatus.STALE:
            raise DerivedRecoveryRequiredError(
                "Derived SourceChunks disagree with canonical visibility; "
                "FTS-only recovery would preserve hidden stale chunks."
            )

        if before.archive_fts.status is DerivedLayerStatus.INVALID:
            raise DerivedRecoveryRequiredError(
                "Archive FTS structure is invalid; refusing implicit "
                "search.db schema repair."
            )

        from athena.source.chunk_store import (
            _DERIVED_APPLICATION_ID as runtime_application_id,
        )
        from athena.source.chunk_store import (
            _DERIVED_SCHEMA_VERSION as runtime_schema_version,
        )
        from athena.source.chunk_store import (
            SourceChunkStore,
        )

        if (
            runtime_application_id != _DERIVED_APPLICATION_ID
            or runtime_schema_version != _DERIVED_SCHEMA_VERSION
        ):
            raise DerivedRecoveryRequiredError(
                "Derived search.db format changed relative to recovery code."
            )

        indexed = SourceChunkStore(self.derived_root).rebuild_archive_fts()
        after = self.inspect()

        if after.archive_store_status is not DerivedLayerStatus.CURRENT:
            raise DerivedRecoveryError(
                "Archive SourceChunk store changed during FTS recovery."
            )

        if after.archive_fts.status is not DerivedLayerStatus.CURRENT:
            raise DerivedRecoveryError(
                "Archive FTS rebuild did not become current."
            )

        return indexed

    def rebuild_canonical_hnsw_from_persisted(self) -> int:
        """Rebuild HNSW from current persisted vectors without a model call."""

        report = self.inspect()

        if report.canonical_fts.status is not DerivedLayerStatus.CURRENT:
            raise DerivedRecoveryRequiredError(
                "Canonical FTS must be current before HNSW reconstruction."
            )

        candidates = tuple(
            item
            for item in report.canonical_embeddings
            if item.embeddings_current
        )

        if not candidates:
            return 0

        _require_safe_hnsw_destination(
            self.derived_root,
            self.hnsw_root,
        )

        from athena.retrieval.hnsw import HnswIndexError, HnswIndexStore

        store = HnswIndexStore(
            self.hnsw_root,
            namespace=_KNOWLEDGE_HNSW_NAMESPACE,
            reference_size=_KNOWLEDGE_REFERENCE_SIZE,
        )

        rebuilt = 0

        try:
            with _open_read_only(self.database_path) as connection:
                for model in candidates:
                    if (
                        model.indexed_snapshot is None
                        or model.dimensions is None
                        or model.document_count is None
                    ):
                        raise DerivedRecoveryError(
                            "Current canonical embedding state is incomplete."
                        )

                    entries = _canonical_hnsw_entries(
                        connection,
                        storage_model_id=model.storage_model_id,
                        dimensions=model.dimensions,
                    )

                    if len(entries) != model.document_count:
                        raise DerivedRecoveryError(
                            "Canonical persisted embedding count changed "
                            "during HNSW rebuild."
                        )

                    store.build(
                        model_id=model.storage_model_id,
                        snapshot=model.indexed_snapshot,
                        dimensions=model.dimensions,
                        entries=entries,
                    )
                    rebuilt += 1
        except HnswIndexError as exc:
            raise DerivedRecoveryError(
                f"Canonical HNSW rebuild failed: {exc}"
            ) from exc

        after = self.inspect()
        rebuilt_ids = {
            item.storage_model_id
            for item in candidates
        }

        for item in after.canonical_embeddings:
            if (
                item.storage_model_id in rebuilt_ids
                and item.embeddings_current
                and not item.hnsw_files_plausible
            ):
                raise DerivedRecoveryError(
                    "Canonical HNSW files failed post-rebuild validation."
                )

        return rebuilt

    def rebuild_archive_hnsw_from_persisted(self) -> int:
        """Rebuild archive HNSW from current vectors without a model call."""

        report = self.inspect()

        if report.archive_store_status is not DerivedLayerStatus.CURRENT:
            raise DerivedRecoveryRequiredError(
                "Archive SourceChunk store must be current before HNSW rebuild."
            )

        if report.archive_fts.status is not DerivedLayerStatus.CURRENT:
            raise DerivedRecoveryRequiredError(
                "Archive FTS must be current before HNSW rebuild."
            )

        candidates = tuple(
            item
            for item in report.archive_embeddings
            if item.embeddings_current
        )

        if not candidates:
            return 0

        _require_safe_hnsw_destination(
            self.derived_root,
            self.hnsw_root,
        )

        from athena.retrieval.hnsw import HnswIndexError, HnswIndexStore

        store = HnswIndexStore(
            self.hnsw_root,
            namespace=_ARCHIVE_HNSW_NAMESPACE,
            reference_size=_ARCHIVE_REFERENCE_SIZE,
        )

        rebuilt = 0

        try:
            with _open_read_only(self.archive_database_path) as connection:
                for model in candidates:
                    if (
                        model.indexed_snapshot is None
                        or model.dimensions is None
                        or model.document_count is None
                    ):
                        raise DerivedRecoveryError(
                            "Current archive embedding state is incomplete."
                        )

                    entries = _archive_hnsw_entries(
                        connection,
                        storage_model_id=model.storage_model_id,
                        snapshot=model.indexed_snapshot,
                        dimensions=model.dimensions,
                    )

                    if len(entries) != model.document_count:
                        raise DerivedRecoveryError(
                            "Archive persisted embedding count changed "
                            "during HNSW rebuild."
                        )

                    store.build(
                        model_id=model.storage_model_id,
                        snapshot=model.indexed_snapshot,
                        dimensions=model.dimensions,
                        entries=entries,
                    )
                    rebuilt += 1
        except HnswIndexError as exc:
            raise DerivedRecoveryError(
                f"Archive HNSW rebuild failed: {exc}"
            ) from exc

        after = self.inspect()
        rebuilt_ids = {
            item.storage_model_id
            for item in candidates
        }

        for item in after.archive_embeddings:
            if (
                item.storage_model_id in rebuilt_ids
                and item.embeddings_current
                and not item.hnsw_files_plausible
            ):
                raise DerivedRecoveryError(
                    "Archive HNSW files failed post-rebuild validation."
                )

        return rebuilt


@contextmanager
def _open_read_only(path: Path) -> Iterator[sqlite3.Connection]:
    uri = f"{path.resolve(strict=False).as_uri()}?mode=ro"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=5.0,
        autocommit=True,
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def _inspect_canonical_fts(
    connection: sqlite3.Connection,
) -> DerivedIndexReport:
    try:
        current_snapshot = _current_commit_seq(connection)
        state = connection.execute(
            """
            SELECT indexed_commit_seq
            FROM search_index_state
            WHERE singleton_id = 1
            """
        ).fetchone()

        if state is None:
            return DerivedIndexReport(
                status=DerivedLayerStatus.INVALID,
                current_snapshot=current_snapshot,
                indexed_snapshot=None,
                source_document_count=None,
                indexed_document_count=None,
                detail="Canonical search index state is missing.",
            )

        indexed_snapshot = int(state["indexed_commit_seq"])

        expected_digest, expected_count = (
            _expected_canonical_fts_digest(connection)
        )
        actual_digest, actual_count = (
            _actual_canonical_fts_digest(connection)
        )

        global_snapshot = _global_commit_seq(
            connection
        )

        if indexed_snapshot > global_snapshot:
            status = DerivedLayerStatus.INVALID
            detail = "Canonical FTS watermark is ahead of canonical commits."
        elif (
            indexed_snapshot < current_snapshot
            or expected_digest != actual_digest
            or expected_count != actual_count
        ):
            status = DerivedLayerStatus.STALE
            detail = "Canonical FTS differs from its deterministic projection."
        else:
            status = DerivedLayerStatus.CURRENT
            detail = None

        return DerivedIndexReport(
            status=status,
            current_snapshot=current_snapshot,
            indexed_snapshot=indexed_snapshot,
            source_document_count=expected_count,
            indexed_document_count=actual_count,
            detail=detail,
        )

    except (
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as exc:
        return DerivedIndexReport(
            status=DerivedLayerStatus.INVALID,
            current_snapshot=None,
            indexed_snapshot=None,
            source_document_count=None,
            indexed_document_count=None,
            detail=(
                "Canonical FTS could not be inspected safely: "
                f"{type(exc).__name__}."
            ),
        )


def _expected_canonical_fts_digest(
    connection: sqlite3.Connection,
) -> tuple[bytes, int]:
    from athena.chat.provenance import (
        strip_model_facing_assistant_trace,
        strip_turn_local_grounding_markers,
    )

    rows: list[tuple[object, ...]] = []

    chat_rows = connection.execute(
        """
        SELECT
            lower(hex(m.message_id)) AS entity_id,
            lower(hex(h.current_revision_id)) AS revision_id,
            m.message_type,
            'Chat message ' || CAST(m.sequence_no AS TEXT) AS title,
            mr.content AS body
        FROM chat_messages AS m
        JOIN chats AS ch
          ON ch.chat_id = m.chat_id
        JOIN entity_registry AS e
          ON e.entity_id = m.message_id
        JOIN entity_heads AS h
          ON h.entity_id = m.message_id
        JOIN chat_message_revisions AS mr
          ON mr.revision_id = h.current_revision_id
        WHERE e.lifecycle_state = 'active'
          AND ch.lifecycle_state = 'active'
          AND ch.archive_mode = 'standard'
          AND mr.protected_payload_id IS NULL
          AND mr.content IS NOT NULL
          AND length(trim(mr.content)) > 0
        ORDER BY m.message_id
        """
    ).fetchall()

    for row in chat_rows:
        message_type = str(row["message_type"])
        body = str(row["body"])

        if message_type == "assistant":
            body = strip_model_facing_assistant_trace(body)
        else:
            body = strip_turn_local_grounding_markers(body)

        rows.append(
            (
                "chat_message",
                str(row["entity_id"]),
                str(row["revision_id"]),
                str(row["title"]),
                body,
            )
        )

    claim_rows = connection.execute(
        """
        SELECT
            lower(hex(c.claim_id)) AS entity_id,
            lower(hex(h.current_revision_id)) AS revision_id,
            cr.statement AS body
        FROM claims AS c
        JOIN entity_registry AS e
          ON e.entity_id = c.claim_id
        JOIN entity_heads AS h
          ON h.entity_id = c.claim_id
        JOIN claim_revisions AS cr
          ON cr.revision_id = h.current_revision_id
        WHERE e.lifecycle_state = 'active'
          AND cr.protected_payload_id IS NULL
          AND cr.statement IS NOT NULL
          AND length(trim(cr.statement)) > 0
        ORDER BY c.claim_id
        """
    ).fetchall()

    rows.extend(
        (
            "claim",
            str(row["entity_id"]),
            str(row["revision_id"]),
            "",
            str(row["body"]),
        )
        for row in claim_rows
    )

    knowledge_rows = connection.execute(
        """
        SELECT
            lower(hex(k.knowledge_id)) AS entity_id,
            lower(hex(h.current_revision_id)) AS revision_id,
            COALESCE(kr.title, '') AS title,
            kr.body AS body
        FROM knowledge_units AS k
        JOIN entity_registry AS e
          ON e.entity_id = k.knowledge_id
        JOIN entity_heads AS h
          ON h.entity_id = k.knowledge_id
        JOIN knowledge_unit_revisions AS kr
          ON kr.revision_id = h.current_revision_id
        WHERE e.lifecycle_state = 'active'
          AND kr.protected_payload_id IS NULL
          AND kr.body IS NOT NULL
          AND length(trim(kr.body)) > 0
        ORDER BY k.knowledge_id
        """
    ).fetchall()

    rows.extend(
        (
            "knowledge",
            str(row["entity_id"]),
            str(row["revision_id"]),
            str(row["title"]),
            str(row["body"]),
        )
        for row in knowledge_rows
    )

    return _digest_rows(rows)


def _actual_canonical_fts_digest(
    connection: sqlite3.Connection,
) -> tuple[bytes, int]:
    cursor = connection.execute(
        """
        SELECT
            entity_type,
            entity_id,
            revision_id,
            title,
            body
        FROM search_fts
        ORDER BY entity_type, entity_id, revision_id, rowid
        """
    )

    return _digest_rows(
        (
            str(row["entity_type"]),
            str(row["entity_id"]),
            str(row["revision_id"]),
            row["title"],
            row["body"],
        )
        for row in cursor
    )


def _current_commit_seq(
    connection: sqlite3.Connection,
) -> int:
    # Lazy import keeps recovery diagnosis independent from model/runtime
    # construction while sharing the exact normal search freshness contract.
    from athena.retrieval.search import (
        current_search_projection_commit_seq,
    )

    return current_search_projection_commit_seq(
        connection
    )


def _global_commit_seq(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq
        FROM commit_records
        """
    ).fetchone()

    return (
        0
        if row is None
        else int(
            row["commit_seq"]
        )
    )



def _archive_visibility_commit_seq(
    connection: sqlite3.Connection,
) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(changes.commit_seq), 0) AS commit_seq
        FROM commit_changes AS changes
        JOIN entity_registry AS registry
          ON registry.entity_id = changes.entity_id
        WHERE registry.entity_type IN (
            'source',
            'source_representation'
        )
        """
    ).fetchone()
    return 0 if row is None else int(row["commit_seq"])


def _visible_representation_pairs(
    connection: sqlite3.Connection,
) -> frozenset[tuple[bytes, bytes]]:
    rows = connection.execute(
        """
        SELECT
            sr.source_id,
            sr.representation_id
        FROM source_representations AS sr
        JOIN sources AS s
          ON s.source_id = sr.source_id
        JOIN entity_registry AS source_entity
          ON source_entity.entity_id = s.source_id
        JOIN entity_registry AS representation_entity
          ON representation_entity.entity_id = sr.representation_id
        LEFT JOIN protected_sources AS protected
          ON protected.source_id = s.source_id
        WHERE source_entity.lifecycle_state = 'active'
          AND representation_entity.lifecycle_state = 'active'
          AND s.lifecycle_state IN ('ready', 'partial')
          AND sr.retention_state = 'retained'
          AND protected.protection_scope_id IS NULL
        """
    ).fetchall()

    return frozenset(
        (
            bytes(row["source_id"]),
            bytes(row["representation_id"]),
        )
        for row in rows
    )


def _inspect_archive(
    path: Path,
    *,
    hnsw_root: Path,
    visible_pairs: frozenset[tuple[bytes, bytes]],
    current_visibility_commit_seq: int,
) -> _ArchiveInspection:
    if not os.path.lexists(path):
        return _ArchiveInspection(
            store_status=DerivedLayerStatus.MISSING,
            fts=DerivedIndexReport(
                status=DerivedLayerStatus.MISSING,
                current_snapshot=None,
                indexed_snapshot=None,
                source_document_count=None,
                indexed_document_count=None,
                detail="Derived search.db is absent.",
            ),
            staged_build_count=None,
            staged_chunk_count=None,
            hidden_chunk_count=None,
            embeddings=(),
            detail=(
                "Derived SourceChunks are absent; full deterministic "
                "regeneration is required before archive FTS."
            ),
        )

    if path.is_symlink() or not path.is_file():
        return _invalid_archive(
            "Derived search.db is not a safe regular file."
        )

    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")

        if not os.path.lexists(sidecar):
            continue

        if sidecar.is_symlink() or not sidecar.is_file():
            return _invalid_archive(
                "Derived SQLite sidecar is not a safe regular file."
            )

    try:
        with _open_read_only(path) as connection:
            application_id = int(
                connection.execute(
                    "PRAGMA application_id"
                ).fetchone()[0]
            )
            schema_version = int(
                connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            )

            if application_id != _DERIVED_APPLICATION_ID:
                return _invalid_archive(
                    "Derived search.db application_id is not ATHENA."
                )

            if schema_version not in {
                3,
                _DERIVED_SCHEMA_VERSION,
            }:
                return _invalid_archive(
                    "Derived search.db schema requires a separate "
                    "migration/regeneration decision."
                )

            quick_rows = tuple(
                str(row[0])
                for row in connection.execute(
                    "PRAGMA quick_check"
                ).fetchall()
            )

            if quick_rows != ("ok",):
                return _invalid_archive(
                    "Derived search.db quick_check failed."
                )

            chunk_rows = connection.execute(
                """
                SELECT
                    chunk_id,
                    source_id,
                    representation_id,
                    content_hash
                FROM source_chunks
                ORDER BY chunk_id
                """
            ).fetchall()

            hidden_chunk_count = sum(
                1
                for row in chunk_rows
                if (
                    bytes(row["source_id"]),
                    bytes(row["representation_id"]),
                )
                not in visible_pairs
            )

            archive_fts = _inspect_archive_fts(connection)

            staged_build_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM source_chunk_staging_builds
                    """
                ).fetchone()[0]
            )
            staged_chunk_count = int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM source_chunk_staging_chunks
                    """
                ).fetchone()[0]
            )

            if hidden_chunk_count:
                store_status = DerivedLayerStatus.STALE
                detail = (
                    "Derived SourceChunks contain entries that are not "
                    "currently visible in canonical public state."
                )
            else:
                store_status = DerivedLayerStatus.CURRENT
                detail = None

            archive_embeddings = _inspect_archive_embeddings(
                connection,
                archive_fts=archive_fts,
                store_status=store_status,
                hnsw_root=hnsw_root,
                visible_pairs=visible_pairs,
                chunk_rows=chunk_rows,
                current_visibility_commit_seq=(
                    current_visibility_commit_seq
                ),
            )

            return _ArchiveInspection(
                store_status=store_status,
                fts=archive_fts,
                staged_build_count=staged_build_count,
                staged_chunk_count=staged_chunk_count,
                hidden_chunk_count=hidden_chunk_count,
                embeddings=archive_embeddings,
                detail=detail,
            )

    except (
        sqlite3.Error,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        return _invalid_archive(
            "Derived search.db could not be inspected safely: "
            f"{type(exc).__name__}."
        )


def _invalid_archive(detail: str) -> _ArchiveInspection:
    return _ArchiveInspection(
        store_status=DerivedLayerStatus.INVALID,
        fts=DerivedIndexReport(
            status=DerivedLayerStatus.INVALID,
            current_snapshot=None,
            indexed_snapshot=None,
            source_document_count=None,
            indexed_document_count=None,
            detail=detail,
        ),
        staged_build_count=None,
        staged_chunk_count=None,
        hidden_chunk_count=None,
        embeddings=(),
        detail=detail,
    )


def _inspect_archive_fts(
    connection: sqlite3.Connection,
) -> DerivedIndexReport:
    try:
        state = connection.execute(
            """
            SELECT chunk_generation, fts_generation
            FROM archive_search_state
            WHERE singleton_id = 1
            """
        ).fetchone()

        if state is None:
            return DerivedIndexReport(
                status=DerivedLayerStatus.INVALID,
                current_snapshot=None,
                indexed_snapshot=None,
                source_document_count=None,
                indexed_document_count=None,
                detail="Archive search generation state is missing.",
            )

        chunk_generation = int(state["chunk_generation"])
        fts_generation = int(state["fts_generation"])

        expected_digest, expected_count = _expected_archive_fts_digest(
            connection
        )
        actual_digest, actual_count = _actual_archive_fts_digest(
            connection
        )

        if fts_generation > chunk_generation:
            status = DerivedLayerStatus.INVALID
            detail = "Archive FTS generation is ahead of SourceChunks."
        elif (
            fts_generation < chunk_generation
            or expected_digest != actual_digest
            or expected_count != actual_count
        ):
            status = DerivedLayerStatus.STALE
            detail = "Archive FTS differs from current SourceChunks."
        else:
            status = DerivedLayerStatus.CURRENT
            detail = None

        return DerivedIndexReport(
            status=status,
            current_snapshot=chunk_generation,
            indexed_snapshot=fts_generation,
            source_document_count=expected_count,
            indexed_document_count=actual_count,
            detail=detail,
        )

    except (
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as exc:
        return DerivedIndexReport(
            status=DerivedLayerStatus.INVALID,
            current_snapshot=None,
            indexed_snapshot=None,
            source_document_count=None,
            indexed_document_count=None,
            detail=(
                "Archive FTS could not be inspected safely: "
                f"{type(exc).__name__}."
            ),
        )


def _expected_archive_fts_digest(
    connection: sqlite3.Connection,
) -> tuple[bytes, int]:
    cursor = connection.execute(
        """
        SELECT
            lower(hex(chunk_id)) AS chunk_id,
            lower(hex(source_id)) AS source_id,
            lower(hex(representation_id)) AS representation_id,
            CAST(chunk_index AS TEXT) AS chunk_index,
            lower(hex(chunking_profile_id)) AS chunking_profile_id,
            CAST(start_anchor_value AS TEXT) AS start_anchor_value,
            CAST(end_anchor_value AS TEXT) AS end_anchor_value,
            lower(hex(content_hash)) AS content_hash,
            lower(hex(build_signature)) AS build_signature,
            chunk_text AS body
        FROM source_chunks
        ORDER BY chunk_id
        """
    )

    return _digest_rows(
        tuple(row)
        for row in cursor
    )


def _actual_archive_fts_digest(
    connection: sqlite3.Connection,
) -> tuple[bytes, int]:
    cursor = connection.execute(
        """
        SELECT
            chunk_id,
            source_id,
            representation_id,
            chunk_index,
            chunking_profile_id,
            start_anchor_value,
            end_anchor_value,
            content_hash,
            build_signature,
            body
        FROM fts_archive
        ORDER BY chunk_id, rowid
        """
    )

    return _digest_rows(
        tuple(row)
        for row in cursor
    )


def _inspect_canonical_embeddings(
    connection: sqlite3.Connection,
    *,
    canonical_fts: DerivedIndexReport,
    hnsw_root: Path,
) -> tuple[DerivedEmbeddingReport, ...]:
    current_snapshot = _current_commit_seq(connection)

    state_rows = connection.execute(
        """
        SELECT
            model_id,
            indexed_commit_seq,
            dimensions,
            document_count
        FROM search_embedding_state
        ORDER BY model_id
        """
    ).fetchall()

    state_by_model = {
        str(row["model_id"]): row
        for row in state_rows
    }

    model_ids = {
        str(row["model_id"])
        for row in connection.execute(
            """
            SELECT DISTINCT model_id
            FROM search_embeddings
            """
        ).fetchall()
    }
    model_ids.update(state_by_model)

    fts_bodies: dict[tuple[str, bytes, bytes], str] = {}

    if canonical_fts.status is DerivedLayerStatus.CURRENT:
        for row in connection.execute(
            """
            SELECT
                entity_type,
                entity_id,
                revision_id,
                body
            FROM search_fts
            """
        ):
            try:
                entity_id = bytes.fromhex(str(row["entity_id"]))
                revision_id = bytes.fromhex(str(row["revision_id"]))
            except ValueError:
                continue

            fts_bodies[
                (
                    str(row["entity_type"]),
                    entity_id,
                    revision_id,
                )
            ] = str(row["body"])

    reports: list[DerivedEmbeddingReport] = []

    for model_id in sorted(model_ids):
        state = state_by_model.get(model_id)

        rows = connection.execute(
            """
            SELECT
                entity_type,
                entity_id,
                revision_id,
                dimensions,
                vector_blob,
                text_sha256
            FROM search_embeddings
            WHERE model_id = ?
            ORDER BY entity_type, entity_id, revision_id
            """,
            (model_id,),
        ).fetchall()

        if state is None:
            reports.append(
                DerivedEmbeddingReport(
                    storage_model_id=model_id,
                    published=False,
                    indexed_snapshot=None,
                    current_snapshot=current_snapshot,
                    dimensions=None,
                    document_count=None,
                    persisted_document_count=len(rows),
                    unpublished_document_count=len(rows),
                    persisted_valid=_vectors_shape_valid(rows, None),
                    embeddings_current=False,
                    hnsw_files_plausible=False,
                    embedding_rebuild_required=True,
                    hnsw_rebuild_required=False,
                )
            )
            continue

        indexed_snapshot = int(state["indexed_commit_seq"])
        dimensions = int(state["dimensions"])
        document_count = int(state["document_count"])

        persisted_valid = (
            dimensions > 0
            and len(rows) == document_count
            and _vectors_shape_valid(rows, dimensions)
        )

        if (
            persisted_valid
            and canonical_fts.status is DerivedLayerStatus.CURRENT
        ):
            for row in rows:
                key = (
                    str(row["entity_type"]),
                    bytes(row["entity_id"]),
                    bytes(row["revision_id"]),
                )
                body = fts_bodies.get(key)

                if body is None:
                    persisted_valid = False
                    break

                if bytes(row["text_sha256"]) != hashlib.sha256(
                    body.encode("utf-8")
                ).digest():
                    persisted_valid = False
                    break

        expected_document_count = (
            canonical_fts.source_document_count
            if canonical_fts.status is DerivedLayerStatus.CURRENT
            else None
        )

        embeddings_current = (
            persisted_valid
            and canonical_fts.status is DerivedLayerStatus.CURRENT
            and indexed_snapshot >= current_snapshot
            and expected_document_count == document_count
        )

        hnsw_files_plausible = (
            embeddings_current
            and _hnsw_files_plausible(
                hnsw_root,
                namespace=_KNOWLEDGE_HNSW_NAMESPACE,
                storage_model_id=model_id,
                snapshot=indexed_snapshot,
                dimensions=dimensions,
                document_count=document_count,
                reference_size=_KNOWLEDGE_REFERENCE_SIZE,
            )
        )

        reports.append(
            DerivedEmbeddingReport(
                storage_model_id=model_id,
                published=True,
                indexed_snapshot=indexed_snapshot,
                current_snapshot=current_snapshot,
                dimensions=dimensions,
                document_count=document_count,
                persisted_document_count=len(rows),
                unpublished_document_count=0,
                persisted_valid=persisted_valid,
                embeddings_current=embeddings_current,
                hnsw_files_plausible=hnsw_files_plausible,
                embedding_rebuild_required=not embeddings_current,
                hnsw_rebuild_required=(
                    embeddings_current
                    and not hnsw_files_plausible
                ),
            )
        )

    return tuple(reports)


def _inspect_archive_embeddings(
    connection: sqlite3.Connection,
    *,
    archive_fts: DerivedIndexReport,
    store_status: DerivedLayerStatus,
    hnsw_root: Path,
    visible_pairs: frozenset[tuple[bytes, bytes]],
    chunk_rows: list[sqlite3.Row],
    current_visibility_commit_seq: int,
) -> tuple[DerivedEmbeddingReport, ...]:
    current_snapshot = (
        0
        if archive_fts.current_snapshot is None
        else archive_fts.current_snapshot
    )

    chunk_metadata = {
        bytes(row["chunk_id"]): (
            bytes(row["content_hash"]),
            (
                bytes(row["source_id"]),
                bytes(row["representation_id"]),
            )
            in visible_pairs,
        )
        for row in chunk_rows
    }

    visible_document_count = sum(
        1
        for _hash, visible in chunk_metadata.values()
        if visible
    )

    state_columns = {
        str(row["name"])
        for row in connection.execute(
            "PRAGMA table_info('archive_embedding_state')"
        ).fetchall()
    }
    visibility_projection = (
        "indexed_visibility_commit_seq"
        if "indexed_visibility_commit_seq" in state_columns
        else "-1 AS indexed_visibility_commit_seq"
    )

    state_rows = connection.execute(
        f"""
        SELECT
            model_id,
            indexed_chunk_generation,
            {visibility_projection},
            dimensions,
            document_count
        FROM archive_embedding_state
        ORDER BY model_id
        """
    ).fetchall()

    state_by_model = {
        str(row["model_id"]): row
        for row in state_rows
    }

    model_ids = {
        str(row["model_id"])
        for row in connection.execute(
            """
            SELECT DISTINCT model_id
            FROM archive_embeddings
            """
        ).fetchall()
    }
    model_ids.update(state_by_model)

    reports: list[DerivedEmbeddingReport] = []

    for model_id in sorted(model_ids):
        state = state_by_model.get(model_id)

        all_rows = connection.execute(
            """
            SELECT
                chunk_id,
                indexed_chunk_generation,
                dimensions,
                vector_blob,
                text_sha256
            FROM archive_embeddings
            WHERE model_id = ?
            ORDER BY indexed_chunk_generation, chunk_id
            """,
            (model_id,),
        ).fetchall()

        if state is None:
            reports.append(
                DerivedEmbeddingReport(
                    storage_model_id=model_id,
                    published=False,
                    indexed_snapshot=None,
                    current_snapshot=current_snapshot,
                    dimensions=None,
                    document_count=None,
                    persisted_document_count=len(all_rows),
                    unpublished_document_count=len(all_rows),
                    persisted_valid=_archive_vectors_shape_valid(
                        all_rows,
                        dimensions=None,
                        chunk_metadata=chunk_metadata,
                    ),
                    embeddings_current=False,
                    hnsw_files_plausible=False,
                    embedding_rebuild_required=True,
                    hnsw_rebuild_required=False,
                )
            )
            continue

        indexed_snapshot = int(
            state["indexed_chunk_generation"]
        )
        indexed_visibility_commit_seq = int(
            state["indexed_visibility_commit_seq"]
        )
        dimensions = int(state["dimensions"])
        document_count = int(state["document_count"])

        published_rows = [
            row
            for row in all_rows
            if int(row["indexed_chunk_generation"]) == indexed_snapshot
        ]

        unpublished_document_count = (
            len(all_rows) - len(published_rows)
        )

        persisted_valid = (
            dimensions > 0
            and len(published_rows) == document_count
            and _archive_vectors_shape_valid(
                published_rows,
                dimensions=dimensions,
                chunk_metadata=chunk_metadata,
            )
        )

        embeddings_current = (
            persisted_valid
            and archive_fts.status is DerivedLayerStatus.CURRENT
            and indexed_snapshot == current_snapshot
            and indexed_visibility_commit_seq
            == current_visibility_commit_seq
            and document_count == visible_document_count
        )

        hnsw_files_plausible = (
            embeddings_current
            and _hnsw_files_plausible(
                hnsw_root,
                namespace=_ARCHIVE_HNSW_NAMESPACE,
                storage_model_id=model_id,
                snapshot=indexed_snapshot,
                dimensions=dimensions,
                document_count=document_count,
                reference_size=_ARCHIVE_REFERENCE_SIZE,
            )
        )

        reports.append(
            DerivedEmbeddingReport(
                storage_model_id=model_id,
                published=True,
                indexed_snapshot=indexed_snapshot,
                current_snapshot=current_snapshot,
                dimensions=dimensions,
                document_count=document_count,
                persisted_document_count=len(published_rows),
                unpublished_document_count=(
                    unpublished_document_count
                ),
                persisted_valid=persisted_valid,
                embeddings_current=embeddings_current,
                hnsw_files_plausible=hnsw_files_plausible,
                embedding_rebuild_required=not embeddings_current,
                hnsw_rebuild_required=(
                    embeddings_current
                    and not hnsw_files_plausible
                ),
            )
        )

    return tuple(reports)


def _vectors_shape_valid(
    rows: Iterable[sqlite3.Row],
    dimensions: int | None,
) -> bool:
    dimensions_seen: set[int] = set()

    for row in rows:
        row_dimensions = int(row["dimensions"])

        if row_dimensions <= 0:
            return False

        if len(bytes(row["vector_blob"])) != row_dimensions * 4:
            return False

        dimensions_seen.add(row_dimensions)

        if (
            dimensions is not None
            and row_dimensions != dimensions
        ):
            return False

    return (
        len(dimensions_seen) <= 1
        if dimensions is None
        else True
    )


def _archive_vectors_shape_valid(
    rows: Iterable[sqlite3.Row],
    *,
    dimensions: int | None,
    chunk_metadata: dict[bytes, tuple[bytes, bool]],
) -> bool:
    dimensions_seen: set[int] = set()

    for row in rows:
        row_dimensions = int(row["dimensions"])

        if row_dimensions <= 0:
            return False

        if len(bytes(row["vector_blob"])) != row_dimensions * 4:
            return False

        dimensions_seen.add(row_dimensions)

        if (
            dimensions is not None
            and row_dimensions != dimensions
        ):
            return False

        metadata = chunk_metadata.get(
            bytes(row["chunk_id"])
        )

        if metadata is None:
            return False

        content_hash, visible = metadata

        if not visible:
            return False

        if bytes(row["text_sha256"]) != content_hash:
            return False

    return (
        len(dimensions_seen) <= 1
        if dimensions is None
        else True
    )


def _hnsw_files_plausible(
    root: Path,
    *,
    namespace: str,
    storage_model_id: str,
    snapshot: int,
    dimensions: int,
    document_count: int,
    reference_size: int,
) -> bool:
    if (
        snapshot < 0
        or dimensions <= 0
        or document_count < 0
    ):
        return False

    if document_count == 0:
        return True

    if (
        os.path.lexists(root)
        and (
            root.is_symlink()
            or not root.is_dir()
        )
    ):
        return False

    digest = hashlib.sha256(
        storage_model_id.encode("utf-8")
    ).hexdigest()[:24]

    stem = (
        f"v{_HNSW_FORMAT_VERSION}-{namespace}-{digest}"
        f"-snapshot-{snapshot}"
    )

    index_path = root / f"{stem}.usearch"
    refs_path = root / f"{stem}.refs"

    if (
        index_path.is_symlink()
        or refs_path.is_symlink()
        or not index_path.is_file()
        or not refs_path.is_file()
    ):
        return False

    try:
        return (
            index_path.stat().st_size > 0
            and refs_path.stat().st_size
            == document_count * reference_size
        )
    except OSError:
        return False


def _canonical_hnsw_entries(
    connection: sqlite3.Connection,
    *,
    storage_model_id: str,
    dimensions: int,
) -> tuple[tuple[bytes, tuple[float, ...]], ...]:
    rows = connection.execute(
        """
        SELECT
            entity_type,
            entity_id,
            revision_id,
            vector_blob,
            dimensions
        FROM search_embeddings
        WHERE model_id = ?
        ORDER BY entity_type, entity_id, revision_id
        """,
        (storage_model_id,),
    ).fetchall()

    entries: list[
        tuple[bytes, tuple[float, ...]]
    ] = []

    for row in rows:
        entity_type = str(row["entity_type"])

        try:
            type_code = _REFERENCE_TYPE_CODE[entity_type]
        except KeyError as exc:
            raise DerivedRecoveryError(
                "Persisted canonical embedding has unknown entity type."
            ) from exc

        if int(row["dimensions"]) != dimensions:
            raise DerivedRecoveryError(
                "Persisted canonical embedding dimensions changed."
            )

        vector = _unpack_vector(
            bytes(row["vector_blob"]),
            dimensions,
        )

        reference = (
            bytes((type_code,))
            + bytes(row["entity_id"])
            + bytes(row["revision_id"])
        )

        if len(reference) != _KNOWLEDGE_REFERENCE_SIZE:
            raise DerivedRecoveryError(
                "Canonical HNSW reference has invalid length."
            )

        entries.append(
            (
                reference,
                vector,
            )
        )

    return tuple(entries)


def _archive_hnsw_entries(
    connection: sqlite3.Connection,
    *,
    storage_model_id: str,
    snapshot: int,
    dimensions: int,
) -> tuple[tuple[bytes, tuple[float, ...]], ...]:
    rows = connection.execute(
        """
        SELECT
            chunk_id,
            vector_blob,
            dimensions
        FROM archive_embeddings
        WHERE model_id = ?
          AND indexed_chunk_generation = ?
        ORDER BY chunk_id
        """,
        (
            storage_model_id,
            snapshot,
        ),
    ).fetchall()

    entries: list[
        tuple[bytes, tuple[float, ...]]
    ] = []

    for row in rows:
        if int(row["dimensions"]) != dimensions:
            raise DerivedRecoveryError(
                "Persisted archive embedding dimensions changed."
            )

        chunk_id = bytes(row["chunk_id"])

        if len(chunk_id) != _ARCHIVE_REFERENCE_SIZE:
            raise DerivedRecoveryError(
                "Archive HNSW reference has invalid length."
            )

        entries.append(
            (
                chunk_id,
                _unpack_vector(
                    bytes(row["vector_blob"]),
                    dimensions,
                ),
            )
        )

    return tuple(entries)


def _unpack_vector(
    blob: bytes,
    dimensions: int,
) -> tuple[float, ...]:
    if dimensions <= 0:
        raise DerivedRecoveryError(
            "Persisted embedding dimensions must be positive."
        )

    if len(blob) != dimensions * 4:
        raise DerivedRecoveryError(
            "Persisted embedding byte length is invalid."
        )

    return tuple(
        float(value)
        for value in struct.unpack(
            f"<{dimensions}f",
            blob,
        )
    )


def _require_safe_hnsw_destination(
    derived_root: Path,
    hnsw_root: Path,
) -> None:
    if os.path.lexists(derived_root):
        if (
            derived_root.is_symlink()
            or not derived_root.is_dir()
        ):
            raise DerivedRecoveryRequiredError(
                "Derived root is not a safe directory."
            )

    if os.path.lexists(hnsw_root):
        if (
            hnsw_root.is_symlink()
            or not hnsw_root.is_dir()
        ):
            raise DerivedRecoveryRequiredError(
                "HNSW root is not a safe directory."
            )


def _digest_rows(
    rows: Iterable[tuple[object, ...]],
) -> tuple[bytes, int]:
    hasher = hashlib.sha256()
    count = 0

    for row in rows:
        count += 1
        hasher.update(
            len(row).to_bytes(
                4,
                byteorder="big",
                signed=False,
            )
        )

        for value in row:
            if value is None:
                hasher.update(b"N")
                continue

            encoded = str(value).encode("utf-8")
            hasher.update(b"S")
            hasher.update(
                len(encoded).to_bytes(
                    8,
                    byteorder="big",
                    signed=False,
                )
            )
            hasher.update(encoded)

    return hasher.digest(), count
