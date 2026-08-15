"""News profile, category, and source configuration."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.news.common import (
    _canonical_json,
    _default_profile_id,
    _source_view,
    _stable_uuid,
    _string_list,
)
from athena.news.context import NewsMixinContext
from athena.news.defaults import DEFAULT_CATEGORIES, DEFAULT_SOURCES
from athena.news.feed import canonicalize_url
from athena.news.models import NewsError
from athena.storage.database import SQLiteDatabase

if TYPE_CHECKING:
    from athena.core.application import AthenaApplication


class NewsConfigurationMixin(NewsMixinContext):
    def __init__(self, app: AthenaApplication) -> None:
        self.app = app
        self.database: SQLiteDatabase = app.database

    def start(self) -> None:
        self._ensure_schema()
        self.bootstrap_defaults()

    def bootstrap_defaults(self) -> None:
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO news_profiles (
                    profile_id, name, enabled, timezone_name, local_hour, local_minute,
                    language_json, output_language, backfill_days, max_articles_per_day, max_bytes_per_day,
                    consent_host_hash, consented_at_us, created_at_us, updated_at_us
                ) VALUES (
                    ?, 'default', 0, 'Europe/Berlin', 7, 0, '[\"en\",\"de\"]', 'de', 7, 180,
                    268435456, NULL, NULL, ?, ?
                )
                """,
                (uuid_to_blob(_default_profile_id()), now, now),
            )
            for category in DEFAULT_CATEGORIES:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO news_categories (
                        category_key, label, ordinal, enabled, weight
                    ) VALUES (?, ?, ?, 1, 1.0)
                    """,
                    (category.key, category.label, category.ordinal),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO news_profile_categories (
                        profile_id, category_key, enabled, weight
                    ) VALUES (?, ?, 1, 1.0)
                    """,
                    (uuid_to_blob(_default_profile_id()), category.key),
                )
            for source in DEFAULT_SOURCES:
                source_id = _stable_uuid("news-source", source.slug)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO news_sources (
                        news_source_id, slug, name, source_class, region, language,
                        feed_url, site_url, active, priority, daily_limit,
                        perspective, independence_group, created_at_us, updated_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid_to_blob(source_id), source.slug, source.name,
                        source.source_class, source.region, source.language,
                        source.feed_url, source.site_url, int(source.enabled),
                        source.priority, source.daily_limit, source.perspective,
                        source.independence_group or source.slug, now, now,
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO news_source_states (news_source_id) VALUES (?)",
                    (uuid_to_blob(source_id),),
                )
                for category_key in source.categories:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO news_source_categories (
                            news_source_id, category_key, weight
                        ) VALUES (?, ?, 1.0)
                        """,
                        (uuid_to_blob(source_id), category_key),
                    )

    def categories(self) -> tuple[dict[str, Any], ...]:
        rows = self.database.connection.execute(
            "SELECT * FROM news_categories ORDER BY ordinal, category_key"
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def sources(self, *, active_only: bool = False) -> tuple[dict[str, Any], ...]:
        where = "WHERE active = 1" if active_only else ""
        rows = self.database.connection.execute(
            f"SELECT * FROM news_sources {where} ORDER BY priority DESC, name"
        ).fetchall()
        return tuple(_source_view(row) for row in rows)

    def add_source(
        self,
        *,
        name: str,
        feed_url: str,
        site_url: str,
        categories: Iterable[str],
        source_class: str = "alternative",
        region: str = "global",
        language: str = "en",
        perspective: str = "user configured",
        independence_group: str | None = None,
        priority: int = 50,
        daily_limit: int = 12,
    ) -> uuid.UUID:
        normalized_feed = canonicalize_url(feed_url)
        normalized_site = canonicalize_url(site_url)
        category_values = tuple(dict.fromkeys(item.strip() for item in categories if item.strip()))
        if not category_values:
            raise ValueError("News source requires at least one category.")
        if not 1 <= daily_limit <= 100:
            raise ValueError("News source daily_limit must be in [1, 100].")
        if not 0 <= priority <= 100:
            raise ValueError("News source priority must be in [0, 100].")
        if source_class not in {"primary", "mainstream", "specialist", "independent", "alternative"}:
            raise ValueError("Unsupported news source class.")
        source_id = new_uuid7()
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            for category in category_values:
                if connection.execute(
                    "SELECT 1 FROM news_categories WHERE category_key = ?", (category,)
                ).fetchone() is None:
                    raise ValueError(f"Unknown news category {category!r}.")
            slug = "user-" + source_id.hex
            connection.execute(
                """
                INSERT INTO news_sources (
                    news_source_id, slug, name, source_class, region, language,
                    feed_url, site_url, active, priority, daily_limit,
                    perspective, independence_group, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(source_id), slug, name.strip(), source_class,
                    region.strip(), language.strip(), normalized_feed, normalized_site,
                    priority, daily_limit, perspective.strip(),
                    (independence_group or slug).strip(), now, now,
                ),
            )
            connection.execute(
                "INSERT INTO news_source_states (news_source_id) VALUES (?)",
                (uuid_to_blob(source_id),),
            )
            for category in category_values:
                connection.execute(
                    "INSERT INTO news_source_categories VALUES (?, ?, 1.0)",
                    (uuid_to_blob(source_id), category),
                )
        self._invalidate_consent()
        return source_id

    def set_source_active(self, source_id: uuid.UUID, *, active: bool) -> None:
        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                "UPDATE news_sources SET active = ?, updated_at_us = ? WHERE news_source_id = ?",
                (int(active), utc_now_us(), uuid_to_blob(source_id)),
            )
            if cursor.rowcount != 1:
                raise NewsError(f"News source {source_id} not found.")
        # Host-set changes intentionally invalidate standing consent.
        self._invalidate_consent()

    def consent_and_enable(self) -> str:
        host_hash = self._active_host_hash()
        now = utc_now_us()
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_profiles
                SET enabled = 1, consent_host_hash = ?, consented_at_us = ?, updated_at_us = ?
                WHERE profile_id = ?
                """,
                (host_hash, now, now, uuid_to_blob(_default_profile_id())),
            )
        return host_hash.hex()

    def disable(self) -> None:
        with self.database.write_transaction() as connection:
            connection.execute(
                "UPDATE news_profiles SET enabled = 0, updated_at_us = ? WHERE profile_id = ?",
                (utc_now_us(), uuid_to_blob(_default_profile_id())),
            )

    def profile(self) -> dict[str, Any]:
        row = self.database.connection.execute(
            "SELECT * FROM news_profiles WHERE profile_id = ?",
            (uuid_to_blob(_default_profile_id()),),
        ).fetchone()
        if row is None:
            raise NewsError("Default news profile missing.")
        value = dict(row)
        value["profile_id"] = str(uuid_from_blob(bytes(row["profile_id"])))
        if row["consent_host_hash"] is not None:
            value["consent_host_hash"] = bytes(row["consent_host_hash"]).hex()
        return value

    def configure_profile(
        self,
        *,
        timezone_name: str | None = None,
        local_hour: int | None = None,
        local_minute: int | None = None,
        backfill_days: int | None = None,
        max_articles_per_day: int | None = None,
        max_bytes_per_day: int | None = None,
        output_language: str | None = None,
        source_languages: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        profile = self._profile_row()
        zone_name = str(profile["timezone_name"]) if timezone_name is None else timezone_name.strip()
        try:
            ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown News timezone {zone_name!r}.") from exc
        hour = int(profile["local_hour"]) if local_hour is None else local_hour
        minute = int(profile["local_minute"]) if local_minute is None else local_minute
        backfill = int(profile["backfill_days"]) if backfill_days is None else backfill_days
        max_articles = (
            int(profile["max_articles_per_day"])
            if max_articles_per_day is None else max_articles_per_day
        )
        max_bytes = int(profile["max_bytes_per_day"]) if max_bytes_per_day is None else max_bytes_per_day
        out_lang = str(profile["output_language"]) if output_language is None else output_language.strip()
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("News schedule clock time is invalid.")
        if not 1 <= backfill <= 30:
            raise ValueError("News backfill_days must be in [1, 30].")
        if not 1 <= max_articles <= 1000:
            raise ValueError("News max_articles_per_day must be in [1, 1000].")
        if not 1024 * 1024 <= max_bytes <= 2 * 1024 * 1024 * 1024:
            raise ValueError("News max_bytes_per_day must be between 1 MiB and 2 GiB.")
        if not 2 <= len(out_lang) <= 16:
            raise ValueError("News output language code is invalid.")
        languages = (
            _string_list(json.loads(str(profile["language_json"])))
            if source_languages is None
            else list(dict.fromkeys(item.strip() for item in source_languages if item.strip()))
        )
        if not languages:
            raise ValueError("News requires at least one source language.")
        with self.database.write_transaction() as connection:
            connection.execute(
                """
                UPDATE news_profiles
                SET timezone_name = ?, local_hour = ?, local_minute = ?,
                    language_json = ?, output_language = ?, backfill_days = ?,
                    max_articles_per_day = ?, max_bytes_per_day = ?, updated_at_us = ?
                WHERE profile_id = ?
                """,
                (
                    zone_name, hour, minute, _canonical_json(languages), out_lang, backfill,
                    max_articles, max_bytes, utc_now_us(), uuid_to_blob(_default_profile_id()),
                ),
            )
        return self.profile()

    def configure_category(
        self, category_key: str, *, enabled: bool | None = None, weight: float | None = None
    ) -> None:
        row = self.database.connection.execute(
            "SELECT enabled, weight FROM news_categories WHERE category_key = ?",
            (category_key,),
        ).fetchone()
        if row is None:
            raise NewsError(f"Unknown News category {category_key!r}.")
        new_enabled = bool(row["enabled"]) if enabled is None else enabled
        new_weight = float(row["weight"]) if weight is None else float(weight)
        if not 0.0 <= new_weight <= 10.0:
            raise ValueError("News category weight must be in [0, 10].")
        with self.database.write_transaction() as connection:
            connection.execute(
                "UPDATE news_categories SET enabled = ?, weight = ? WHERE category_key = ?",
                (int(new_enabled), new_weight, category_key),
            )
            connection.execute(
                """
                INSERT INTO news_profile_categories (profile_id, category_key, enabled, weight)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id, category_key) DO UPDATE SET
                    enabled = excluded.enabled, weight = excluded.weight
                """,
                (uuid_to_blob(_default_profile_id()), category_key, int(new_enabled), new_weight),
            )
