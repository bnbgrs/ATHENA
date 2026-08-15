"""Closed weekly/monthly News period synthesis."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, timedelta
from typing import Any

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.models import JobPriority, JobRecord, JobState, WaitingReason
from athena.news.common import (
    _canonical_json,
    _default_profile_id,
    _json_object,
    _optional_uuid_blob,
    _period_research_question,
    _required_str,
    _stable_uuid,
    _string_list,
)
from athena.news.context import NewsMixinContext
from athena.news.models import NEWS_PERIOD_JOB_TYPE, NEWS_PIPELINE_VERSION, NewsError
from athena.news.schema import NEWS_SCHEMA_ID
from athena.research.models import ResearchScopeState


class NewsPeriodMixin(NewsMixinContext):
    def _schedule_rollups(self, local_today: date) -> tuple[uuid.UUID, ...]:
        created: list[uuid.UUID] = []
        # On Monday, the previous Monday-Sunday week is now closed.
        if local_today.weekday() == 0:
            end = local_today - timedelta(days=1)
            start = end - timedelta(days=6)
            job_id = self._ensure_period_job("weekly", start.isoformat(), end.isoformat())
            if job_id is not None:
                created.append(job_id)
        # On the first day of a month, the previous calendar month is closed.
        if local_today.day == 1:
            end = local_today - timedelta(days=1)
            start = end.replace(day=1)
            job_id = self._ensure_period_job("monthly", start.isoformat(), end.isoformat())
            if job_id is not None:
                created.append(job_id)
        return tuple(created)

    def _ensure_period_job(
        self, period_kind: str, period_start: str, period_end: str
    ) -> uuid.UUID | None:
        if period_kind not in {"weekly", "monthly"}:
            raise ValueError("News period kind must be weekly or monthly.")
        date.fromisoformat(period_start)
        date.fromisoformat(period_end)
        existing = self.database.connection.execute(
            """
            SELECT job_id FROM news_period_runs
            WHERE profile_id = ? AND period_kind = ? AND period_start = ?
            """,
            (uuid_to_blob(_default_profile_id()), period_kind, period_start),
        ).fetchone()
        if existing is not None:
            return None
        actor_id = self.app.chat.ensure_local_user()
        requested = _canonical_json(
            {
                "profile_id": str(_default_profile_id()),
                "period_kind": period_kind,
                "period_start": period_start,
                "period_end": period_end,
            }
        )
        try:
            job = self.app.job_repository.create(
                job_type=NEWS_PERIOD_JOB_TYPE,
                actor_id=actor_id,
                priority=JobPriority.BACKGROUND,
                requested_scope_json=requested,
                pinned_configuration_json=_canonical_json(
                    {"pipeline_version": NEWS_PIPELINE_VERSION, "news_schema": NEWS_SCHEMA_ID}
                ),
            )
        except sqlite3.IntegrityError:
            return None
        period_id = _stable_uuid(
            "news-period", f"{period_kind}:{period_start}:{period_end}"
        )
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO news_period_runs (
                    period_id, profile_id, job_id, period_kind, period_start, period_end,
                    state, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    uuid_to_blob(period_id), uuid_to_blob(_default_profile_id()),
                    uuid_to_blob(job.job_id), period_kind, period_start, period_end, now, now,
                ),
            )
        return job.job_id

    def _process_period_leased(self, job: JobRecord) -> JobRecord:
        assert job.lease_token is not None
        scope_json = _json_object(job.requested_scope_json)
        period_kind = _required_str(scope_json, "period_kind")
        period_start = _required_str(scope_json, "period_start")
        period_end = _required_str(scope_json, "period_end")
        row = self.database.connection.execute(
            "SELECT * FROM news_period_runs WHERE job_id = ?",
            (uuid_to_blob(job.job_id),),
        ).fetchone()
        if row is None:
            raise NewsError("News period job lost its durable period run.")
        if str(row["state"]) in {"completed", "partial", "unreconstructable"}:
            return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)
        child_id = _optional_uuid_blob(row["research_job_id"])
        if child_id is not None:
            child = self.app.jobs.get(child_id)
            if not child.state.terminal:
                return self.app.jobs.wait(
                    job.job_id, lease_token=job.lease_token, reason=WaitingReason.DEPENDENCY
                )
            if child.state is not JobState.COMPLETED:
                self._finish_period_without_research(row, "research_failed")
                return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)
            self._materialize_period_research(row, child_id)
            return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)

        daily_rows = self.database.connection.execute(
            """
            SELECT * FROM news_runs
            WHERE profile_id = ? AND target_date BETWEEN ? AND ?
            ORDER BY target_date
            """,
            (uuid_to_blob(_default_profile_id()), period_start, period_end),
        ).fetchall()
        expected_days = (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days + 1
        if len(daily_rows) < expected_days or any(
            str(item["state"]) not in {"completed", "partial", "unreconstructable"}
            for item in daily_rows
        ):
            return self.app.jobs.wait(
                job.job_id,
                lease_token=job.lease_token,
                reason=WaitingReason.DEPENDENCY,
                next_run_at_us=utc_now_us() + 10 * 60 * 1_000_000,
            )
        source_rows = self.database.connection.execute(
            """
            SELECT DISTINCT discovery.article_source_id
            FROM news_discoveries AS discovery
            JOIN news_runs AS run ON run.run_id = discovery.run_id
            WHERE run.profile_id = ? AND run.target_date BETWEEN ? AND ?
              AND discovery.article_source_id IS NOT NULL
              AND discovery.dedup_state = 'unique'
            ORDER BY discovery.article_source_id
            """,
            (uuid_to_blob(_default_profile_id()), period_start, period_end),
        ).fetchall()
        source_ids = tuple(uuid_from_blob(bytes(item[0])) for item in source_rows)
        if not source_ids:
            self._finish_period_without_research(row, "no_captured_articles")
            return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)
        profile = self._profile_row()
        try:
            research_job = self.app.research.enqueue_local(
                query=_period_research_question(
                    period_kind, period_start, period_end, str(profile["output_language"]),
                    self._period_source_metadata(period_start, period_end),
                ),
                priority=JobPriority.BACKGROUND,
                explicit_source_ids=source_ids,
                coverage_target=1.0,
            )
        except (RuntimeError, OSError, ValueError):
            return self.app.jobs.wait(
                job.job_id,
                lease_token=job.lease_token,
                reason=WaitingReason.BACKOFF,
                next_run_at_us=utc_now_us() + 5 * 60 * 1_000_000,
            )
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_period_runs
                SET state = 'researching', research_job_id = ?, updated_at_us = ?
                WHERE period_id = ?
                """,
                (uuid_to_blob(research_job.job_id), utc_now_us(), row["period_id"]),
            )
        return self.app.jobs.wait(
            job.job_id, lease_token=job.lease_token, reason=WaitingReason.DEPENDENCY
        )

    def _materialize_period_research(self, period: Any, research_job_id: uuid.UUID) -> None:
        scope = self.app.research_repository.get_scope_for_job(research_job_id)
        if scope is None or scope.state is not ResearchScopeState.COMPLETED:
            raise NewsError("Completed period Research job has no completed scope.")
        result = self.app.research_repository.get_result_for_scope(scope.scope_id)
        if result is None:
            raise NewsError("Completed period Research has no ResearchResult.")
        content = _json_object(result.content_json)
        digest_id = new_uuid7()
        digest_content = {
            "summary": str(content.get("summary", "")),
            "developments": _string_list(content.get("findings")),
            "contradictions": _string_list(content.get("contradictions")),
            "uncertainty": str(content.get("uncertainty", "")),
            "coverage": content.get("coverage", {}),
            "problem_sources": content.get("problem_sources", []),
            "research_result_id": str(result.result_id),
            "canonical_knowledge_written": False,
        }
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            revision = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_no), 0) + 1 FROM news_digests
                    WHERE profile_id = ? AND period_kind = ? AND period_start = ?
                    """,
                    (period["profile_id"], period["period_kind"], period["period_start"]),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO news_digests (
                    digest_id, profile_id, period_kind, period_start, period_end,
                    revision_no, content_json, research_result_ids_json, created_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(digest_id), period["profile_id"], period["period_kind"],
                    period["period_start"], period["period_end"], revision,
                    _canonical_json(digest_content), _canonical_json([str(result.result_id)]), now,
                ),
            )
            daily_partial = connection.execute(
                """
                SELECT COUNT(*) FROM news_runs
                WHERE profile_id = ? AND target_date BETWEEN ? AND ?
                  AND state != 'completed'
                """,
                (period["profile_id"], period["period_start"], period["period_end"]),
            ).fetchone()[0]
            state = "partial" if int(daily_partial) else "completed"
            connection.execute(
                """
                UPDATE news_period_runs SET state = ?, research_result_id = ?,
                    digest_id = ?, completed_at_us = ?, updated_at_us = ?
                WHERE period_id = ?
                """,
                (
                    state, uuid_to_blob(result.result_id), uuid_to_blob(digest_id),
                    now, now, period["period_id"],
                ),
            )

    def _finish_period_without_research(self, period: Any, reason: str) -> None:
        digest_id = new_uuid7()
        now = utc_now_us()
        content = {
            "summary": "No period research digest could be produced.",
            "developments": [],
            "contradictions": [],
            "uncertainty": reason,
            "canonical_knowledge_written": False,
        }
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO news_digests (
                    digest_id, profile_id, period_kind, period_start, period_end, revision_no,
                    content_json, research_result_ids_json, created_at_us
                ) VALUES (?, ?, ?, ?, ?, 1, ?, '[]', ?)
                """,
                (
                    uuid_to_blob(digest_id), period["profile_id"], period["period_kind"],
                    period["period_start"], period["period_end"], _canonical_json(content), now,
                ),
            )
            connection.execute(
                """
                UPDATE news_period_runs SET state = 'unreconstructable', digest_id = ?,
                    completed_at_us = ?, updated_at_us = ? WHERE period_id = ?
                """,
                (uuid_to_blob(digest_id), now, now, period["period_id"]),
            )
