from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from athena.common.ids import new_uuid7, uuid_to_blob
from athena.common.time import utc_now_us
from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.external.gateway import ExternalResponse
from athena.jobs.models import JobState
from athena.model.adapters.lm_studio import ProviderOutputLimitError
from athena.news.common import _research_question
from athena.news.event_structuring import (
    NewsEventMetadata,
    NewsEventStructuringMixin,
    _event_batch_ranges,
    _validate_event_output,
)
from athena.news.feed import FeedItem, canonicalize_url
from athena.news.service import NewsService
from athena.storage.schema import (
    PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID,
    PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
)


def _app(tmp_path: Path, *, root_name: str = "runtime") -> AthenaApplication:
    app = AthenaApplication(AthenaSettings(local_root=tmp_path / root_name))
    app.start()
    return app


def _only_bbc_world(app: AthenaApplication, news: NewsService) -> None:
    with app.database.write_transaction() as connection:
        connection.execute("UPDATE news_sources SET active = 0")
        connection.execute(
            "UPDATE news_sources SET active = 1, daily_limit = 20 WHERE slug = 'bbc-world'"
        )
        connection.execute(
            """
            UPDATE news_profiles
            SET backfill_days = 1, max_articles_per_day = 20
            WHERE name = 'default'
            """
        )
    news._invalidate_consent()


def _news_source_id(app: AthenaApplication, slug: str = "bbc-world") -> bytes:
    row = app.database.connection.execute(
        "SELECT news_source_id FROM news_sources WHERE slug = ?", (slug,)
    ).fetchone()
    assert row is not None
    return bytes(row["news_source_id"])


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _insert_completed_research_result(
    app: AthenaApplication,
    content: dict[str, object],
) -> tuple[object, object]:
    job = app.research.enqueue_local(query="deterministic News audit fixture")
    scope = app.research.initialize(job.job_id)
    result_id = new_uuid7()
    content_json = _canonical_json(content)
    content_hash = hashlib.sha256(content_json.encode("utf-8")).digest()
    now = utc_now_us()
    with app.database.write_transaction() as connection:
        connection.execute(
            "UPDATE research_scopes SET state = 'completed', updated_at_us = ? WHERE scope_id = ?",
            (now, uuid_to_blob(scope.scope_id)),
        )
        connection.execute(
            """
            INSERT INTO research_results (
                result_id, scope_id, final_artifact_id,
                content_json, content_hash, snapshot_commit_seq,
                model_signature_id, synthesis_pipeline_version,
                candidate_total, processed_count, successful_count,
                irrelevant_count, failed_count, unavailable_count,
                excluded_count, coverage_ratio, problem_sources_json,
                created_at_us
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, 'news-audit-fixture-v1',
                      0, 0, 0, 0, 0, 0, 0, 0.0, '[]', ?)
            """,
            (
                uuid_to_blob(result_id),
                uuid_to_blob(scope.scope_id),
                content_json,
                content_hash,
                scope.snapshot_commit_seq,
                now,
            ),
        )
    return job.job_id, result_id


def test_news_event_structuring_batches_large_result_sets() -> None:
    assert _event_batch_ranges(30) == (
        (0, 8),
        (8, 16),
        (16, 24),
        (24, 30),
    )


def test_news_event_validator_preserves_global_batch_ordinals() -> None:
    raw = {
        "events": [
            {
                "finding_ordinal": ordinal,
                "eligibility": "event",
                "eligibility_reason": "current_development",
                "event_time_start": "",
                "event_time_end": "",
                "event_time_precision": "unknown",
                "location": "",
                "actors": [],
                "core_action": f"Action {ordinal}",
            }
            for ordinal in (8, 9)
        ]
    }

    validated = _validate_event_output(
        raw,
        (8, 9),
    )

    assert [
        item["finding_ordinal"]
        for item in validated
    ] == [8, 9]


def test_news_event_output_overflow_recursively_splits_batch() -> None:
    class FakeStructurer(NewsEventStructuringMixin):
        def __init__(self) -> None:
            self.calls: list[tuple[int, ...]] = []

        def _structure_event_batch(self, **kwargs: object):
            ordinals = kwargs["expected_ordinals"]
            assert isinstance(ordinals, tuple)
            self.calls.append(ordinals)

            if len(ordinals) > 2:
                raise ProviderOutputLimitError(
                    "synthetic output overflow"
                )

            return tuple(
                (
                    {"finding_ordinal": ordinal},
                    new_uuid7(),
                )
                for ordinal in ordinals
            )

    fake = FakeStructurer()

    result = fake._structure_event_batch_resilient(
        run={},
        result=object(),
        config=object(),
        signature=object(),
        evidence=tuple(
            {"finding_ordinal": ordinal}
            for ordinal in range(8)
        ),
        expected_ordinals=tuple(range(8)),
        parent_job=None,
    )

    assert [
        item["finding_ordinal"]
        for item, _run_id in result
    ] == list(range(8))

    assert fake.calls[0] == tuple(range(8))
    assert any(
        len(call) == 4
        for call in fake.calls
    )
    assert any(
        len(call) == 2
        for call in fake.calls
    )


def test_news_event_validator_runtime_wiring_uses_temporal_normalization() -> None:
    import inspect

    from athena.news.event_structuring import (
        _normalize_event_time_metadata,
        _validate_event_output,
    )

    validator_source = inspect.getsource(
        _validate_event_output
    )

    assert (
        "_normalize_event_time_metadata("
        in validator_source
    )

    assert (
        "_validate_event_time("
        not in validator_source
    )

    assert (
        _normalize_event_time_metadata(
            "day",
            "2026-07",
            "",
        )
        == (
            "unknown",
            None,
            None,
        )
    )

    assert (
        _normalize_event_time_metadata(
            "day",
            "2026-08-15",
            "",
        )
        == (
            "day",
            "2026-08-15",
            None,
        )
    )


def test_research_contract_requires_event_clustering_attribution_and_disagreement() -> None:
    prompt = _research_question(
        "2026-08-15",
        "de",
        "Wire A [independence_group=wire]; Paper B [independence_group=paper]",
    )
    lowered = prompt.casefold()
    assert "berichte über dasselbe ereignis" in lowered
    assert "statt einen punkt pro artikel" in lowered
    assert "unterschiedliche ereignisse getrennt" in lowered
    assert "attribuiere meinungen" in lowered
    assert "widerspruch" in lowered
    assert "independence_group" in prompt
    assert "nicht als unabhängige bestätigung" in lowered


def test_ten_day_backfill_keeps_exact_historical_dates_and_survives_restart(
    tmp_path: Path,
) -> None:
    root_name = "restart-runtime"
    app = _app(tmp_path, root_name=root_name)
    try:
        news = NewsService(app)
        news.start()
        with app.database.write_transaction() as connection:
            connection.execute(
                "UPDATE news_profiles SET backfill_days = 10 WHERE name = 'default'"
            )
        news.consent_and_enable()
        now = datetime(2026, 8, 15, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        created = news.schedule_due(now=now)
        assert len(created) == 10
        dates = [
            str(row["target_date"])
            for row in app.database.connection.execute(
                "SELECT target_date FROM news_runs ORDER BY target_date"
            ).fetchall()
        ]
        assert dates == [
            "2026-08-06",
            "2026-08-07",
            "2026-08-08",
            "2026-08-09",
            "2026-08-10",
            "2026-08-11",
            "2026-08-12",
            "2026-08-13",
            "2026-08-14",
            "2026-08-15",
        ]
    finally:
        app.stop()

    restarted = _app(tmp_path, root_name=root_name)
    try:
        news = NewsService(restarted)
        news.start()
        now = datetime(2026, 8, 15, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        assert news.schedule_due(now=now) == ()
        assert restarted.database.connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE job_type = 'news.daily'"
        ).fetchone()[0] == 10
        assert restarted.database.connection.execute(
            "SELECT COUNT(*) FROM news_runs"
        ).fetchone()[0] == 10
    finally:
        restarted.stop()


def test_published_day_is_evaluated_in_profile_timezone(tmp_path: Path) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        published = datetime(2026, 8, 14, 22, 30, tzinfo=timezone.utc)
        item = FeedItem(
            canonical_url="https://example.com/story",
            url_hash=hashlib.sha256(b"story").digest(),
            title="Story",
            summary="",
            published_at_us=int(published.timestamp() * 1_000_000),
        )
        assert news._item_matches_day(item, date(2026, 8, 15), "Europe/Berlin")
        assert not news._item_matches_day(item, date(2026, 8, 14), "Europe/Berlin")
        assert not news._item_matches_day(item, date(2026, 8, 15), "Invalid/Zone")
    finally:
        app.stop()


def test_daily_byte_budget_bounds_article_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        _only_bbc_world(app, news)
        budget = 1024 * 1024
        with app.database.write_transaction() as connection:
            connection.execute(
                "UPDATE news_profiles SET max_bytes_per_day = ? WHERE name = 'default'",
                (budget,),
            )
        news.consent_and_enable()
        target = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
        feed = tmp_path / "budget-feed.xml"
        feed.write_text(
            """<?xml version='1.0'?><rss version='2.0'><channel>
            <item><title>One</title><link>https://www.bbc.com/news/one</link></item>
            <item><title>Two</title><link>https://www.bbc.com/news/two</link></item>
            <item><title>Three</title><link>https://www.bbc.com/news/three</link></item>
            </channel></rss>""",
            encoding="utf-8",
        )
        article = tmp_path / "large-article.html"
        article.write_bytes(b"x" * 700_000)
        successful_bytes = 0

        def fake_capture(_authorization_id: object, url: str, **kwargs: object):
            nonlocal successful_bytes
            path = feed if "rss.xml" in url else article
            max_bytes = int(kwargs.get("max_bytes", 8 * 1024 * 1024))
            if path.stat().st_size > max_bytes:
                raise ValueError("bounded fake transport refused oversized response")
            result = app.sources.capture_external_snapshot(path, source_uri=url)
            successful_bytes += result.blob.byte_length
            return result

        monkeypatch.setattr(app.external_access, "capture_url", fake_capture)

        def fake_research(**_kwargs: object):
            return app.jobs.create(
                job_type="research.exhaustive",
                requested_scope={"fixture": True},
                pinned_configuration={"fixture": True},
            )

        monkeypatch.setattr(app.research, "enqueue_local", fake_research)
        job_id = news.queue_date(target)
        leased = app.jobs.acquire(job_id, worker_id="news-budget", lease_seconds=300)
        current = news.process_leased(leased)
        assert current.state is JobState.WAITING
        view = news.run_view(target)
        assert view is not None
        assert view.captured_count == 1
        assert successful_bytes <= budget
        assert view.failed_count == 2
    finally:
        app.stop()


def test_malicious_cross_host_feed_item_is_denied_without_direct_fallback(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        _only_bbc_world(app, news)
        news.consent_and_enable()
        feed_url = "https://feeds.bbci.co.uk/news/world/rss.xml"
        payload = b"""<?xml version='1.0'?><rss version='2.0'><channel>
        <item><title>Injected</title><link>https://evil.example/steal</link></item>
        </channel></rss>"""

        class FakeTor:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(
                self, url: str, *, max_bytes: int, timeout_seconds: float
            ) -> ExternalResponse:
                del timeout_seconds
                self.calls.append(url)
                assert len(payload) <= max_bytes
                return ExternalResponse(
                    final_url=url,
                    status=200,
                    headers={"content-type": "application/rss+xml"},
                    body=payload,
                )

        transport = FakeTor()
        app.external_access.transports["tor"] = transport
        target = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
        job_id = news.queue_date(target)
        leased = app.jobs.acquire(job_id, worker_id="news-host-scope", lease_seconds=300)
        current = news.process_leased(leased)
        assert current.state is JobState.COMPLETED
        assert transport.calls == [feed_url]
        view = news.run_view(target)
        assert view is not None
        assert view.discovered_count == 1
        assert view.captured_count == 0
        assert view.failed_count == 1
        auth_rows = app.database.connection.execute(
            "SELECT privacy_route FROM external_access_authorizations"
        ).fetchall()
        assert [str(row["privacy_route"]) for row in auth_rows] == ["tor_preferred"]
        denied = app.database.connection.execute(
            """
            SELECT COUNT(*) FROM external_access_events
            WHERE destination_host = 'evil.example' AND outcome = 'denied'
            """
        ).fetchone()[0]
        assert denied == 1
    finally:
        app.stop()


def test_same_url_can_preserve_later_changed_source_capture(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        source_config_id = _news_source_id(app)
        first_job = news.queue_date("2026-08-14")
        second_job = news.queue_date("2026-08-15")
        first_run = news._get_or_create_run(first_job, "2026-08-14")
        second_run = news._get_or_create_run(second_job, "2026-08-15")
        url = canonicalize_url("https://www.bbc.com/news/corrected-story")
        url_hash = hashlib.sha256(url.encode("utf-8")).digest()
        item = FeedItem(url, url_hash, "Corrected story", "", None)
        first_path = tmp_path / "revision-1.html"
        second_path = tmp_path / "revision-2.html"
        first_path.write_text("<p>reported value: 10</p>", encoding="utf-8")
        second_path.write_text("<p>correction: reported value is 12</p>", encoding="utf-8")
        first_source = app.sources.capture_external_snapshot(first_path, source_uri=url)
        second_source = app.sources.capture_external_snapshot(second_path, source_uri=url)
        first_id, first_new = news._record_discovery(
            first_run["run_id"], source_config_id, item, ("politics",)
        )
        second_id, second_new = news._record_discovery(
            second_run["run_id"], source_config_id, item, ("politics",)
        )
        assert first_new and second_new
        news._mark_discovery_captured(first_id, first_source.source.source_id)
        news._mark_discovery_captured(second_id, second_source.source.source_id)
        rows = app.database.connection.execute(
            """
            SELECT source.content_sha256
            FROM news_discoveries AS discovery
            JOIN sources AS source ON source.source_id = discovery.article_source_id
            WHERE discovery.url_hash = ?
            ORDER BY discovery.discovered_at_us, discovery.discovery_id
            """,
            (url_hash,),
        ).fetchall()
        assert len(rows) == 2
        assert bytes(rows[0]["content_sha256"]) != bytes(rows[1]["content_sha256"])
    finally:
        app.stop()


def test_same_run_duplicate_url_is_idempotent(tmp_path: Path) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        source_config_id = _news_source_id(app)
        job_id = news.queue_date("2026-08-15")
        run = news._get_or_create_run(job_id, "2026-08-15")
        url = canonicalize_url("https://www.bbc.com/news/duplicate")
        item = FeedItem(
            url,
            hashlib.sha256(url.encode("utf-8")).digest(),
            "Duplicate",
            "",
            None,
        )
        first_id, first_new = news._record_discovery(
            run["run_id"], source_config_id, item, ("politics",)
        )
        second_id, second_new = news._record_discovery(
            run["run_id"], source_config_id, item, ("politics",)
        )
        assert first_new
        assert not second_new
        assert second_id == first_id
        assert app.database.connection.execute(
            "SELECT COUNT(*) FROM news_discoveries WHERE run_id = ?",
            (run["run_id"],),
        ).fetchone()[0] == 1
    finally:
        app.stop()


def test_event_and_digest_materialization_preserves_sources_disagreement_and_zero_canonical_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        before = (
            app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0],
            app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
        )
        news_job_id = news.queue_date("2026-08-15")
        run_view = news.run_view("2026-08-15")
        assert run_view is not None
        run = news._run_row(run_view.run_id)
        source_config_id = _news_source_id(app)
        article_source_ids = []
        for index in range(5):
            path = tmp_path / f"evidence-{index}.html"
            path.write_text(f"<p>independent evidence {index}</p>", encoding="utf-8")
            url = canonicalize_url(f"https://www.bbc.com/news/evidence-{index}")
            capture = app.sources.capture_external_snapshot(path, source_uri=url)
            article_source_ids.append(capture.source.source_id)
            item = FeedItem(
                url,
                hashlib.sha256(url.encode("utf-8")).digest(),
                f"Evidence {index}",
                "",
                None,
            )
            discovery_id, was_new = news._record_discovery(
                run["run_id"], source_config_id, item, ("politics", "geopolitics")
            )
            assert was_new
            news._mark_discovery_captured(discovery_id, capture.source.source_id)

        content = {
            "summary": "Two distinct developments were identified.",
            "findings": [
                "Five reports describe the same ceasefire event; The Intercept argues that its durability is doubtful.",
                "A separate central-bank decision occurred later that day.",
            ],
            "contradictions": ["Sources disagree on the reported number of violations."],
            "uncertainty": "The ceasefire durability remains uncertain.",
            "coverage": {},
            "problem_sources": [],
            "snapshot_commit_seq": 0,
        }
        research_job_id, result_id = _insert_completed_research_result(app, content)

        def finding_sources(_artifact_id: object, ordinal: int):
            if ordinal == 0:
                return tuple(article_source_ids)
            return (article_source_ids[-1],)

        def contradiction_sources(_artifact_id: object, _ordinal: int):
            return tuple(article_source_ids[:2])

        monkeypatch.setattr(news, "_finding_source_ids", finding_sources)
        monkeypatch.setattr(news, "_contradiction_source_ids", contradiction_sources)

        structuring_run_id = new_uuid7()
        actor_id = app.chat.ensure_local_user()
        now_us = utc_now_us()
        with app.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO processing_runs (
                    processing_run_id, run_type, started_at_us, finished_at_us,
                    status, trigger_actor_id, pipeline_version, input_snapshot_json,
                    configuration_hash
                ) VALUES (?, 'news.test.structuring', ?, ?, 'succeeded', ?, 'test', '{}', ?)
                """,
                (
                    uuid_to_blob(structuring_run_id),
                    now_us,
                    now_us,
                    uuid_to_blob(actor_id),
                    bytes(32),
                ),
            )

        def deterministic_event_metadata(**kwargs: object):
            findings = kwargs["findings"]
            assert isinstance(findings, tuple)
            return tuple(
                NewsEventMetadata(
                    finding_ordinal=ordinal,
                    event_time_start=None,
                    event_time_end=None,
                    event_time_precision="unknown",
                    location=None,
                    actors=(),
                    core_action=None,
                    publication_time_min_us=None,
                    publication_time_max_us=None,
                    retrieval_time_min_us=None,
                    retrieval_time_max_us=None,
                    structuring_run_id=structuring_run_id,
                )
                for ordinal, _finding in enumerate(findings)
            )

        monkeypatch.setattr(news, "_structure_event_metadata", deterministic_event_metadata)
        news._materialize_research(run, research_job_id)

        events = app.database.connection.execute(
            "SELECT * FROM news_events WHERE run_id = ? ORDER BY event_ordinal",
            (run["run_id"],),
        ).fetchall()
        assert len(events) == 2
        first_sources = json.loads(str(events[0]["source_ids_json"]))
        assert len(first_sources) == 5
        assert json.loads(str(events[0]["contradictions_json"])) == [
            "Sources disagree on the reported number of violations."
        ]
        assert "argues" in str(events[0]["summary"])
        assert "The Intercept" in str(events[0]["summary"])
        assert json.loads(str(events[1]["contradictions_json"])) == []

        digest = news.latest_digest()
        assert digest is not None
        assert digest["period_kind"] == "daily"
        assert digest["content"]["research_result_id"] == str(result_id)
        assert digest["content"]["canonical_knowledge_written"] is False
        assert len(digest["content"]["events"]) == 2
        assert sorted(len(event["source_ids"]) for event in digest["content"]["events"]) == [1, 5]
        after = (
            app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0],
            app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
        )
        assert after == before
        assert news_job_id is not None
    finally:
        app.stop()


def test_central_scheduler_dispatches_news_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path)
    try:
        assert "news.daily" in app.job_scheduler.supported_job_types
        job_id = app.news.queue_date("2026-08-15")
        def complete_news(job):
            assert job.job_id == job_id and job.lease_token is not None
            return app.jobs.complete(job.job_id, lease_token=job.lease_token)
        monkeypatch.setattr(app.news, "process_leased", complete_news)
        result = app.job_scheduler.tick(worker_id="central-news-test")
        assert result.selected_job_id == job_id
        assert result.selected_job_type == "news.daily"
        assert result.final_state is JobState.COMPLETED
    finally:
        app.stop()


def test_exact_content_duplicate_is_classified_and_excluded(tmp_path: Path) -> None:
    app=_app(tmp_path)
    try:
        news = app.news
        source_config_id = _news_source_id(app)
        job_id = news.queue_date("2026-08-15")
        run = news._get_or_create_run(job_id, "2026-08-15")
        path = tmp_path / "same.html"
        path.write_text("same immutable body", encoding="utf-8")
        states=[]
        for index in range(2):
            url=canonicalize_url(f"https://www.bbc.com/news/exact-{index}")
            item=FeedItem(url,hashlib.sha256(url.encode()).digest(),f"Report {index}","same summary",None)
            capture=app.sources.capture_external_snapshot(path,source_uri=url)
            discovery_id,_=news._record_discovery(run["run_id"],source_config_id,item,("politics",))
            news._mark_discovery_captured(discovery_id,capture.source.source_id)
            row=app.database.connection.execute("SELECT dedup_state FROM news_discoveries WHERE discovery_id=?",(discovery_id.bytes,)).fetchone()
            states.append(str(row["dedup_state"]))
        assert states == ["unique", "exact_duplicate"]
    finally:
        app.stop()


def test_source_failure_backoff_and_success_cursor_are_persistent(tmp_path: Path) -> None:
    app=_app(tmp_path)
    try:
        news = app.news
        source_id = _news_source_id(app)
        job_id = news.queue_date("2026-08-15")
        run = news._get_or_create_run(job_id, "2026-08-15")
        news._record_source_failure(run["run_id"],source_id,RuntimeError("network down"))
        state=app.database.connection.execute("SELECT * FROM news_source_states WHERE news_source_id=?",(source_id,)).fetchone()
        assert int(state["consecutive_failures"]) == 1 and state["next_retry_at_us"] is not None
        news._record_source_success(source_id,last_published_at_us=123456,last_canonical_url="https://www.bbc.com/news/cursor")
        state=app.database.connection.execute("SELECT * FROM news_source_states WHERE news_source_id=?",(source_id,)).fetchone()
        assert int(state["consecutive_failures"]) == 0 and state["next_retry_at_us"] is None
        assert int(state["last_published_at_us"]) == 123456
    finally:
        app.stop()

def test_news_event_validator_keeps_context_out_of_event_metadata() -> None:
    raw = {
        "events": [
            {
                "finding_ordinal": 0,
                "eligibility": "context",
                "eligibility_reason": "background",
                "event_time_start": "2026-08-15",
                "event_time_end": "",
                "event_time_precision": "day",
                "location": "Berlin",
                "actors": ["Example actor"],
                "core_action": "Historical background",
            }
        ]
    }

    validated = _validate_event_output(
        raw,
        (0,),
    )

    item = validated[0]

    assert item["eligibility"] == "context"
    assert item["eligibility_reason"] == "background"
    assert item["event_time_precision"] == "unknown"
    assert item["event_time_start"] is None
    assert item["event_time_end"] is None
    assert item["location"] is None
    assert item["actors"] == ()
    assert item["core_action"] is None


def test_durable_event_eligibility_filters_context_without_losing_finding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(tmp_path)

    try:
        news = NewsService(app)
        news.start()

        _news_job_id = news.queue_date(
            "2026-08-15"
        )

        run_view = news.run_view(
            "2026-08-15"
        )
        assert run_view is not None

        run = news._run_row(
            run_view.run_id
        )

        source_config_id = _news_source_id(
            app
        )

        path = tmp_path / "eligibility.html"
        path.write_text(
            "<p>AMD development and background.</p>",
            encoding="utf-8",
        )

        url = canonicalize_url(
            "https://www.bbc.com/news/eligibility"
        )

        capture = app.sources.capture_external_snapshot(
            path,
            source_uri=url,
        )

        item = FeedItem(
            url,
            hashlib.sha256(
                url.encode("utf-8")
            ).digest(),
            "Eligibility evidence",
            "",
            None,
        )

        discovery_id, was_new = (
            news._record_discovery(
                run["run_id"],
                source_config_id,
                item,
                ("technology",),
            )
        )
        assert was_new

        news._mark_discovery_captured(
            discovery_id,
            capture.source.source_id,
        )

        findings = (
            "AMD announced a new accelerator.",
            (
                "Background: accelerators use "
                "parallel compute architectures."
            ),
        )

        content = {
            "summary": (
                "One development plus background."
            ),
            "findings": list(findings),
            "contradictions": [],
            "uncertainty": "",
            "coverage": {},
            "problem_sources": [],
            "snapshot_commit_seq": 0,
        }

        (
            research_job_id,
            _result_id,
        ) = _insert_completed_research_result(
            app,
            content,
        )

        scope = (
            app.research_repository
            .get_scope_for_job(
                research_job_id
            )
        )
        assert scope is not None

        result = (
            app.research_repository
            .get_result_for_scope(
                scope.scope_id
            )
        )
        assert result is not None

        monkeypatch.setattr(
            news,
            "_finding_source_ids",
            lambda _artifact_id, _ordinal: (
                capture.source.source_id,
            ),
        )

        monkeypatch.setattr(
            news,
            "_contradiction_source_ids",
            lambda _artifact_id, _ordinal: (),
        )

        structuring_run_id = new_uuid7()
        actor_id = app.chat.ensure_local_user()
        now_us = utc_now_us()

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO processing_runs (
                    processing_run_id,
                    run_type,
                    started_at_us,
                    finished_at_us,
                    status,
                    trigger_actor_id,
                    pipeline_version,
                    input_snapshot_json,
                    configuration_hash
                ) VALUES (
                    ?,
                    'news.test.eligibility',
                    ?,
                    ?,
                    'succeeded',
                    ?,
                    'test',
                    '{}',
                    ?
                )
                """,
                (
                    uuid_to_blob(
                        structuring_run_id
                    ),
                    now_us,
                    now_us,
                    uuid_to_blob(actor_id),
                    bytes(32),
                ),
            )

        assessments = (
            NewsEventMetadata(
                finding_ordinal=0,
                event_time_start=None,
                event_time_end=None,
                event_time_precision="unknown",
                location=None,
                actors=("AMD",),
                core_action=(
                    "announced a new accelerator"
                ),
                publication_time_min_us=None,
                publication_time_max_us=None,
                retrieval_time_min_us=None,
                retrieval_time_max_us=None,
                structuring_run_id=(
                    structuring_run_id
                ),
                eligibility="event",
                eligibility_reason=(
                    "current_development"
                ),
            ),
            NewsEventMetadata(
                finding_ordinal=1,
                event_time_start=None,
                event_time_end=None,
                event_time_precision="unknown",
                location=None,
                actors=(),
                core_action=None,
                publication_time_min_us=None,
                publication_time_max_us=None,
                retrieval_time_min_us=None,
                retrieval_time_max_us=None,
                structuring_run_id=(
                    structuring_run_id
                ),
                eligibility="context",
                eligibility_reason="background",
            ),
        )

        news._persist_finding_assessments(
            run,
            result,
            findings,
            assessments,
        )

        def must_not_restructure(
            **_kwargs: object,
        ):
            raise AssertionError(
                "Persisted eligibility must be reused."
            )

        monkeypatch.setattr(
            news,
            "_structure_event_metadata",
            must_not_restructure,
        )

        news._materialize_research(
            run,
            research_job_id,
        )

        persisted = (
            app.database.connection.execute(
                """
                SELECT
                    finding_ordinal,
                    eligibility,
                    eligibility_reason
                FROM news_finding_assessments
                WHERE run_id = ?
                ORDER BY finding_ordinal
                """,
                (run["run_id"],),
            ).fetchall()
        )

        assert [
            tuple(row)
            for row in persisted
        ] == [
            (
                0,
                "event",
                "current_development",
            ),
            (
                1,
                "context",
                "background",
            ),
        ]

        events = (
            app.database.connection.execute(
                """
                SELECT
                    event_ordinal,
                    finding_ordinal,
                    summary
                FROM news_events
                WHERE run_id = ?
                ORDER BY event_ordinal
                """,
                (run["run_id"],),
            ).fetchall()
        )

        assert len(events) == 1
        assert int(
            events[0]["event_ordinal"]
        ) == 0
        assert int(
            events[0]["finding_ordinal"]
        ) == 0
        assert str(
            events[0]["summary"]
        ) == findings[0]

        digest = news.latest_digest()
        assert digest is not None

        digest_content = digest["content"]

        assert (
            digest_content[
                "event_eligibility"
            ]
            == {
                "assessed_finding_count": 2,
                "event_count": 1,
                "context_count": 1,
            }
        )

        assert len(
            digest_content["events"]
        ) == 1

        assert (
            digest_content["events"][0][
                "finding_ordinal"
            ]
            == 0
        )

        assert (
            digest_content[
                "context_findings"
            ]
            == [
                {
                    "finding_ordinal": 1,
                    "text": findings[1],
                    "eligibility_reason": (
                        "background"
                    ),
                    "source_ids": [
                        str(
                            capture.source.source_id
                        )
                    ],
                }
            ]
        )

        assert (
            app.database.connection.execute(
                "SELECT COUNT(*) "
                "FROM knowledge_units"
            ).fetchone()[0]
            == 0
        )

        assert (
            app.database.connection.execute(
                "SELECT COUNT(*) "
                "FROM claims"
            ).fetchone()[0]
            == 0
        )

    finally:
        app.stop()

def test_v29_migration_backfills_legacy_event_assessment_without_model(
    tmp_path: Path,
) -> None:
    root_name = "runtime-v29-event-backfill"

    app = _app(
        tmp_path,
        root_name=root_name,
    )

    database_path = app.database.path

    finding = (
        "AMD announced a legacy accelerator "
        "development."
    )

    try:
        news = NewsService(app)
        news.start()

        news.queue_date("2026-08-15")

        run_view = news.run_view(
            "2026-08-15"
        )
        assert run_view is not None

        run = news._run_row(
            run_view.run_id
        )

        content = {
            "summary": "Legacy migration fixture.",
            "findings": [finding],
            "contradictions": [],
            "uncertainty": "",
            "coverage": {},
            "problem_sources": [],
            "snapshot_commit_seq": 0,
        }

        (
            research_job_id,
            result_id,
        ) = _insert_completed_research_result(
            app,
            content,
        )

        assert isinstance(
            research_job_id,
            uuid.UUID,
        )
        assert isinstance(
            result_id,
            uuid.UUID,
        )

        now_us = utc_now_us()

        with app.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_runs
                SET research_job_id = ?,
                    research_result_id = ?
                WHERE run_id = ?
                """,
                (
                    uuid_to_blob(
                        research_job_id
                    ),
                    uuid_to_blob(
                        result_id
                    ),
                    run["run_id"],
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
                    event_time_precision,
                    actors_json,
                    research_job_id,
                    research_result_id,
                    created_at_us
                ) VALUES (
                    ?, ?, 0, 0, ?, ?, ?,
                    '[]', '[]', '[]',
                    'unknown', '[]',
                    ?, ?, ?
                )
                """,
                (
                    uuid_to_blob(
                        new_uuid7()
                    ),
                    run["run_id"],
                    hashlib.sha256(
                        finding.encode("utf-8")
                    ).digest(),
                    "Legacy event",
                    finding,
                    uuid_to_blob(
                        research_job_id
                    ),
                    uuid_to_blob(
                        result_id
                    ),
                    now_us,
                ),
            )

    finally:
        app.stop()

    legacy = sqlite3.connect(
        database_path,
        autocommit=True,
    )

    # Normalize additive v39 state before this
    # fixture declares the database to be an
    # older schema boundary. Production migration
    # behavior remains intentionally fail-closed.
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "grounded_response_receipts"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protection_representation_blobs"
    )
    legacy.execute(
        "DROP TABLE IF EXISTS "
        "source_protected_semantic_payloads"
    )
    legacy.row_factory = sqlite3.Row

    try:
        # This test first creates the current schema and then reconstructs
        # the historical v29 boundary. Remove every additive v31/v32 object
        # before declaring the database to be v29.
        # Reconstruct a pre-v32 boundary: remove every additive
        # Protected-Content object before downgrading metadata.
        legacy.execute("DROP TRIGGER trg_source_protection_transition_block_blob_reuse")
        legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_update")
        legacy.execute("DROP TRIGGER trg_source_protection_transition_block_source_delete")
        legacy.execute("DROP TRIGGER trg_source_protection_transition_block_representation")
        legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_update")
        legacy.execute("DROP TRIGGER trg_source_protection_transition_block_old_blob_delete")
        legacy.execute("DROP TABLE source_protection_transitions")
        legacy.execute(
            "DROP TABLE protected_sources"
        )

        legacy.execute(
            "DROP TABLE "
            "protected_blob_envelopes"
        )
        legacy.execute(
            "DROP TABLE "
            "protected_payloads"
        )
        legacy.execute(
            "DROP TABLE "
            "protection_scope_keys"
        )
        legacy.execute(
            "DROP TABLE "
            "protection_scopes"
        )
        legacy.execute(
            "DROP TABLE "
            "key_slots"
        )

        legacy.execute(
            "DROP TRIGGER "
            "trg_blob_records_archive_replication_outbox"
        )

        legacy.execute(
            "DROP TABLE "
            "archive_replication_watermark"
        )

        legacy.execute(
            "DROP TABLE "
            "archive_replication_outbox"
        )

        legacy.execute(
            "DROP TABLE "
            "news_finding_assessments"
        )

        legacy.execute(
            "DROP INDEX "
            "uq_news_events_run_finding_ordinal"
        )

        legacy.execute(
            "ALTER TABLE news_events "
            "DROP COLUMN finding_ordinal"
        )

        legacy.execute(
            """
            UPDATE news_schema_metadata
            SET schema_version = 3,
                schema_id = 'news-domain-v3'
            WHERE singleton_id = 1
            """
        )

        legacy.execute(
            """
            UPDATE schema_metadata
            SET schema_version = ?,
                last_migration_id = ?,
                minimum_reader_version = ?
            WHERE singleton_id = 1
            """,
            (
                PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
                PRECISE_RESEARCH_PROVENANCE_MIGRATION_ID,
                PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION,
            ),
        )

        legacy.execute(
            f"PRAGMA user_version = "
            f"{PRECISE_RESEARCH_PROVENANCE_SCHEMA_VERSION}"
        )

    finally:
        legacy.close()

    migrated = _app(
        tmp_path,
        root_name=root_name,
    )

    try:
        assessment = (
            migrated.database.connection.execute(
                """
                SELECT
                    research_result_id,
                    finding_ordinal,
                    finding_sha256,
                    eligibility,
                    eligibility_reason,
                    event_time_precision,
                    actors_json,
                    structuring_run_id
                FROM news_finding_assessments
                """
            ).fetchone()
        )

        assert assessment is not None

        assert (
            bytes(
                assessment[
                    "research_result_id"
                ]
            )
            == uuid_to_blob(result_id)
        )

        assert int(
            assessment["finding_ordinal"]
        ) == 0

        assert (
            bytes(
                assessment["finding_sha256"]
            )
            == hashlib.sha256(
                finding.encode("utf-8")
            ).digest()
        )

        assert (
            assessment["eligibility"]
            == "event"
        )

        assert (
            assessment["eligibility_reason"]
            == "current_development"
        )

        assert (
            assessment[
                "event_time_precision"
            ]
            == "unknown"
        )

        assert (
            assessment["actors_json"]
            == "[]"
        )

        # No historical model reclassification occurred.
        assert (
            assessment["structuring_run_id"]
            is None
        )

        event = (
            migrated.database.connection.execute(
                """
                SELECT
                    event_ordinal,
                    finding_ordinal,
                    summary
                FROM news_events
                """
            ).fetchone()
        )

        assert event is not None
        assert int(
            event["event_ordinal"]
        ) == 0
        assert int(
            event["finding_ordinal"]
        ) == 0
        assert event["summary"] == finding

        assert (
            migrated.database.connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            == []
        )

    finally:
        migrated.stop()
