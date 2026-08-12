"""Materialization and verification of durable SourceAnchors."""

from __future__ import annotations

import hashlib
import uuid

from athena.chat.service import ChatService
from athena.source.anchor_repository import SourceAnchorRepository
from athena.source.chunk_store import SourceChunkStore
from athena.source.chunking_service import SourceChunkingService
from athena.source.models import SourceAnchorRecord, SourceAnchorType
from athena.source.representation_service import SourceTextRepresentationService


class SourceAnchorIntegrityError(RuntimeError):
    """Raised when a persisted SourceAnchor no longer matches its representation."""


class SourceAnchorService:
    """Create stable text-range evidence from verified retained representations."""

    def __init__(
        self,
        *,
        repository: SourceAnchorRepository,
        source_text: SourceTextRepresentationService,
        source_chunks: SourceChunkingService,
        chunk_store: SourceChunkStore,
        chat: ChatService,
    ) -> None:
        self.repository = repository
        self.source_text = source_text
        self.source_chunks = source_chunks
        self.chunk_store = chunk_store
        self.chat = chat

    def materialize_chunk(self, chunk_id: uuid.UUID) -> SourceAnchorRecord:
        chunk = self.source_chunks.verify(chunk_id)
        actor_id = self.chat.ensure_local_user()
        page_range = self.source_text.page_range_for_text_range(
            chunk.representation_id,
            start_offset=chunk.start_anchor_value,
            end_offset=chunk.end_anchor_value,
        )
        anchor = self.repository.materialize_text_range(
            actor_id=actor_id,
            source_id=chunk.source_id,
            representation_id=chunk.representation_id,
            start_offset=chunk.start_anchor_value,
            end_offset=chunk.end_anchor_value,
            quoted_hash=chunk.content_hash,
            page_start=page_range[0] if page_range is not None else None,
            page_end=page_range[1] if page_range is not None else None,
        )
        self.chunk_store.set_anchor_hint(chunk.chunk_id, anchor.anchor_id)
        return anchor

    def materialize_text_range(
        self,
        representation_id: uuid.UUID,
        *,
        start_offset: int,
        end_offset: int,
    ) -> SourceAnchorRecord:
        representation, _ = self.source_text.get(representation_id)
        text = self.source_text.read_text(representation_id)
        if not 0 <= start_offset < end_offset <= len(text):
            raise ValueError("SourceAnchor range is outside the retained representation.")
        quoted_hash = hashlib.sha256(text[start_offset:end_offset].encode("utf-8")).digest()
        page_range = self.source_text.page_range_for_text_range(
            representation_id,
            start_offset=start_offset,
            end_offset=end_offset,
        )
        actor_id = self.chat.ensure_local_user()
        return self.repository.materialize_text_range(
            actor_id=actor_id,
            source_id=representation.source_id,
            representation_id=representation_id,
            start_offset=start_offset,
            end_offset=end_offset,
            quoted_hash=quoted_hash,
            page_start=page_range[0] if page_range is not None else None,
            page_end=page_range[1] if page_range is not None else None,
        )

    def get(self, anchor_id: uuid.UUID) -> SourceAnchorRecord:
        return self.repository.get(anchor_id)

    def verify(self, anchor_id: uuid.UUID) -> SourceAnchorRecord:
        anchor = self.repository.get(anchor_id)
        if anchor.anchor_type is not SourceAnchorType.TEXT_RANGE:
            raise NotImplementedError("VS4 Step 5 verifies text_range SourceAnchors only.")
        if anchor.representation_id is None or anchor.start_offset is None or anchor.end_offset is None:
            raise SourceAnchorIntegrityError("Text SourceAnchor is missing its representation/range.")
        text = self.source_text.read_text(anchor.representation_id)
        if not 0 <= anchor.start_offset < anchor.end_offset <= len(text):
            raise SourceAnchorIntegrityError("SourceAnchor range is outside its representation.")
        actual_hash = hashlib.sha256(
            text[anchor.start_offset : anchor.end_offset].encode("utf-8")
        ).digest()
        if anchor.quoted_hash is None or actual_hash != anchor.quoted_hash:
            raise SourceAnchorIntegrityError("SourceAnchor quoted hash disagrees with representation.")
        expected_pages = self.source_text.page_range_for_text_range(
            anchor.representation_id,
            start_offset=anchor.start_offset,
            end_offset=anchor.end_offset,
        )
        actual_pages = (
            (anchor.page_start, anchor.page_end)
            if anchor.page_start is not None and anchor.page_end is not None
            else None
        )
        if expected_pages != actual_pages:
            raise SourceAnchorIntegrityError(
                "SourceAnchor page range disagrees with retained representation page map."
            )
        return anchor

    def read_text(self, anchor_id: uuid.UUID) -> str:
        anchor = self.verify(anchor_id)
        assert anchor.representation_id is not None
        assert anchor.start_offset is not None
        assert anchor.end_offset is not None
        text = self.source_text.read_text(anchor.representation_id)
        return text[anchor.start_offset : anchor.end_offset]

    def list_for_source(self, source_id: uuid.UUID, *, limit: int = 500) -> tuple[SourceAnchorRecord, ...]:
        return self.repository.list_for_source(source_id, limit=limit)
