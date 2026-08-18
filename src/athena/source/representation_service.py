"""Use cases for deterministic retained text SourceRepresentations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from athena.chat.service import ChatService
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.source.blob_store import BlobStore
from athena.source.models import (
    BlobRecord,
    SourceRecord,
    SourceRepresentationPageRecord,
    SourceRepresentationRecord,
    SourceRepresentationStructureRecord,
    TextRepresentationResult,
)
from athena.source.repository import SourceRepository
from athena.source.representation_repository import (
    CanonicalWriteFence,
    SourceRepresentationRepository,
)
from athena.source.representation_store import (
    PreparedTextRepresentation,
    TextRepresentationStore,
    UnsupportedTextSourceError,
)

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
_PARSER_ID = "athena.native_text"
_PARSER_VERSION = "1"
_PIPELINE_VERSION = "native-text-v1"
_TEXT_OPTIONS: dict[str, object] = {
    "encoding": "utf-8-strict",
    "utf8_bom": "strip",
    "line_endings": "lf",
    "unicode_normalization": "none",
}


@dataclass(frozen=True, slots=True)
class TextRepresentationBuildResult:
    result: TextRepresentationResult
    processing_run: ProcessingRun


class SourceTextRepresentationService:
    """Create retained normalized text from a verified archived Source blob."""

    def __init__(
        self,
        *,
        sources: SourceRepository,
        representations: SourceRepresentationRepository,
        blob_store: BlobStore,
        representation_store: TextRepresentationStore,
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
        return dict(_TEXT_OPTIONS)

    def supports(self, source: SourceRecord) -> bool:
        try:
            _require_supported_text_source(source)
        except UnsupportedTextSourceError:
            return False
        return True

    def build(
        self,
        source_id: uuid.UUID,
        *,
        write_fence: CanonicalWriteFence | None = None,
    ) -> TextRepresentationBuildResult:
        source, source_blob = self.sources.get(source_id)
        _require_supported_text_source(source)
        actor_id = self.chat.ensure_local_user()
        run = self.runs.start_run(
            run_type="source_text_representation",
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
                "representation_type": "normalized_text",
                "retention_state": "retained",
                "parser_id": _PARSER_ID,
                "parser_version": _PARSER_VERSION,
                "options": _TEXT_OPTIONS,
            },
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )

        prepared: PreparedTextRepresentation | None = None
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
                prepared = None
                stored_blob = None
            else:
                stored_blob = self.representation_store.commit(prepared)
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
                options=_TEXT_OPTIONS,
                write_fence=write_fence,
            )
            return TextRepresentationBuildResult(
                result=result,
                processing_run=self.runs.load_run(run.processing_run_id),
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

    def get(self, representation_id: uuid.UUID) -> tuple[SourceRepresentationRecord, BlobRecord]:
        return self.representations.get(representation_id)

    def list_for_source(
        self,
        source_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> tuple[tuple[SourceRepresentationRecord, BlobRecord], ...]:
        # Preserve SourceNotFound behavior even when the representation list is empty.
        self.sources.get(source_id)
        return self.representations.list_for_source(source_id, limit=limit)

    def verify(self, representation_id: uuid.UUID) -> Path:
        representation, blob = self.representations.get(representation_id)
        if representation.content_hash != blob.integrity_sha256:
            raise RuntimeError("SourceRepresentation content hash disagrees with its BlobRecord.")
        return self.blob_store.verify_blob(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
            expected_sha256=representation.content_hash,
            expected_length=blob.byte_length,
        )

    def read_text(self, representation_id: uuid.UUID) -> str:
        return self.verify(representation_id).read_text(encoding="utf-8")


    def list_pages(
        self, representation_id: uuid.UUID
    ) -> tuple[SourceRepresentationPageRecord, ...]:
        return self.representations.list_pages(representation_id)

    def get_structure(
        self, structure_id: uuid.UUID
    ) -> SourceRepresentationStructureRecord:
        return self.representations.get_structure(structure_id)

    def list_structures(
        self, representation_id: uuid.UUID
    ) -> tuple[SourceRepresentationStructureRecord, ...]:
        return self.representations.list_structures(representation_id)

    def page_range_for_text_range(
        self,
        representation_id: uuid.UUID,
        *,
        start_offset: int,
        end_offset: int,
    ) -> tuple[int, int] | None:
        return self.representations.page_range_for_text_range(
            representation_id,
            start_offset=start_offset,
            end_offset=end_offset,
        )


def _require_supported_text_source(source: SourceRecord) -> None:
    suffix = Path(source.original_name or "").suffix.lower()
    if source.mime_type in _TEXT_MIME_TYPES:
        return
    if source.mime_type in {None, "application/octet-stream"} and suffix in _TEXT_SUFFIXES:
        return
    raise UnsupportedTextSourceError(
        "VS4 Step 2 supports deterministic text representations only for TXT/Markdown Sources."
    )
