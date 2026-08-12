from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.blob_store import BlobIntegrityError
from athena.source.models import RepresentationRetentionState, SourceLifecycleState
from athena.source.representation_store import TextDecodingError, UnsupportedTextSourceError


def _started_app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def test_txt_representation_uses_archived_bytes_and_is_deterministic(tmp_path) -> None:
    original = tmp_path / "notes.txt"
    original_bytes = b"\xef\xbb\xbfAlpha\r\nBeta\rGamma\n"
    original.write_bytes(original_bytes)

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)
    source_blob_path = app.sources.verify(captured.source.source_id)
    source_blob_before = source_blob_path.read_bytes()
    original.unlink()

    built = app.source_text.build(captured.source.source_id)
    representation = built.result.representation
    expected = "Alpha\nBeta\nGamma\n"
    expected_bytes = expected.encode("utf-8")

    assert built.processing_run.status == "succeeded"
    assert built.processing_run.model_signature_id is None
    assert built.processing_run.pipeline_version == "native-text-v1"
    assert representation.retention_state is RepresentationRetentionState.RETAINED
    assert representation.content_hash == hashlib.sha256(expected_bytes).digest()
    assert representation.parser_id == "athena.native_text"
    assert representation.parser_version == "1"
    assert json.loads(representation.options_json) == {
        "encoding": "utf-8-strict",
        "line_endings": "lf",
        "unicode_normalization": "none",
        "utf8_bom": "strip",
    }
    assert app.source_text.read_text(representation.representation_id) == expected
    assert source_blob_path.read_bytes() == source_blob_before == original_bytes
    assert not original.exists()

    source_after, _ = app.sources.get(captured.source.source_id)
    assert source_after.lifecycle_state is SourceLifecycleState.READY
    app.stop()


def test_repeated_same_pipeline_keeps_immutable_runs_and_reuses_representation_blob(tmp_path) -> None:
    original = tmp_path / "repeat.md"
    original.write_bytes(b"# Heading\r\n\r\nBody\r\n")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)
    first = app.source_text.build(captured.source.source_id)
    second = app.source_text.build(captured.source.source_id)

    assert first.result.representation.representation_id != second.result.representation.representation_id
    assert first.processing_run.processing_run_id != second.processing_run.processing_run_id
    assert first.result.representation.content_hash == second.result.representation.content_hash
    assert first.result.blob.blob_id == second.result.blob.blob_id
    assert not first.result.reused_blob
    assert second.result.reused_blob
    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM source_representations WHERE source_id = ?",
        (captured.source.source_id.bytes,),
    ).fetchone()[0] == 2
    app.stop()


def test_newline_normalization_is_stable_across_stream_chunk_boundary(tmp_path) -> None:
    original = tmp_path / "boundary.txt"
    original.write_bytes((b"a" * (1024 * 1024 - 1)) + b"\r\nZ")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)
    built = app.source_text.build(captured.source.source_id)
    text = app.source_text.read_text(built.result.representation.representation_id)

    assert text == ("a" * (1024 * 1024 - 1)) + "\nZ"
    app.stop()


def test_representation_has_raw_archive_entity_and_processing_run_provenance(tmp_path) -> None:
    original = tmp_path / "provenance.txt"
    original.write_text("trace representation", encoding="utf-8")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)
    built = app.source_text.build(captured.source.source_id)
    representation = built.result.representation

    entity = app.database.connection.execute(
        "SELECT entity_type, domain FROM entity_registry WHERE entity_id = ?",
        (representation.representation_id.bytes,),
    ).fetchone()
    assert entity is not None
    assert (entity["entity_type"], entity["domain"]) == (
        "source_representation",
        "raw_archive",
    )
    provenance = app.database.connection.execute(
        """
        SELECT operation, processing_run_id
        FROM provenance_records
        WHERE provenance_id = ?
        """,
        (representation.provenance_id.bytes,),
    ).fetchone()
    assert provenance is not None
    assert provenance["operation"] == "source.representation.text.create"
    assert bytes(provenance["processing_run_id"]) == built.processing_run.processing_run_id.bytes
    inputs = app.database.connection.execute(
        """
        SELECT input_entity_id, input_role, ordinal
        FROM provenance_inputs
        WHERE provenance_id = ?
        ORDER BY ordinal
        """,
        (representation.provenance_id.bytes,),
    ).fetchall()
    assert [(str(row["input_role"]), int(row["ordinal"])) for row in inputs] == [
        ("source", 0),
        ("source_blob", 1),
    ]
    assert bytes(inputs[0]["input_entity_id"]) == captured.source.source_id.bytes
    assert bytes(inputs[1]["input_entity_id"]) == captured.blob.blob_id.bytes
    app.stop()


def test_invalid_utf8_fails_run_without_representation_commit(tmp_path) -> None:
    original = tmp_path / "invalid.txt"
    original.write_bytes(b"valid-prefix\xffinvalid")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)

    with pytest.raises(TextDecodingError, match="strict UTF-8"):
        app.source_text.build(captured.source.source_id)

    assert app.database.connection.execute("SELECT COUNT(*) FROM source_representations").fetchone()[0] == 0
    run = app.database.connection.execute(
        "SELECT status, error_detail FROM processing_runs ORDER BY started_at_us DESC LIMIT 1"
    ).fetchone()
    assert run is not None
    assert run["status"] == "failed"
    assert "TextDecodingError" in str(run["error_detail"])
    source, _ = app.sources.get(captured.source.source_id)
    assert source.lifecycle_state is SourceLifecycleState.CAPTURED
    app.stop()


def test_unsupported_source_type_fails_before_processing_run(tmp_path) -> None:
    original = tmp_path / "document.pdf"
    original.write_bytes(b"%PDF-1.7\nnot-yet-supported")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)

    with pytest.raises(UnsupportedTextSourceError, match="TXT/Markdown"):
        app.source_text.build(captured.source.source_id)

    assert app.database.connection.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
    assert app.database.connection.execute("SELECT COUNT(*) FROM source_representations").fetchone()[0] == 0
    app.stop()


def test_magic_bytes_override_misleading_text_extension(tmp_path) -> None:
    original = tmp_path / "renamed.txt"
    original.write_bytes(b"%PDF-1.7\npretends-to-be-text")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)
    assert captured.source.mime_type == "application/pdf"

    with pytest.raises(UnsupportedTextSourceError, match="TXT/Markdown"):
        app.source_text.build(captured.source.source_id)

    assert app.database.connection.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0] == 0
    app.stop()


def test_representation_survives_restart_and_verifies_from_retained_blob(tmp_path) -> None:
    original = tmp_path / "restart.txt"
    original.write_bytes(b"one\r\ntwo\r\n")

    first_app = _started_app(tmp_path)
    captured = first_app.sources.capture_file(original)
    built = first_app.source_text.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    first_app.stop()

    second_app = _started_app(tmp_path)
    representation, blob = second_app.source_text.get(representation_id)
    path = second_app.source_text.verify(representation_id)
    assert representation.processing_run_id == built.processing_run.processing_run_id
    assert path.read_bytes() == b"one\ntwo\n"
    assert blob.integrity_sha256 == hashlib.sha256(b"one\ntwo\n").digest()
    assert second_app.source_text.read_text(representation_id) == "one\ntwo\n"
    second_app.stop()


def test_representation_verification_fails_closed_after_blob_corruption(tmp_path) -> None:
    original = tmp_path / "corrupt-me.txt"
    original.write_bytes(b"line one\r\nline two\r\n")

    app = _started_app(tmp_path)
    captured = app.sources.capture_file(original)
    built = app.source_text.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    representation_path = app.source_text.verify(representation_id)
    representation_path.write_bytes(b"corrupt")

    with pytest.raises(BlobIntegrityError, match="integrity verification failed"):
        app.source_text.verify(representation_id)
    app.stop()
