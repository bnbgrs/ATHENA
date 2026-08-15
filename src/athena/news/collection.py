"""Gateway-only News feed discovery and immutable article capture."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.external.gateway import ExternalAccessError
from athena.jobs.models import JobRecord
from athena.jobs.repository import JobTransitionError
from athena.news.context import NewsMixinContext
from athena.news.feed import FeedParseError, parse_discovery_payload


class NewsCollectionMixin(NewsMixinContext):
    def reconcile_dependencies(self) -> int:
        rows = self.database.connection.execute(
            """
            SELECT run.job_id, run.research_job_id
            FROM news_runs AS run
            JOIN jobs AS parent ON parent.job_id = run.job_id
            WHERE run.state = 'researching' AND parent.state = 'waiting'
              AND run.research_job_id IS NOT NULL
            """
        ).fetchall()
        woken = 0
        period_rows = self.database.connection.execute(
            """
            SELECT run.job_id, run.research_job_id
            FROM news_period_runs AS run
            JOIN jobs AS parent ON parent.job_id = run.job_id
            WHERE run.state = 'researching' AND parent.state = 'waiting'
              AND run.research_job_id IS NOT NULL
            """
        ).fetchall()
        for row in (*rows, *period_rows):
            child = self.app.jobs.get(uuid_from_blob(bytes(row["research_job_id"])))
            if child.state.terminal:
                try:
                    self.app.jobs.wake(uuid_from_blob(bytes(row["job_id"])))
                except JobTransitionError:
                    pass
                else:
                    woken += 1
        return woken

    def _discover_and_capture(
        self, run: Any, target_date: str, *, parent_job: JobRecord
    ) -> None:
        profile = self._profile_row()
        self._require_consent_unchanged(profile)
        authorization_id = self._materialize_short_authorization(profile)
        target = date.fromisoformat(target_date)
        source_rows = self.database.connection.execute(
            """
            SELECT source.*, COALESCE(SUM(category.weight * link.weight), 0.0) AS topic_score
            FROM news_sources AS source
            JOIN json_each(?) AS language ON language.value = source.language
            LEFT JOIN news_source_categories AS link
              ON link.news_source_id = source.news_source_id
            LEFT JOIN news_profile_categories AS category
              ON category.category_key = link.category_key
             AND category.profile_id = ? AND category.enabled = 1
            WHERE source.active = 1
            GROUP BY source.news_source_id
            ORDER BY (source.priority + COALESCE(SUM(category.weight * link.weight), 0.0)) DESC,
                     source.name
            """,
            (str(profile["language_json"]), profile["profile_id"]),
        ).fetchall()
        discovered = 0
        captured = 0
        failed = 0
        feed_successes = 0
        total_bytes = 0
        max_total_bytes = int(profile["max_bytes_per_day"])
        per_source_budget = max(
            1, int(profile["max_articles_per_day"]) // max(1, len(source_rows))
        )
        for source in source_rows:
            if self._source_in_backoff(source["news_source_id"], now_us=utc_now_us()):
                continue
            assert parent_job.lease_token is not None
            self.app.jobs.heartbeat(
                parent_job.job_id,
                lease_token=parent_job.lease_token,
                extend_seconds=300,
            )
            try:
                remaining = max_total_bytes - total_bytes
                if remaining <= 0:
                    break
                feed_capture = self.app.external_access.capture_url(
                    authorization_id,
                    str(source["feed_url"]),
                    max_bytes=min(4 * 1024 * 1024, remaining),
                )
                feed_path = self.app.sources.verify(feed_capture.source.source_id)
                payload = Path(feed_path).read_bytes()
                total_bytes += int(feed_capture.blob.byte_length)
                feed_successes += 1
                items = parse_discovery_payload(payload, source_url=str(source["feed_url"]))
                published=[item.published_at_us for item in items if item.published_at_us is not None]
                self._record_source_success(
                    source["news_source_id"],
                    last_published_at_us=max(published) if published else None,
                    last_canonical_url=items[-1].canonical_url if items else None,
                )
            except (ExternalAccessError, FeedParseError, OSError, ValueError) as exc:
                failed += 1
                self._record_source_failure(run["run_id"], source["news_source_id"], exc)
                continue
            categories = self._source_categories(source["news_source_id"])
            selected = [
                item for item in items
                if self._item_matches_day(item, target, str(profile["timezone_name"]))
            ][: min(int(source["daily_limit"]), per_source_budget)]
            for item in selected:
                discovery_id, was_new = self._record_discovery(
                    run["run_id"], source["news_source_id"], item, categories
                )
                if not was_new:
                    continue
                discovered += 1
                try:
                    self.app.jobs.heartbeat(
                        parent_job.job_id,
                        lease_token=parent_job.lease_token,
                        extend_seconds=300,
                    )
                    remaining = max_total_bytes - total_bytes
                    if remaining <= 0:
                        break
                    article = self.app.external_access.capture_url(
                        authorization_id,
                        item.canonical_url,
                        max_bytes=min(8 * 1024 * 1024, remaining),
                    )
                except (ExternalAccessError, OSError, ValueError) as exc:
                    failed += 1
                    self._mark_discovery_failed(discovery_id, exc)
                    continue
                total_bytes += int(article.blob.byte_length)
                if self._mark_discovery_captured(discovery_id, article.source.source_id):
                    captured += 1
                if (
                    captured >= int(profile["max_articles_per_day"])
                    or total_bytes >= max_total_bytes
                ):
                    break
            if (
                captured >= int(profile["max_articles_per_day"])
                or total_bytes >= max_total_bytes
            ):
                break
        if source_rows and feed_successes == 0:
            raise ExternalAccessError(
                "No configured news feed was reachable through the authorized privacy route."
            )
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_runs
                SET state = 'captured', discovered_count = ?, captured_count = ?,
                    failed_count = ?, authorization_id = ?, updated_at_us = ?
                WHERE run_id = ?
                """,
                (
                    discovered, captured, failed, uuid_to_blob(authorization_id),
                    utc_now_us(), run["run_id"],
                ),
            )
