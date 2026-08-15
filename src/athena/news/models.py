"""News subsystem value objects, identifiers, and domain errors."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

NEWS_JOB_TYPE = "news.daily"
NEWS_PERIOD_JOB_TYPE = "news.period"
NEWS_PIPELINE_VERSION = "news-daily-v1"


class NewsError(RuntimeError):
    """Base News subsystem error."""


class NewsConsentRequired(NewsError):
    """Raised when configured network hosts differ from standing user consent."""


@dataclass(frozen=True, slots=True)
class NewsRunView:
    run_id: uuid.UUID
    target_date: str
    state: str
    discovered_count: int
    captured_count: int
    failed_count: int
    research_job_id: uuid.UUID | None
    research_result_id: uuid.UUID | None
    digest_id: uuid.UUID | None
