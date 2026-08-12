"""Deterministic lexical ranking and consolidation for local retrieval."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from athena.retrieval.search import (
    LocalSearchService,
    SearchEntityType,
    SearchResult,
)

_TYPE_AUTHORITY = {
    SearchEntityType.KNOWLEDGE: 1.00,
    SearchEntityType.CLAIM: 0.88,
    SearchEntityType.CHAT_MESSAGE: 0.68,
}

# Ranking only. These values never change canonical truth or lifecycle state.
_FTS_WEIGHT = 0.72
_AUTHORITY_WEIGHT = 0.20
_CONTRADICTION_WEIGHT = 0.08
_DIVERSITY_SIMILARITY_THRESHOLD = 0.82
_DIVERSITY_PENALTY = 0.16


@dataclass(frozen=True, slots=True)
class RankedSearchResult:
    entity_id: uuid.UUID
    revision_id: uuid.UUID
    entity_type: SearchEntityType
    title: str | None
    snippet: str
    text: str
    score: float
    lexical_score: float
    authority_score: float
    contradiction_score: float
    contradiction_count: int
    duplicate_count: int
    duplicate_entity_ids: tuple[uuid.UUID, ...]


class RetrievalRankingService:
    """Consolidate redundant FTS hits and rank a diverse candidate set.

    Exact normalized duplicates are collapsed. Near-similar results are not
    merged because lexical similarity alone cannot establish semantic identity.
    Instead, a ranking-only diversity penalty reduces redundant result flooding.
    Explicitly contradictory Claims are exempt from suppressing each other.
    """

    def __init__(self, search: LocalSearchService) -> None:
        self.search_service = search
        self.database = search.database

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        entity_type: SearchEntityType | None = None,
    ) -> tuple[RankedSearchResult, ...]:
        candidate_limit = min(200, max(50, limit * 8))
        raw = self.search_service.search(
            query,
            limit=candidate_limit,
            entity_type=entity_type,
        )
        if not raw:
            return ()

        consolidated = self._consolidate_exact_duplicates(raw)
        scored = self._base_scores(consolidated)
        return self._diversify(scored, limit=limit)

    def _consolidate_exact_duplicates(
        self,
        raw: tuple[SearchResult, ...],
    ) -> tuple[tuple[SearchResult, tuple[uuid.UUID, ...]], ...]:
        groups: dict[str, list[SearchResult]] = {}
        order: list[str] = []

        for item in raw:
            key = _normalize_text(item.text)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(item)

        consolidated: list[tuple[SearchResult, tuple[uuid.UUID, ...]]] = []
        for key in order:
            group = groups[key]
            representative = max(
                group,
                key=lambda item: (
                    _TYPE_AUTHORITY[item.entity_type],
                    item.score,
                    item.entity_id.hex,
                ),
            )
            group_contradiction_count = max(
                item.contradiction_count for item in group
            )
            if representative.contradiction_count != group_contradiction_count:
                representative = SearchResult(
                    entity_id=representative.entity_id,
                    revision_id=representative.revision_id,
                    entity_type=representative.entity_type,
                    title=representative.title,
                    snippet=representative.snippet,
                    text=representative.text,
                    score=representative.score,
                    contradiction_count=group_contradiction_count,
                )
            duplicates = tuple(
                item.entity_id
                for item in sorted(
                    group,
                    key=lambda item: (
                        item.entity_type.value,
                        item.entity_id.hex,
                    ),
                )
                if item.entity_id != representative.entity_id
            )
            consolidated.append((representative, duplicates))

        return tuple(consolidated)

    def _base_scores(
        self,
        consolidated: tuple[tuple[SearchResult, tuple[uuid.UUID, ...]], ...],
    ) -> tuple[RankedSearchResult, ...]:
        raw_scores = [max(0.0, item.score) for item, _ in consolidated]
        maximum = max(raw_scores, default=0.0)
        minimum = min(raw_scores, default=0.0)

        results: list[RankedSearchResult] = []
        for item, duplicates in consolidated:
            lexical = _normalize_score(item.score, minimum=minimum, maximum=maximum)
            authority = _TYPE_AUTHORITY[item.entity_type]

            # Contradiction presence is a retrieval signal, not a truth penalty.
            # It slightly boosts visibility so conflicting knowledge is not hidden.
            contradiction = min(1.0, item.contradiction_count / 2.0)
            final = (
                lexical * _FTS_WEIGHT
                + authority * _AUTHORITY_WEIGHT
                + contradiction * _CONTRADICTION_WEIGHT
            )
            results.append(
                RankedSearchResult(
                    entity_id=item.entity_id,
                    revision_id=item.revision_id,
                    entity_type=item.entity_type,
                    title=item.title,
                    snippet=item.snippet,
                    text=item.text,
                    score=final,
                    lexical_score=lexical,
                    authority_score=authority,
                    contradiction_score=contradiction,
                    contradiction_count=item.contradiction_count,
                    duplicate_count=len(duplicates),
                    duplicate_entity_ids=duplicates,
                )
            )

        results.sort(
            key=lambda item: (
                -item.score,
                item.entity_type.value,
                item.entity_id.hex,
            )
        )
        return tuple(results)

    def _diversify(
        self,
        scored: tuple[RankedSearchResult, ...],
        *,
        limit: int,
    ) -> tuple[RankedSearchResult, ...]:
        selected: list[RankedSearchResult] = []
        remaining = list(scored)

        while remaining and len(selected) < limit:
            best_index = 0
            for index, candidate in enumerate(remaining):
                penalty = self._diversity_penalty(candidate, selected)
                adjusted = candidate.score - penalty
                tie_break = (
                    adjusted,
                    candidate.score,
                    _TYPE_AUTHORITY[candidate.entity_type],
                    candidate.entity_id.hex,
                )
                best = remaining[best_index]
                best_penalty = self._diversity_penalty(best, selected)
                best_tie = (
                    best.score - best_penalty,
                    best.score,
                    _TYPE_AUTHORITY[best.entity_type],
                    best.entity_id.hex,
                )
                if tie_break > best_tie:
                    best_index = index

            chosen = remaining.pop(best_index)
            applied_penalty = self._diversity_penalty(chosen, selected)
            if applied_penalty:
                chosen = RankedSearchResult(
                    entity_id=chosen.entity_id,
                    revision_id=chosen.revision_id,
                    entity_type=chosen.entity_type,
                    title=chosen.title,
                    snippet=chosen.snippet,
                    text=chosen.text,
                    score=max(0.0, chosen.score - applied_penalty),
                    lexical_score=chosen.lexical_score,
                    authority_score=chosen.authority_score,
                    contradiction_score=chosen.contradiction_score,
                    contradiction_count=chosen.contradiction_count,
                    duplicate_count=chosen.duplicate_count,
                    duplicate_entity_ids=chosen.duplicate_entity_ids,
                )
            selected.append(chosen)

        return tuple(selected)

    def _diversity_penalty(
        self,
        candidate: RankedSearchResult,
        selected: list[RankedSearchResult],
    ) -> float:
        candidate_tokens = _token_set(candidate.text)
        if not candidate_tokens:
            return 0.0

        maximum_similarity = 0.0
        for prior in selected:
            if self._claims_explicitly_contradict(candidate, prior):
                continue
            similarity = _jaccard(candidate_tokens, _token_set(prior.text))
            maximum_similarity = max(maximum_similarity, similarity)

        if maximum_similarity < _DIVERSITY_SIMILARITY_THRESHOLD:
            return 0.0
        return _DIVERSITY_PENALTY * maximum_similarity

    def _claims_explicitly_contradict(
        self,
        left: RankedSearchResult,
        right: RankedSearchResult,
    ) -> bool:
        if (
            left.entity_type is not SearchEntityType.CLAIM
            or right.entity_type is not SearchEntityType.CLAIM
        ):
            return False
        row = self.database.connection.execute(
            """
            SELECT 1
            FROM claim_evidence
            WHERE claim_id = ?
              AND evidence_entity_id = ?
              AND evidence_role = 'contradicts'
            LIMIT 1
            """,
            (left.entity_id.bytes, right.entity_id.bytes),
        ).fetchone()
        return row is not None


def _normalize_score(value: float, *, minimum: float, maximum: float) -> float:
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


def _token_set(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"\w+", _normalize_text(value), flags=re.UNICODE))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
