from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from athena.retrieval.archive import ArchiveHybridRetrievalService, ArchiveSearchError
from athena.retrieval.fusion import reciprocal_rank_contribution
from athena.retrieval.hybrid import HybridRetrievalService
from athena.retrieval.search import SearchEntityType


def _canonical_lexical(entity_id: uuid.UUID, text: str, raw_score: float):
    return SimpleNamespace(
        entity_id=entity_id,
        revision_id=uuid.uuid5(entity_id, "revision"),
        entity_type=SearchEntityType.KNOWLEDGE,
        title=None,
        text=text,
        lexical_score=raw_score,
        contradiction_count=0,
        duplicate_entity_ids=(),
    )


def _canonical_semantic(entity_id: uuid.UUID, text: str, similarity: float):
    return SimpleNamespace(
        entity_id=entity_id,
        revision_id=uuid.uuid5(entity_id, "revision"),
        entity_type=SearchEntityType.KNOWLEDGE,
        title=None,
        text=text,
        similarity=similarity,
        contradiction_count=0,
    )


class _LexicalStub:
    def __init__(self, results) -> None:
        self.results = tuple(results)

    def search(self, _query: str, **_kwargs):
        return self.results


class _SemanticStub:
    def __init__(self, results) -> None:
        self.results = tuple(results)

    def search(self, _query: str, **_kwargs):
        return self.results


def _archive_result(chunk_id: uuid.UUID, source_id: uuid.UUID, text: str, score: float):
    representation_id = uuid.uuid5(source_id, "representation")
    profile_id = uuid.uuid5(source_id, "profile")
    return SimpleNamespace(
        chunk_id=chunk_id,
        source_id=source_id,
        representation_id=representation_id,
        chunk_index=0,
        chunking_profile_id=profile_id,
        start_anchor_value=0,
        end_anchor_value=len(text),
        content_hash=b"a" * 32,
        build_signature=b"b" * 32,
        source_name="source.txt",
        source_uri="source://test",
        snippet=text,
        text=text,
        score=score,
    )


def _archive_semantic(chunk_id: uuid.UUID, source_id: uuid.UUID, text: str, similarity: float):
    representation_id = uuid.uuid5(source_id, "representation")
    profile_id = uuid.uuid5(source_id, "profile")
    return SimpleNamespace(
        chunk_id=chunk_id,
        source_id=source_id,
        representation_id=representation_id,
        chunk_index=0,
        chunking_profile_id=profile_id,
        start_anchor_value=0,
        end_anchor_value=len(text),
        content_hash=b"a" * 32,
        build_signature=b"b" * 32,
        source_name="source.txt",
        source_uri="source://test",
        text=text,
        similarity=similarity,
    )


def test_reciprocal_rank_contribution_is_one_based_and_configurable() -> None:
    assert reciprocal_rank_contribution(1, k=60) == pytest.approx(1 / 61)
    assert reciprocal_rank_contribution(2, k=10) == pytest.approx(1 / 12)
    with pytest.raises(ValueError, match="rank"):
        reciprocal_rank_contribution(0)
    with pytest.raises(ValueError, match="k"):
        reciprocal_rank_contribution(1, k=0)


def test_canonical_hybrid_uses_rrf_ranks_not_raw_score_scale() -> None:
    a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    b = uuid.UUID("00000000-0000-0000-0000-000000000002")
    c = uuid.UUID("00000000-0000-0000-0000-000000000003")
    texts = {a: "alpha evidence", b: "beta evidence", c: "gamma evidence"}

    def run(lexical_scores, semantic_scores):
        service = HybridRetrievalService(
            _LexicalStub(
                _canonical_lexical(entity_id, texts[entity_id], raw)
                for entity_id, raw in zip((a, b, c), lexical_scores, strict=True)
            ),
            _SemanticStub(
                _canonical_semantic(entity_id, texts[entity_id], raw)
                for entity_id, raw in zip((b, c, a), semantic_scores, strict=True)
            ),
        )
        return service.search("query", model_id="embed", limit=3)

    ordinary = run((0.9, 0.8, 0.7), (0.75, 0.50, 0.25))
    rescaled = run((9_000_000.0, 0.00002, -500.0), (1000.0, -20.0, -9000.0))

    assert [item.entity_id for item in ordinary] == [item.entity_id for item in rescaled]
    assert [item.score for item in ordinary] == pytest.approx(
        [item.score for item in rescaled]
    )
    assert ordinary[0].entity_id == b
    assert ordinary[0].lexical_score == pytest.approx(1 / 62)
    assert ordinary[0].semantic_score == pytest.approx(1 / 61)
    assert ordinary[0].score == pytest.approx(1 / 62 + 1 / 61)


def test_archive_hybrid_uses_rrf_ranks_not_raw_score_scale() -> None:
    a = uuid.UUID("10000000-0000-0000-0000-000000000001")
    b = uuid.UUID("10000000-0000-0000-0000-000000000002")
    c = uuid.UUID("10000000-0000-0000-0000-000000000003")
    sources = {
        a: uuid.UUID("20000000-0000-0000-0000-000000000001"),
        b: uuid.UUID("20000000-0000-0000-0000-000000000002"),
        c: uuid.UUID("20000000-0000-0000-0000-000000000003"),
    }
    texts = {a: "alpha source", b: "beta source", c: "gamma source"}

    def run(lexical_scores, semantic_scores):
        service = ArchiveHybridRetrievalService(
            _LexicalStub(
                _archive_result(entity_id, sources[entity_id], texts[entity_id], raw)
                for entity_id, raw in zip((a, b, c), lexical_scores, strict=True)
            ),
            _SemanticStub(
                _archive_semantic(entity_id, sources[entity_id], texts[entity_id], raw)
                for entity_id, raw in zip((b, c, a), semantic_scores, strict=True)
            ),
        )
        return service.search("query", model_id="embed", limit=3)

    ordinary = run((0.9, 0.8, 0.7), (0.75, 0.50, 0.25))
    rescaled = run((1e12, -3.0, -4.0), (7000.0, 2.0, -1e9))

    assert [item.chunk_id for item in ordinary] == [item.chunk_id for item in rescaled]
    assert [item.score for item in ordinary] == pytest.approx(
        [item.score for item in rescaled]
    )
    assert ordinary[0].chunk_id == b
    assert ordinary[0].lexical_score == pytest.approx(1 / 62)
    assert ordinary[0].semantic_score == pytest.approx(1 / 61)


def test_rrf_k_must_be_positive_for_both_hybrid_services() -> None:
    with pytest.raises(ValueError, match="RRF k"):
        HybridRetrievalService(_LexicalStub(()), _SemanticStub(()), rrf_k=0)
    with pytest.raises(ArchiveSearchError, match="RRF k"):
        ArchiveHybridRetrievalService(_LexicalStub(()), _SemanticStub(()), rrf_k=0)
