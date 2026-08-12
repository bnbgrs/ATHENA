from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace

import pytest

from athena.retrieval.archive import ArchiveHybridSearchResult
from athena.retrieval.context import ContextBuilderError
from athena.retrieval.source_context import (
    SourceContextBuilderService,
    SourceContextIntegrityError,
)
from athena.source.models import SourceAnchorRecord, SourceAnchorType


class FakeAnchors:
    def __init__(self, source_id: uuid.UUID) -> None:
        self.source_id = source_id
        self.calls: list[tuple[uuid.UUID, int, int]] = []
        self.records: dict[uuid.UUID, SourceAnchorRecord] = {}
        self.texts: dict[uuid.UUID, str] = {}

    def materialize_text_range(
        self,
        representation_id: uuid.UUID,
        *,
        start_offset: int,
        end_offset: int,
    ) -> SourceAnchorRecord:
        self.calls.append((representation_id, start_offset, end_offset))
        quoted = CURRENT_TEXT[start_offset:end_offset]
        anchor_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{representation_id}:{start_offset}:{end_offset}:{quoted}",
        )
        record = SourceAnchorRecord(
            anchor_id=anchor_id,
            source_id=self.source_id,
            representation_id=representation_id,
            anchor_type=SourceAnchorType.TEXT_RANGE,
            start_offset=start_offset,
            end_offset=end_offset,
            page_start=None,
            page_end=None,
            start_time_ms=None,
            end_time_ms=None,
            geometry_json=None,
            quoted_hash=hashlib.sha256(quoted.encode("utf-8")).digest(),
            created_at_us=1,
        )
        self.records[anchor_id] = record
        self.texts[anchor_id] = quoted
        return record

    def verify(self, anchor_id: uuid.UUID) -> SourceAnchorRecord:
        return self.records[anchor_id]

    def read_text(self, anchor_id: uuid.UUID) -> str:
        return self.texts[anchor_id]


CURRENT_TEXT = ""


def _result(text: str, *, score: float = 0.9) -> ArchiveHybridSearchResult:
    global CURRENT_TEXT
    CURRENT_TEXT = text
    source_id = uuid.uuid4()
    representation_id = uuid.uuid4()
    return ArchiveHybridSearchResult(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        representation_id=representation_id,
        chunk_index=0,
        chunking_profile_id=uuid.uuid4(),
        start_anchor_value=0,
        end_anchor_value=len(text),
        content_hash=hashlib.sha256(text.encode("utf-8")).digest(),
        build_signature=b"b" * 32,
        source_name="source.txt",
        source_uri="file:///source.txt",
        text=text,
        score=score,
        lexical_score=0.8,
        semantic_score=1.0,
    )


def test_source_context_materializes_anchor_and_never_exposes_chunk_id() -> None:
    result = _result("Berlin is mentioned in the imported source.")
    anchors = FakeAnchors(result.source_id)
    builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]

    bundle = builder.build_from_hybrid(
        query="Berlin",
        results=(result,),
        max_estimated_tokens=1200,
        max_items=4,
    )

    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert item.source_id == result.source_id
    assert item.representation_id == result.representation_id
    assert item.start_offset == 0
    assert item.end_offset == len(result.text)
    assert item.text == result.text
    assert item.quoted_hash == result.content_hash
    assert anchors.calls == [(result.representation_id, 0, len(result.text))]
    assert str(item.anchor_id) in bundle.rendered_text
    assert str(result.chunk_id) not in bundle.rendered_text
    assert "chunk_id" not in bundle.rendered_text
    assert '"evidence_class": "source"' in bundle.rendered_text


def test_source_context_truncates_to_exact_anchored_prefix_when_budget_is_small() -> None:
    text = "Berlin source evidence. " * 300
    result = _result(text)
    anchors = FakeAnchors(result.source_id)
    builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]

    bundle = builder.build_from_hybrid(
        query="Berlin",
        results=(result,),
        max_estimated_tokens=400,
        max_items=1,
    )

    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert item.truncated is True
    assert 0 < item.end_offset < len(text)
    assert item.text == text[item.start_offset : item.end_offset]
    assert item.quoted_hash == hashlib.sha256(item.text.encode("utf-8")).digest()
    assert bundle.estimated_tokens <= 400
    assert anchors.calls == [(result.representation_id, 0, item.end_offset)]


def test_source_context_rejects_tampered_archive_text_before_anchor_materialization() -> None:
    result = _result("Berlin")
    tampered = ArchiveHybridSearchResult(
        chunk_id=result.chunk_id,
        source_id=result.source_id,
        representation_id=result.representation_id,
        chunk_index=result.chunk_index,
        chunking_profile_id=result.chunking_profile_id,
        start_anchor_value=result.start_anchor_value,
        end_anchor_value=result.end_anchor_value,
        content_hash=b"x" * 32,
        build_signature=result.build_signature,
        source_name=result.source_name,
        source_uri=result.source_uri,
        text=result.text,
        score=result.score,
        lexical_score=result.lexical_score,
        semantic_score=result.semantic_score,
    )
    anchors = FakeAnchors(result.source_id)
    builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]

    with pytest.raises(ContextBuilderError, match="content hash"):
        builder.build_from_hybrid(query="Berlin", results=(tampered,))

    assert anchors.calls == []


def test_source_context_verify_bundle_rejects_tampered_ephemeral_text() -> None:
    result = _result("Berlin is durable source evidence.")
    anchors = FakeAnchors(result.source_id)
    builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]
    bundle = builder.build_from_hybrid(query="Berlin", results=(result,))
    item = bundle.items[0]

    tampered_item = replace(item, text=item.text + " injected")
    tampered_bundle = replace(bundle, items=(tampered_item,))

    with pytest.raises(SourceContextIntegrityError, match="text hash changed"):
        builder.verify_bundle(tampered_bundle)


def test_source_context_verify_bundle_rejects_anchor_metadata_tamper() -> None:
    result = _result("Berlin anchor integrity.")
    anchors = FakeAnchors(result.source_id)
    builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]
    bundle = builder.build_from_hybrid(query="Berlin", results=(result,))
    anchor_id = bundle.items[0].anchor_id
    anchor = anchors.records[anchor_id]

    anchors.records[anchor_id] = replace(anchor, quoted_hash=b"x" * 32)

    with pytest.raises(SourceContextIntegrityError, match="quoted source hash"):
        builder.verify_bundle(bundle)


def test_source_context_verify_bundle_accepts_untampered_bundle() -> None:
    result = _result("Berlin verified source evidence.")
    anchors = FakeAnchors(result.source_id)
    builder = SourceContextBuilderService(anchors)  # type: ignore[arg-type]
    bundle = builder.build_from_hybrid(query="Berlin", results=(result,))

    builder.verify_bundle(bundle)
