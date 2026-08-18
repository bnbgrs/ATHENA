from __future__ import annotations

import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.core.derived_recovery import (
    DerivedLayerStatus,
    DerivedRecoveryRequiredError,
    DerivedRecoveryService,
)
from athena.knowledge.models import KnowledgeKind
from athena.retrieval.archive import ArchiveSemanticSearchService
from athena.retrieval.semantic import LocalSemanticSearchService
from athena.storage.database import SQLiteDatabase


@dataclass
class _FakeEmbeddingProvider:
    calls: int = 0

    def embed(
        self,
        *,
        model_id: str,
        texts,
    ):
        del model_id
        self.calls += 1

        return tuple(
            (
                1.0 if "berlin" in text.casefold() else 0.0,
                1.0 if "hauptstadt" in text.casefold() else 0.0,
                0.25,
            )
            for text in texts
        )


def _app(root: Path) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=root,
        )
    )
    app.start()
    return app


def _prepare_public_data(
    app: AthenaApplication,
    tmp_path: Path,
) -> None:
    chat_id = app.chat.create_chat()
    message = app.chat.add_user_message(
        chat_id=chat_id,
        content="Berlin ist die Hauptstadt Deutschlands.",
    )
    app.knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=message.sequence_no,
        knowledge_kind=KnowledgeKind.FACT,
    )

    source_path = tmp_path / "derived-recovery-source.txt"
    source_path.write_text(
        "Berlin ist die Hauptstadt Deutschlands.\n",
        encoding="utf-8",
    )

    captured = app.sources.capture_file(
        source_path
    )
    represented = app.source_text.build(
        captured.source.source_id
    )
    app.source_chunks.build_default(
        represented.result.representation.representation_id
    )
    app.search.rebuild()


def _authoritative_snapshot(
    app: AthenaApplication,
) -> tuple[tuple[tuple[object, ...], ...], ...]:
    queries = (
        """
        SELECT
            hex(entity_id),
            entity_type,
            lifecycle_state
        FROM entity_registry
        ORDER BY entity_id
        """,
        """
        SELECT
            hex(entity_id),
            hex(current_revision_id)
        FROM entity_heads
        ORDER BY entity_id
        """,
        """
        SELECT
            hex(knowledge_id)
        FROM knowledge_units
        ORDER BY knowledge_id
        """,
        """
        SELECT
            hex(revision_id),
            body,
            title,
            hex(protected_payload_id)
        FROM knowledge_unit_revisions
        ORDER BY revision_id
        """,
        """
        SELECT
            hex(source_id),
            hex(blob_id),
            lifecycle_state
        FROM sources
        ORDER BY source_id
        """,
        """
        SELECT
            hex(representation_id),
            hex(source_id),
            retention_state,
            hex(content_hash)
        FROM source_representations
        ORDER BY representation_id
        """,
        """
        SELECT
            hex(blob_id),
            byte_length,
            hex(integrity_sha256),
            encryption_state
        FROM blob_records
        ORDER BY blob_id
        """,
    )

    result: list[
        tuple[tuple[object, ...], ...]
    ] = []

    for query in queries:
        rows = app.database.connection.execute(
            query
        ).fetchall()

        result.append(
            tuple(
                tuple(row)
                for row in rows
            )
        )

    return tuple(result)


def test_read_only_inspection_does_not_create_missing_search_db(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)
    database_path = state_root / "athena.db"

    database = SQLiteDatabase(database_path)
    database.start()
    database.stop()

    derived_root = tmp_path / "derived"

    service = DerivedRecoveryService(
        database_path=database_path,
        derived_root=derived_root,
    )

    report = service.inspect()

    assert report.canonical_integrity_confirmed is True
    assert report.normal_writes_allowed is False
    assert report.protected_scopes_locked is True
    assert (
        report.canonical_fts.status
        is DerivedLayerStatus.CURRENT
    )
    assert (
        report.archive_store_status
        is DerivedLayerStatus.MISSING
    )
    assert (
        report.archive_fts.status
        is DerivedLayerStatus.MISSING
    )
    assert not derived_root.exists()

    with pytest.raises(
        DerivedRecoveryRequiredError
    ):
        service.rebuild_archive_fts()

    assert not derived_root.exists()


def test_invalid_search_db_is_diagnosed_without_replacement(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)
    database_path = state_root / "athena.db"

    database = SQLiteDatabase(database_path)
    database.start()
    database.stop()

    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    search_db = derived_root / "search.db"
    original = b"ATHENA-invalid-derived-database"
    search_db.write_bytes(original)

    service = DerivedRecoveryService(
        database_path=database_path,
        derived_root=derived_root,
    )

    report = service.inspect()

    assert (
        report.archive_store_status
        is DerivedLayerStatus.INVALID
    )
    assert search_db.read_bytes() == original

    with pytest.raises(
        DerivedRecoveryRequiredError
    ):
        service.rebuild_archive_fts()

    assert search_db.read_bytes() == original


def test_stale_fts_layers_rebuild_without_authoritative_mutation(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        _prepare_public_data(
            app,
            tmp_path,
        )

        service = DerivedRecoveryService(
            database_path=app.paths.database_path,
            derived_root=app.paths.derived_root,
        )

        initial = service.inspect()

        assert (
            initial.canonical_fts.status
            is DerivedLayerStatus.CURRENT
        )
        assert (
            initial.archive_store_status
            is DerivedLayerStatus.CURRENT
        )
        assert (
            initial.archive_fts.status
            is DerivedLayerStatus.CURRENT
        )

        authoritative_before = _authoritative_snapshot(
            app
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                "DELETE FROM search_fts"
            )
            connection.execute(
                """
                UPDATE search_index_state
                SET indexed_commit_seq = 0
                WHERE singleton_id = 1
                """
            )

        with app.source_chunk_store.connect() as connection:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            try:
                connection.execute(
                    "DELETE FROM fts_archive"
                )
                connection.execute(
                    """
                    UPDATE archive_search_state
                    SET fts_generation = 0
                    WHERE singleton_id = 1
                    """
                )
                connection.execute(
                    "COMMIT"
                )
            except BaseException:
                if connection.in_transaction:
                    connection.execute(
                        "ROLLBACK"
                    )
                raise

        stale = service.inspect()

        assert (
            stale.canonical_fts.status
            is DerivedLayerStatus.STALE
        )
        assert (
            stale.archive_fts.status
            is DerivedLayerStatus.STALE
        )

        assert service.rebuild_canonical_fts() > 0
        assert service.rebuild_archive_fts() > 0

        repaired = service.inspect()

        assert (
            repaired.canonical_fts.status
            is DerivedLayerStatus.CURRENT
        )
        assert (
            repaired.archive_store_status
            is DerivedLayerStatus.CURRENT
        )
        assert (
            repaired.archive_fts.status
            is DerivedLayerStatus.CURRENT
        )

        authoritative_after = _authoritative_snapshot(
            app
        )

        assert authoritative_after == authoritative_before

        assert app.search.search(
            "Hauptstadt"
        )
        assert app.archive_search.search(
            "Hauptstadt"
        )

    finally:
        app.stop()


def test_hnsw_rebuild_uses_persisted_vectors_without_provider_call(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        _prepare_public_data(
            app,
            tmp_path,
        )

        provider = _FakeEmbeddingProvider()

        semantic = LocalSemanticSearchService(
            app.database,
            provider,
            hnsw_root=(
                app.paths.derived_root
                / "hnsw"
            ),
        )

        archive_semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )

        canonical_status = semantic.rebuild(
            "recovery-fake-embed"
        )
        archive_status = archive_semantic.rebuild(
            "recovery-fake-embed"
        )

        assert canonical_status.current
        assert archive_status.current

        hnsw_root = (
            app.paths.derived_root
            / "hnsw"
        )

        hnsw_files = tuple(
            path
            for path in hnsw_root.iterdir()
            if path.is_file()
        )

        assert hnsw_files

        for path in hnsw_files:
            path.unlink()

        service = DerivedRecoveryService(
            database_path=app.paths.database_path,
            derived_root=app.paths.derived_root,
        )

        before = service.inspect()

        assert len(
            before.canonical_embeddings
        ) == 1
        assert len(
            before.archive_embeddings
        ) == 1

        canonical_embedding = (
            before.canonical_embeddings[0]
        )
        archive_embedding = (
            before.archive_embeddings[0]
        )

        assert canonical_embedding.embeddings_current
        assert archive_embedding.embeddings_current
        assert canonical_embedding.hnsw_rebuild_required
        assert archive_embedding.hnsw_rebuild_required

        provider_calls_before = provider.calls
        authoritative_before = _authoritative_snapshot(
            app
        )

        assert (
            service.rebuild_canonical_hnsw_from_persisted()
            == 1
        )
        assert (
            service.rebuild_archive_hnsw_from_persisted()
            == 1
        )

        assert provider.calls == provider_calls_before
        assert (
            _authoritative_snapshot(app)
            == authoritative_before
        )

        repaired = service.inspect()

        assert (
            repaired.canonical_embeddings[0]
            .hnsw_files_plausible
        )
        assert (
            repaired.archive_embeddings[0]
            .hnsw_files_plausible
        )

        canonical_after = semantic.status(
            "recovery-fake-embed"
        )
        archive_after = archive_semantic.status(
            "recovery-fake-embed"
        )

        assert canonical_after is not None
        assert archive_after is not None
        assert canonical_after.current
        assert archive_after.current

    finally:
        app.stop()


def test_stale_embeddings_are_not_regenerated_by_recovery(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        _prepare_public_data(
            app,
            tmp_path,
        )

        provider = _FakeEmbeddingProvider()

        semantic = LocalSemanticSearchService(
            app.database,
            provider,
            hnsw_root=(
                app.paths.derived_root
                / "hnsw"
            ),
        )

        archive_semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )

        semantic.rebuild(
            "stale-recovery-embed"
        )
        archive_semantic.rebuild(
            "stale-recovery-embed"
        )

        provider_calls_before_change = provider.calls

        chat_id = app.chat.create_chat()
        message = app.chat.add_user_message(
            chat_id=chat_id,
            content="Neue kanonische Information nach Embedding-Snapshot.",
        )
        app.knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=message.sequence_no,
            knowledge_kind=KnowledgeKind.IDEA,
        )

        second_path = tmp_path / "second-source.txt"
        second_path.write_text(
            "Neue ?ffentliche SourceChunk-Generation.\n",
            encoding="utf-8",
        )
        captured = app.sources.capture_file(
            second_path
        )
        represented = app.source_text.build(
            captured.source.source_id
        )
        app.source_chunks.build_default(
            represented.result.representation.representation_id
        )

        service = DerivedRecoveryService(
            database_path=app.paths.database_path,
            derived_root=app.paths.derived_root,
        )

        service.rebuild_canonical_fts()

        report = service.inspect()

        assert (
            report.canonical_fts.status
            is DerivedLayerStatus.CURRENT
        )
        assert (
            report.archive_fts.status
            is DerivedLayerStatus.CURRENT
        )

        assert (
            report.canonical_embeddings[0]
            .embedding_rebuild_required
        )
        assert (
            report.archive_embeddings[0]
            .embedding_rebuild_required
        )

        assert (
            service.rebuild_canonical_hnsw_from_persisted()
            == 0
        )
        assert (
            service.rebuild_archive_hnsw_from_persisted()
            == 0
        )

        assert provider.calls == provider_calls_before_change

    finally:
        app.stop()


def test_derived_recovery_import_does_not_load_model_runtime(
    tmp_path: Path,
) -> None:
    del tmp_path

    code = r"""
import sys
import athena.core.derived_recovery

forbidden = (
    "athena.core.application",
    "athena.model.adapters.lm_studio",
    "athena.model.adapters.lm_studio_embeddings",
    "athena.news.service",
    "athena.security.service",
)

loaded = [
    name
    for name in forbidden
    if name in sys.modules
]

if loaded:
    raise SystemExit(
        "forbidden runtime imports: "
        + ", ".join(loaded)
    )
"""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )

def test_legacy_global_fts_watermark_remains_valid_when_projection_matches(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        _prepare_public_data(
            app,
            tmp_path,
        )

        service = DerivedRecoveryService(
            database_path=app.paths.database_path,
            derived_root=app.paths.derived_root,
        )

        initial = service.inspect()

        assert (
            initial.canonical_fts.status
            is DerivedLayerStatus.CURRENT
        )

        projection_snapshot = (
            initial.canonical_fts.current_snapshot
        )

        assert projection_snapshot is not None

        global_row = app.database.connection.execute(
            """
            SELECT COALESCE(MAX(commit_seq), 0) AS commit_seq
            FROM commit_records
            """
        ).fetchone()

        assert global_row is not None

        global_snapshot = int(
            global_row["commit_seq"]
        )

        # _prepare_public_data performs Source-side canonical commits after the
        # searchable Knowledge change. This reproduces the old global-watermark
        # format without changing deterministic FTS content.
        assert global_snapshot >= projection_snapshot

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE search_index_state
                SET indexed_commit_seq = ?
                WHERE singleton_id = 1
                """,
                (
                    global_snapshot,
                ),
            )

        report = service.inspect()

        assert (
            report.canonical_fts.status
            is DerivedLayerStatus.CURRENT
        )
        assert (
            report.canonical_fts.current_snapshot
            == projection_snapshot
        )
        assert (
            report.canonical_fts.indexed_snapshot
            == global_snapshot
        )

    finally:
        app.stop()


def test_recovery_accepts_visibility_projected_archive_embeddings(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path / "runtime"
    )

    try:
        _prepare_public_data(
            app,
            tmp_path,
        )

        second_path = tmp_path / "visibility-second-source.txt"
        second_path.write_text(
            "Berlin second visible archive source.\n",
            encoding="utf-8",
        )
        second = app.sources.capture_file(second_path)
        represented = app.source_text.build(
            second.source.source_id
        )
        app.source_chunks.build_default(
            represented.result.representation.representation_id
        )

        provider = _FakeEmbeddingProvider()
        archive_semantic = ArchiveSemanticSearchService(
            lexical=app.archive_search,
            provider=provider,
        )
        published = archive_semantic.rebuild(
            "visibility-recovery-embed"
        )
        assert published.current
        assert published.document_count >= 2

        source_rows = app.database.connection.execute(
            """
            SELECT source_id
            FROM sources
            WHERE source_id != ?
            ORDER BY created_at_us, source_id
            LIMIT 1
            """,
            (second.source.source_id.bytes,),
        ).fetchall()
        assert len(source_rows) == 1
        deleted_source_id = uuid.UUID(
            bytes=bytes(source_rows[0]["source_id"])
        )

        preview = app.lifecycle_deletion.preview(
            deleted_source_id
        )
        app.lifecycle_deletion.delete(
            deleted_source_id,
            preview_digest=preview.preview_digest,
        )

        repaired = archive_semantic.ensure_current(
            "visibility-recovery-embed"
        )
        assert repaired.current

        service = DerivedRecoveryService(
            database_path=app.paths.database_path,
            derived_root=app.paths.derived_root,
        )
        report = service.inspect()

        # SourceChunks remain reconstructible but hidden after logical
        # deletion, so the store-level report stays stale. The semantic
        # projection itself is nevertheless current because its persisted
        # visibility watermark and vector set exactly match public evidence.
        assert (
            report.archive_store_status
            is DerivedLayerStatus.STALE
        )
        assert len(report.archive_embeddings) == 1
        archive_embedding = report.archive_embeddings[0]
        assert archive_embedding.embeddings_current
        assert archive_embedding.hnsw_files_plausible
        assert not archive_embedding.embedding_rebuild_required

    finally:
        app.stop()
