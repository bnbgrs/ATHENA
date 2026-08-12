"""Application service for safe Raw Archive source capture."""

from __future__ import annotations

import uuid
from pathlib import Path

from athena.chat.service import ChatService
from athena.source.blob_store import BlobStore
from athena.source.models import BlobRecord, SourceCaptureResult, SourceRecord
from athena.source.repository import SourceRepository


class SourceCaptureService:
    """Coordinate durable blob capture with authoritative Source persistence."""

    def __init__(
        self,
        *,
        repository: SourceRepository,
        blob_store: BlobStore,
        chat: ChatService,
    ) -> None:
        self.repository = repository
        self.blob_store = blob_store
        self.chat = chat

    def capture_file(self, path: Path) -> SourceCaptureResult:
        source_path = path.expanduser()
        prepared_blob = self.blob_store.capture_file(source_path)
        source_path = source_path.resolve()
        existing_blob = self.repository.find_blob_by_integrity(
            integrity_sha256=prepared_blob.integrity_sha256,
            byte_length=prepared_blob.byte_length,
        )
        if existing_blob is not None:
            self.blob_store.verify_blob(
                storage_area=existing_blob.storage_area,
                storage_locator=existing_blob.storage_locator,
                expected_sha256=existing_blob.integrity_sha256,
                expected_length=existing_blob.byte_length,
            )
        actor_id = self.chat.ensure_local_user()
        return self.repository.capture_file(
            actor_id=actor_id,
            original_name=source_path.name,
            source_uri=source_path.as_uri(),
            prepared_blob=prepared_blob,
        )

    def get(self, source_id: uuid.UUID) -> tuple[SourceRecord, BlobRecord]:
        return self.repository.get(source_id)

    def list(self, *, limit: int = 50) -> tuple[tuple[SourceRecord, BlobRecord], ...]:
        return self.repository.list(limit=limit)

    def verify(self, source_id: uuid.UUID) -> Path:
        _source, blob = self.repository.get(source_id)
        return self.blob_store.verify_blob(
            storage_area=blob.storage_area,
            storage_locator=blob.storage_locator,
            expected_sha256=blob.integrity_sha256,
            expected_length=blob.byte_length,
        )
