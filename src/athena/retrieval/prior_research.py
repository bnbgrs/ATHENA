"""Lexical retrieval and bounded context over durable prior Research results."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.retrieval.context import ContextBuilderError, estimate_tokens
from athena.retrieval.lexical_relevance import required_term_matches
from athena.storage.database import SQLiteDatabase

_MAX_SEARCH_LIMIT = 100
_MAX_CANDIDATES = 500
_MIN_CONTEXT_BUDGET = 128
_MAX_CONTEXT_BUDGET = 64_000
_MIN_CONTEXT_ITEMS = 1
_MAX_CONTEXT_ITEMS = 100
_CONTEXT_VERSION = 1
_CONTEXT_ID_PATTERN = re.compile(r"CTX-(\d{3})")
_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)

_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "again",
        "all",
        "and",
        "are",
        "aus",
        "bei",
        "das",
        "dazu",
        "dem",
        "den",
        "der",
        "did",
        "die",
        "do",
        "does",
        "earlier",
        "ein",
        "eine",
        "ergab",
        "ergebnis",
        "ergebnisse",
        "find",
        "findings",
        "for",
        "found",
        "frueher",
        "fruehere",
        "frueheren",
        "haben",
        "has",
        "hatten",
        "have",
        "herausgefunden",
        "im",
        "in",
        "is",
        "ist",
        "mit",
        "noch",
        "our",
        "previous",
        "prior",
        "project",
        "projekt",
        "recherche",
        "rechercheergebnis",
        "rechercheergebnisse",
        "recherchen",
        "research",
        "result",
        "results",
        "show",
        "showed",
        "summary",
        "the",
        "to",
        "ueber",
        "und",
        "uns",
        "unser",
        "unsere",
        "unserem",
        "unseren",
        "unserer",
        "was",
        "we",
        "welche",
        "welcher",
        "welches",
        "what",
        "wir",
        "wurde",
        "wurden",
        "zu",
        "zum",
        "zur",
        "\u00fcber",
    }
)


class PriorResearchSearchError(RuntimeError):
    """Raised when durable prior Research cannot be searched safely."""


class PriorResearchContextIntegrityError(RuntimeError):
    """Raised when selected prior Research changes or is corrupt."""


@dataclass(frozen=True, slots=True)
class PriorResearchSearchResult:
    result_id: uuid.UUID
    scope_id: uuid.UUID
    final_artifact_id: uuid.UUID | None
    content_hash: bytes
    query_text: str
    text: str
    coverage_ratio: float
    created_at_us: int
    score: float


@dataclass(frozen=True, slots=True)
class PriorResearchContextItem:
    context_id: str
    result_id: uuid.UUID
    scope_id: uuid.UUID
    final_artifact_id: uuid.UUID | None
    content_hash: bytes
    query_text: str
    text: str
    coverage_ratio: float
    created_at_us: int
    score: float
    truncated: bool


@dataclass(frozen=True, slots=True)
class PriorResearchContextBundle:
    query: str
    items: tuple[PriorResearchContextItem, ...]
    omitted_count: int
    estimated_tokens: int
    max_estimated_tokens: int
    rendered_text: str


class PriorResearchSearchService:
    """Search immutable completed Research results without a routing model."""

    def __init__(
        self,
        database: SQLiteDatabase,
    ) -> None:
        self.database = database

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> tuple[PriorResearchSearchResult, ...]:
        normalized_query = query.strip()

        if not normalized_query:
            raise PriorResearchSearchError(
                "Prior Research search query must not be empty."
            )

        if not 1 <= limit <= _MAX_SEARCH_LIMIT:
            raise PriorResearchSearchError(
                "Prior Research search limit must be between 1 and 100."
            )

        query_terms = _informative_terms(
            normalized_query
        )

        # A vague request must never select an arbitrary old Research result.
        if not query_terms:
            return ()

        rows = self.database.connection.execute(
            """
            SELECT
                rr.result_id,
                rr.scope_id,
                rr.final_artifact_id,
                rr.content_json,
                rr.content_hash,
                rr.coverage_ratio,
                rr.created_at_us,
                rs.query_text
            FROM research_results AS rr
            JOIN research_scopes AS rs
              ON rs.scope_id = rr.scope_id
WHERE rs.state = 'completed'
  AND NOT EXISTS (
      SELECT 1
      FROM news_runs AS nr
      WHERE nr.research_job_id = rs.job_id
         OR nr.research_result_id = rr.result_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM news_period_runs AS npr
      WHERE npr.research_job_id = rs.job_id
         OR npr.research_result_id = rr.result_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM news_finding_assessments AS nfa
      WHERE nfa.research_result_id = rr.result_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM news_events AS ne
      WHERE ne.research_result_id = rr.result_id
  )
ORDER BY
                rr.created_at_us DESC,
                rr.result_id DESC
            LIMIT ?
            """,
            (_MAX_CANDIDATES,),
        ).fetchall()

        ranked: list[PriorResearchSearchResult] = []

        for row in rows:
            base = self._result_from_row(
                row,
                score=0.0,
            )

            candidate_tokens = _candidate_tokens(
                base.query_text,
                base.text,
            )

            matched = sum(
                1
                for term in query_terms
                if term in candidate_tokens
            )

            required = required_term_matches(
                len(query_terms)
            )

            if matched < required:
                continue

            ranked.append(
                PriorResearchSearchResult(
                    result_id=base.result_id,
                    scope_id=base.scope_id,
                    final_artifact_id=base.final_artifact_id,
                    content_hash=base.content_hash,
                    query_text=base.query_text,
                    text=base.text,
                    coverage_ratio=base.coverage_ratio,
                    created_at_us=base.created_at_us,
                    score=matched / len(query_terms),
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.score,
                -item.coverage_ratio,
                -item.created_at_us,
                item.result_id.hex,
            )
        )

        return tuple(
            ranked[:limit]
        )

    def get_result(
        self,
        result_id: uuid.UUID,
    ) -> PriorResearchSearchResult:
        row = self.database.connection.execute(
            """
            SELECT
                rr.result_id,
                rr.scope_id,
                rr.final_artifact_id,
                rr.content_json,
                rr.content_hash,
                rr.coverage_ratio,
                rr.created_at_us,
                rs.query_text
            FROM research_results AS rr
            JOIN research_scopes AS rs
              ON rs.scope_id = rr.scope_id
            WHERE rr.result_id = ?
AND rs.state = 'completed'
AND NOT EXISTS (
    SELECT 1
    FROM news_runs AS nr
    WHERE nr.research_job_id = rs.job_id
       OR nr.research_result_id = rr.result_id
)
AND NOT EXISTS (
    SELECT 1
    FROM news_period_runs AS npr
    WHERE npr.research_job_id = rs.job_id
       OR npr.research_result_id = rr.result_id
)
AND NOT EXISTS (
    SELECT 1
    FROM news_finding_assessments AS nfa
    WHERE nfa.research_result_id = rr.result_id
)
AND NOT EXISTS (
    SELECT 1
    FROM news_events AS ne
    WHERE ne.research_result_id = rr.result_id
)
            """,
            (
                uuid_to_blob(
                    result_id
                ),
            ),
        ).fetchone()

        if row is None:
            raise PriorResearchSearchError(
                "Completed Research result "
                f"{result_id} does not exist."
            )

        return self._result_from_row(
            row,
            score=0.0,
        )

    @staticmethod
    def _result_from_row(
        row: Any,
        *,
        score: float,
    ) -> PriorResearchSearchResult:
        content_json = str(
            row["content_json"]
        )

        content_hash = bytes(
            row["content_hash"]
        )

        actual_hash = hashlib.sha256(
            content_json.encode("utf-8")
        ).digest()

        if actual_hash != content_hash:
            raise PriorResearchSearchError(
                "Prior Research result content hash "
                "does not match durable content."
            )

        try:
            payload = json.loads(
                content_json
            )
        except json.JSONDecodeError as exc:
            raise PriorResearchSearchError(
                "Prior Research result contains invalid JSON."
            ) from exc

        semantic_text = _render_semantic_result(
            query_text=str(
                row["query_text"]
            ),
            payload=payload,
            coverage_ratio=float(
                row["coverage_ratio"]
            ),
        )

        final_blob = row[
            "final_artifact_id"
        ]

        return PriorResearchSearchResult(
            result_id=uuid_from_blob(
                bytes(
                    row["result_id"]
                )
            ),
            scope_id=uuid_from_blob(
                bytes(
                    row["scope_id"]
                )
            ),
            final_artifact_id=(
                None
                if final_blob is None
                else uuid_from_blob(
                    bytes(final_blob)
                )
            ),
            content_hash=content_hash,
            query_text=str(
                row["query_text"]
            ),
            text=semantic_text,
            coverage_ratio=float(
                row["coverage_ratio"]
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
            score=score,
        )


class PriorResearchContextBuilderService:
    """Build and re-verify bounded context over prior Research results."""

    def __init__(
        self,
        search: PriorResearchSearchService,
    ) -> None:
        self.search = search

    def build(
        self,
        *,
        query: str,
        results: tuple[
            PriorResearchSearchResult,
            ...
        ],
        max_estimated_tokens: int = 1200,
        max_items: int = 8,
    ) -> PriorResearchContextBundle:
        normalized_query = query.strip()

        if not normalized_query:
            raise ContextBuilderError(
                "Prior Research context query must not be empty."
            )

        if not (
            _MIN_CONTEXT_BUDGET
            <= max_estimated_tokens
            <= _MAX_CONTEXT_BUDGET
        ):
            raise ContextBuilderError(
                "Prior Research context token budget "
                "must be between 128 and 64000."
            )

        if not (
            _MIN_CONTEXT_ITEMS
            <= max_items
            <= _MAX_CONTEXT_ITEMS
        ):
            raise ContextBuilderError(
                "Prior Research context max-items "
                "must be between 1 and 100."
            )

        considered = results[
            :max_items
        ]

        omitted_count = max(
            0,
            len(results)
            - len(considered),
        )

        planned: list[
            PriorResearchContextItem
        ] = []

        for result in considered:
            self._verify_search_result(
                result
            )

            context_id = (
                f"CTX-{len(planned) + 1:03d}"
            )

            item = _context_item(
                context_id=context_id,
                result=result,
                text=result.text,
                truncated=False,
            )

            if (
                _bundle_tokens(
                    query=normalized_query,
                    items=tuple(
                        [
                            *planned,
                            item,
                        ]
                    ),
                )
                <= max_estimated_tokens
            ):
                planned.append(
                    item
                )
                continue

            if not planned:
                truncated = self._truncate_first_to_fit(
                    query=normalized_query,
                    result=result,
                    context_id=context_id,
                    budget=max_estimated_tokens,
                )

                if truncated is not None:
                    planned.append(
                        truncated
                    )

                    omitted_count += max(
                        0,
                        len(considered) - 1,
                    )
                else:
                    omitted_count += len(
                        considered
                    )

                break

            omitted_count += 1

        items = tuple(
            planned
        )

        rendered = _render_context(
            query=normalized_query,
            items=items,
        )

        estimated = estimate_tokens(
            rendered
        )

        if estimated > max_estimated_tokens:
            raise RuntimeError(
                "Prior Research Context Builder "
                "exceeded its deterministic budget."
            )

        bundle = PriorResearchContextBundle(
            query=normalized_query,
            items=items,
            omitted_count=omitted_count,
            estimated_tokens=estimated,
            max_estimated_tokens=max_estimated_tokens,
            rendered_text=rendered,
        )

        self.verify_bundle(
            bundle
        )

        return bundle

    def verify_bundle(
        self,
        bundle: PriorResearchContextBundle,
    ) -> None:
        indices: list[int] = []

        for item in bundle.items:
            match = _CONTEXT_ID_PATTERN.fullmatch(
                item.context_id
            )

            if match is None:
                raise PriorResearchContextIntegrityError(
                    "Prior Research context ID "
                    "must use CTX-NNN."
                )

            indices.append(
                int(
                    match.group(1)
                )
            )

            durable = self.search.get_result(
                item.result_id
            )

            if durable.scope_id != item.scope_id:
                raise PriorResearchContextIntegrityError(
                    "Prior Research result "
                    "changed scope identity."
                )

            if (
                durable.final_artifact_id
                != item.final_artifact_id
            ):
                raise PriorResearchContextIntegrityError(
                    "Prior Research result changed "
                    "final artifact identity."
                )

            if (
                durable.content_hash
                != item.content_hash
            ):
                raise PriorResearchContextIntegrityError(
                    "Prior Research result changed content hash."
                )

            if (
                durable.query_text
                != item.query_text
            ):
                raise PriorResearchContextIntegrityError(
                    "Prior Research result "
                    "changed its scope query."
                )

            if (
                durable.coverage_ratio
                != item.coverage_ratio
            ):
                raise PriorResearchContextIntegrityError(
                    "Prior Research result changed coverage."
                )

            if item.truncated:
                if (
                    not durable.text.startswith(
                        item.text
                    )
                    or len(item.text)
                    >= len(durable.text)
                ):
                    raise PriorResearchContextIntegrityError(
                        "Truncated Prior Research context "
                        "no longer matches durable text."
                    )
            elif durable.text != item.text:
                raise PriorResearchContextIntegrityError(
                    "Prior Research context text "
                    "changed after build."
                )

        expected_indices = list(
            range(
                1,
                len(indices) + 1,
            )
        )

        if indices != expected_indices:
            raise PriorResearchContextIntegrityError(
                "Prior Research context IDs are "
                "not contiguous from CTX-001."
            )

        rendered = _render_context(
            query=bundle.query,
            items=bundle.items,
        )

        if rendered != bundle.rendered_text:
            raise PriorResearchContextIntegrityError(
                "Rendered Prior Research context "
                "changed after build."
            )

        estimated = estimate_tokens(
            rendered
        )

        if estimated != bundle.estimated_tokens:
            raise PriorResearchContextIntegrityError(
                "Prior Research context token estimate "
                "changed after build."
            )

        if estimated > bundle.max_estimated_tokens:
            raise PriorResearchContextIntegrityError(
                "Prior Research context exceeds "
                "its deterministic budget."
            )

    def _verify_search_result(
        self,
        result: PriorResearchSearchResult,
    ) -> None:
        durable = self.search.get_result(
            result.result_id
        )

        if (
            durable.scope_id != result.scope_id
            or durable.final_artifact_id
            != result.final_artifact_id
            or durable.content_hash
            != result.content_hash
            or durable.query_text
            != result.query_text
            or durable.text
            != result.text
            or durable.coverage_ratio
            != result.coverage_ratio
            or durable.created_at_us
            != result.created_at_us
        ):
            raise PriorResearchContextIntegrityError(
                "Prior Research search result no longer "
                "matches durable storage."
            )

    def _truncate_first_to_fit(
        self,
        *,
        query: str,
        result: PriorResearchSearchResult,
        context_id: str,
        budget: int,
    ) -> PriorResearchContextItem | None:
        if len(result.text) < 2:
            return None

        low = 1
        high = len(
            result.text
        ) - 1

        best: (
            PriorResearchContextItem
            | None
        ) = None

        while low <= high:
            midpoint = (
                low + high
            ) // 2

            item = _context_item(
                context_id=context_id,
                result=result,
                text=result.text[:midpoint],
                truncated=True,
            )

            if (
                _bundle_tokens(
                    query=query,
                    items=(item,),
                )
                <= budget
            ):
                best = item
                low = midpoint + 1
            else:
                high = midpoint - 1

        return best


def _render_semantic_result(
    *,
    query_text: str,
    payload: Any,
    coverage_ratio: float,
) -> str:
    if not isinstance(
        payload,
        Mapping,
    ):
        raise PriorResearchSearchError(
            "Prior Research result JSON "
            "must be an object."
        )

    summary = payload.get(
        "summary"
    )
    findings = payload.get(
        "findings"
    )
    contradictions = payload.get(
        "contradictions"
    )
    uncertainty = payload.get(
        "uncertainty"
    )

    if (
        not isinstance(
            summary,
            str,
        )
        or not isinstance(
            uncertainty,
            str,
        )
    ):
        raise PriorResearchSearchError(
            "Prior Research result text fields are invalid."
        )

    if (
        not isinstance(
            findings,
            list,
        )
        or any(
            not isinstance(
                item,
                str,
            )
            for item in findings
        )
        or not isinstance(
            contradictions,
            list,
        )
        or any(
            not isinstance(
                item,
                str,
            )
            for item in contradictions
        )
    ):
        raise PriorResearchSearchError(
            "Prior Research result finding fields are invalid."
        )

    lines = [
        f"Research query: {query_text}",
        f"Summary: {summary}",
    ]

    lines.extend(
        f"Finding {index}: {item}"
        for index, item in enumerate(
            findings,
            start=1,
        )
    )

    lines.extend(
        f"Contradiction {index}: {item}"
        for index, item in enumerate(
            contradictions,
            start=1,
        )
    )

    lines.append(
        "Uncertainty: "
        + (
            uncertainty
            if uncertainty
            else "<none>"
        )
    )

    lines.append(
        "Coverage ratio: "
        f"{coverage_ratio:.6f}"
    )

    return "\n".join(
        lines
    )


def _informative_terms(
    value: str,
) -> tuple[str, ...]:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

    selected: list[str] = []
    seen: set[str] = set()

    for token in _TOKEN_PATTERN.findall(
        normalized
    ):
        if (
            len(token) < 2
            or token in _QUERY_STOPWORDS
        ):
            continue

        if token in seen:
            continue

        seen.add(
            token
        )
        selected.append(
            token
        )

        if len(selected) >= 12:
            break

    return tuple(
        selected
    )


def _candidate_tokens(
    *values: str,
) -> frozenset[str]:
    tokens: set[str] = set()

    for value in values:
        normalized = unicodedata.normalize(
            "NFKC",
            value,
        ).casefold()

        tokens.update(
            _TOKEN_PATTERN.findall(
                normalized
            )
        )

    return frozenset(
        tokens
    )


def _context_item(
    *,
    context_id: str,
    result: PriorResearchSearchResult,
    text: str,
    truncated: bool,
) -> PriorResearchContextItem:
    return PriorResearchContextItem(
        context_id=context_id,
        result_id=result.result_id,
        scope_id=result.scope_id,
        final_artifact_id=result.final_artifact_id,
        content_hash=result.content_hash,
        query_text=result.query_text,
        text=text,
        coverage_ratio=result.coverage_ratio,
        created_at_us=result.created_at_us,
        score=result.score,
        truncated=truncated,
    )


def _bundle_tokens(
    *,
    query: str,
    items: tuple[
        PriorResearchContextItem,
        ...
    ],
) -> int:
    return estimate_tokens(
        _render_context(
            query=query,
            items=items,
        )
    )


def _render_context(
    *,
    query: str,
    items: tuple[
        PriorResearchContextItem,
        ...
    ],
) -> str:
    payload = {
        "athena_prior_research_context_version": _CONTEXT_VERSION,
        "policy": (
            "Prior Research is a durable ATHENA synthesis "
            "from an earlier ResearchScope. Treat it as "
            "research evidence, not as Canonical Knowledge "
            "and not as a raw SourceAnchor."
        ),
        "query": query,
        "items": [
            {
                "context_id": item.context_id,
                "evidence_class": "research",
                "research_result_id": str(
                    item.result_id
                ),
                "research_scope_id": str(
                    item.scope_id
                ),
                "final_artifact_id": (
                    None
                    if item.final_artifact_id is None
                    else str(
                        item.final_artifact_id
                    )
                ),
                "content_sha256": item.content_hash.hex(),
                "research_query": item.query_text,
                "coverage_ratio": item.coverage_ratio,
                "created_at_us": item.created_at_us,
                "score": round(
                    item.score,
                    6,
                ),
                "truncated": item.truncated,
                "text": item.text,
            }
            for item in items
        ],
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )
