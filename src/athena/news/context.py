"""Typing contract shared by News mixins without changing runtime dispatch."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any, Iterable

from athena.jobs.models import JobRecord
from athena.news.feed import FeedItem
from athena.news.models import NewsRunView
from athena.storage.database import SQLiteDatabase

if TYPE_CHECKING:
    from athena.core.application import AthenaApplication
    from athena.news.event_structuring import NewsEventMetadata
    from athena.research.models import ResearchResultRecord, ResearchScopeRecord


class NewsMixinContext:
    """Cross-mixin contract; concrete implementations are later in NewsService MRO."""

    app: AthenaApplication
    database: SQLiteDatabase

    def _ensure_schema(self) -> None:
        raise NotImplementedError

    def bootstrap_defaults(self) -> None:
        raise NotImplementedError

    def _invalidate_consent(self) -> None:
        raise NotImplementedError

    def _active_host_hash(self) -> bytes:
        raise NotImplementedError

    def _active_hosts(self) -> tuple[str, ...]:
        raise NotImplementedError

    def _profile_row(self) -> Any:
        raise NotImplementedError

    def _require_consent_unchanged(self, profile: Any) -> None:
        raise NotImplementedError

    def _materialize_short_authorization(self, profile: Any) -> uuid.UUID:
        raise NotImplementedError

    def _ensure_daily_job(self, target_date: str) -> uuid.UUID | None:
        raise NotImplementedError

    def _schedule_rollups(self, local_today: date) -> tuple[uuid.UUID, ...]:
        raise NotImplementedError

    def _get_or_create_run(self, job_id: uuid.UUID, target_date: str) -> Any:
        raise NotImplementedError

    def _run_row(self, run_id: uuid.UUID) -> Any:
        raise NotImplementedError

    def _discover_and_capture(
        self, run: Any, target_date: str, *, parent_job: JobRecord
    ) -> None:
        raise NotImplementedError

    def _materialize_research(
        self,
        run: Any,
        research_job_id: uuid.UUID,
        *,
        parent_job: JobRecord | None = None,
    ) -> None:
        raise NotImplementedError

    def _finish_without_research(self, run: Any, *, state: str, reason: str) -> None:
        raise NotImplementedError

    def _research_source_metadata(self, run_id: bytes) -> str:
        raise NotImplementedError

    def _period_source_metadata(self, period_start: str, period_end: str) -> str:
        raise NotImplementedError

    def _process_period_leased(self, job: JobRecord) -> JobRecord:
        raise NotImplementedError

    def _materialize_period_research(self, period: Any, research_job_id: uuid.UUID) -> None:
        raise NotImplementedError

    def _finish_period_without_research(self, period: Any, reason: str) -> None:
        raise NotImplementedError

    def _record_source_failure(
        self, run_id: bytes, news_source_id: bytes, exc: BaseException
    ) -> None:
        raise NotImplementedError

    def _source_in_backoff(self, *args: Any, **kwargs: Any) -> bool:
        raise NotImplementedError

    def _record_source_success(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    def _source_categories(self, news_source_id: bytes) -> tuple[str, ...]:
        raise NotImplementedError

    def _record_discovery(
        self,
        run_id: bytes,
        news_source_id: bytes,
        item: FeedItem,
        categories: tuple[str, ...],
    ) -> tuple[uuid.UUID, bool]:
        raise NotImplementedError

    def _mark_discovery_captured(
        self, discovery_id: uuid.UUID, source_id: uuid.UUID
    ) -> bool:
        raise NotImplementedError

    def _mark_discovery_failed(
        self, discovery_id: uuid.UUID, exc: BaseException
    ) -> None:
        raise NotImplementedError

    @staticmethod
    def _item_matches_day(item: FeedItem, target: date, timezone_name: str) -> bool:
        raise NotImplementedError

    def run_view(self, target_date: str) -> NewsRunView | None:
        raise NotImplementedError

    def _source_ids_for_analysis_artifacts(
        self, artifact_ids: Iterable[uuid.UUID]
    ) -> tuple[uuid.UUID, ...]:
        raise NotImplementedError

    def _finding_source_ids(
        self, artifact_id: uuid.UUID | None, ordinal: int
    ) -> tuple[uuid.UUID, ...]:
        raise NotImplementedError

    def _structure_event_metadata(
        self,
        *,
        run: Any,
        scope: ResearchScopeRecord,
        result: ResearchResultRecord,
        findings: tuple[str, ...],
        parent_job: JobRecord | None = None,
    ) -> tuple[NewsEventMetadata, ...]:
        raise NotImplementedError
