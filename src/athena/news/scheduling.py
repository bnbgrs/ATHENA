"""Daily News scheduling and parent-job orchestration."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from athena.common.ids import uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.external.gateway import ExternalAccessError
from athena.jobs.models import JobPriority, JobRecord, JobState, WaitingReason
from athena.news.common import (
    _default_profile_id,
    _json_object,
    _optional_uuid_blob,
    _required_str,
    _research_question,
    _run_view,
)
from athena.news.context import NewsMixinContext
from athena.news.event_structuring import NewsEventStructuringRetryable
from athena.news.models import (
    NEWS_JOB_TYPE,
    NEWS_PERIOD_JOB_TYPE,
    NewsConsentRequired,
    NewsError,
    NewsRunView,
)


class NewsSchedulingMixin(NewsMixinContext):
    def schedule_due(self, *, now: datetime | None = None) -> tuple[uuid.UUID, ...]:
        profile = self._profile_row()
        if not bool(profile["enabled"]):
            return ()
        self._require_consent_unchanged(profile)
        try:
            zone = ZoneInfo(str(profile["timezone_name"]))
        except ZoneInfoNotFoundError as exc:
            raise NewsError("Configured News timezone is unavailable.") from exc
        local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
        scheduled_today = local_now.replace(
            hour=int(profile["local_hour"]),
            minute=int(profile["local_minute"]),
            second=0,
            microsecond=0,
        )
        latest = (
            local_now.date()
            if local_now >= scheduled_today
            else local_now.date() - timedelta(days=1)
        )
        oldest = latest - timedelta(days=int(profile["backfill_days"]) - 1)
        created: list[uuid.UUID] = []
        cursor = oldest
        while cursor <= latest:
            job_id = self._ensure_daily_job(cursor.isoformat())
            if job_id is not None:
                created.append(job_id)
            cursor += timedelta(days=1)
        created.extend(self._schedule_rollups(local_now.date()))
        return tuple(created)

    def queue_date(self, target_date: str) -> uuid.UUID:
        date.fromisoformat(target_date)
        job_id = self._ensure_daily_job(target_date)
        if job_id is not None:
            return job_id
        row = self.database.connection.execute(
            """
            SELECT job_id FROM news_runs
            WHERE profile_id = ? AND target_date = ?
            """,
            (uuid_to_blob(_default_profile_id()), target_date),
        ).fetchone()
        if row is None:
            raise NewsError("News run exists without durable job identity.")
        return uuid_from_blob(bytes(row["job_id"]))

    def run_view(self, target_date: str) -> NewsRunView | None:
        row = self.database.connection.execute(
            "SELECT * FROM news_runs WHERE profile_id = ? AND target_date = ?",
            (uuid_to_blob(_default_profile_id()), target_date),
        ).fetchone()
        return None if row is None else _run_view(row)

    def latest_digest(self) -> dict[str, Any] | None:
        row = self.database.connection.execute(
            "SELECT * FROM news_digests ORDER BY period_start DESC, revision_no DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "digest_id": str(uuid_from_blob(bytes(row["digest_id"]))),
            "period_kind": str(row["period_kind"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
            "revision_no": int(row["revision_no"]),
            "content": json.loads(str(row["content_json"])),
        }

    def process_leased(self, job: JobRecord) -> JobRecord:
        if job.lease_token is None:
            raise NewsError("News worker requires a leased News job.")
        if job.job_type == NEWS_PERIOD_JOB_TYPE:
            return self._process_period_leased(job)
        if job.job_type != NEWS_JOB_TYPE:
            raise NewsError(f"Unsupported News job type {job.job_type!r}.")
        scope = _json_object(job.requested_scope_json)
        target_date = _required_str(scope, "target_date")
        run = self._get_or_create_run(job.job_id, target_date)
        if run["state"] in {"completed", "partial", "unreconstructable"}:
            return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)

        research_job_id = _optional_uuid_blob(run["research_job_id"])
        if research_job_id is not None:
            research_job = self.app.jobs.get(research_job_id)
            if not research_job.state.terminal:
                return self.app.jobs.wait(
                    job.job_id,
                    lease_token=job.lease_token,
                    reason=WaitingReason.DEPENDENCY,
                )
            if research_job.state is not JobState.COMPLETED:
                self._finish_without_research(
                    run,
                    state="partial",
                    reason="research_failed",
                )
                return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)
            try:
                self._materialize_research(
                    run,
                    research_job_id,
                    parent_job=job,
                )
            except NewsEventStructuringRetryable:
                return self.app.jobs.wait(
                    job.job_id,
                    lease_token=job.lease_token,
                    reason=WaitingReason.BACKOFF,
                    next_run_at_us=utc_now_us() + 5 * 60 * 1_000_000,
                )
            return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)

        if str(run["state"]) == "queued":
            try:
                self._discover_and_capture(run, target_date, parent_job=job)
            except NewsConsentRequired:
                return self.app.jobs.wait(
                    job.job_id,
                    lease_token=job.lease_token,
                    reason=WaitingReason.USER,
                )
            except ExternalAccessError:
                return self.app.jobs.wait(
                    job.job_id,
                    lease_token=job.lease_token,
                    reason=WaitingReason.NETWORK,
                    next_run_at_us=utc_now_us() + 5 * 60 * 1_000_000,
                )
        refreshed = self._run_row(uuid_from_blob(bytes(run["run_id"])))
        if int(refreshed["captured_count"]) == 0:
            past = date.fromisoformat(target_date) < datetime.now(timezone.utc).date()
            state = "unreconstructable" if past else "partial"
            self._finish_without_research(
                refreshed,
                state=state,
                reason="no_captured_articles",
            )
            return self.app.jobs.complete(job.job_id, lease_token=job.lease_token)

        source_ids = tuple(
            uuid_from_blob(bytes(row["article_source_id"]))
            for row in self.database.connection.execute(
                """
                SELECT article_source_id FROM news_discoveries
                WHERE run_id = ? AND article_source_id IS NOT NULL
                  AND dedup_state = 'unique'
                ORDER BY discovery_id
                """,
                (refreshed["run_id"],),
            ).fetchall()
        )
        profile = self._profile_row()
        try:
            research_job = self.app.research.enqueue_local(
                query=_research_question(
                    target_date,
                    str(profile["output_language"]),
                    self._research_source_metadata(refreshed["run_id"]),
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
                UPDATE news_runs
                SET research_job_id = ?, state = 'researching', updated_at_us = ?
                WHERE run_id = ?
                """,
                (
                    uuid_to_blob(research_job.job_id),
                    utc_now_us(),
                    refreshed["run_id"],
                ),
            )
        return self.app.jobs.wait(
            job.job_id,
            lease_token=job.lease_token,
            reason=WaitingReason.DEPENDENCY,
        )
