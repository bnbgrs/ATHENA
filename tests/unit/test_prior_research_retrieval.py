from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.retrieval.prior_research import (
    PriorResearchContextBuilderService,
    PriorResearchSearchError,
    PriorResearchSearchService,
)


def _runtime(
    root: Path,
) -> AthenaApplication:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=root
        )
    )

    for directory in app.paths.required_local_directories:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    app.database.start()

    return app


def _insert_completed_result(
    app: AthenaApplication,
    *,
    query: str,
    summary: str,
    findings: tuple[str, ...] = (),
):
    job = app.research.enqueue_local(
        query=query
    )

    scope = app.research.initialize(
        job.job_id
    )

    now_us = utc_now_us()

    payload = {
        "summary": summary,
        "findings": list(
            findings
        ),
        "contradictions": [],
        "uncertainty": "",
        "coverage": {
            "candidate_total": 0,
            "processed_count": 0,
            "successful_count": 0,
            "irrelevant_count": 0,
            "failed_count": 0,
            "unavailable_count": 0,
            "excluded_count": 0,
            "eligible_count": 0,
            "coverage_ratio": 0.0,
        },
        "problem_sources": [],
        "snapshot_commit_seq": scope.snapshot_commit_seq,
    }

    content_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    content_hash = hashlib.sha256(
        content_json.encode(
            "utf-8"
        )
    ).digest()

    result_id = new_uuid7()

    with app.database.write_transaction() as connection:
        connection.execute(
            """
            UPDATE research_scopes
            SET state = 'completed',
                updated_at_us = ?
            WHERE scope_id = ?
            """,
            (
                now_us,
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
                0, 0, 0, 0, 0, 0, 0,
                0.0, '[]', ?
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
                "test-prior-research-v1",
                now_us,
            ),
        )

    return result_id, scope


def test_search_prefers_matching_completed_research_and_vague_query_is_empty(
    tmp_path: Path,
) -> None:
    app = _runtime(
        tmp_path
        / "runtime"
    )

    try:
        target_id, _scope = _insert_completed_result(
            app,
            query=(
                "Investigate Project Helios "
                "launch code"
            ),
            summary=(
                "Project Helios launch "
                "code is 2468."
            ),
            findings=(
                "Project Helios uses "
                "code 2468.",
            ),
        )

        _insert_completed_result(
            app,
            query="Investigate ocean salinity",
            summary="Ocean salinity was reviewed.",
        )

        search = PriorResearchSearchService(
            app.database
        )

        results = search.search(
            "What did our previous research "
            "find about Project Helios?",
            limit=5,
        )

        assert results
        assert results[0].result_id == target_id
        assert "2468" in results[0].text

        assert (
            search.search(
                "What did our previous research show?",
                limit=5,
            )
            == ()
        )

    finally:
        app.database.stop()


def test_corrupt_research_result_hash_fails_closed(
    tmp_path: Path,
) -> None:
    app = _runtime(
        tmp_path
        / "runtime"
    )

    try:
        result_id, _scope = _insert_completed_result(
            app,
            query=(
                "Investigate Project "
                "Helios launch code"
            ),
            summary=(
                "Project Helios launch "
                "code is 2468."
            ),
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE research_results
                SET content_json = ?
                WHERE result_id = ?
                """,
                (
                    '{"summary":"tampered"}',
                    uuid_to_blob(
                        result_id
                    ),
                ),
            )

        search = PriorResearchSearchService(
            app.database
        )

        with pytest.raises(
            PriorResearchSearchError,
            match="content hash",
        ):
            search.search(
                "Project Helios launch code",
                limit=5,
            )

    finally:
        app.database.stop()


def test_context_builder_reverifies_durable_result(
    tmp_path: Path,
) -> None:
    app = _runtime(
        tmp_path
        / "runtime"
    )

    try:
        result_id, _scope = _insert_completed_result(
            app,
            query=(
                "Investigate Project "
                "Helios launch code"
            ),
            summary=(
                "Project Helios launch "
                "code is 2468."
            ),
        )

        search = PriorResearchSearchService(
            app.database
        )

        results = search.search(
            "Project Helios launch code",
            limit=5,
        )

        builder = PriorResearchContextBuilderService(
            search
        )

        bundle = builder.build(
            query="What was the Helios code?",
            results=results,
            max_estimated_tokens=800,
            max_items=4,
        )

        assert len(bundle.items) == 1
        assert bundle.items[0].result_id == result_id
        assert bundle.items[0].context_id == "CTX-001"

        assert (
            '"evidence_class": "research"'
            in bundle.rendered_text
        )

        builder.verify_bundle(
            bundle
        )

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE research_results
                SET content_json = ?
                WHERE result_id = ?
                """,
                (
                    '{"summary":"tampered"}',
                    uuid_to_blob(
                        result_id
                    ),
                ),
            )

        with pytest.raises(
            PriorResearchSearchError,
            match="content hash",
        ):
            builder.verify_bundle(
                bundle
            )

    finally:
        app.database.stop()


def test_daily_and_period_news_research_never_appears_as_prior_research(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        settings=AthenaSettings(
            local_root=(
                tmp_path
                / "runtime"
            )
        )
    )

    app.start()

    try:
        (
            daily_result_id,
            daily_scope,
        ) = _insert_completed_result(
            app,
            query=(
                "Investigate "
                "DailyBorealis "
                "assigned code"
            ),
            summary=(
                "DailyBorealis has "
                "assigned code 4404."
            ),
        )

        (
            period_result_id,
            period_scope,
        ) = _insert_completed_result(
            app,
            query=(
                "Investigate "
                "PeriodBorealis "
                "assigned code"
            ),
            summary=(
                "PeriodBorealis has "
                "assigned code 5505."
            ),
        )

        (
            normal_result_id,
            _normal_scope,
        ) = _insert_completed_result(
            app,
            query=(
                "Investigate "
                "NormalBorealis "
                "assigned code"
            ),
            summary=(
                "NormalBorealis has "
                "assigned code 6606."
            ),
        )

        daily_parent_job_id = (
            app.news.queue_date(
                "2026-08-15"
            )
        )

        period_parent_job_id = (
            app.news._ensure_period_job(
                "weekly",
                "2026-08-03",
                "2026-08-09",
            )
        )

        assert (
            period_parent_job_id
            is not None
        )

        # Race-window state:
        # News owns the Research job,
        # but result IDs are not yet
        # materialized onto News runs.
        with (
            app.database
            .write_transaction()
        ) as connection:
            connection.execute(
                """
                UPDATE news_runs
                SET research_job_id = ?
                WHERE job_id = ?
                """,
                (
                    uuid_to_blob(
                        daily_scope.job_id
                    ),
                    uuid_to_blob(
                        daily_parent_job_id
                    ),
                ),
            )

            connection.execute(
                """
                UPDATE news_period_runs
                SET research_job_id = ?
                WHERE job_id = ?
                """,
                (
                    uuid_to_blob(
                        period_scope.job_id
                    ),
                    uuid_to_blob(
                        period_parent_job_id
                    ),
                ),
            )

        search = (
            PriorResearchSearchService(
                app.database
            )
        )

        assert (
            search.search(
                (
                    "DailyBorealis "
                    "assigned code"
                ),
                limit=5,
            )
            == ()
        )

        assert (
            search.search(
                (
                    "PeriodBorealis "
                    "assigned code"
                ),
                limit=5,
            )
            == ()
        )

        normal = search.search(
            (
                "NormalBorealis "
                "assigned code"
            ),
            limit=5,
        )

        assert normal
        assert (
            normal[0].result_id
            == normal_result_id
        )

        # Post-materialization ownership:
        # both result links now exist.
        with (
            app.database
            .write_transaction()
        ) as connection:
            connection.execute(
                """
                UPDATE news_runs
                SET research_result_id = ?
                WHERE job_id = ?
                """,
                (
                    uuid_to_blob(
                        daily_result_id
                    ),
                    uuid_to_blob(
                        daily_parent_job_id
                    ),
                ),
            )

            connection.execute(
                """
                UPDATE news_period_runs
                SET research_result_id = ?
                WHERE job_id = ?
                """,
                (
                    uuid_to_blob(
                        period_result_id
                    ),
                    uuid_to_blob(
                        period_parent_job_id
                    ),
                ),
            )

        assert (
            search.search(
                (
                    "DailyBorealis "
                    "assigned code"
                ),
                limit=5,
            )
            == ()
        )

        assert (
            search.search(
                (
                    "PeriodBorealis "
                    "assigned code"
                ),
                limit=5,
            )
            == ()
        )

        with pytest.raises(
            PriorResearchSearchError,
            match="does not exist",
        ):
            search.get_result(
                daily_result_id
            )

        with pytest.raises(
            PriorResearchSearchError,
            match="does not exist",
        ):
            search.get_result(
                period_result_id
            )

        normal_loaded = (
            search.get_result(
                normal_result_id
            )
        )

        assert (
            normal_loaded.result_id
            == normal_result_id
        )

    finally:
        app.stop()


def test_prior_research_natural_question_rejects_wrong_named_entity(
    tmp_path: Path,
) -> None:
    app = _runtime(
        tmp_path
        / "runtime"
    )

    try:
        (
            wrong_result_id,
            _wrong_scope,
        ) = _insert_completed_result(
            app,
            query=(
                "Project Atlas "
                "assigned code"
            ),
            summary=(
                "Project Atlas is "
                "assigned code 1101."
            ),
        )

        (
            target_result_id,
            _target_scope,
        ) = _insert_completed_result(
            app,
            query=(
                "Project Borealis "
                "assigned code"
            ),
            summary=(
                "Project Borealis is "
                "assigned code 2202."
            ),
        )

        search = (
            PriorResearchSearchService(
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
            item.result_id
            for item in results
        ] == [
            target_result_id,
        ]

        assert all(
            item.result_id
            != wrong_result_id
            for item in results
        )

    finally:
        app.database.stop()
