from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.source.anchor_service import SourceAnchorIntegrityError
from athena.source.chunking_service import SourceChunkIntegrityError
from athena.source.docx_representation_store import (
    DocxRepresentationError,
    DocxTextUnavailableError,
    UnsupportedDocxSourceError,
)
from athena.source.models import (
    SourceAnchorType,
    SourceRepresentationStructureType,
    SourceRepresentationType,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W}">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
</w:styles>
"""
_DOCUMENT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W}"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly Report</w:t></w:r></w:p>
  <w:p><w:r><w:t>DOCX_RETRIEVAL_TOKEN</w:t></w:r></w:p>
  <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Listed fact</w:t></w:r></w:p>
  <w:tbl>
    <w:tr>
      <w:tc><w:p><w:r><w:t>Metric</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>
    </w:tr>
    <w:tr>
      <w:tc><w:p><w:r><w:t>Revenue</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc>
    </w:tr>
  </w:tbl>
  <w:sectPr/>
</w:body></w:document>
"""


def _app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(settings=AthenaSettings(local_root=tmp_path / "local"))
    app.start()
    return app


def _docx_bytes(*, document: str = _DOCUMENT, styles: str | None = _STYLES) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (
            ("[Content_Types].xml", _CONTENT_TYPES),
            ("word/document.xml", document),
            ("word/styles.xml", styles),
        ):
            if payload is None:
                continue
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload.encode("utf-8"))
    return output.getvalue()


def test_docx_native_text_and_structure_are_retained_after_original_is_removed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.docx"
    original = _docx_bytes()
    path.write_bytes(original)

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    assert captured.source.mime_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    archived = app.sources.verify(captured.source.source_id)
    path.unlink()

    built = app.source_docx.build(captured.source.source_id)
    representation = built.result.representation
    text = app.source_text.read_text(representation.representation_id)

    assert representation.representation_type is SourceRepresentationType.NORMALIZED_TEXT
    assert representation.parser_id == "athena.native_docx"
    assert representation.parser_version == "1"
    assert built.processing_run.pipeline_version == "native-docx-text-v1"
    assert built.processing_run.status == "succeeded"
    assert text == (
        "Quarterly Report\n\nDOCX_RETRIEVAL_TOKEN\n\nListed fact\n\n"
        "Metric\tValue\nRevenue\t42"
    )
    assert tuple(item.structure_type for item in built.structures[:4]) == (
        SourceRepresentationStructureType.HEADING,
        SourceRepresentationStructureType.PARAGRAPH,
        SourceRepresentationStructureType.LIST_ITEM,
        SourceRepresentationStructureType.TABLE,
    )
    assert any(
        item.structure_type is SourceRepresentationStructureType.TABLE_CELL
        and item.path == "/body/table[1]/row[2]/cell[2]"
        for item in built.structures
    )
    assert app.source_docx.verify_structure_map(representation.representation_id) == built.structures
    assert archived.read_bytes() == original
    assert not path.exists()
    app.stop()


def test_docx_table_cell_and_heading_materialize_stable_structural_anchors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "anchors.docx"
    path.write_bytes(_docx_bytes())

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_docx.build(captured.source.source_id)

    cell = next(
        item
        for item in built.structures
        if item.path == "/body/table[1]/row[2]/cell[2]"
    )
    cell_anchor = app.source_anchors.materialize_structure(cell.structure_id)
    assert cell_anchor.anchor_type is SourceAnchorType.TABLE_CELL
    assert app.source_anchors.structure_id_for_anchor(cell_anchor.anchor_id) == cell.structure_id
    assert app.source_anchors.read_text(cell_anchor.anchor_id) == "42"
    assert app.source_anchors.verify(cell_anchor.anchor_id) == cell_anchor

    heading = next(
        item
        for item in built.structures
        if item.structure_type is SourceRepresentationStructureType.HEADING
    )
    metadata = json.loads(heading.metadata_json)
    assert metadata["heading_level"] == 1
    heading_anchor = app.source_anchors.materialize_structure(heading.structure_id)
    assert heading_anchor.anchor_type is SourceAnchorType.STRUCTURED_PATH
    assert app.source_anchors.read_text(heading_anchor.anchor_id) == "Quarterly Report"
    app.stop()


def test_docx_structure_anchor_materialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "idempotent.docx"
    path.write_bytes(_docx_bytes())

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_docx.build(captured.source.source_id)
    cell = next(
        item
        for item in built.structures
        if item.path == "/body/table[1]/row[1]/cell[1]"
    )

    first = app.source_anchors.materialize_structure(cell.structure_id)
    second = app.source_anchors.materialize_structure(cell.structure_id)
    assert second.anchor_id == first.anchor_id
    app.stop()


def test_docx_structure_map_tamper_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "tamper.docx"
    path.write_bytes(_docx_bytes())

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_docx.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    target = built.structures[-1]
    app.database.connection.execute(
        "UPDATE source_representation_structures SET content_hash = ? WHERE structure_id = ?",
        (b"x" * 32, target.structure_id.bytes),
    )

    with pytest.raises(RuntimeError, match="structure text hash"):
        app.source_docx.verify_structure_map(representation_id)
    with pytest.raises(SourceAnchorIntegrityError, match="structure hash"):
        app.source_anchors.materialize_structure(target.structure_id)
    app.stop()


def test_malformed_docx_fails_without_losing_captured_original(tmp_path: Path) -> None:
    path = tmp_path / "broken.docx"
    original = b"PK\x03\x04not-a-valid-zip-container"
    path.write_bytes(original)

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    source_id = captured.source.source_id

    with pytest.raises(DocxRepresentationError):
        app.source_docx.build(source_id)

    source, _blob = app.sources.get(source_id)
    assert source.lifecycle_state.value == "captured"
    assert app.sources.verify(source_id).read_bytes() == original
    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM source_representations WHERE source_id = ?",
        (source_id.bytes,),
    ).fetchone()[0] == 0
    app.stop()



def test_blank_docx_fails_without_creating_a_representation(tmp_path: Path) -> None:
    document = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{_W}"><w:body><w:p/><w:sectPr/></w:body></w:document>'''
    path = tmp_path / "blank.docx"
    original = _docx_bytes(document=document)
    path.write_bytes(original)

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    with pytest.raises(DocxTextUnavailableError, match="no usable native document text"):
        app.source_docx.build(captured.source.source_id)
    assert app.sources.verify(captured.source.source_id).read_bytes() == original
    assert app.database.connection.execute(
        "SELECT COUNT(*) FROM source_representations WHERE source_id = ?",
        (captured.source.source_id.bytes,),
    ).fetchone()[0] == 0
    app.stop()

def test_zip_named_docx_without_required_ooxml_parts_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fake.docx"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("unrelated.txt", "not a Word document")
    original = output.getvalue()
    path.write_bytes(original)

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    with pytest.raises(UnsupportedDocxSourceError, match="required OOXML"):
        app.source_docx.build(captured.source.source_id)
    assert app.sources.verify(captured.source.source_id).read_bytes() == original
    app.stop()


def test_docx_large_table_chunking_prefers_retained_cell_boundaries(tmp_path: Path) -> None:
    cell_a = "A" * 700
    cell_b = "B" * 700
    cell_c = "C" * 700
    document = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{_W}"><w:body>
<w:tbl><w:tr>
<w:tc><w:p><w:r><w:t>{cell_a}</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>{cell_b}</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>{cell_c}</w:t></w:r></w:p></w:tc>
</w:tr></w:tbl>
<w:sectPr/>
</w:body></w:document>'''
    path = tmp_path / "large-table.docx"
    path.write_bytes(_docx_bytes(document=document))

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_docx.build(captured.source.source_id)
    chunk_build = app.source_chunks.build_default(built.result.representation.representation_id)

    assert chunk_build.profile.algorithm == "document_structure_char_v1"
    assert len(chunk_build.chunks) == 3
    cells = tuple(
        item
        for item in built.structures
        if item.structure_type is SourceRepresentationStructureType.TABLE_CELL
    )
    assert len(cells) == 3
    for cell in cells:
        assert any(
            chunk.start_anchor_value <= cell.start_offset
            and chunk.end_anchor_value >= cell.end_offset
            for chunk in chunk_build.chunks
        )
    app.stop()


def test_docx_chunking_fails_closed_when_retained_structure_map_is_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-map.docx"
    path.write_bytes(_docx_bytes())

    app = _app(tmp_path)
    captured = app.sources.capture_file(path)
    built = app.source_docx.build(captured.source.source_id)
    representation_id = built.result.representation.representation_id
    app.database.connection.execute(
        "DELETE FROM source_representation_structures WHERE representation_id = ?",
        (representation_id.bytes,),
    )

    with pytest.raises(SourceChunkIntegrityError, match="missing its retained structure map"):
        app.source_chunks.build_default(representation_id)
    app.stop()
