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


@dataclass(frozen=True, slots=True)
class SourceCaptureResult:
    source: SourceRecord
    blob: BlobRecord
    reused_blob: bool
