"""Hybrid lexical + semantic candidate fusion."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from athena.retrieval.ranking import RetrievalRankingService
from athena.retrieval.search import SearchEntityType
from athena.retrieval.semantic import LocalSemanticSearchService

_TYPE_AUTHORITY = {
    SearchEntityType.KNOWLEDGE: 1.00,
    SearchEntityType.CLAIM: 0.88,
    SearchEntityType.CHAT_MESSAGE: 0.68,
}

_LEXICAL_WEIGHT = 0.42
_SEMANTIC_WEIGHT = 0.38
_AUTHORITY_WEIGHT = 0.14
_CONTRADICTION_WEIGHT = 0.06
_DIVERSITY_THRESHOLD = 0.82
_DIVERSITY_PENALTY = 0.14


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    entity_id: uuid.UUID
    revision_id: uuid.UUID
    entity_type: SearchEntityType
    title: str | None
    text: str
    score: float
    lexical_score: float
    semantic_score: float
    authority_score: float
    contradiction_count: int
    duplicate_count: int


@dataclass(slots=True)
class _Candidate:
    entity_id: uuid.UUID
    revision_id: uuid.UUID
    entity_type: SearchEntityType
    title: str | None
    text: str
    lexical_score: float
    semantic_score: float
    contradiction_count: int
    member_entity_ids: frozenset[uuid.UUID]


class HybridRetrievalService:
    """Fuse Step-2 lexical ranking with independent semantic candidates."""

    def __init__(
        self,
        lexical: RetrievalRankingService,
        semantic: LocalSemanticSearchService,
    ) -> None:
        self.lexical = lexical
        self.semantic = semantic

    def search(
        self,
        query: str,
        *,
        model_id: str,
        limit: int = 20,
        entity_type: SearchEntityType | None = None,
    ) -> tuple[HybridSearchResult, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("Hybrid search limit must be between 1 and 200.")

        lexical_candidate_limit = min(200, max(60, limit * 8))
        semantic_candidate_limit = min(400, max(60, limit * 8))
        lexical_results = self.lexical.search(
            query,
            limit=lexical_candidate_limit,
            entity_type=entity_type,
        )
        semantic_results = self.semantic.search(
            query,
            model_id=model_id,
            limit=semantic_candidate_limit,
        )

        by_entity: dict[tuple[SearchEntityType, uuid.UUID], _Candidate] = {}
        for lexical_result in lexical_results:
            by_entity[(lexical_result.entity_type, lexical_result.entity_id)] = _Candidate(
                entity_id=lexical_result.entity_id,
                revision_id=lexical_result.revision_id,
                entity_type=lexical_result.entity_type,
                title=lexical_result.title,
                text=lexical_result.text,
                lexical_score=lexical_result.lexical_score,
                semantic_score=0.0,
                contradiction_count=lexical_result.contradiction_count,
                member_entity_ids=frozenset(
                    (lexical_result.entity_id, *lexical_result.duplicate_entity_ids)
                ),
            )

        semantic_values = [
            semantic_result.similarity
            for semantic_result in semantic_results
            if entity_type is None or semantic_result.entity_type is entity_type
        ]
        sem_min = min(semantic_values, default=0.0)
        sem_max = max(semantic_values, default=0.0)

        for semantic_result in semantic_results:
            if (
                entity_type is not None
                and semantic_result.entity_type is not entity_type
            ):
                continue
            semantic_score = _normalize_similarity(
                semantic_result.similarity,
                minimum=sem_min,
                maximum=sem_max,
            )
            key = (semantic_result.entity_type, semantic_result.entity_id)
            current = by_entity.get(key)
            if current is None:
                by_entity[key] = _Candidate(
                    entity_id=semantic_result.entity_id,
                    revision_id=semantic_result.revision_id,
                    entity_type=semantic_result.entity_type,
                    title=semantic_result.title,
                    text=semantic_result.text,
                    lexical_score=0.0,
                    semantic_score=semantic_score,
                    contradiction_count=semantic_result.contradiction_count,
                    member_entity_ids=frozenset((semantic_result.entity_id,)),
                )
            else:
                current.semantic_score = max(
                    current.semantic_score,
                    semantic_score,
                )
                current.contradiction_count = max(
                    current.contradiction_count,
                    semantic_result.contradiction_count,
                )
                current.member_entity_ids = (
                    current.member_entity_ids | frozenset((semantic_result.entity_id,))
                )

        consolidated = _consolidate_exact(tuple(by_entity.values()))
        scored = tuple(_score(candidate) for candidate in consolidated)
        return _diversify(scored, limit=limit)


def _score(candidate: _Candidate) -> HybridSearchResult:
    authority = _TYPE_AUTHORITY[candidate.entity_type]
    contradiction = min(1.0, candidate.contradiction_count / 2.0)
    score = (
        candidate.lexical_score * _LEXICAL_WEIGHT
        + candidate.semantic_score * _SEMANTIC_WEIGHT
        + authority * _AUTHORITY_WEIGHT
        + contradiction * _CONTRADICTION_WEIGHT
    )
    return HybridSearchResult(
        entity_id=candidate.entity_id,
        revision_id=candidate.revision_id,
        entity_type=candidate.entity_type,
        title=candidate.title,
        text=candidate.text,
        score=score,
        lexical_score=candidate.lexical_score,
        semantic_score=candidate.semantic_score,
        authority_score=authority,
        contradiction_count=candidate.contradiction_count,
        duplicate_count=max(0, len(candidate.member_entity_ids) - 1),
    )


def _consolidate_exact(candidates: tuple[_Candidate, ...]) -> tuple[_Candidate, ...]:
    groups: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        groups.setdefault(_normalize_text(candidate.text), []).append(candidate)

    output: list[_Candidate] = []
    for group in groups.values():
        representative = max(
            group,
            key=lambda item: (
                _TYPE_AUTHORITY[item.entity_type],
                item.lexical_score,
                item.semantic_score,
                item.entity_id.hex,
            ),
        )
        output.append(
            _Candidate(
                entity_id=representative.entity_id,
                revision_id=representative.revision_id,
                entity_type=representative.entity_type,
                title=representative.title,
                text=representative.text,
                lexical_score=max(item.lexical_score for item in group),
                semantic_score=max(item.semantic_score for item in group),
                contradiction_count=max(
                    item.contradiction_count for item in group
                ),
                member_entity_ids=frozenset().union(
                    *(item.member_entity_ids for item in group)
                ),
            )
        )
    return tuple(output)


def _diversify(
    scored: tuple[HybridSearchResult, ...],
    *,
    limit: int,
) -> tuple[HybridSearchResult, ...]:
    remaining = sorted(
        scored,
        key=lambda item: (
            -item.score,
            item.entity_type.value,
            item.entity_id.hex,
        ),
    )
    selected: list[HybridSearchResult] = []

    while remaining and len(selected) < limit:
        best_index = 0
        best_key: tuple[float, float, float, str] | None = None
        for index, candidate in enumerate(remaining):
            penalty = _diversity_penalty(candidate, selected)
            key = (
                candidate.score - penalty,
                candidate.score,
                _TYPE_AUTHORITY[candidate.entity_type],
                candidate.entity_id.hex,
            )
            if best_key is None or key > best_key:
                best_key = key
                best_index = index

        chosen = remaining.pop(best_index)
        penalty = _diversity_penalty(chosen, selected)
        if penalty:
            chosen = HybridSearchResult(
                entity_id=chosen.entity_id,
                revision_id=chosen.revision_id,
                entity_type=chosen.entity_type,
                title=chosen.title,
                text=chosen.text,
                score=max(0.0, chosen.score - penalty),
                lexical_score=chosen.lexical_score,
                semantic_score=chosen.semantic_score,
                authority_score=chosen.authority_score,
                contradiction_count=chosen.contradiction_count,
                duplicate_count=chosen.duplicate_count,
            )
        selected.append(chosen)

    return tuple(selected)


def _diversity_penalty(
    candidate: HybridSearchResult,
    selected: list[HybridSearchResult],
) -> float:
    candidate_tokens = _tokens(candidate.text)
    maximum = 0.0
    for prior in selected:
        similarity = _jaccard(candidate_tokens, _tokens(prior.text))
        maximum = max(maximum, similarity)
    if maximum < _DIVERSITY_THRESHOLD:
        return 0.0
    return _DIVERSITY_PENALTY * maximum


def _normalize_similarity(
    value: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if maximum <= minimum:
        return 1.0
    return min(1.0, max(0.0, (value - minimum) / (maximum - minimum)))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        character if character.isalnum() else " "
        for character in normalized
    )
    return " ".join(normalized.split())


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"\w+", _normalize_text(value), flags=re.UNICODE))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
