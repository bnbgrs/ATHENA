"""Deterministic native text and structure extraction for DOCX Sources."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from athena.source.models import SourceRepresentationStructureType
from athena.source.representation_store import (
    PreparedTextRepresentation,
    StoredRepresentationBlob,
    TextRepresentationStore,
)
from athena.storage.paths import RuntimePaths

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_W_NS}}}"
_DOCUMENT_XML = "word/document.xml"
_STYLES_XML = "word/styles.xml"
_CONTENT_TYPES_XML = "[Content_Types].xml"
_MAX_DOCUMENT_XML_BYTES = 64 * 1024 * 1024
_MAX_STYLES_XML_BYTES = 8 * 1024 * 1024
_BLOCK_SEPARATOR = "\n\n"
_CELL_BLOCK_SEPARATOR = "\n"
_CELL_SEPARATOR = "\t"
_ROW_SEPARATOR = "\n"


class DocxRepresentationError(RuntimeError):
    """Base error for native DOCX representation work."""


class UnsupportedDocxSourceError(DocxRepresentationError):
    """Raised when the Source is not a supported DOCX package."""


class DocxTextUnavailableError(DocxRepresentationError):
    """Raised when the package contains no usable document text."""


@dataclass(frozen=True, slots=True)
class DocxStructureSpan:
    structure_index: int
    structure_type: SourceRepresentationStructureType
    path: str
    parent_index: int | None
    start_offset: int
    end_offset: int
    content_sha256: bytes
    metadata_json: str


@dataclass(frozen=True, slots=True)
class PreparedDocxTextRepresentation:
    staging_path: Path
    byte_length: int
    content_sha256: bytes
    structures: tuple[DocxStructureSpan, ...]


@dataclass(slots=True)
class _PendingStructure:
    structure_type: SourceRepresentationStructureType
    path: str
    parent_index: int | None
    start_offset: int
    end_offset: int | None
    metadata: dict[str, object]


class _TextAndStructureBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.offset = 0
        self.structures: list[_PendingStructure] = []

    def append(self, value: str) -> None:
        if not value:
            return
        self.parts.append(value)
        self.offset += len(value)

    def begin(
        self,
        structure_type: SourceRepresentationStructureType,
        *,
        path: str,
        parent_index: int | None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        index = len(self.structures)
        self.structures.append(
            _PendingStructure(
                structure_type=structure_type,
                path=path,
                parent_index=parent_index,
                start_offset=self.offset,
                end_offset=None,
                metadata=dict(metadata or {}),
            )
        )
        return index

    def end(self, index: int) -> None:
        pending = self.structures[index]
        if pending.end_offset is not None:
            raise RuntimeError("DOCX structure span was finalized twice.")
        pending.end_offset = self.offset

    def finish(self) -> tuple[str, tuple[DocxStructureSpan, ...]]:
        text = "".join(self.parts)
        records: list[DocxStructureSpan] = []
        for index, pending in enumerate(self.structures):
            if pending.end_offset is None:
                raise RuntimeError("DOCX structure span was not finalized.")
            fragment = text[pending.start_offset : pending.end_offset]
            records.append(
                DocxStructureSpan(
                    structure_index=index,
                    structure_type=pending.structure_type,
                    path=pending.path,
                    parent_index=pending.parent_index,
                    start_offset=pending.start_offset,
                    end_offset=pending.end_offset,
                    content_sha256=hashlib.sha256(fragment.encode("utf-8")).digest(),
                    metadata_json=json.dumps(
                        pending.metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                )
            )
        return text, tuple(records)


class DocxNativeTextRepresentationStore:
    """Extract DOCX text plus retained block/table structure without Office automation."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self._text_store = TextRepresentationStore(paths)

    def extract(
        self,
        source_path: Path,
    ) -> PreparedDocxTextRepresentation:
        staging_dir = (
            self.paths.spool_root
            / "representations"
            / "staging"
        )
        staging_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        staging_path = (
            staging_dir
            / f"docx-text-{secrets.token_hex(16)}.partial"
        )

        try:
            document_root, styles = (
                _read_docx_parts(
                    source_path
                )
            )

            text, structures = (
                _render_docx_text(
                    document_root,
                    styles,
                )
            )

            encoded = text.encode(
                "utf-8"
            )

            with staging_path.open(
                "xb"
            ) as target:
                target.write(
                    encoded
                )
                target.flush()
                os.fsync(
                    target.fileno()
                )

            return PreparedDocxTextRepresentation(
                staging_path=staging_path,
                byte_length=len(
                    encoded
                ),
                content_sha256=(
                    hashlib.sha256(
                        encoded
                    ).digest()
                ),
                structures=structures,
            )

        except Exception:
            staging_path.unlink(
                missing_ok=True
            )
            raise


    def discard(self, prepared: PreparedDocxTextRepresentation) -> None:
        prepared.staging_path.unlink(missing_ok=True)

    def commit(self, prepared: PreparedDocxTextRepresentation) -> StoredRepresentationBlob:
        base = PreparedTextRepresentation(
            staging_path=prepared.staging_path,
            byte_length=prepared.byte_length,
            content_sha256=prepared.content_sha256,
        )
        return self._text_store.commit(base)


def _read_docx_parts(
    source_path: Path,
) -> tuple[
    ET.Element,
    dict[str, tuple[str | None, int | None]],
]:
    try:
        with zipfile.ZipFile(
            source_path,
            "r",
        ) as archive:
            return _read_docx_parts_from_archive(
                archive
            )

    except zipfile.BadZipFile as exc:
        raise DocxRepresentationError(
            "Cannot parse DOCX ZIP container."
        ) from exc

    except (
        OSError,
        KeyError,
    ) as exc:
        raise DocxRepresentationError(
            "Cannot read DOCX package parts."
        ) from exc



def extract_docx_text_bytes(
    payload: bytes,
) -> str:
    """Extract DOCX text directly from plaintext bytes in memory."""

    try:
        with zipfile.ZipFile(
            io.BytesIO(
                payload
            ),
            "r",
        ) as archive:
            document_root, styles = (
                _read_docx_parts_from_archive(
                    archive
                )
            )

    except zipfile.BadZipFile as exc:
        raise DocxRepresentationError(
            "Cannot parse DOCX ZIP container."
        ) from exc

    except (
        OSError,
        KeyError,
    ) as exc:
        raise DocxRepresentationError(
            "Cannot read DOCX package parts."
        ) from exc

    text, _structures = (
        _render_docx_text(
            document_root,
            styles,
        )
    )

    return text


def _read_docx_parts_from_archive(
    archive: zipfile.ZipFile,
) -> tuple[
    ET.Element,
    dict[str, tuple[str | None, int | None]],
]:
    names = set(
        archive.namelist()
    )

    if (
        _CONTENT_TYPES_XML not in names
        or _DOCUMENT_XML not in names
    ):
        raise UnsupportedDocxSourceError(
            "DOCX package is missing required "
            "OOXML document parts."
        )

    _require_safe_member(
        archive,
        _DOCUMENT_XML,
        _MAX_DOCUMENT_XML_BYTES,
    )

    document_bytes = archive.read(
        _DOCUMENT_XML
    )

    styles: dict[
        str,
        tuple[str | None, int | None],
    ] = {}

    if _STYLES_XML in names:
        _require_safe_member(
            archive,
            _STYLES_XML,
            _MAX_STYLES_XML_BYTES,
        )

        styles = _parse_styles(
            archive.read(
                _STYLES_XML
            )
        )

    try:
        root = ET.fromstring(
            document_bytes
        )

    except ET.ParseError as exc:
        raise DocxRepresentationError(
            "DOCX word/document.xml "
            "is malformed XML."
        ) from exc

    if root.tag != f"{_W}document":
        raise UnsupportedDocxSourceError(
            "DOCX main part is not a "
            "WordprocessingML document."
        )

    return (
        root,
        styles,
    )


def _render_docx_text(
    document_root: ET.Element,
    styles: dict[
        str,
        tuple[str | None, int | None],
    ],
) -> tuple[
    str,
    tuple[DocxStructureSpan, ...],
]:
    body = document_root.find(
        f"{_W}body"
    )

    if body is None:
        raise DocxRepresentationError(
            "DOCX word/document.xml "
            "has no body element."
        )

    builder = (
        _TextAndStructureBuilder()
    )

    _render_block_container(
        body,
        builder=builder,
        path="/body",
        parent_index=None,
        separator=_BLOCK_SEPARATOR,
        styles=styles,
    )

    text, structures = (
        builder.finish()
    )

    if not text.strip():
        raise DocxTextUnavailableError(
            "DOCX contains no usable "
            "native document text."
        )

    return (
        text,
        structures,
    )


def _require_safe_member(archive: zipfile.ZipFile, name: str, maximum_size: int) -> None:
    info = archive.getinfo(name)
    if info.file_size > maximum_size:
        raise DocxRepresentationError(
            f"DOCX part {name!r} exceeds the native parser safety limit."
        )
    if info.file_size > 1_048_576 and info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > 500:
            raise DocxRepresentationError(
                f"DOCX part {name!r} has an unsafe compression ratio."
            )


def _parse_styles(payload: bytes) -> dict[str, tuple[str | None, int | None]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DocxRepresentationError("DOCX word/styles.xml is malformed XML.") from exc
    result: dict[str, tuple[str | None, int | None]] = {}
    for style in root.findall(f"{_W}style"):
        if style.get(f"{_W}type") != "paragraph":
            continue
        style_id = style.get(f"{_W}styleId")
        if not style_id:
            continue
        name_node = style.find(f"{_W}name")
        name = name_node.get(f"{_W}val") if name_node is not None else None
        outline = style.find(f"{_W}pPr/{_W}outlineLvl")
        outline_level: int | None = None
        if outline is not None:
            raw = outline.get(f"{_W}val")
            if raw is not None:
                try:
                    outline_level = int(raw)
                except ValueError:
                    outline_level = None
        result[style_id] = (name, outline_level)
    return result


def _render_block_container(
    container: ET.Element,
    *,
    builder: _TextAndStructureBuilder,
    path: str,
    parent_index: int | None,
    separator: str,
    styles: dict[str, tuple[str | None, int | None]],
) -> None:
    blocks = [child for child in container if child.tag in {f"{_W}p", f"{_W}tbl"}]
    paragraph_number = 0
    table_number = 0
    for ordinal, block in enumerate(blocks):
        if block.tag == f"{_W}p":
            paragraph_number += 1
            _render_paragraph(
                block,
                builder=builder,
                path=f"{path}/p[{paragraph_number}]",
                parent_index=parent_index,
                styles=styles,
            )
        else:
            table_number += 1
            _render_table(
                block,
                builder=builder,
                path=f"{path}/table[{table_number}]",
                parent_index=parent_index,
                styles=styles,
            )
        if ordinal + 1 < len(blocks):
            builder.append(separator)


def _render_paragraph(
    paragraph: ET.Element,
    *,
    builder: _TextAndStructureBuilder,
    path: str,
    parent_index: int | None,
    styles: dict[str, tuple[str | None, int | None]],
) -> None:
    structure_type, metadata = _paragraph_classification(paragraph, styles)
    index = builder.begin(
        structure_type,
        path=path,
        parent_index=parent_index,
        metadata=metadata,
    )
    builder.append(_paragraph_text(paragraph))
    builder.end(index)


def _render_table(
    table: ET.Element,
    *,
    builder: _TextAndStructureBuilder,
    path: str,
    parent_index: int | None,
    styles: dict[str, tuple[str | None, int | None]],
) -> None:
    rows = table.findall(f"{_W}tr")
    table_index = builder.begin(
        SourceRepresentationStructureType.TABLE,
        path=path,
        parent_index=parent_index,
        metadata={"row_count": len(rows)},
    )
    for row_number, row in enumerate(rows, start=1):
        row_path = f"{path}/row[{row_number}]"
        cells = row.findall(f"{_W}tc")
        row_index = builder.begin(
            SourceRepresentationStructureType.TABLE_ROW,
            path=row_path,
            parent_index=table_index,
            metadata={"row_index": row_number, "cell_count": len(cells)},
        )
        logical_column = 1
        for cell_number, cell in enumerate(cells, start=1):
            cell_path = f"{row_path}/cell[{cell_number}]"
            properties = _cell_properties(cell)
            cell_index = builder.begin(
                SourceRepresentationStructureType.TABLE_CELL,
                path=cell_path,
                parent_index=row_index,
                metadata={
                    "row_index": row_number,
                    "cell_index": cell_number,
                    "column_index": logical_column,
                    **properties,
                },
            )
            _render_block_container(
                cell,
                builder=builder,
                path=cell_path,
                parent_index=cell_index,
                separator=_CELL_BLOCK_SEPARATOR,
                styles=styles,
            )
            builder.end(cell_index)
            grid_span = properties.get("grid_span", 1)
            logical_column += grid_span if isinstance(grid_span, int) else 1
            if cell_number < len(cells):
                builder.append(_CELL_SEPARATOR)
        builder.end(row_index)
        if row_number < len(rows):
            builder.append(_ROW_SEPARATOR)
    builder.end(table_index)


def _paragraph_classification(
    paragraph: ET.Element,
    styles: dict[str, tuple[str | None, int | None]],
) -> tuple[SourceRepresentationStructureType, dict[str, object]]:
    p_pr = paragraph.find(f"{_W}pPr")
    style_id: str | None = None
    num_id: str | None = None
    list_level: int | None = None
    direct_outline_level: int | None = None
    if p_pr is not None:
        p_style = p_pr.find(f"{_W}pStyle")
        if p_style is not None:
            style_id = p_style.get(f"{_W}val")
        direct_outline = p_pr.find(f"{_W}outlineLvl")
        if direct_outline is not None:
            raw_outline = direct_outline.get(f"{_W}val")
            if raw_outline is not None:
                try:
                    direct_outline_level = int(raw_outline)
                except ValueError:
                    direct_outline_level = None
        num_pr = p_pr.find(f"{_W}numPr")
        if num_pr is not None:
            ilvl = num_pr.find(f"{_W}ilvl")
            num = num_pr.find(f"{_W}numId")
            raw_level = ilvl.get(f"{_W}val") if ilvl is not None else None
            raw_num = num.get(f"{_W}val") if num is not None else None
            if raw_level is not None:
                try:
                    list_level = int(raw_level)
                except ValueError:
                    list_level = None
            num_id = raw_num

    style_name: str | None = None
    outline_level: int | None = None
    if style_id is not None:
        style_name, outline_level = styles.get(style_id, (None, None))

    heading_level = _heading_level(
        style_id,
        style_name,
        direct_outline_level if direct_outline_level is not None else outline_level,
    )
    metadata: dict[str, object] = {}
    if style_id is not None:
        metadata["style_id"] = style_id
    if style_name is not None:
        metadata["style_name"] = style_name
    if heading_level is not None:
        metadata["heading_level"] = heading_level
        return SourceRepresentationStructureType.HEADING, metadata
    if num_id is not None or list_level is not None:
        if num_id is not None:
            metadata["numbering_id"] = num_id
        if list_level is not None:
            metadata["list_level"] = list_level
        return SourceRepresentationStructureType.LIST_ITEM, metadata
    return SourceRepresentationStructureType.PARAGRAPH, metadata


def _heading_level(
    style_id: str | None,
    style_name: str | None,
    outline_level: int | None,
) -> int | None:
    if outline_level is not None and 0 <= outline_level <= 8:
        return outline_level + 1
    for value in (style_name, style_id):
        if not value:
            continue
        match = re.fullmatch(r"heading\s*([1-9])", value.strip(), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in {f"{_W}br", f"{_W}cr"}:
            parts.append("\n")
        elif node.tag == f"{_W}noBreakHyphen":
            parts.append("\u2011")
        elif node.tag == f"{_W}softHyphen":
            parts.append("\u00ad")
    return "".join(parts).replace("\r\n", "\n").replace("\r", "\n")


def _cell_properties(cell: ET.Element) -> dict[str, object]:
    properties: dict[str, object] = {}
    tc_pr = cell.find(f"{_W}tcPr")
    if tc_pr is None:
        return properties
    grid_span = tc_pr.find(f"{_W}gridSpan")
    if grid_span is not None:
        raw = grid_span.get(f"{_W}val")
        if raw is not None:
            try:
                properties["grid_span"] = int(raw)
            except ValueError:
                properties["grid_span"] = raw
    v_merge = tc_pr.find(f"{_W}vMerge")
    if v_merge is not None:
        properties["vertical_merge"] = v_merge.get(f"{_W}val") or "continue"
    return properties
