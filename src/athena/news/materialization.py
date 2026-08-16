"""Research-result to derived News event/digest materialization."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Iterable

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.models import JobRecord
from athena.news.common import (
    _canonical_json,
    _default_profile_id,
    _event_title,
    _event_tokens,
    _json_object,
    _normalize_text,
    _string_list,
)
from athena.news.context import NewsMixinContext
from athena.news.event_structuring import NewsEventMetadata
from athena.news.models import NewsError
from athena.research.models import (
    ResearchResultRecord,
    ResearchScopeState,
)


class NewsMaterializationMixin(NewsMixinContext):
    def _materialize_research(
        self,
        run: Any,
        research_job_id: uuid.UUID,
        *,
        parent_job: JobRecord | None = None,
    ) -> None:
        scope = self.app.research_repository.get_scope_for_job(
            research_job_id
        )
        if (
            scope is None
            or scope.state is not ResearchScopeState.COMPLETED
        ):
            raise NewsError(
                "Completed research job has no completed ResearchScope."
            )

        result = self.app.research_repository.get_result_for_scope(
            scope.scope_id
        )
        if result is None:
            raise NewsError(
                "Completed News research has no ResearchResult."
            )

        content = _json_object(result.content_json)
        findings = _string_list(content.get("findings"))
        contradictions = _string_list(
            content.get("contradictions")
        )

        existing = self.database.connection.execute(
            """
            SELECT *
            FROM news_events
            WHERE run_id = ?
            ORDER BY event_ordinal
            """,
            (run["run_id"],),
        ).fetchall()

        assessments = self._load_finding_assessments(
            run,
            result,
            tuple(findings),
        )

        # Compatibility path for events created before the v30
        # eligibility schema. Historical ATHENA materialized every
        # Research finding as an event, so that original decision can
        # be preserved deterministically without another model call.
        if not assessments and existing:
            assessments = self._legacy_assessments_from_events(
                existing,
                tuple(findings),
            )
            self._persist_finding_assessments(
                run,
                result,
                tuple(findings),
                assessments,
            )

        if not assessments and findings:
            assessments = self._structure_event_metadata(
                run=run,
                scope=scope,
                result=result,
                findings=tuple(findings),
                parent_job=parent_job,
            )
            self._persist_finding_assessments(
                run,
                result,
                tuple(findings),
                assessments,
            )

        if len(assessments) != len(findings):
            raise NewsError(
                "Persisted News finding assessments disagree "
                "with completed Research findings."
            )

        assessment_by_ordinal = {
            item.finding_ordinal: item
            for item in assessments
        }

        if set(assessment_by_ordinal) != set(
            range(len(findings))
        ):
            raise NewsError(
                "News finding assessments lost or duplicated "
                "a Research finding ordinal."
            )

        eligible_ordinals = [
            ordinal
            for ordinal in range(len(findings))
            if assessment_by_ordinal[ordinal].eligibility
            == "event"
        ]

        if existing:
            event_ordinals = [
                int(row["event_ordinal"])
                for row in existing
            ]
            finding_ordinals = [
                int(row["finding_ordinal"])
                for row in existing
            ]

            if event_ordinals != list(
                range(len(existing))
            ):
                raise NewsError(
                    "Persisted News event ordering is invalid."
                )

            if finding_ordinals != eligible_ordinals:
                raise NewsError(
                    "Persisted News events disagree with "
                    "durable finding eligibility."
                )

        elif eligible_ordinals:
            prepared: list[tuple[object, ...]] = []
            cluster_keys: set[bytes] = set()
            now = utc_now_us()

            for event_ordinal, finding_ordinal in enumerate(
                eligible_ordinals
            ):
                finding = findings[finding_ordinal]
                item = assessment_by_ordinal[finding_ordinal]

                source_ids = self._finding_source_ids(
                    result.final_artifact_id,
                    finding_ordinal,
                )

                cluster_key = hashlib.sha256(
                    _normalize_text(finding).encode("utf-8")
                ).digest()

                if cluster_key in cluster_keys:
                    raise NewsError(
                        "Research produced duplicate event findings "
                        "instead of one cluster."
                    )

                cluster_keys.add(cluster_key)

                related_contradictions = [
                    text
                    for index, text in enumerate(
                        contradictions
                    )
                    if set(source_ids).intersection(
                        self._contradiction_source_ids(
                            result.final_artifact_id,
                            index,
                        )
                    )
                ]

                title = _event_title(finding)

                categories = (
                    self._categories_for_article_sources(
                        run["run_id"],
                        source_ids,
                    )
                )

                (
                    source_count,
                    independent_count,
                    relevance,
                ) = self._event_source_metrics(
                    run["run_id"],
                    source_ids,
                )

                (
                    novelty,
                    first_seen,
                ) = self._event_novelty_and_first_seen(
                    run["run_id"],
                    title=title,
                    summary=finding,
                    categories=categories,
                    now_us=now,
                )

                source_id_set = set(source_ids)

                conflicting_ids = {
                    source_id
                    for index, _text in enumerate(
                        contradictions
                    )
                    for source_id in (
                        self._contradiction_source_ids(
                            result.final_artifact_id,
                            index,
                        )
                    )
                    if source_id in source_id_set
                }

                breadth = min(
                    1.0,
                    independent_count / 3.0,
                )

                importance = round(
                    min(
                        1.0,
                        0.50 * relevance
                        + 0.30 * novelty
                        + 0.20 * breadth,
                    ),
                    6,
                )

                prepared.append(
                    (
                        uuid_to_blob(new_uuid7()),
                        run["run_id"],
                        event_ordinal,
                        finding_ordinal,
                        cluster_key,
                        title,
                        finding,
                        _canonical_json(categories),
                        _canonical_json(
                            [
                                str(value)
                                for value in source_ids
                            ]
                        ),
                        _canonical_json(
                            related_contradictions
                        ),
                        item.event_time_start,
                        item.event_time_end,
                        item.event_time_precision,
                        item.location,
                        _canonical_json(
                            list(item.actors)
                        ),
                        item.core_action,
                        item.publication_time_min_us,
                        item.publication_time_max_us,
                        item.retrieval_time_min_us,
                        item.retrieval_time_max_us,
                        (
                            uuid_to_blob(
                                item.structuring_run_id
                            )
                            if item.structuring_run_id
                            is not None
                            else None
                        ),
                        first_seen,
                        now,
                        importance,
                        relevance,
                        novelty,
                        source_count,
                        independent_count,
                        len(conflicting_ids),
                        uuid_to_blob(research_job_id),
                        uuid_to_blob(result.result_id),
                        now,
                    )
                )

            event_insert_sql = (
                """
                INSERT INTO news_events (
                    event_id,
                    run_id,
                    event_ordinal,
                    finding_ordinal,
                    cluster_key,
                    title,
                    summary,
                    categories_json,
                    source_ids_json,
                    contradictions_json,
                    event_time_start,
                    event_time_end,
                    event_time_precision,
                    location_text,
                    actors_json,
                    core_action,
                    publication_time_min_us,
                    publication_time_max_us,
                    retrieval_time_min_us,
                    retrieval_time_max_us,
                    structuring_run_id,
                    first_seen_us,
                    last_updated_us,
                    importance,
                    relevance,
                    novelty,
                    source_count,
                    independent_source_count,
                    conflicting_source_count,
                    research_job_id,
                    research_result_id,
                    created_at_us
                ) VALUES (
                """
                + ",".join("?" for _ in range(32))
                + ")"
            )

            with self.database.write_transaction() as connection:
                connection.executemany(
                    event_insert_sql,
                    prepared,
                )

            existing = self.database.connection.execute(
                """
                SELECT *
                FROM news_events
                WHERE run_id = ?
                ORDER BY event_ordinal
                """,
                (run["run_id"],),
            ).fetchall()

        context_findings: list[dict[str, Any]] = []

        for item in assessments:
            if item.eligibility != "context":
                continue

            source_ids = self._finding_source_ids(
                result.final_artifact_id,
                item.finding_ordinal,
            )

            context_findings.append(
                {
                    "finding_ordinal": (
                        item.finding_ordinal
                    ),
                    "text": findings[
                        item.finding_ordinal
                    ],
                    "eligibility_reason": (
                        item.eligibility_reason
                    ),
                    "source_ids": [
                        str(source_id)
                        for source_id in source_ids
                    ],
                }
            )

        events: list[dict[str, Any]] = []

        for row in existing:
            self._ensure_event_members(row)

            persisted_event_id = uuid_from_blob(
                bytes(row["event_id"])
            )

            categories = _string_list(
                json.loads(
                    str(row["categories_json"])
                )
            )

            related_event_ids = self._suggest_event_links(
                run["run_id"],
                persisted_event_id,
                title=str(row["title"]),
                summary=str(row["summary"]),
                categories=list(categories),
            )

            events.append(
                self._event_digest_payload(
                    row,
                    possible_continuations=(
                        related_event_ids
                    ),
                )
            )

        events.sort(
            key=lambda event: (
                -float(event["importance"]),
                -float(event["relevance"]),
                -float(event["novelty"]),
                str(event["title"]),
                str(event["event_id"]),
            )
        )

        digest_id = new_uuid7()

        category_index: dict[
            str,
            list[str],
        ] = {}

        for event in events:
            for category in event["categories"]:
                category_index.setdefault(
                    str(category),
                    [],
                ).append(
                    str(event["event_id"])
                )

        digest_content = {
            "summary": str(
                content.get("summary", "")
            ),
            "events": events,
            "context_findings": context_findings,
            "event_eligibility": {
                "assessed_finding_count": (
                    len(assessments)
                ),
                "event_count": len(
                    eligible_ordinals
                ),
                "context_count": len(
                    context_findings
                ),
            },
            "events_by_category": category_index,
            "developments_since_previous_digest": [
                str(event["event_id"])
                for event in events
                if event["possible_continuations"]
            ],
            "contradictions": contradictions,
            "uncertainty": str(
                content.get("uncertainty", "")
            ),
            "coverage": content.get(
                "coverage",
                {},
            ),
            "problem_sources": content.get(
                "problem_sources",
                [],
            ),
            "research_result_id": str(
                result.result_id
            ),
            "research_status": {
                "job_id": str(
                    research_job_id
                ),
                "result_id": str(
                    result.result_id
                ),
                "state": "completed",
            },
            "canonical_knowledge_written": False,
        }

        now = utc_now_us()

        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO news_digests (
                    digest_id,
                    profile_id,
                    period_kind,
                    period_start,
                    period_end,
                    revision_no,
                    content_json,
                    research_result_ids_json,
                    created_at_us
                ) VALUES (?, ?, 'daily', ?, ?, 1, ?, ?, ?)
                """,
                (
                    uuid_to_blob(digest_id),
                    run["profile_id"],
                    run["target_date"],
                    run["target_date"],
                    _canonical_json(
                        digest_content
                    ),
                    _canonical_json(
                        [str(result.result_id)]
                    ),
                    now,
                ),
            )

            final_state = (
                "partial"
                if int(run["failed_count"]) > 0
                else "completed"
            )

            connection.executemany(
                """
                INSERT INTO news_digest_items(
                    digest_id,
                    rank_no,
                    event_id,
                    importance,
                    relevance,
                    novelty
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        uuid_to_blob(digest_id),
                        rank_no,
                        uuid_to_blob(
                            uuid.UUID(
                                str(
                                    event["event_id"]
                                )
                            )
                        ),
                        float(event["importance"]),
                        float(event["relevance"]),
                        float(event["novelty"]),
                    )
                    for rank_no, event in enumerate(
                        events,
                        start=1,
                    )
                ],
            )

            connection.execute(
                """
                UPDATE news_runs
                SET state = ?,
                    research_result_id = ?,
                    digest_id = ?,
                    completed_at_us = ?,
                    updated_at_us = ?
                WHERE run_id = ?
                """,
                (
                    final_state,
                    uuid_to_blob(
                        result.result_id
                    ),
                    uuid_to_blob(digest_id),
                    now,
                    now,
                    run["run_id"],
                ),
            )

    def _load_finding_assessments(
        self,
        run: Any,
        result: ResearchResultRecord,
        findings: tuple[str, ...],
    ) -> tuple[NewsEventMetadata, ...]:
        rows = self.database.connection.execute(
            """
            SELECT *
            FROM news_finding_assessments
            WHERE run_id = ?
            ORDER BY finding_ordinal
            """,
            (run["run_id"],),
        ).fetchall()

        if not rows:
            return ()

        if len(rows) != len(findings):
            raise NewsError(
                "Persisted News finding assessments are incomplete."
            )

        output: list[NewsEventMetadata] = []

        for expected_ordinal, row in enumerate(rows):
            ordinal = int(
                row["finding_ordinal"]
            )

            if ordinal != expected_ordinal:
                raise NewsError(
                    "Persisted News finding assessment "
                    "ordinals are not contiguous."
                )

            persisted_result_id = uuid_from_blob(
                bytes(row["research_result_id"])
            )

            if persisted_result_id != result.result_id:
                raise NewsError(
                    "Persisted News finding assessment "
                    "references another ResearchResult."
                )

            expected_hash = hashlib.sha256(
                findings[ordinal].encode("utf-8")
            ).digest()

            if bytes(row["finding_sha256"]) != expected_hash:
                raise NewsError(
                    "Persisted News finding assessment "
                    "does not match immutable finding text."
                )

            output.append(
                NewsEventMetadata(
                    finding_ordinal=ordinal,
                    event_time_start=(
                        str(row["event_time_start"])
                        if row["event_time_start"]
                        is not None
                        else None
                    ),
                    event_time_end=(
                        str(row["event_time_end"])
                        if row["event_time_end"]
                        is not None
                        else None
                    ),
                    event_time_precision=str(
                        row["event_time_precision"]
                    ),
                    location=(
                        str(row["location_text"])
                        if row["location_text"]
                        is not None
                        else None
                    ),
                    actors=tuple(
                        _string_list(
                            json.loads(
                                str(
                                    row[
                                        "actors_json"
                                    ]
                                )
                            )
                        )
                    ),
                    core_action=(
                        str(row["core_action"])
                        if row["core_action"]
                        is not None
                        else None
                    ),
                    publication_time_min_us=(
                        int(
                            row[
                                "publication_time_min_us"
                            ]
                        )
                        if row[
                            "publication_time_min_us"
                        ]
                        is not None
                        else None
                    ),
                    publication_time_max_us=(
                        int(
                            row[
                                "publication_time_max_us"
                            ]
                        )
                        if row[
                            "publication_time_max_us"
                        ]
                        is not None
                        else None
                    ),
                    retrieval_time_min_us=(
                        int(
                            row[
                                "retrieval_time_min_us"
                            ]
                        )
                        if row[
                            "retrieval_time_min_us"
                        ]
                        is not None
                        else None
                    ),
                    retrieval_time_max_us=(
                        int(
                            row[
                                "retrieval_time_max_us"
                            ]
                        )
                        if row[
                            "retrieval_time_max_us"
                        ]
                        is not None
                        else None
                    ),
                    structuring_run_id=(
                        uuid_from_blob(
                            bytes(
                                row[
                                    "structuring_run_id"
                                ]
                            )
                        )
                        if row[
                            "structuring_run_id"
                        ]
                        is not None
                        else None
                    ),
                    eligibility=str(
                        row["eligibility"]
                    ),
                    eligibility_reason=str(
                        row["eligibility_reason"]
                    ),
                )
            )

        return tuple(output)

    def _persist_finding_assessments(
        self,
        run: Any,
        result: ResearchResultRecord,
        findings: tuple[str, ...],
        assessments: tuple[
            NewsEventMetadata,
            ...,
        ],
    ) -> None:
        if len(assessments) != len(findings):
            raise NewsError(
                "News finding assessment count does not "
                "match Research findings."
            )

        ordinals = [
            item.finding_ordinal
            for item in assessments
        ]

        if ordinals != list(
            range(len(findings))
        ):
            raise NewsError(
                "News finding assessments must preserve "
                "all Research finding ordinals."
            )

        now = utc_now_us()

        rows: list[tuple[object, ...]] = []

        for item in assessments:
            finding = findings[
                item.finding_ordinal
            ]

            rows.append(
                (
                    run["run_id"],
                    uuid_to_blob(
                        result.result_id
                    ),
                    item.finding_ordinal,
                    hashlib.sha256(
                        finding.encode("utf-8")
                    ).digest(),
                    item.eligibility,
                    item.eligibility_reason,
                    item.event_time_start,
                    item.event_time_end,
                    item.event_time_precision,
                    item.location,
                    _canonical_json(
                        list(item.actors)
                    ),
                    item.core_action,
                    item.publication_time_min_us,
                    item.publication_time_max_us,
                    item.retrieval_time_min_us,
                    item.retrieval_time_max_us,
                    (
                        uuid_to_blob(
                            item.structuring_run_id
                        )
                        if item.structuring_run_id
                        is not None
                        else None
                    ),
                    now,
                )
            )

        sql = (
            """
            INSERT INTO news_finding_assessments (
                run_id,
                research_result_id,
                finding_ordinal,
                finding_sha256,
                eligibility,
                eligibility_reason,
                event_time_start,
                event_time_end,
                event_time_precision,
                location_text,
                actors_json,
                core_action,
                publication_time_min_us,
                publication_time_max_us,
                retrieval_time_min_us,
                retrieval_time_max_us,
                structuring_run_id,
                created_at_us
            ) VALUES (
            """
            + ",".join("?" for _ in range(18))
            + ")"
        )

        with self.database.write_transaction() as connection:
            connection.executemany(
                sql,
                rows,
            )

    def _legacy_assessments_from_events(
        self,
        rows: list[Any],
        findings: tuple[str, ...],
    ) -> tuple[NewsEventMetadata, ...]:
        if len(rows) != len(findings):
            raise NewsError(
                "Legacy News events cannot be mapped "
                "safely to Research findings."
            )

        output: list[NewsEventMetadata] = []

        for ordinal, row in enumerate(rows):
            if (
                int(row["event_ordinal"])
                != ordinal
                or int(row["finding_ordinal"])
                != ordinal
                or str(row["summary"])
                != findings[ordinal]
            ):
                raise NewsError(
                    "Legacy News event/finding identity "
                    "cannot be recovered safely."
                )

            output.append(
                NewsEventMetadata(
                    finding_ordinal=ordinal,
                    event_time_start=(
                        str(row["event_time_start"])
                        if row["event_time_start"]
                        is not None
                        else None
                    ),
                    event_time_end=(
                        str(row["event_time_end"])
                        if row["event_time_end"]
                        is not None
                        else None
                    ),
                    event_time_precision=str(
                        row["event_time_precision"]
                    ),
                    location=(
                        str(row["location_text"])
                        if row["location_text"]
                        is not None
                        else None
                    ),
                    actors=tuple(
                        _string_list(
                            json.loads(
                                str(
                                    row[
                                        "actors_json"
                                    ]
                                )
                            )
                        )
                    ),
                    core_action=(
                        str(row["core_action"])
                        if row["core_action"]
                        is not None
                        else None
                    ),
                    publication_time_min_us=(
                        int(
                            row[
                                "publication_time_min_us"
                            ]
                        )
                        if row[
                            "publication_time_min_us"
                        ]
                        is not None
                        else None
                    ),
                    publication_time_max_us=(
                        int(
                            row[
                                "publication_time_max_us"
                            ]
                        )
                        if row[
                            "publication_time_max_us"
                        ]
                        is not None
                        else None
                    ),
                    retrieval_time_min_us=(
                        int(
                            row[
                                "retrieval_time_min_us"
                            ]
                        )
                        if row[
                            "retrieval_time_min_us"
                        ]
                        is not None
                        else None
                    ),
                    retrieval_time_max_us=(
                        int(
                            row[
                                "retrieval_time_max_us"
                            ]
                        )
                        if row[
                            "retrieval_time_max_us"
                        ]
                        is not None
                        else None
                    ),
                    structuring_run_id=(
                        uuid_from_blob(
                            bytes(
                                row[
                                    "structuring_run_id"
                                ]
                            )
                        )
                        if row[
                            "structuring_run_id"
                        ]
                        is not None
                        else None
                    ),
                    eligibility="event",
                    eligibility_reason=(
                        "current_development"
                    ),
                )
            )

        return tuple(output)

    def _event_digest_payload(
        self,
        row: Any,
        *,
        possible_continuations: tuple[uuid.UUID, ...],
    ) -> dict[str, Any]:
        return {
            "event_id": str(uuid_from_blob(bytes(row["event_id"]))),
            "finding_ordinal": int(row["finding_ordinal"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "categories": list(_string_list(json.loads(str(row["categories_json"])))),
            "source_ids": list(_string_list(json.loads(str(row["source_ids_json"])))),
            "contradictions": list(
                _string_list(json.loads(str(row["contradictions_json"])))
            ),
            "event_time": {
                "start": (
                    str(row["event_time_start"])
                    if row["event_time_start"] is not None
                    else None
                ),
                "end": (
                    str(row["event_time_end"])
                    if row["event_time_end"] is not None
                    else None
                ),
                "precision": str(row["event_time_precision"]),
            },
            "publication_time_window_us": {
                "start": (
                    int(row["publication_time_min_us"])
                    if row["publication_time_min_us"] is not None
                    else None
                ),
                "end": (
                    int(row["publication_time_max_us"])
                    if row["publication_time_max_us"] is not None
                    else None
                ),
            },
            "retrieval_time_window_us": {
                "start": (
                    int(row["retrieval_time_min_us"])
                    if row["retrieval_time_min_us"] is not None
                    else None
                ),
                "end": (
                    int(row["retrieval_time_max_us"])
                    if row["retrieval_time_max_us"] is not None
                    else None
                ),
            },
            "location": (
                str(row["location_text"]) if row["location_text"] is not None else None
            ),
            "actors": list(_string_list(json.loads(str(row["actors_json"])))),
            "core_action": (
                str(row["core_action"]) if row["core_action"] is not None else None
            ),
            "event_structuring_run_id": (
                str(uuid_from_blob(bytes(row["structuring_run_id"])))
                if row["structuring_run_id"] is not None
                else None
            ),
            "importance": float(row["importance"]),
            "relevance": float(row["relevance"]),
            "novelty": float(row["novelty"]),
            "source_count": int(row["source_count"]),
            "independent_source_count": int(row["independent_source_count"]),
            "conflicting_source_count": int(row["conflicting_source_count"]),
            "first_seen_us": int(row["first_seen_us"]) if row["first_seen_us"] is not None else None,
            "last_updated_us": int(row["last_updated_us"]) if row["last_updated_us"] is not None else None,
            "research_job_id": str(uuid_from_blob(bytes(row["research_job_id"]))) if row["research_job_id"] is not None else None,
            "research_result_id": str(uuid_from_blob(bytes(row["research_result_id"]))) if row["research_result_id"] is not None else None,
            "possible_continuations": [str(value) for value in possible_continuations],
        }

    def _ensure_event_members(self, row: Any) -> None:
        event_id=bytes(row["event_id"])
        source_ids=_string_list(json.loads(str(row["source_ids_json"])))
        with self.database.write_transaction() as connection:
            for source_id in source_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO news_event_members(event_id,source_id,membership_kind) VALUES (?,?,'supporting')",
                    (event_id, uuid_to_blob(uuid.UUID(source_id))),
                )

    def _event_source_metrics(
        self, run_id: bytes, source_ids: Iterable[uuid.UUID]
    ) -> tuple[int, int, float]:
        ids=tuple(source_ids)
        if not ids:
            return 0, 0, 0.0
        placeholders=','.join('?' for _ in ids)
        rows=self.database.connection.execute(
            f"""
            SELECT DISTINCT source.independence_group, source.priority, discovery.article_source_id
            FROM news_discoveries AS discovery
            JOIN news_sources AS source ON source.news_source_id=discovery.news_source_id
            WHERE discovery.run_id=? AND discovery.article_source_id IN ({placeholders})
              AND discovery.dedup_state='unique'
            """, (run_id, *(uuid_to_blob(item) for item in ids))
        ).fetchall()
        source_count=len({bytes(row["article_source_id"]) for row in rows})
        independent_count=len({str(row["independence_group"]) for row in rows})
        priority_score=(sum(int(row["priority"]) for row in rows)/(100.0*len(rows))) if rows else 0.0
        relevance=round(min(1.0, 0.65*priority_score + 0.35*min(1.0,independent_count/3.0)), 6)
        return source_count, independent_count, relevance

    def _event_novelty_and_first_seen(
        self, run_id: bytes, *, title: str, summary: str, categories: list[str], now_us: int
    ) -> tuple[float, int]:
        tokens=_event_tokens(title+' '+summary)
        if not tokens:
            return 1.0, now_us
        current_categories=set(categories)
        rows=self.database.connection.execute(
            """
            SELECT event.title,event.summary,event.categories_json,event.first_seen_us,event.created_at_us
            FROM news_events AS event
            JOIN news_runs AS previous_run ON previous_run.run_id=event.run_id
            JOIN news_runs AS current_run ON current_run.run_id=?
            WHERE previous_run.profile_id=current_run.profile_id
              AND previous_run.target_date < current_run.target_date
              AND previous_run.target_date >= date(current_run.target_date,'-14 days')
            ORDER BY previous_run.target_date DESC,event.event_ordinal LIMIT 256
            """, (run_id,)
        ).fetchall()
        max_score = 0.0
        first_seen = now_us
        for row in rows:
            previous_categories=set(_string_list(json.loads(str(row["categories_json"]))))
            if current_categories and previous_categories and not current_categories.intersection(previous_categories):
                continue
            other = _event_tokens(str(row["title"]) + " " + str(row["summary"]))
            union = tokens.union(other)
            score=len(tokens.intersection(other))/len(union) if union else 0.0
            max_score=max(max_score,score)
            if score >= 0.72:
                prior=int(row["first_seen_us"]) if row["first_seen_us"] is not None else int(row["created_at_us"])
                first_seen=min(first_seen,prior)
        return round(max(0.0,1.0-max_score),6), first_seen

    def _finding_source_ids(
        self, artifact_id: uuid.UUID | None, ordinal: int
    ) -> tuple[uuid.UUID, ...]:
        if artifact_id is None:
            return ()
        artifacts = (
            self.app.research_repository.source_analysis_artifact_ids_for_synthesis_output(
                artifact_id,
                output_kind="finding",
                output_ordinal=ordinal,
            )
        )
        return self._source_ids_for_analysis_artifacts(artifacts)

    def _contradiction_source_ids(
        self, artifact_id: uuid.UUID | None, ordinal: int
    ) -> tuple[uuid.UUID, ...]:
        if artifact_id is None:
            return ()
        artifacts = (
            self.app.research_repository.source_analysis_artifact_ids_for_synthesis_output(
                artifact_id,
                output_kind="contradiction",
                output_ordinal=ordinal,
            )
        )
        return self._source_ids_for_analysis_artifacts(artifacts)

    def _source_ids_for_analysis_artifacts(
        self, artifact_ids: Iterable[uuid.UUID]
    ) -> tuple[uuid.UUID, ...]:
        result: set[uuid.UUID] = set()
        for artifact_id in artifact_ids:
            artifact = self.app.source_analysis_repository.get_artifact(artifact_id)
            analysis = self.app.source_analysis_repository.get_analysis(artifact.analysis_id)
            result.add(analysis.source_id)
        return tuple(sorted(result, key=lambda value: value.bytes))

    def _categories_for_article_sources(
        self, run_id: bytes, source_ids: Iterable[uuid.UUID]
    ) -> list[str]:
        ids = tuple(source_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.database.connection.execute(
            f"""
            SELECT DISTINCT category.value AS category_key
            FROM news_discoveries AS discovery,
                 json_each(discovery.category_keys_json) AS category
            WHERE discovery.run_id = ?
              AND discovery.article_source_id IN ({placeholders})
              AND discovery.dedup_state = 'unique'
            ORDER BY category.value
            """,
            (run_id, *(uuid_to_blob(item) for item in ids)),
        ).fetchall()
        return [str(row["category_key"]) for row in rows]

    def _research_source_metadata(self, run_id: bytes) -> str:
        rows = self.database.connection.execute(
            """
            SELECT source.name, source.source_class, source.independence_group,
                   source.perspective, source.priority
            FROM news_discoveries AS discovery
            JOIN news_sources AS source ON source.news_source_id = discovery.news_source_id
            WHERE discovery.run_id = ? AND discovery.article_source_id IS NOT NULL
            GROUP BY source.news_source_id
            ORDER BY source.priority DESC, source.name
            """,
            (run_id,),
        ).fetchall()
        parts = [
            f"{row['name']} [class={row['source_class']}; "
            f"independence_group={row['independence_group']}; "
            f"perspective={row['perspective']}]"
            for row in rows
        ]
        return "; ".join(parts)[:6000]

    def _period_source_metadata(self, period_start: str, period_end: str) -> str:
        rows = self.database.connection.execute(
            """
            SELECT DISTINCT source.name, source.source_class, source.independence_group,
                            source.perspective, source.priority
            FROM news_discoveries AS discovery
            JOIN news_runs AS run ON run.run_id = discovery.run_id
            JOIN news_sources AS source ON source.news_source_id = discovery.news_source_id
            WHERE run.profile_id = ? AND run.target_date BETWEEN ? AND ?
              AND discovery.article_source_id IS NOT NULL
            ORDER BY source.priority DESC, source.name
            """,
            (uuid_to_blob(_default_profile_id()), period_start, period_end),
        ).fetchall()
        return "; ".join(
            f"{row['name']} [class={row['source_class']}; "
            f"independence_group={row['independence_group']}; "
            f"perspective={row['perspective']}]"
            for row in rows
        )[:6000]

    def _suggest_event_links(
        self,
        run_id: bytes,
        event_id: uuid.UUID,
        *,
        title: str,
        summary: str,
        categories: list[str],
    ) -> tuple[uuid.UUID, ...]:
        current_tokens = _event_tokens(title + " " + summary)
        if not current_tokens:
            return ()
        current_categories = set(categories)
        rows = self.database.connection.execute(
            """
            SELECT event.event_id, event.title, event.summary, event.categories_json
            FROM news_events AS event
            JOIN news_runs AS previous_run ON previous_run.run_id = event.run_id
            JOIN news_runs AS current_run ON current_run.run_id = ?
            WHERE previous_run.profile_id = current_run.profile_id
              AND previous_run.target_date < current_run.target_date
              AND previous_run.target_date >= date(current_run.target_date, '-14 days')
            ORDER BY previous_run.target_date DESC, event.event_ordinal
            LIMIT 256
            """,
            (run_id,),
        ).fetchall()
        linked: list[uuid.UUID] = []
        for row in rows:
            previous_categories = set(
                _string_list(json.loads(str(row["categories_json"])))
            )
            if (
                current_categories
                and previous_categories
                and not current_categories.intersection(previous_categories)
            ):
                continue
            other_tokens = _event_tokens(str(row["title"]) + " " + str(row["summary"]))
            union = current_tokens.union(other_tokens)
            score = (
                len(current_tokens.intersection(other_tokens)) / len(union)
                if union
                else 0.0
            )
            if score < 0.72:
                continue
            previous_id = uuid_from_blob(bytes(row["event_id"]))
            with self.database.write_transaction() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO news_event_links (
                        from_event_id, to_event_id, relation, score, created_at_us
                    ) VALUES (?, ?, 'possible_continuation', ?, ?)
                    """,
                    (
                        uuid_to_blob(previous_id),
                        uuid_to_blob(event_id),
                        score,
                        utc_now_us(),
                    ),
                )
            linked.append(previous_id)
            if len(linked) >= 5:
                break
        return tuple(linked)

    def _finish_without_research(self, run: Any, *, state: str, reason: str) -> None:
        digest_id = new_uuid7()
        now = utc_now_us()
        content = {
            "summary": "No research digest could be produced for this period.",
            "events": [],
            "contradictions": [],
            "uncertainty": reason,
            "canonical_knowledge_written": False,
        }
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO news_digests (
                    digest_id, profile_id, period_kind, period_start, period_end,
                    revision_no, content_json, research_result_ids_json, created_at_us
                ) VALUES (?, ?, 'daily', ?, ?, 1, ?, '[]', ?)
                """,
                (
                    uuid_to_blob(digest_id),
                    run["profile_id"],
                    run["target_date"],
                    run["target_date"],
                    _canonical_json(content),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE news_runs
                SET state = ?, digest_id = ?, completed_at_us = ?, updated_at_us = ?
                WHERE run_id = ?
                """,
                (state, uuid_to_blob(digest_id), now, now, run["run_id"]),
            )
