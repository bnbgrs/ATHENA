"""Domain models for immutable Raw Archive source capture."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class SourceType(str, Enum):
    """Logical source types defined by the v1 persistent data model."""

    FILE = "file"
    WEB_SNAPSHOT = "web_snapshot"
    EMAIL = "email"
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    API_CAPTURE = "api_capture"
    CHAT_EXPORT = "chat_export"
    OTHER = "other"


class SourceLifecycleState(str, Enum):
    """Technical processing state of a captured Source."""

    CAPTURED = "captured"
    PROCESSING = "processing"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    CANCELLED = "cancelled"


class BlobStorageArea(str, Enum):
    """Physical area containing the verified immutable blob bytes."""

    ARCHIVE = "archive"
    SPOOL = "spool"


class SourceRepresentationType(str, Enum):
    """Technical representations derived from immutable Source bytes."""

    NORMALIZED_TEXT = "normalized_text"
    EXTRACTED_TEXT = "extracted_text"


class SourceRepresentationStructureType(str, Enum):
    """Retained technical structure extracted from a document representation."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"


class SourceAnchorType(str, Enum):
    """Stable source location types from the persistent data model."""

    WHOLE_SOURCE = "whole_source"
    TEXT_RANGE = "text_range"
    PAGE_RANGE = "page_range"
    PAGE_REGION = "page_region"
    AUDIO_TIME_RANGE = "audio_time_range"
    VIDEO_TIME_RANGE = "video_time_range"
    TABLE_CELL = "table_cell"
    MESSAGE = "message"
    STRUCTURED_PATH = "structured_path"


class RepresentationRetentionState(str, Enum):
    """Whether one immutable representation is retained for durable provenance."""

    RETAINED = "retained"
    DISPOSABLE = "disposable"


@dataclass(frozen=True, slots=True)
class BlobRecord:
    blob_id: uuid.UUID
    byte_length: int
    media_type: str | None
    storage_area: BlobStorageArea
    storage_locator: str
    integrity_sha256: bytes
    encryption_state: str
    created_at_us: int
    verified_at_us: int


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: uuid.UUID
    source_type: SourceType
    created_at_us: int
    acquired_at_us: int
    original_name: str | None
    original_modified_at_us: int | None
    mime_type: str | None
    blob_id: uuid.UUID
    content_sha256: bytes
    source_uri: str | None
    lifecycle_state: SourceLifecycleState
    provenance_id: uuid.UUID
    protection_scope_id: uuid.UUID | None = None
    protected_metadata_payload_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SourceCaptureResult:
    source: SourceRecord
    blob: BlobRecord
    reused_blob: bool


@dataclass(frozen=True, slots=True)
class SourceRepresentationRecord:
    representation_id: uuid.UUID
    source_id: uuid.UUID
    representation_type: SourceRepresentationType
    blob_id: uuid.UUID
    processing_run_id: uuid.UUID
    content_hash: bytes
    retention_state: RepresentationRetentionState
    media_type: str
    parser_id: str
    parser_version: str
    options_json: str
    created_at_us: int
    provenance_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SourceRepresentationPageRecord:
    representation_id: uuid.UUID
    page_number: int
    start_offset: int
    end_offset: int
    content_hash: bytes


@dataclass(frozen=True, slots=True)
class SourceRepresentationStructureRecord:
    structure_id: uuid.UUID
    representation_id: uuid.UUID
    structure_index: int
    structure_type: SourceRepresentationStructureType
    path: str
    parent_structure_id: uuid.UUID | None
    start_offset: int
    end_offset: int
    content_hash: bytes
    metadata_json: str


@dataclass(frozen=True, slots=True)
class TextRepresentationResult:
    representation: SourceRepresentationRecord
    blob: BlobRecord
    reused_blob: bool


@dataclass(frozen=True, slots=True)
class SourceAnchorRecord:
    anchor_id: uuid.UUID
    source_id: uuid.UUID
    representation_id: uuid.UUID | None
    anchor_type: SourceAnchorType
    start_offset: int | None
    end_offset: int | None
    page_start: int | None
    page_end: int | None
    start_time_ms: int | None
    end_time_ms: int | None
    geometry_json: str | None
    quoted_hash: bytes | None
    created_at_us: int
