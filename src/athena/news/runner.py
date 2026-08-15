"""News worker loop that reuses ATHENA's durable queue and Core child scheduler."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from athena.news.service import NewsService

if TYPE_CHECKING:
    from athena.core.application import AthenaApplication


class NewsRunner:
    """Drive News jobs while letting the Core scheduler advance child Research jobs."""

    def __init__(self, app: AthenaApplication, service: NewsService | None = None) -> None:
        self.app = app
        self.news = service or NewsService(app)
        self.news.start()

    def tick(self, *, worker_id: str = "news-runner") -> str:
        """Delegate News and child work to ATHENA's single durable scheduler."""
        result = self.app.job_scheduler.tick(worker_id=worker_id)
        return "idle" if result.idle else result.action

    def run(self, *, max_ticks: int | None = None, idle_sleep_seconds: float = 5.0) -> int:
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            status = self.tick()
            ticks += 1
            if status == "idle":
                time.sleep(idle_sleep_seconds)
        return ticks
