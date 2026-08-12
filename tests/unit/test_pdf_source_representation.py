from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.models import SourceRepresentationType
from athena.source.pdf_representation_store import (
    PdfNativeTextUnavailableError,
    PdfRepresentationError,
)


def _app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def _native_text_pdf(pages: tuple[str, ...]) -> bytes:
    """Build a small deterministic PDF with one Helvetica text run per page."""
    font_id = 3 + (2 * len(pages))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2*i} 0 R' for i in range(len(pages)))}] "
            f"/Count {len(pages)} >>"
        ).encode("ascii"),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, text in enumerate(pages):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )

    highest = max(objects)
    output = bytearray(b"%PDF-1.4\n%ATHENA\n")
    offsets = [0] * (highest + 1)
    for object_id in range(1, highest + 1):
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {highest + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for object_id in range(1, highest + 1):
        output.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


def test_pdf_native_text_is_retained_with_verified_page_map(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    original = _native_text_pdf(("Alpha page one", "Beta page two"))
    path.write_bytes(original)

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    assert captured.source.mime_type == "application/pdf"
    archived = app.sources.verify(captured.source.source_id)
    path.unlink()

    built = app.source_pdf.build(captured.source.source_id)
    representation = built.result.representation
    text = app.source_text.read_text(representation.representation_id)
    pages = built.pages

    assert representation.representation_type is SourceRepresentationType.EXTRACTED_TEXT
    assert representation.parser_id == "athena.native_pdf"
    assert representation.parser_version.startswith("1+pypdf-")
    assert built.processing_run.pipeline_version == "native-pdf-text-v1"
    assert built.processing_run.status == "succeeded"
    assert len(pages) == 2
    assert "Alpha page one" in text
    assert "Beta page two" in text
    assert text[pages[0].start_offset : pages[0].end_offset].strip() == "Alpha page one"
    assert text[pages[1].start_offset : pages[1].end_offset].strip() == "Beta page two"
    for page in pages:
        actual = hashlib.sha256(
            text[page.start_offset : page.end_offset].encode("utf-8")
        ).digest()
        assert actual == page.content_hash
    assert archived.read_bytes() == original
    assert not path.exists()
    app.stop()


def test_pdf_page_map_drives_page_aware_source_anchor(tmp_path: Path) -> None:
    path = tmp_path / "pages.pdf"
    path.write_bytes(_native_text_pdf(("First page marker", "Second page marker")))

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_pdf.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    text = app.source_text.read_text(representation_id)

    start = text.index("Second page marker")
    end = start + len("Second page marker")
    anchor = app.source_anchors.materialize_text_range(
        representation_id,
        start_offset=start,
        end_offset=end,
    )

    assert anchor.page_start == 2
    assert anchor.page_end == 2
    assert app.source_anchors.verify(anchor.anchor_id) == anchor
    app.stop()


def test_pdf_anchor_crossing_pages_records_page_range(tmp_path: Path) -> None:
    path = tmp_path / "cross-pages.pdf"
    path.write_bytes(_native_text_pdf(("Page one tail", "Page two head")))

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_pdf.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    pages = built.pages
    start = max(pages[0].start_offset, pages[0].end_offset - 5)
    end = min(pages[1].end_offset, pages[1].start_offset + 5)
    assert start < end

    anchor = app.source_anchors.materialize_text_range(
        representation_id,
        start_offset=start,
        end_offset=end,
    )
    assert (anchor.page_start, anchor.page_end) == (1, 2)
    app.stop()


def test_pdf_page_map_tamper_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "tamper.pdf"
    path.write_bytes(_native_text_pdf(("Stable page text",)))

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_pdf.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    app.database.connection.execute(
        "UPDATE source_representation_pages SET content_hash = ? WHERE representation_id = ?",
        (b"x" * 32, representation_id.bytes),
    )

    with pytest.raises(RuntimeError, match="page-map text hash"):
        app.source_pdf.verify_page_map(representation_id)
    app.stop()


def test_malformed_pdf_fails_without_losing_captured_original(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    original = b"%PDF-1.7\nthis is not a parseable PDF"
    path.write_bytes(original)

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    source_id = captured.source.source_id

    with pytest.raises(PdfRepresentationError):
        app.source_pdf.build(source_id)

    source, _blob = app.sources.get(source_id)
    assert source.lifecycle_state.value == "captured"
    assert app.sources.verify(source_id).read_bytes() == original
    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM source_representations WHERE source_id = ?",
        (source_id.bytes,),
    ).fetchone()[0] == 0
    app.stop()


def test_blank_native_pdf_requires_future_ocr_fallback(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    path.write_bytes(_native_text_pdf(("",)))

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    with pytest.raises(PdfNativeTextUnavailableError, match="OCR fallback"):
        app.source_pdf.build(captured.source.source_id)
    app.stop()
