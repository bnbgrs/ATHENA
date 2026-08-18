"""News consent, durable run, discovery, and schema helpers."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.jobs.models import JobPriority
from athena.news.common import (
    _canonical_json,
    _default_profile_id,
    _event_tokens,
    _stable_uuid,
)
from athena.news.context import NewsMixinContext
from athena.news.feed import FeedItem
from athena.news.models import NEWS_JOB_TYPE, NEWS_PIPELINE_VERSION, NewsConsentRequired, NewsError
from athena.news.schema import NEWS_SCHEMA_ID, NEWS_SCHEMA_VERSION


class NewsPersistenceMixin(NewsMixinContext):
    def _materialize_short_authorization(self, profile: Any) -> uuid.UUID:
        self._require_consent_unchanged(profile)
        hosts = self._active_hosts()
        authorization = self.app.external_access.authorize_explicit(
            purpose="daily_news_standing_user_profile",
            allowed_hosts=hosts,
            privacy_route="tor_preferred",
            ttl_seconds=24 * 60 * 60,
        )
        return authorization.authorization_id

    def _require_consent_unchanged(self, profile: Any) -> None:
        persisted = profile["consent_host_hash"]
        if persisted is None or bytes(persisted) != self._active_host_hash():
            raise NewsConsentRequired(
                "News source hosts changed or were never consented; run explicit News consent again."
            )

    def _invalidate_consent(self) -> None:
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_profiles SET consent_host_hash = NULL, consented_at_us = NULL,
                    updated_at_us = ? WHERE profile_id = ?
                """,
                (utc_now_us(), uuid_to_blob(_default_profile_id())),
            )

    def _active_hosts(self) -> tuple[str, ...]:
        hosts: set[str] = set()
        for row in self.database.connection.execute(
            "SELECT feed_url, site_url FROM news_sources WHERE active = 1"
        ).fetchall():
            for field in ("feed_url", "site_url"):
                host = urlsplit(str(row[field])).hostname
                if host:
                    hosts.add(host.encode("idna").decode("ascii").lower().rstrip("."))
        return tuple(sorted(hosts))

    def _active_host_hash(self) -> bytes:
        return hashlib.sha256(_canonical_json(self._active_hosts()).encode("utf-8")).digest()

    def _profile_row(self) -> Any:
        row = self.database.connection.execute(
            "SELECT * FROM news_profiles WHERE profile_id = ?",
            (uuid_to_blob(_default_profile_id()),),
        ).fetchone()
        if row is None:
            raise NewsError("Default News profile does not exist.")
        return row

    def _ensure_daily_job(self, target_date: str) -> uuid.UUID | None:
        existing = self.database.connection.execute(
            "SELECT job_id FROM news_runs WHERE profile_id = ? AND target_date = ?",
            (uuid_to_blob(_default_profile_id()), target_date),
        ).fetchone()
        if existing is not None:
            return None
        actor_id = self.app.chat.ensure_local_user()
        scope_json = _canonical_json(
            {"profile_id": str(_default_profile_id()), "target_date": target_date}
        )
        pinned_json = _canonical_json(
            {"pipeline_version": NEWS_PIPELINE_VERSION, "news_schema": NEWS_SCHEMA_ID}
        )
        try:
            job = self.app.job_repository.create(
                job_type=NEWS_JOB_TYPE,
                actor_id=actor_id,
                priority=JobPriority.BACKGROUND,
                requested_scope_json=scope_json,
                pinned_configuration_json=pinned_json,
            )
        except sqlite3.IntegrityError:
            row = self.database.connection.execute(
                """
                SELECT job_id FROM jobs
                WHERE job_type = ?
                  AND json_extract(requested_scope_json, '$.profile_id') = ?
                  AND json_extract(requested_scope_json, '$.target_date') = ?
                """,
                (NEWS_JOB_TYPE, str(_default_profile_id()), target_date),
            ).fetchone()
            if row is None:
                raise
            job_id = uuid_from_blob(bytes(row["job_id"]))
            self._get_or_create_run(job_id, target_date)
            return None
        self._get_or_create_run(job.job_id, target_date)
        return job.job_id

    def _get_or_create_run(self, job_id: uuid.UUID, target_date: str) -> Any:
        now = utc_now_us()
        run_id = _stable_uuid("news-run", f"{_default_profile_id()}:{target_date}")
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO news_runs (
                    run_id, profile_id, job_id, target_date, state,
                    discovered_count, captured_count, failed_count,
                    created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, 'queued', 0, 0, 0, ?, ?)
                """,
                (
                    uuid_to_blob(run_id), uuid_to_blob(_default_profile_id()),
                    uuid_to_blob(job_id), target_date, now, now,
                ),
            )
        return self._run_row(run_id)

    def _run_row(self, run_id: uuid.UUID) -> Any:
        row = self.database.connection.execute(
            "SELECT * FROM news_runs WHERE run_id = ?", (uuid_to_blob(run_id),)
        ).fetchone()
        if row is None:
            raise NewsError(f"News run {run_id} not found.")
        return row

    def _record_discovery(
        self,
        run_id: bytes,
        news_source_id: bytes,
        item: FeedItem,
        categories: tuple[str, ...],
    ) -> tuple[uuid.UUID, bool]:
        discovery_id = new_uuid7()
        try:
            with self.database.write_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO news_discoveries (
                        discovery_id, run_id, news_source_id, canonical_url, url_hash,
                        title, summary, published_at_us, category_keys_json,
                        state, discovered_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', ?)
                    """,
                    (
                        uuid_to_blob(discovery_id), run_id, news_source_id,
                        item.canonical_url, item.url_hash, item.title, item.summary,
                        item.published_at_us, _canonical_json(categories), utc_now_us(),
                    ),
                )
            return discovery_id, True
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" not in str(exc):
                raise
            row = self.database.connection.execute(
                "SELECT discovery_id FROM news_discoveries WHERE run_id = ? AND url_hash = ?",
                (run_id, item.url_hash),
            ).fetchone()
            if row is None:
                raise
            return uuid_from_blob(bytes(row["discovery_id"])), False

    def _mark_discovery_captured(
        self, discovery_id: uuid.UUID, source_id: uuid.UUID
    ) -> bool:
        """Attach immutable snapshot and classify same-run exact/near duplicates."""
        discovery_blob = uuid_to_blob(discovery_id)
        source_blob = uuid_to_blob(source_id)
        current = self.database.connection.execute(
            "SELECT * FROM news_discoveries WHERE discovery_id = ?", (discovery_blob,)
        ).fetchone()
        source = self.database.connection.execute(
            "SELECT content_sha256 FROM sources WHERE source_id = ?", (source_blob,)
        ).fetchone()
        if current is None or source is None:
            raise NewsError("Captured News discovery lost its Source identity.")
        content_hash = bytes(source["content_sha256"])
        duplicate = self.database.connection.execute(
            """
            SELECT discovery_id FROM news_discoveries
            WHERE run_id = ? AND discovery_id != ? AND state = 'captured'
              AND dedup_state = 'unique' AND content_sha256 = ?
            ORDER BY discovered_at_us, discovery_id LIMIT 1
            """,
            (current["run_id"], discovery_blob, content_hash),
        ).fetchone()
        state = "unique"
        duplicate_blob = None
        near_score = None
        if duplicate is not None:
            state = "exact_duplicate"
            duplicate_blob = bytes(duplicate["discovery_id"])
            near_score = 1.0
        else:
            tokens = _event_tokens(f"{current['title']} {current['summary']}")
            if len(tokens) >= 6:
                rows = self.database.connection.execute(
                    """
                    SELECT discovery_id, title, summary FROM news_discoveries
                    WHERE run_id = ? AND discovery_id != ? AND state = 'captured'
                      AND dedup_state = 'unique'
                    ORDER BY discovered_at_us, discovery_id
                    """, (current["run_id"], discovery_blob)
                ).fetchall()
                best_score = 0.0
                best_blob = None
                for row in rows:
                    other=_event_tokens(f"{row['title']} {row['summary']}")
                    union=tokens.union(other)
                    score=len(tokens.intersection(other))/len(union) if union else 0.0
                    if score > best_score:
                        best_score = score
                        best_blob = bytes(row["discovery_id"])
                if best_blob is not None and best_score >= 0.90:
                    state = "near_duplicate"
                    duplicate_blob = best_blob
                    near_score = best_score
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_discoveries
                SET state='captured', article_source_id=?, failure_reason=NULL,
                    content_sha256=?, dedup_state=?, duplicate_of_discovery_id=?,
                    near_duplicate_score=?
                WHERE discovery_id=?
                """,
                (source_blob, content_hash, state, duplicate_blob, near_score, discovery_blob),
            )
        return state == "unique"

    def _mark_discovery_failed(self, discovery_id: uuid.UUID, exc: BaseException) -> None:
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_discoveries SET state = 'failed', failure_reason = ?
                WHERE discovery_id = ?
                """,
                (type(exc).__name__, uuid_to_blob(discovery_id)),
            )

    def _record_source_failure(
        self, run_id: bytes, news_source_id: bytes, exc: BaseException
    ) -> None:
        now = utc_now_us()
        detail = type(exc).__name__
        row=self.database.connection.execute(
            "SELECT consecutive_failures FROM news_source_states WHERE news_source_id=?",
            (news_source_id,),
        ).fetchone()
        failures=1 if row is None else int(row["consecutive_failures"])+1
        delay=min(6*60*60, 5*60*(2 ** min(failures-1, 6)))
        with self.database.write_transaction() as connection:
            connection.execute(
                "INSERT INTO news_source_run_failures(failure_id,run_id,news_source_id,detail,created_at_us) VALUES (?,?,?,?,?)",
                (uuid_to_blob(new_uuid7()), run_id, news_source_id, detail, now),
            )
            connection.execute(
                """
                INSERT INTO news_source_states(news_source_id,last_attempt_at_us,consecutive_failures,next_retry_at_us,last_error)
                VALUES (?,?,?,?,?)
                ON CONFLICT(news_source_id) DO UPDATE SET
                    last_attempt_at_us=excluded.last_attempt_at_us,
                    consecutive_failures=excluded.consecutive_failures,
                    next_retry_at_us=excluded.next_retry_at_us,last_error=excluded.last_error
                """, (news_source_id, now, failures, now+delay*1_000_000, detail)
            )

    def _record_source_success(
        self, news_source_id: bytes, *, last_published_at_us: int | None,
        last_canonical_url: str | None,
    ) -> None:
        now=utc_now_us()
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO news_source_states(
                    news_source_id,last_attempt_at_us,last_success_at_us,last_published_at_us,
                    last_canonical_url,consecutive_failures,next_retry_at_us,last_error
                ) VALUES (?,?,?,?,?,0,NULL,NULL)
                ON CONFLICT(news_source_id) DO UPDATE SET
                    last_attempt_at_us=excluded.last_attempt_at_us,
                    last_success_at_us=excluded.last_success_at_us,
                    last_published_at_us=CASE
                        WHEN excluded.last_published_at_us IS NULL THEN news_source_states.last_published_at_us
                        WHEN news_source_states.last_published_at_us IS NULL THEN excluded.last_published_at_us
                        ELSE MAX(news_source_states.last_published_at_us, excluded.last_published_at_us) END,
                    last_canonical_url=COALESCE(excluded.last_canonical_url,news_source_states.last_canonical_url),
                    consecutive_failures=0,next_retry_at_us=NULL,last_error=NULL
                """, (news_source_id,now,now,last_published_at_us,last_canonical_url)
            )

    def _source_in_backoff(self, news_source_id: bytes, *, now_us: int) -> bool:
        row=self.database.connection.execute(
            "SELECT next_retry_at_us FROM news_source_states WHERE news_source_id=?", (news_source_id,)
        ).fetchone()
        return row is not None and row["next_retry_at_us"] is not None and int(row["next_retry_at_us"]) > now_us

    def _source_categories(self, news_source_id: bytes) -> tuple[str, ...]:
        rows = self.database.connection.execute(
            """
            SELECT link.category_key
            FROM news_source_categories AS link
            JOIN news_profile_categories AS category
              ON category.category_key = link.category_key AND category.profile_id = ?
            WHERE link.news_source_id = ? AND category.enabled = 1
            ORDER BY link.category_key
            """,
            (uuid_to_blob(_default_profile_id()), news_source_id),
        ).fetchall()
        return tuple(str(row["category_key"]) for row in rows)

    @staticmethod
    def _item_matches_day(item: FeedItem, target: date, timezone_name: str) -> bool:
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return False
        if item.published_at_us is None:
            return target == datetime.now(zone).date()
        dt = datetime.fromtimestamp(item.published_at_us / 1_000_000, tz=timezone.utc)
        return dt.astimezone(zone).date() == target

    def _ensure_schema(self) -> None:
        row = self.database.connection.execute(
            "SELECT schema_version, schema_id FROM news_schema_metadata WHERE singleton_id = 1"
        ).fetchone()
        if (
            row is None
            or int(row["schema_version"]) != NEWS_SCHEMA_VERSION
            or str(row["schema_id"]) != NEWS_SCHEMA_ID
        ):
            raise NewsError("ATHENA News schema is missing or incompatible.")
