from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.retrieval.archive import ArchiveSemanticSearchService


@dataclass
class _UnusedEmbeddingProvider:
    def embed(self, *, model_id: str, texts):
        del model_id
        return tuple(
            (1.0, 0.0, 0.0)
            for _ in texts
        )


def _started_app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=tmp_path / "runtime"
        )
    )
    app.start()
    return app


def _build_fixture_chunks(
    app: AthenaApplication,
    tmp_path: Path,
    *,
    count: int,
) -> int:
    total = 0

    for index in range(count):
        source_path = tmp_path / f"planner-{index:03d}.txt"
        source_path.write_text(
            (
                f"ATHENA_A06_PLANNER_{index:03d} "
                + ("bounded embedding planner payload " * 16)
            ),
            encoding="utf-8",
            newline="",
        )
        captured = app.sources.capture_file(
            source_path
        )
        represented = app.source_text.build(
            captured.source.source_id
        )
        built = app.source_chunks.build_default(
            represented.result.representation.representation_id
        )
        total += len(built.chunks)

    assert total >= count
    return total


def _semantic(
    app: AthenaApplication,
) -> ArchiveSemanticSearchService:
    return ArchiveSemanticSearchService(
        lexical=app.archive_search,
        provider=_UnusedEmbeddingProvider(),
        batch_size=64,
    )


def test_rebuild_planner_uses_visibility_snapshot_not_per_chunk_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _started_app(tmp_path)

    try:
        chunk_count = _build_fixture_chunks(
            app,
            tmp_path,
            count=12,
        )
        semantic = _semantic(app)
        generation = semantic.chunk_store.current_generation()

        def forbidden_visibility_lookup(*_args, **_kwargs):
            raise AssertionError(
                "Embedding planner performed a per-chunk "
                "authoritative visibility lookup."
            )

        monkeypatch.setattr(
            app.archive_search,
            "is_visible_representation",
            forbidden_visibility_lookup,
        )

        plan = semantic.prepare_rebuild_batch(
            "a06-fake-embed",
            target_chunk_generation=generation,
            limit=64,
        )

        assert len(plan.items) == chunk_count
        assert plan.total_document_count == chunk_count
        assert plan.reached_end is True
    finally:
        app.stop()


def test_rebuild_planner_bulk_loads_existing_embeddings_per_scan_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _started_app(tmp_path)

    try:
        chunk_count = _build_fixture_chunks(
            app,
            tmp_path,
            count=12,
        )
        semantic = _semantic(app)
        generation = semantic.chunk_store.current_generation()
        statements: list[str] = []

        original_connect = semantic.chunk_store.connect

        @contextmanager
        def traced_connect() -> Iterator:
            with original_connect() as connection:
                connection.set_trace_callback(
                    statements.append
                )
                try:
                    yield connection
                finally:
                    connection.set_trace_callback(None)

        monkeypatch.setattr(
            semantic.chunk_store,
            "connect",
            traced_connect,
        )

        plan = semantic.prepare_rebuild_batch(
            "a06-fake-embed",
            target_chunk_generation=generation,
            limit=64,
        )

        normalized = tuple(
            " ".join(statement.casefold().split())
            for statement in statements
        )

        direct_lookups = tuple(
            statement
            for statement in normalized
            if (
                "from archive_embeddings" in statement
                and "where chunk_id =" in statement
                and "indexed_chunk_generation =" in statement
            )
        )
        bulk_lookups = tuple(
            statement
            for statement in normalized
            if (
                "from archive_embeddings" in statement
                and "chunk_id in (" in statement
                and "indexed_chunk_generation =" in statement
            )
        )

        assert len(plan.items) == chunk_count
        assert direct_lookups == ()
        assert len(bulk_lookups) == 1
    finally:
        app.stop()
