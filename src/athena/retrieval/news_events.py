"""Read-only lexical retrieval over durable Event-eligible ATHENA News events."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, replace
from typing import Any

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
        "aktuell",
        "aktuelle",
        "aktuellen",
        "aktuelles",
        "and",
        "are",
        "aus",
        "bei",
        "current",
        "das",
        "dem",
        "den",
        "der",
        "die",
        "do",
        "does",
        "ein",
        "eine",
        "entwicklung",
        "entwicklungen",
        "for",
        "gibt",
        "has",
        "have",
        "heute",
        "im",
        "in",
        "is",
        "ist",
        "latest",
        "meldung",
        "meldungen",
        "nachricht",
        "nachrichten",
        "neu",
        "neue",
        "neuen",
        "neues",
        "neueste",
        "neuesten",
        "news",
        "of",
        "project",
        "projekt",
        "recent",
        "schlagzeilen",
        "the",
        "to",
        "today",
        "ueber",
        "und",
        "update",
        "updates",
        "was",
        "what",
        "zu",
        "zum",
        "zur",
        "\u00fcber",
    }
)

_EVENT_SELECT = """
SELECT
    event.event_id,
    event.run_id,
    event.finding_ordinal,
    event.title,
    event.summary,
    event.categories_json,
    event.source_ids_json,
    event.contradictions_json,
    event.event_time_start,
    event.event_time_end,
    event.event_time_precision,
    event.location_text,
    event.actors_json,
    event.core_action,
    event.publication_time_min_us,
    event.publication_time_max_us,
    event.retrieval_time_min_us,
    event.retrieval_time_max_us,
    event.first_seen_us,
    event.last_updated_us,
    event.importance,
    event.relevance,
    event.novelty,
    event.source_count,
    event.independent_source_count,
    event.conflicting_source_count,
    event.created_at_us,
    run.target_date,
    run.state AS run_state,
    COALESCE(
        event.research_result_id,
        run.research_result_id
    ) AS effective_research_result_id,
    assessment.finding_sha256,
    assessment.eligibility,
    result.content_json AS research_content_json,
    result.content_hash AS research_content_hash
FROM news_events AS event
JOIN news_runs AS run
  ON run.run_id = event.run_id
JOIN news_finding_assessments AS assessment
  ON assessment.run_id = event.run_id
 AND assessment.finding_ordinal = event.finding_ordinal
 AND assessment.research_result_id = COALESCE(
        event.research_result_id,
        run.research_result_id
     )
JOIN research_results AS result
  ON result.result_id = assessment.research_result_id
WHERE assessment.eligibility = 'event'
  AND run.state IN ('completed', 'partial')
"""


class NewsEventSearchError(RuntimeError):
    """Raised when durable News events cannot be searched safely."""


class NewsEventContextIntegrityError(RuntimeError):
    """Raised when selected News evidence changes or fails verification."""


@dataclass(frozen=True, slots=True)
class NewsEventSearchResult:
    event_id: uuid.UUID
    run_id: uuid.UUID
    research_result_id: uuid.UUID
    finding_ordinal: int
    finding_hash: bytes
    source_ids: tuple[uuid.UUID, ...]
    target_date: str
    title: str
    summary: str
    categories: tuple[str, ...]
    contradictions: tuple[str, ...]
    event_time_start: str | None
    event_time_end: str | None
    event_time_precision: str
    location: str | None
    actors: tuple[str, ...]
    core_action: str | None
    publication_time_min_us: int | None
    publication_time_max_us: int | None
    retrieval_time_min_us: int | None
    retrieval_time_max_us: int | None
    first_seen_us: int
    last_updated_us: int
    importance: float
    relevance: float
    novelty: float
    source_count: int
    independent_source_count: int
    conflicting_source_count: int
    created_at_us: int
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class NewsEventContextItem:
    context_id: str
    event: NewsEventSearchResult
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class NewsEventContextBundle:
    query: str
    items: tuple[NewsEventContextItem, ...]
    omitted_count: int
    estimated_tokens: int
    max_estimated_tokens: int
    rendered_text: str


class NewsEventSearchService:
    """Search only durable findings already admitted to News event semantics."""

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
    ) -> tuple[NewsEventSearchResult, ...]:
        normalized_query = query.strip()

        if not normalized_query:
            raise NewsEventSearchError(
                "News event search query must not be empty."
            )

        if not 1 <= limit <= _MAX_SEARCH_LIMIT:
            raise NewsEventSearchError(
                "News event search limit must be between 1 and 100."
            )

        query_terms = _informative_terms(
            normalized_query
        )

        # Never turn "latest news" alone into an arbitrary event selection.
        if not query_terms:
            return ()

        rows = self.database.connection.execute(
            _EVENT_SELECT
            + """
ORDER BY
    COALESCE(
        event.publication_time_max_us,
        event.last_updated_us,
        event.created_at_us
    ) DESC,
    event.importance DESC,
    event.event_id DESC
LIMIT ?
""",
            (_MAX_CANDIDATES,),
        ).fetchall()

        ranked: list[
            NewsEventSearchResult
        ] = []

        for row in rows:
            base = self._event_from_row(
                row,
                score=0.0,
            )

            tokens = _candidate_tokens(
                base.text
            )

            matched = sum(
                1
                for term in query_terms
                if term in tokens
            )

            required = required_term_matches(
                len(query_terms)
            )

            if matched < required:
                continue

            ranked.append(
                replace(
                    base,
                    score=(
                        matched
                        / len(query_terms)
                    ),
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.score,
                -_freshness_us(item),
                -item.importance,
                -item.relevance,
                -item.novelty,
                item.event_id.hex,
            )
        )

        return tuple(
            ranked[:limit]
        )

    def get_event(
        self,
        event_id: uuid.UUID,
    ) -> NewsEventSearchResult:
        row = self.database.connection.execute(
            _EVENT_SELECT
            + """
  AND event.event_id = ?
""",
            (
                uuid_to_blob(
                    event_id
                ),
            ),
        ).fetchone()

        if row is None:
            raise NewsEventSearchError(
                "Eligible durable News event "
                f"{event_id} does not exist."
            )

        return self._event_from_row(
            row,
            score=0.0,
        )

    @staticmethod
    def _event_from_row(
        row: Any,
        *,
        score: float,
    ) -> NewsEventSearchResult:
        if str(row["eligibility"]) != "event":
            raise NewsEventSearchError(
                "News retrieval encountered a non-event finding."
            )

        if str(row["run_state"]) not in {
            "completed",
            "partial",
        }:
            raise NewsEventSearchError(
                "News event belongs to a non-readable run state."
            )

        finding_ordinal = int(
            row["finding_ordinal"]
        )

        if finding_ordinal < 0:
            raise NewsEventSearchError(
                "News event has an invalid finding ordinal."
            )

        summary = str(
            row["summary"]
        )

        finding_hash = bytes(
            row["finding_sha256"]
        )

        if len(finding_hash) != 32:
            raise NewsEventSearchError(
                "News finding hash must be SHA-256 bytes."
            )

        if (
            hashlib.sha256(
                summary.encode(
                    "utf-8"
                )
            ).digest()
            != finding_hash
        ):
            raise NewsEventSearchError(
                "News event summary no longer matches "
                "durable finding eligibility."
            )

        research_content_json = str(
            row[
                "research_content_json"
            ]
        )

        research_content_hash = bytes(
            row[
                "research_content_hash"
            ]
        )

        if (
            hashlib.sha256(
                research_content_json.encode(
                    "utf-8"
                )
            ).digest()
            != research_content_hash
        ):
            raise NewsEventSearchError(
                "News ResearchResult content hash "
                "does not match durable content."
            )

        try:
            research_payload = json.loads(
                research_content_json
            )
        except json.JSONDecodeError as exc:
            raise NewsEventSearchError(
                "News ResearchResult contains invalid JSON."
            ) from exc

        if not isinstance(
            research_payload,
            dict,
        ):
            raise NewsEventSearchError(
                "News ResearchResult payload "
                "must be an object."
            )

        findings = research_payload.get(
            "findings"
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
        ):
            raise NewsEventSearchError(
                "News ResearchResult findings are invalid."
            )

        if finding_ordinal >= len(
            findings
        ):
            raise NewsEventSearchError(
                "News event finding ordinal is outside "
                "the durable ResearchResult."
            )

        if findings[
            finding_ordinal
        ] != summary:
            raise NewsEventSearchError(
                "News event summary no longer matches "
                "its durable Research finding."
            )

        research_blob = row[
            "effective_research_result_id"
        ]

        if research_blob is None:
            raise NewsEventSearchError(
                "News event lost its ResearchResult identity."
            )

        categories = _string_list(
            row["categories_json"],
            label="categories",
        )

        contradictions = _string_list(
            row["contradictions_json"],
            label="contradictions",
        )

        actors = _string_list(
            row["actors_json"],
            label="actors",
        )

        source_ids = _uuid_list(
            row["source_ids_json"]
        )

        result = NewsEventSearchResult(
            event_id=uuid_from_blob(
                bytes(
                    row["event_id"]
                )
            ),
            run_id=uuid_from_blob(
                bytes(
                    row["run_id"]
                )
            ),
            research_result_id=uuid_from_blob(
                bytes(
                    research_blob
                )
            ),
            finding_ordinal=(
                finding_ordinal
            ),
            finding_hash=finding_hash,
            source_ids=source_ids,
            target_date=str(
                row["target_date"]
            ),
            title=str(
                row["title"]
            ),
            summary=summary,
            categories=categories,
            contradictions=contradictions,
            event_time_start=_optional_str(
                row[
                    "event_time_start"
                ]
            ),
            event_time_end=_optional_str(
                row[
                    "event_time_end"
                ]
            ),
            event_time_precision=str(
                row[
                    "event_time_precision"
                ]
            ),
            location=_optional_str(
                row[
                    "location_text"
                ]
            ),
            actors=actors,
            core_action=_optional_str(
                row[
                    "core_action"
                ]
            ),
            publication_time_min_us=_optional_int(
                row[
                    "publication_time_min_us"
                ]
            ),
            publication_time_max_us=_optional_int(
                row[
                    "publication_time_max_us"
                ]
            ),
            retrieval_time_min_us=_optional_int(
                row[
                    "retrieval_time_min_us"
                ]
            ),
            retrieval_time_max_us=_optional_int(
                row[
                    "retrieval_time_max_us"
                ]
            ),
            first_seen_us=int(
                row["first_seen_us"]
            ),
            last_updated_us=int(
                row["last_updated_us"]
            ),
            importance=float(
                row["importance"]
            ),
            relevance=float(
                row["relevance"]
            ),
            novelty=float(
                row["novelty"]
            ),
            source_count=int(
                row["source_count"]
            ),
            independent_source_count=int(
                row[
                    "independent_source_count"
                ]
            ),
            conflicting_source_count=int(
                row[
                    "conflicting_source_count"
                ]
            ),
            created_at_us=int(
                row["created_at_us"]
            ),
            text="",
            score=score,
        )

        return replace(
            result,
            text=_render_event_text(
                result
            ),
        )


class NewsEventContextBuilderService:
    """Build and re-verify bounded context over durable News events."""

    def __init__(
        self,
        search: NewsEventSearchService,
    ) -> None:
        self.search = search

    def build(
        self,
        *,
        query: str,
        results: tuple[
            NewsEventSearchResult,
            ...
        ],
        max_estimated_tokens: int = 1200,
        max_items: int = 8,
    ) -> NewsEventContextBundle:
        normalized_query = query.strip()

        if not normalized_query:
            raise ContextBuilderError(
                "News event context query must not be empty."
            )

        if not (
            _MIN_CONTEXT_BUDGET
            <= max_estimated_tokens
            <= _MAX_CONTEXT_BUDGET
        ):
            raise ContextBuilderError(
                "News event context token budget "
                "must be between 128 and 64000."
            )

        if not (
            _MIN_CONTEXT_ITEMS
            <= max_items
            <= _MAX_CONTEXT_ITEMS
        ):
            raise ContextBuilderError(
                "News event context max-items "
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
            NewsEventContextItem
        ] = []

        for event in considered:
            self._verify_search_result(
                event
            )

            context_id = (
                f"CTX-{len(planned) + 1:03d}"
            )

            item = NewsEventContextItem(
                context_id=context_id,
                event=event,
                text=event.text,
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
                    event=event,
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
                "News Event Context Builder "
                "exceeded its deterministic budget."
            )

        bundle = NewsEventContextBundle(
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
        bundle: NewsEventContextBundle,
    ) -> None:
        indices: list[int] = []

        for item in bundle.items:
            match = _CONTEXT_ID_PATTERN.fullmatch(
                item.context_id
            )

            if match is None:
                raise NewsEventContextIntegrityError(
                    "News context ID must use CTX-NNN."
                )

            indices.append(
                int(
                    match.group(1)
                )
            )

            durable = self.search.get_event(
                item.event.event_id
            )

            if not _same_durable_event(
                durable,
                item.event,
            ):
                raise NewsEventContextIntegrityError(
                    "News event changed after context selection."
                )

            if item.truncated:
                if (
                    not durable.text.startswith(
                        item.text
                    )
                    or len(item.text)
                    >= len(durable.text)
                ):
                    raise NewsEventContextIntegrityError(
                        "Truncated News context no longer "
                        "matches durable event text."
                    )
            elif durable.text != item.text:
                raise NewsEventContextIntegrityError(
                    "News context text changed after build."
                )

        expected_indices = list(
            range(
                1,
                len(indices) + 1,
            )
        )

        if indices != expected_indices:
            raise NewsEventContextIntegrityError(
                "News context IDs are not contiguous "
                "from CTX-001."
            )

        rendered = _render_context(
            query=bundle.query,
            items=bundle.items,
        )

        if rendered != bundle.rendered_text:
            raise NewsEventContextIntegrityError(
                "Rendered News context changed after build."
            )

        estimated = estimate_tokens(
            rendered
        )

        if estimated != bundle.estimated_tokens:
            raise NewsEventContextIntegrityError(
                "News context token estimate changed."
            )

        if estimated > bundle.max_estimated_tokens:
            raise NewsEventContextIntegrityError(
                "News context exceeds its deterministic budget."
            )

    def _verify_search_result(
        self,
        event: NewsEventSearchResult,
    ) -> None:
        durable = self.search.get_event(
            event.event_id
        )

        if not _same_durable_event(
            durable,
            event,
        ):
            raise NewsEventContextIntegrityError(
                "News search result no longer "
                "matches durable storage."
            )

    def _truncate_first_to_fit(
        self,
        *,
        query: str,
        event: NewsEventSearchResult,
        context_id: str,
        budget: int,
    ) -> NewsEventContextItem | None:
        if len(event.text) < 2:
            return None

        low = 1
        high = len(
            event.text
        ) - 1

        best: (
            NewsEventContextItem
            | None
        ) = None

        while low <= high:
            midpoint = (
                low + high
            ) // 2

            item = NewsEventContextItem(
                context_id=context_id,
                event=event,
                text=event.text[
                    :midpoint
                ],
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


def _same_durable_event(
    left: NewsEventSearchResult,
    right: NewsEventSearchResult,
) -> bool:
    return (
        replace(
            left,
            score=0.0,
        )
        == replace(
            right,
            score=0.0,
        )
    )


def _render_event_text(
    event: NewsEventSearchResult,
) -> str:
    lines = [
        f"News date: {event.target_date}",
        f"Title: {event.title}",
        f"Summary: {event.summary}",
        (
            "Event time: "
            f"{event.event_time_start or '<unknown>'}"
            f" to "
            f"{event.event_time_end or '<none>'}"
            f" ({event.event_time_precision})"
        ),
        (
            "Location: "
            f"{event.location or '<unknown>'}"
        ),
        (
            "Actors: "
            + (
                ", ".join(
                    event.actors
                )
                if event.actors
                else "<none>"
            )
        ),
        (
            "Core action: "
            f"{event.core_action or '<unknown>'}"
        ),
        (
            "Categories: "
            + (
                ", ".join(
                    event.categories
                )
                if event.categories
                else "<none>"
            )
        ),
    ]

    lines.extend(
        f"Contradiction {index}: {text}"
        for index, text in enumerate(
            event.contradictions,
            start=1,
        )
    )

    lines.extend(
        [
            (
                "Publication time range us: "
                f"{event.publication_time_min_us}"
                f" to "
                f"{event.publication_time_max_us}"
            ),
            (
                "Retrieval time range us: "
                f"{event.retrieval_time_min_us}"
                f" to "
                f"{event.retrieval_time_max_us}"
            ),
            (
                "Source metrics: "
                f"total={event.source_count} "
                f"independent={event.independent_source_count} "
                f"conflicting={event.conflicting_source_count}"
            ),
            (
                "Source IDs: "
                + (
                    ", ".join(
                        str(
                            source_id
                        )
                        for source_id
                        in event.source_ids
                    )
                    if event.source_ids
                    else "<none>"
                )
            ),
        ]
    )

    return "\n".join(
        lines
    )


def _render_context(
    *,
    query: str,
    items: tuple[
        NewsEventContextItem,
        ...
    ],
) -> str:
    payload = {
        "athena_news_event_context_version": (
            _CONTEXT_VERSION
        ),
        "policy": (
            "News evidence is a durable ATHENA News event "
            "admitted by Event Eligibility from external-source "
            "research. It is not Canonical Knowledge, not a raw "
            "SourceAnchor, and not generic Prior Research."
        ),
        "query": query,
        "items": [
            {
                "context_id": (
                    item.context_id
                ),
                "evidence_class": "news",
                "news_event_id": str(
                    item.event.event_id
                ),
                "news_run_id": str(
                    item.event.run_id
                ),
                "research_result_id": str(
                    item.event.research_result_id
                ),
                "finding_ordinal": (
                    item.event.finding_ordinal
                ),
                "finding_sha256": (
                    item.event.finding_hash.hex()
                ),
                "source_ids": [
                    str(
                        source_id
                    )
                    for source_id
                    in item.event.source_ids
                ],
                "target_date": (
                    item.event.target_date
                ),
                "importance": (
                    item.event.importance
                ),
                "relevance": (
                    item.event.relevance
                ),
                "novelty": (
                    item.event.novelty
                ),
                "score": round(
                    item.event.score,
                    6,
                ),
                "truncated": (
                    item.truncated
                ),
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


def _bundle_tokens(
    *,
    query: str,
    items: tuple[
        NewsEventContextItem,
        ...
    ],
) -> int:
    return estimate_tokens(
        _render_context(
            query=query,
            items=items,
        )
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
            or token
            in _QUERY_STOPWORDS
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
    value: str,
) -> frozenset[str]:
    normalized = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

    return frozenset(
        _TOKEN_PATTERN.findall(
            normalized
        )
    )


def _string_list(
    raw: object,
    *,
    label: str,
) -> tuple[str, ...]:
    try:
        parsed = json.loads(
            str(raw)
        )
    except json.JSONDecodeError as exc:
        raise NewsEventSearchError(
            f"News event {label} JSON is invalid."
        ) from exc

    if (
        not isinstance(
            parsed,
            list,
        )
        or any(
            not isinstance(
                item,
                str,
            )
            for item in parsed
        )
    ):
        raise NewsEventSearchError(
            f"News event {label} must be a string list."
        )

    return tuple(
        parsed
    )


def _uuid_list(
    raw: object,
) -> tuple[uuid.UUID, ...]:
    values = _string_list(
        raw,
        label="source IDs",
    )

    try:
        parsed = tuple(
            uuid.UUID(
                value
            )
            for value in values
        )
    except ValueError as exc:
        raise NewsEventSearchError(
            "News event source IDs contain an invalid UUID."
        ) from exc

    if len(
        set(
            parsed
        )
    ) != len(
        parsed
    ):
        raise NewsEventSearchError(
            "News event source IDs contain duplicates."
        )

    return parsed


def _optional_str(
    value: object,
) -> str | None:
    if value is None:
        return None

    result = str(
        value
    ).strip()

    return result or None


def _optional_int(
    value: object,
) -> int | None:
    if value is None:
        return None

    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
    ):
        raise NewsEventSearchError(
            "News event timestamp must be "
            "an integer or null."
        )

    return value

def _freshness_us(
    event: NewsEventSearchResult,
) -> int:
    return max(
        event.publication_time_max_us
        or 0,
        event.last_updated_us,
        event.created_at_us,
    )
