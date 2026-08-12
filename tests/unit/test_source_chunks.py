from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.chunking_service import SourceChunkIntegrityError


def _started_app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def _build_representation(app: AthenaApplication, tmp_path: Path, text: str):
    original = tmp_path / "chunk-source.md"
    original.write_text(text, encoding="utf-8", newline="")
    captured = app.sources.capture_file(original)
    represented = app.source_text.build(captured.source.source_id)
    return captured, represented.result.representation


def test_default_chunk_build_is_exact_contiguous_derived_state(tmp_path) -> None:
    text = (
        "# Heading\n\n"
        + ("Paragraph alpha words. " * 45)
        + "\n\n"
        + ("Paragraph beta words. " * 45)
        + "\n"
    )
    app = _started_app(tmp_path)
    captured, representation = _build_representation(app, tmp_path, text)

    built = app.source_chunks.build_default(representation.representation_id)

    assert built.processing_run.status == "succeeded"
    assert built.processing_run.model_signature_id is None
    assert built.profile.algorithm == "paragraph_char_v1"
    assert built.profile.target_size == 1200
    assert built.profile.overlap_size == 0
    assert len(built.chunks) >= 2
    assert "source_chunks" not in {
        str(row[0])
        for row in app.database.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert app.paths.derived_root.joinpath("search.db").exists()

    reconstructed = "".join(chunk.chunk_text for chunk in built.chunks)
    assert reconstructed == text
    assert built.chunks[0].start_anchor_value == 0
    assert built.chunks[-1].end_anchor_value == len(text)
    for index, chunk in enumerate(built.chunks):
        assert chunk.chunk_index == index
        assert chunk.source_id == captured.source.source_id
        assert chunk.representation_id == representation.representation_id
        assert chunk.content_hash == hashlib.sha256(chunk.chunk_text.encode("utf-8")).digest()
        assert chunk.uri == f"derived://chunk/{chunk.chunk_id}"
        if index:
            assert built.chunks[index - 1].end_anchor_value == chunk.start_anchor_value
    app.stop()


def test_rebuild_replaces_derived_chunk_ids_but_preserves_boundaries_and_signature(tmp_path) -> None:
    text = ("First paragraph. " * 80) + "\n\n" + ("Second paragraph. " * 80)
    app = _started_app(tmp_path)
    _, representation = _build_representation(app, tmp_path, text)

    first = app.source_chunks.build_default(representation.representation_id)
    second = app.source_chunks.build_default(representation.representation_id)

    assert first.profile.chunking_profile_id == second.profile.chunking_profile_id
    assert first.build_signature == second.build_signature
    assert first.processing_run.processing_run_id != second.processing_run.processing_run_id
    assert [chunk.chunk_id for chunk in first.chunks] != [chunk.chunk_id for chunk in second.chunks]
    assert [
        (chunk.start_anchor_value, chunk.end_anchor_value, chunk.content_hash)
        for chunk in first.chunks
    ] == [
        (chunk.start_anchor_value, chunk.end_anchor_value, chunk.content_hash)
        for chunk in second.chunks
    ]
    stored = app.source_chunks.list_for_representation(representation.representation_id)
    assert [chunk.chunk_id for chunk in stored] == [chunk.chunk_id for chunk in second.chunks]
    app.stop()


def test_long_paragraph_uses_line_space_then_hard_boundaries_without_gaps(tmp_path) -> None:
    text = ("word " * 700) + "TAIL"
    app = _started_app(tmp_path)
    _, representation = _build_representation(app, tmp_path, text)

    built = app.source_chunks.build_default(representation.representation_id)

    assert len(built.chunks) >= 3
    assert all(len(chunk.chunk_text) <= 1200 for chunk in built.chunks)
    assert "".join(chunk.chunk_text for chunk in built.chunks) == text
    app.stop()


def test_chunk_verify_detects_derived_text_tampering(tmp_path) -> None:
    text = "Alpha paragraph.\n\nBeta paragraph.\n"
    app = _started_app(tmp_path)
    _, representation = _build_representation(app, tmp_path, text)
    built = app.source_chunks.build_default(representation.representation_id)
    chunk = built.chunks[0]

    derived = sqlite3.connect(app.paths.derived_root / "search.db", autocommit=True)
    derived.execute(
        "UPDATE source_chunks SET chunk_text = 'tampered' WHERE chunk_id = ?",
        (chunk.chunk_id.bytes,),
    )
    derived.close()

    with pytest.raises(SourceChunkIntegrityError, match="text disagrees"):
        app.source_chunks.verify(chunk.chunk_id)
    app.stop()


def test_chunk_build_survives_restart_and_raw_archive_entities_are_unchanged(tmp_path) -> None:
    text = "Restartable text\n\n" + ("more text " * 180)
    first_app = _started_app(tmp_path)
    captured, representation = _build_representation(first_app, tmp_path, text)
    before = first_app.database.connection.execute(
        "SELECT count(*) FROM entity_registry WHERE domain = 'raw_archive'"
    ).fetchone()[0]
    built = first_app.source_chunks.build_default(representation.representation_id)
    after = first_app.database.connection.execute(
        "SELECT count(*) FROM entity_registry WHERE domain = 'raw_archive'"
    ).fetchone()[0]
    assert after == before
    chunk_id = built.chunks[0].chunk_id
    first_app.stop()

    second_app = _started_app(tmp_path)
    chunk = second_app.source_chunks.verify(chunk_id)
    assert chunk.source_id == captured.source.source_id
    assert chunk.representation_id == representation.representation_id
    assert second_app.source_chunks.list_for_representation(representation.representation_id)
    second_app.stop()


def test_default_profile_is_durable_reproducibility_metadata(tmp_path) -> None:
    app = _started_app(tmp_path)
    first = app.chunking_profiles.get_or_create_default()
    second = app.chunking_profiles.get_or_create_default()

    assert first == second
    row = app.database.connection.execute(
        "SELECT count(*) FROM chunking_profiles"
    ).fetchone()
    assert row is not None and int(row[0]) == 1
    assert first.configuration_hash == second.configuration_hash
    app.stop()
