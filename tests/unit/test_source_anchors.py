from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from athena.common.ids import uuid_to_blob
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.anchor_service import SourceAnchorIntegrityError
from athena.source.models import SourceAnchorType


def _started_app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def _build(app: AthenaApplication, tmp_path: Path, text: str):
    original = tmp_path / "anchor-source.md"
    original.write_text(text, encoding="utf-8", newline="")
    source = app.sources.capture_file(original).source
    representation = app.source_text.build(source.source_id).result.representation
    chunks = app.source_chunks.build_default(representation.representation_id)
    return source, representation, chunks


def test_materialize_chunk_creates_persistent_raw_archive_anchor(tmp_path) -> None:
    text = "Berlin evidence paragraph.\n\nSecond paragraph.\n"
    app = _started_app(tmp_path)
    source, representation, built = _build(app, tmp_path, text)
    chunk = built.chunks[0]

    anchor = app.source_anchors.materialize_chunk(chunk.chunk_id)

    assert anchor.source_id == source.source_id
    assert anchor.representation_id == representation.representation_id
    assert anchor.anchor_type is SourceAnchorType.TEXT_RANGE
    assert anchor.start_offset == chunk.start_anchor_value
    assert anchor.end_offset == chunk.end_anchor_value
    assert anchor.quoted_hash == chunk.content_hash
    row = app.database.connection.execute(
        "SELECT domain, entity_type FROM entity_registry WHERE entity_id = ?",
        (uuid_to_blob(anchor.anchor_id),),
    ).fetchone()
    assert row is not None
    assert tuple(row) == ("raw_archive", "source_anchor")
    derived = sqlite3.connect(app.paths.derived_root / "search.db")
    hint = derived.execute(
        "SELECT anchor_id FROM source_chunks WHERE chunk_id = ?", (chunk.chunk_id.bytes,)
    ).fetchone()
    derived.close()
    assert hint is not None and bytes(hint[0]) == anchor.anchor_id.bytes
    app.stop()


def test_same_range_is_idempotent_and_rechunking_preserves_anchor(tmp_path) -> None:
    text = ("Stable anchor sentence. " * 60) + "\n\n" + ("Tail. " * 30)
    app = _started_app(tmp_path)
    _, representation, first_build = _build(app, tmp_path, text)
    first_chunk = first_build.chunks[0]
    first_anchor = app.source_anchors.materialize_chunk(first_chunk.chunk_id)
    duplicate = app.source_anchors.materialize_chunk(first_chunk.chunk_id)
    assert duplicate.anchor_id == first_anchor.anchor_id

    second_build = app.source_chunks.build_default(representation.representation_id)
    second_chunk = next(
        chunk
        for chunk in second_build.chunks
        if (chunk.start_anchor_value, chunk.end_anchor_value, chunk.content_hash)
        == (first_chunk.start_anchor_value, first_chunk.end_anchor_value, first_chunk.content_hash)
    )
    assert second_chunk.chunk_id != first_chunk.chunk_id
    assert app.source_anchors.verify(first_anchor.anchor_id) == first_anchor
    rebuilt_anchor = app.source_anchors.materialize_chunk(second_chunk.chunk_id)
    assert rebuilt_anchor.anchor_id == first_anchor.anchor_id
    app.stop()


def test_anchor_read_returns_exact_representation_slice(tmp_path) -> None:
    text = "prefix αβγ middle Berlin suffix"
    app = _started_app(tmp_path)
    source_path = tmp_path / "manual.txt"
    source_path.write_text(text, encoding="utf-8", newline="")
    source = app.sources.capture_file(source_path).source
    representation = app.source_text.build(source.source_id).result.representation
    start = text.index("αβγ")
    end = text.index(" suffix")

    anchor = app.source_anchors.materialize_text_range(
        representation.representation_id, start_offset=start, end_offset=end
    )

    expected = text[start:end]
    assert app.source_anchors.read_text(anchor.anchor_id) == expected
    assert anchor.quoted_hash == hashlib.sha256(expected.encode("utf-8")).digest()
    app.stop()


def test_anchor_verify_fails_closed_on_quoted_hash_tampering(tmp_path) -> None:
    app = _started_app(tmp_path)
    _, _, built = _build(app, tmp_path, "Tamper-resistant anchor text.\n")
    anchor = app.source_anchors.materialize_chunk(built.chunks[0].chunk_id)
    app.database.connection.execute(
        "UPDATE source_anchors SET quoted_hash = ? WHERE anchor_id = ?",
        (b"x" * 32, uuid_to_blob(anchor.anchor_id)),
    )

    with pytest.raises(SourceAnchorIntegrityError, match="quoted hash disagrees"):
        app.source_anchors.verify(anchor.anchor_id)
    app.stop()


def test_anchor_range_outside_representation_is_rejected(tmp_path) -> None:
    app = _started_app(tmp_path)
    source_path = tmp_path / "short.txt"
    source_path.write_text("short", encoding="utf-8")
    source = app.sources.capture_file(source_path).source
    representation = app.source_text.build(source.source_id).result.representation

    with pytest.raises(ValueError, match="outside"):
        app.source_anchors.materialize_text_range(
            representation.representation_id, start_offset=0, end_offset=99
        )
    app.stop()
