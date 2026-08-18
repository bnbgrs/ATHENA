"""Use cases for retained native-text PDF SourceRepresentations."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from athena.chat.service import ChatService
from athena.model.provenance import ModelRunRepository, ProcessingRun
from athena.source.blob_store import BlobStore
from athena.source.models import (
    SourceRecord,
    SourceRepresentationPageRecord,
    SourceRepresentationType,
    TextRepresentationResult,
)
from athena.source.pdf_representation_store import (
    PdfNativeTextRepresentationStore,
    PreparedPdfTextRepresentation,
    UnsupportedPdfSourceError,
)
from athena.source.repository import SourceRepository
from athena.source.representation_repository import (
    CanonicalWriteFence,
    SourceRepresentationRepository,
)

_PDF_SUFFIXES = {".pdf"}
_PDF_MIME_TYPES = {"application/pdf"}
_PYPDF_VERSION = version("pypdf")
_PARSER_ID = "athena.native_pdf"
_PARSER_VERSION = f"1+pypdf-{_PYPDF_VERSION}"
_PIPELINE_VERSION = "native-pdf-text-v1"
_PDF_OPTIONS: dict[str, object] = {
    "engine": "pypdf",
    "engine_version": _PYPDF_VERSION,
    "line_endings": "lf",
    "page_order": "document",
    "page_separator": "\n\n",
    "unicode_normalization": "none",
}


@dataclass(frozen=True, slots=True)
class PdfRepresentationBuildResult:
    result: TextRepresentationResult
    processing_run: ProcessingRun
    pages: tuple[SourceRepresentationPageRecord, ...]


class SourcePdfRepresentationService:
    """Create retained native PDF text plus a stable page-offset map."""

    def __init__(
        self,
        *,
        sources: SourceRepository,
        representations: SourceRepresentationRepository,
        blob_store: BlobStore,
        representation_store: PdfNativeTextRepresentationStore,
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
        return dict(_PDF_OPTIONS)

    def supports(self, source: SourceRecord) -> bool:
        suffix = Path(source.original_name or "").suffix.lower()
        if source.mime_type in _PDF_MIME_TYPES:
            return True
        return source.mime_type in {None, "application/octet-stream"} and suffix in _PDF_SUFFIXES

    def build(
        self,
        source_id: uuid.UUID,
        *,
        write_fence: CanonicalWriteFence | None = None,
    ) -> PdfRepresentationBuildResult:
        source, source_blob = self.sources.get(source_id)
        _require_supported_pdf_source(source)
        actor_id = self.chat.ensure_local_user()
        run = self.runs.start_run(
            run_type="source_pdf_native_text_representation",
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
                "representation_type": SourceRepresentationType.EXTRACTED_TEXT.value,
                "retention_state": "retained",
                "parser_id": _PARSER_ID,
                "parser_version": _PARSER_VERSION,
                "options": _PDF_OPTIONS,
                "page_map": "codepoint_offsets_v1",
            },
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )

        prepared: PreparedPdfTextRepresentation | None = None
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
            page_map = tuple(
                (
                    page.page_number,
                    page.start_offset,
                    page.end_offset,
                    page.content_sha256,
                )
                for page in prepared.pages
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
                options=_PDF_OPTIONS,
                representation_type=SourceRepresentationType.EXTRACTED_TEXT,
                operation="source.representation.pdf_text.create",
                page_map=page_map,
                write_fence=write_fence,
            )
            pages = self.verify_page_map(result.representation.representation_id)
            return PdfRepresentationBuildResult(
                result=result,
                processing_run=self.runs.load_run(run.processing_run_id),
                pages=pages,
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

    def verify_page_map(
        self, representation_id: uuid.UUID
    ) -> tuple[SourceRepresentationPageRecord, ...]:
        representation, blob = self.representations.get(representation_id)
        if representation.representation_type is not SourceRepresentationType.EXTRACTED_TEXT:
            raise ValueError("PDF page-map verification requires extracted_text representation.")
        text_path = self.blob_store.verify_blob(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
            expected_sha256=representation.content_hash,
            expected_length=blob.byte_length,
        )
        text = text_path.read_text(encoding="utf-8")
        pages = self.representations.list_pages(representation_id)
        if not pages:
            raise RuntimeError("Native PDF representation is missing its retained page map.")
        expected_numbers = tuple(range(1, len(pages) + 1))
        if tuple(page.page_number for page in pages) != expected_numbers:
            raise RuntimeError("PDF page map is not contiguous from page 1.")
        previous_end = 0
        for page in pages:
            if page.start_offset < previous_end or page.end_offset < page.start_offset:
                raise RuntimeError("PDF page map contains overlapping or invalid offsets.")
            if page.end_offset > len(text):
                raise RuntimeError("PDF page map extends beyond retained text.")
            actual = hashlib.sha256(
                text[page.start_offset : page.end_offset].encode("utf-8")
            ).digest()
            if actual != page.content_hash:
                raise RuntimeError("PDF page-map text hash verification failed.")
            previous_end = page.end_offset
        return pages


def _require_supported_pdf_source(source: SourceRecord) -> None:
    suffix = Path(source.original_name or "").suffix.lower()
    if source.mime_type in _PDF_MIME_TYPES:
        return
    if source.mime_type in {None, "application/octet-stream"} and suffix in _PDF_SUFFIXES:
        return
    raise UnsupportedPdfSourceError(
        "VS6 Step 1 native PDF extraction supports PDF Sources only."
    )
