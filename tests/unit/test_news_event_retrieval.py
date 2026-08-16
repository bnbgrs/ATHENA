from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.retrieval.news_events import (
    NewsEventContextBuilderService,
    NewsEventSearchError,
    NewsEventSearchService,
)


def _canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        allow_nan=False,
    )


def _app(
    tmp_path: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )
    app.start()
    return app


def _insert_news_event(
    app: AthenaApplication,
    *,
    target_date: str = "2026-08-16",
    title: str = "Project Helios update",
    summary: str = (
        "Project Helios announced launch code 5931."
    ),
):
    news_job_id = app.news.queue_date(
        target_date
    )

    run = app.database.connection.execute(
        """
        SELECT *
        FROM news_runs
        WHERE job_id = ?
        """,
        (
            uuid_to_blob(
                news_job_id
            ),
        ),
    ).fetchone()

    assert run is not None

    research_job = app.research.enqueue_local(
        query=(
            "News research for Project Helios"
        )
    )

    scope = app.research.initialize(
        research_job.job_id
    )

    result_id = new_uuid7()

    research_payload = {
        "summary": summary,
        "findings": [
            summary,
        ],
        "contradictions": [],
        "uncertainty": "",
        "coverage": {
            "candidate_total": 1,
            "processed_count": 1,
            "successful_count": 1,
            "irrelevant_count": 0,
            "failed_count": 0,
            "unavailable_count": 0,
            "excluded_count": 0,
            "eligible_count": 1,
            "coverage_ratio": 1.0,
        },
        "problem_sources": [],
        "snapshot_commit_seq": (
            scope.snapshot_commit_seq
        ),
    }

    content_json = _canonical_json(
        research_payload
    )

    content_hash = hashlib.sha256(
        content_json.encode(
            "utf-8"
        )
    ).digest()

    finding_hash = hashlib.sha256(
        summary.encode(
            "utf-8"
        )
    ).digest()

    event_id = new_uuid7()
    now = utc_now_us()

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE research_scopes
            SET state = 'completed',
                updated_at_us = ?
            WHERE scope_id = ?
            """,
            (
                now,
                uuid_to_blob(
                    scope.scope_id
                ),
            ),
        )

        connection.execute(
            """
            INSERT INTO research_results (
                result_id,
                scope_id,
                final_artifact_id,
                content_json,
                content_hash,
                snapshot_commit_seq,
                model_signature_id,
                synthesis_pipeline_version,
                candidate_total,
                processed_count,
                successful_count,
                irrelevant_count,
                failed_count,
                unavailable_count,
                excluded_count,
                coverage_ratio,
                problem_sources_json,
                created_at_us
            ) VALUES (
                ?, ?, NULL, ?, ?, ?, NULL, ?,
                1, 1, 1, 0, 0, 0, 0,
                1.0, '[]', ?
            )
            """,
            (
                uuid_to_blob(
                    result_id
                ),
                uuid_to_blob(
                    scope.scope_id
                ),
                content_json,
                content_hash,
                scope.snapshot_commit_seq,
                "news-event-retrieval-test-v1",
                now,
            ),
        )

        connection.execute(
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
                ?, ?, 0, ?, 'event',
                'current_development',
                ?, NULL, 'day', ?,
                ?, ?, ?, ?, ?, ?,
                NULL, ?
            )
            """,
            (
                run["run_id"],
                uuid_to_blob(
                    result_id
                ),
                finding_hash,
                target_date,
                "Berlin",
                _canonical_json(
                    [
                        "Project Helios",
                    ]
                ),
                "announced launch code 5931",
                now,
                now,
                now,
                now,
                now,
            ),
        )

        connection.execute(
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
                ?, ?, 0, 0, ?, ?, ?,
                ?, ?, ?, ?, NULL, 'day',
                ?, ?, ?, ?, ?, ?, ?,
                NULL, ?, ?, 0.95, 0.90, 0.85,
                0, 0, 0, ?, ?, ?
            )
            """,
            (
                uuid_to_blob(
                    event_id
                ),
                run["run_id"],
                hashlib.sha256(
                    summary.casefold().encode(
                        "utf-8"
                    )
                ).digest(),
                title,
                summary,
                _canonical_json(
                    [
                        "technology",
                    ]
                ),
                _canonical_json(
                    []
                ),
                _canonical_json(
                    []
                ),
                target_date,
                "Berlin",
                _canonical_json(
                    [
                        "Project Helios",
                    ]
                ),
                "announced launch code 5931",
                now,
                now,
                now,
                now,
                now,
                now,
                uuid_to_blob(
                    research_job.job_id
                ),
                uuid_to_blob(
                    result_id
                ),
                now,
            ),
        )

        connection.execute(
            """
            UPDATE news_runs
            SET state = 'completed',
                research_job_id = ?,
                research_result_id = ?,
                completed_at_us = ?,
                updated_at_us = ?
            WHERE run_id = ?
            """,
            (
                uuid_to_blob(
                    research_job.job_id
                ),
                uuid_to_blob(
                    result_id
                ),
                now,
                now,
                run["run_id"],
            ),
        )

    return (
        event_id,
        result_id,
        finding_hash,
    )


def test_news_search_uses_only_event_eligible_durable_findings(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            event_id,
            result_id,
            finding_hash,
        ) = _insert_news_event(
            app
        )

        search = NewsEventSearchService(
            app.database
        )

        results = search.search(
            "latest news about Project Helios launch code",
            limit=5,
        )

        assert results
        assert results[0].event_id == event_id
        assert (
            results[0].research_result_id
            == result_id
        )
        assert (
            results[0].finding_hash
            == finding_hash
        )
        assert "5931" in results[0].text

        assert (
            search.search(
                "latest news",
                limit=5,
            )
            == ()
        )

    finally:
        app.stop()


def test_news_search_excludes_context_findings(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            event_id,
            _result_id,
            _finding_hash,
        ) = _insert_news_event(
            app
        )

        with app.database.write_transaction() as connection:
            event_row = connection.execute(
                """
                SELECT run_id
                FROM news_events
                WHERE event_id = ?
                """,
                (
                    uuid_to_blob(
                        event_id
                    ),
                ),
            ).fetchone()

            assert event_row is not None

            connection.execute(
                """
                DELETE FROM news_events
                WHERE event_id = ?
                """,
                (
                    uuid_to_blob(
                        event_id
                    ),
                ),
            )

            connection.execute(
                """
                UPDATE news_finding_assessments
                SET eligibility = 'context',
                    eligibility_reason = 'background',
                    event_time_start = NULL,
                    event_time_end = NULL,
                    event_time_precision = 'unknown',
                    location_text = NULL,
                    actors_json = '[]',
                    core_action = NULL
                WHERE run_id = ?
                  AND finding_ordinal = 0
                """,
                (
                    event_row["run_id"],
                ),
            )

        search = NewsEventSearchService(
            app.database
        )

        assert (
            search.search(
                "Project Helios launch code",
                limit=5,
            )
            == ()
        )

        with pytest.raises(
            NewsEventSearchError,
            match="does not exist",
        ):
            search.get_event(
                event_id
            )

    finally:
        app.stop()


def test_news_search_fails_closed_on_finding_hash_mismatch(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            event_id,
            _result_id,
            _finding_hash,
        ) = _insert_news_event(
            app
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_finding_assessments
                SET finding_sha256 = ?
                WHERE run_id = (
                    SELECT run_id
                    FROM news_events
                    WHERE event_id = ?
                )
                  AND finding_ordinal = 0
                """,
                (
                    b"x" * 32,
                    uuid_to_blob(
                        event_id
                    ),
                ),
            )

        search = NewsEventSearchService(
            app.database
        )

        with pytest.raises(
            NewsEventSearchError,
            match="finding eligibility",
        ):
            search.search(
                "Project Helios launch code",
                limit=5,
            )

    finally:
        app.stop()


def test_news_context_builder_reverifies_event_before_use(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            event_id,
            _result_id,
            _finding_hash,
        ) = _insert_news_event(
            app
        )

        search = NewsEventSearchService(
            app.database
        )

        results = search.search(
            "Project Helios launch code",
            limit=5,
        )

        builder = NewsEventContextBuilderService(
            search
        )

        bundle = builder.build(
            query="What is the latest Helios code?",
            results=results,
            max_estimated_tokens=900,
            max_items=4,
        )

        assert len(
            bundle.items
        ) == 1
        assert (
            bundle.items[0].event.event_id
            == event_id
        )
        assert (
            bundle.items[0].context_id
            == "CTX-001"
        )
        assert (
            '"evidence_class": "news"'
            in bundle.rendered_text
        )

        builder.verify_bundle(
            bundle
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_events
                SET summary = ?
                WHERE event_id = ?
                """,
                (
                    "tampered News summary",
                    uuid_to_blob(
                        event_id
                    ),
                ),
            )

        with pytest.raises(
            NewsEventSearchError,
            match="finding eligibility",
        ):
            builder.verify_bundle(
                bundle
            )

    finally:
        app.stop()


def test_news_search_does_not_select_wrong_named_entity_from_generic_terms(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            wrong_event_id,
            _wrong_result_id,
            _wrong_finding_hash,
        ) = _insert_news_event(
            app,
            target_date="2026-08-15",
            title="Project Atlas update",
            summary=(
                "Project Atlas has "
                "assigned code 1101."
            ),
        )

        (
            target_event_id,
            _target_result_id,
            _target_finding_hash,
        ) = _insert_news_event(
            app,
            target_date="2026-08-16",
            title="Project Borealis update",
            summary=(
                "Project Borealis has "
                "assigned code 2202."
            ),
        )

        search = (
            NewsEventSearchService(
                app.database
            )
        )

        results = search.search(
            (
                "Project Borealis "
                "assigned code"
            ),
            limit=5,
        )

        assert results
        assert (
            results[0].event_id
            == target_event_id
        )
        assert all(
            item.event_id
            != wrong_event_id
            for item in results
        )

    finally:
        app.stop()


def test_news_natural_question_rejects_wrong_named_entity(
    tmp_path: Path,
) -> None:
    app = _app(
        tmp_path
    )

    try:
        (
            wrong_event_id,
            _wrong_result_id,
            _wrong_hash,
        ) = _insert_news_event(
            app,
            target_date="2026-08-15",
            title="Project Atlas update",
            summary=(
                "Project Atlas is "
                "assigned code 1101."
            ),
        )

        (
            target_event_id,
            _target_result_id,
            _target_hash,
        ) = _insert_news_event(
            app,
            target_date="2026-08-16",
            title="Project Borealis update",
            summary=(
                "Project Borealis is "
                "assigned code 2202."
            ),
        )

        search = (
            NewsEventSearchService(
                app.database
            )
        )

        results = search.search(
            (
                "What code is assigned "
                "to Project Borealis?"
            ),
            limit=5,
        )

        assert results
        assert [
            item.event_id
            for item in results
        ] == [
            target_event_id,
        ]

        assert all(
            item.event_id
            != wrong_event_id
            for item in results
        )

    finally:
        app.stop()
