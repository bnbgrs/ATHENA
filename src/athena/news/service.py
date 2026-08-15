"""Composed ATHENA News application service."""

from __future__ import annotations

from athena.news.collection import NewsCollectionMixin
from athena.news.config import NewsConfigurationMixin
from athena.news.event_structuring import NewsEventStructuringMixin
from athena.news.materialization import NewsMaterializationMixin
from athena.news.periods import NewsPeriodMixin
from athena.news.persistence import NewsPersistenceMixin
from athena.news.scheduling import NewsSchedulingMixin


class NewsService(
    NewsConfigurationMixin,
    NewsSchedulingMixin,
    NewsPeriodMixin,
    NewsCollectionMixin,
    NewsEventStructuringMixin,
    NewsMaterializationMixin,
    NewsPersistenceMixin,
):
    """Configurable, durable, fail-closed automated News service."""
