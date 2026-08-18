"""Use cases for retained native DOCX SourceRepresentations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from athena.chat.service import ChatService
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.source.blob_store import BlobStore
from athena.source.docx_representation_store import (
    DocxNativeTextRepresentationStore,
    PreparedDocxTextRepresentation,
    UnsupportedDocxSourceError,
)
from athena.source.models import (
    SourceRecord,
    SourceRepresentationStructureRecord,
    SourceRepresentationType,
    TextRepresentationResult,
)
from athena.source.repository import SourceRepository
from athena.source.representation_repository import (
    CanonicalWriteFence,
    SourceRepresentationRepository,
)

_DOCX_SUFFIXES = {".docx"}
_DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_CONTAINER_MIME_TYPES = {"application/zip", "application/octet-stream", None}
_PARSER_ID = "athena.native_docx"
_PARSER_VERSION = "1"
_PIPELINE_VERSION = "native-docx-text-v1"
_DOCX_OPTIONS: dict[str, object] = {
    "engine": "stdlib-zipfile-elementtree",
    "line_endings": "lf",
    "unicode_normalization": "none",
    "body_block_separator": "\\n\\n",
    "table_cell_separator": "\\t",
    "table_row_separator": "\\n",
    "structure_map": "ooxml-block-path-v1",
}


@dataclass(frozen=True, slots=True)
class DocxRepresentationBuildResult:
    result: TextRepresentationResult
    processing_run: ProcessingRun
    structures: tuple[SourceRepresentationStructureRecord, ...]


class SourceDocxRepresentationService:
    """Create retained DOCX text plus durable technical document structure."""

    def __init__(
        self,
        *,
        sources: SourceRepository,
        representations: SourceRepresentationRepository,
        blob_store: BlobStore,
        representation_store: DocxNativeTextRepresentationStore,
        runs: ModelRunRepository,
        chat: ChatService,
    ) -> None:
        self.sources = sources
        self.representations = representations
        self.blob_store = blob_store
        self.representation_store = representation_store
        self.runs = runs
        self.chat = chat

    @property
    def parser_signature(self) -> str:
        return f"{_PARSER_ID}@{_PARSER_VERSION}"

    @property
    def parser_id(self) -> str:
        return _PARSER_ID

    @property
    def parser_version(self) -> str:
        return _PARSER_VERSION

    @property
    def parser_options(self) -> dict[str, object]:
        return dict(_DOCX_OPTIONS)

    def supports(self, source: SourceRecord) -> bool:
        suffix = Path(source.original_name or "").suffix.lower()
        if source.mime_type in _DOCX_MIME_TYPES:
            return True
        return suffix in _DOCX_SUFFIXES and source.mime_type in _CONTAINER_MIME_TYPES

    def build(
        self,
        source_id: uuid.UUID,
        *,
        write_fence: CanonicalWriteFence | None = None,
    ) -> DocxRepresentationBuildResult:
        source, source_blob = self.sources.get(source_id)
        _require_supported_docx_source(source)
        actor_id = self.chat.ensure_local_user()
        run = self.runs.start_run(
            run_type="source_docx_native_text_representation",
            trigger_actor_id=actor_id,
            pipeline_version=_PIPELINE_VERSION,
            input_snapshot={
                "source_id": str(source.source_id),
                "blob_id": str(source_blob.blob_id),
                "source_sha256": source.content_sha256.hex(),
                "source_byte_length": source_blob.byte_length,
                "mime_type": source.mime_type,
                "original_name": source.original_name,
            },
            configuration={
                "representation_type": SourceRepresentationType.NORMALIZED_TEXT.value,
                "retention_state": "retained",
                "parser_id": _PARSER_ID,
                "parser_version": _PARSER_VERSION,
                "options": _DOCX_OPTIONS,
            },
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )

        prepared: PreparedDocxTextRepresentation | None = None
        try:
            source_path = self.blob_store.verify_blob(
                storage_area=source_blob.storage_area,
                storage_locator=source_blob.storage_locator,
                expected_sha256=source_blob.integrity_sha256,
                expected_length=source_blob.byte_length,
            )
            prepared = self.representation_store.extract(source_path)
            content_hash = prepared.content_sha256
            existing_blob = self.sources.find_blob_by_integrity(
                integrity_sha256=content_hash,
                byte_length=prepared.byte_length,
            )
            if existing_blob is not None:
                self.blob_store.verify_blob(
                    storage_area=existing_blob.storage_area,
                    storage_locator=existing_blob.storage_locator,
                    expected_sha256=existing_blob.integrity_sha256,
                    expected_length=existing_blob.byte_length,
                )
                self.representation_store.discard(prepared)
                stored_blob = None
            else:
                stored_blob = self.representation_store.commit(prepared)

            structure_map = tuple(
                (
                    item.structure_index,
                    item.structure_type,
                    item.path,
                    item.parent_index,
                    item.start_offset,
                    item.end_offset,
                    item.content_sha256,
                    item.metadata_json,
                )
                for item in prepared.structures
            )
            prepared = None
            result = self.representations.create_retained_text(
                actor_id=actor_id,
                source_id=source_id,
                processing_run_id=run.processing_run_id,
                stored_blob=stored_blob,
                existing_blob=existing_blob,
                content_hash=content_hash,
                parser_id=_PARSER_ID,
                parser_version=_PARSER_VERSION,
                options=_DOCX_OPTIONS,
                representation_type=SourceRepresentationType.NORMALIZED_TEXT,
                operation="source.representation.docx_text.create",
                structure_map=structure_map,
                write_fence=write_fence,
            )
            structures = self.verify_structure_map(result.representation.representation_id)
            return DocxRepresentationBuildResult(
                result=result,
                processing_run=self.runs.load_run(run.processing_run_id),
                structures=structures,
            )
        except Exception as exc:
            if prepared is not None:
                self.representation_store.discard(prepared)
            current = self.runs.load_run(run.processing_run_id)
            if current.status == "running":
                self.runs.finish_run(
                    run.processing_run_id,
                    status="failed",
                    error_detail=type(exc).__name__,
                )
            raise

    def verify_structure_map(
        self, representation_id: uuid.UUID
    ) -> tuple[SourceRepresentationStructureRecord, ...]:
        representation, blob = self.representations.get(representation_id)
        if representation.parser_id != _PARSER_ID:
            raise ValueError("DOCX structure verification requires native DOCX representation.")
        text = self.blob_store.verify_blob(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
            expected_sha256=representation.content_hash,
            expected_length=blob.byte_length,
        ).read_text(encoding="utf-8")
        structures = self.representations.list_structures(representation_id)
        if not structures:
            raise RuntimeError("Native DOCX representation is missing its retained structure map.")
        if tuple(item.structure_index for item in structures) != tuple(range(len(structures))):
            raise RuntimeError("DOCX structure map indexes are not contiguous from zero.")
        known_ids = {item.structure_id for item in structures}
        for item in structures:
            if item.parent_structure_id is not None and item.parent_structure_id not in known_ids:
                raise RuntimeError("DOCX structure map contains an unknown parent.")
            if not 0 <= item.start_offset <= item.end_offset <= len(text):
                raise RuntimeError("DOCX structure range is outside retained text.")
            actual = hashlib.sha256(
                text[item.start_offset : item.end_offset].encode("utf-8")
            ).digest()
            if actual != item.content_hash:
                raise RuntimeError("DOCX structure text hash verification failed.")
            try:
                metadata = json.loads(item.metadata_json)
            except json.JSONDecodeError as exc:
                raise RuntimeError("DOCX structure metadata is invalid JSON.") from exc
            if not isinstance(metadata, dict):
                raise RuntimeError("DOCX structure metadata must be a JSON object.")
        return structures


def _require_supported_docx_source(source: SourceRecord) -> None:
    suffix = Path(source.original_name or "").suffix.lower()
    if source.mime_type in _DOCX_MIME_TYPES:
        return
    if suffix in _DOCX_SUFFIXES and source.mime_type in _CONTAINER_MIME_TYPES:
        return
    raise UnsupportedDocxSourceError(
        "VS6 Step 2 native DOCX extraction supports DOCX Sources only."
    )
