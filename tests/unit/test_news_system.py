from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.models import JobState
from athena.news.defaults import DEFAULT_CATEGORIES, DEFAULT_SOURCES
from athena.news.feed import (
    FeedParseError,
    canonicalize_url,
    parse_discovery_payload,
    parse_feed,
)
from athena.news.models import NewsConsentRequired
from athena.news.service import NewsService


def _app(tmp_path: Path) -> AthenaApplication:
    app = AthenaApplication(AthenaSettings(local_root=tmp_path / "runtime"))
    app.start()
    return app


def test_default_taxonomy_has_22_editable_categories_and_diverse_source_classes(tmp_path: Path) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        categories = news.categories()
        assert len(categories) == 22
        assert len({row["category_key"] for row in categories}) == 22
        assert [row["ordinal"] for row in categories] == list(range(1, 23))
        sources = news.sources()
        classes = {row["source_class"] for row in sources}
        assert {"primary", "mainstream", "specialist", "independent", "alternative"} <= classes
        assert len({row["region"] for row in sources}) >= 4
        assert news.profile()["enabled"] == 0
    finally:
        app.stop()



def test_web_discovery_keeps_only_same_host_article_candidates() -> None:
    payload = b"""<!doctype html><html><body>
    <nav><a href='/about'>About us</a></nav>
    <article><h2><a href='/news/story?utm_source=front'>Important local story</a></h2></article>
    <article><a href='https://evil.example/news/injected'>Injected external story</a></article>
    <h2><a href='/story/second?fbclid=tracking'>Second useful story</a></h2>
    </body></html>"""
    items = parse_discovery_payload(payload, source_url="https://news.example/world")
    assert [item.canonical_url for item in items] == [
        "https://news.example/news/story",
        "https://news.example/story/second",
    ]
    assert [item.title for item in items] == [
        "Important local story",
        "Second useful story",
    ]
    assert all(item.published_at_us is None for item in items)


def test_news_sitemap_discovery_preserves_publication_time_and_normalizes_url() -> None:
    payload = b"""<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'
            xmlns:news='http://www.google.com/schemas/sitemap-news/0.9'>
      <url>
        <loc>https://news.example/article/one?utm_campaign=x</loc>
        <news:news>
          <news:publication_date>2026-08-15T07:30:00Z</news:publication_date>
          <news:title>One verified sitemap headline</news:title>
        </news:news>
      </url>
      <url><loc>https://evil.example/article/injected</loc></url>
    </urlset>"""
    items = parse_discovery_payload(payload, source_url="https://news.example/sitemap.xml")
    assert len(items) == 1
    assert items[0].canonical_url == "https://news.example/article/one"
    assert items[0].title == "One verified sitemap headline"
    assert items[0].published_at_us is not None


def test_starter_catalog_references_only_declared_categories() -> None:
    keys = {item.key for item in DEFAULT_CATEGORIES}
    assert len(keys) == 22
    assert DEFAULT_SOURCES
    for source in DEFAULT_SOURCES:
        assert source.categories
        assert set(source.categories) <= keys
        assert source.feed_url.startswith("https://")
        assert source.site_url.startswith("https://")


def test_feed_parser_normalizes_tracking_and_rejects_dtd() -> None:
    payload = b"""<?xml version='1.0'?>
    <rss version='2.0'><channel><item>
      <title> Example headline </title>
      <link>https://Example.COM/story?utm_source=x&amp;b=2&amp;a=1#frag</link>
      <description> short summary </description>
      <pubDate>Sat, 15 Aug 2026 05:00:00 GMT</pubDate>
    </item></channel></rss>"""
    items = parse_feed(payload, feed_url="https://example.com/feed.xml")
    assert len(items) == 1
    assert items[0].canonical_url == "https://example.com/story?a=1&b=2"
    assert items[0].published_at_us is not None
    with pytest.raises(FeedParseError):
        parse_feed(
            b"<!DOCTYPE rss [<!ENTITY x 'boom'>]><rss><channel/></rss>",
            feed_url="https://example.com/feed.xml",
        )


def test_atom_parser_and_url_credential_rejection() -> None:
    payload = b"""<?xml version='1.0'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry><title>Atom title</title>
      <link rel='alternate' href='/story'/>
      <updated>2026-08-15T05:00:00Z</updated>
      <summary>Atom summary</summary></entry>
    </feed>"""
    items = parse_feed(payload, feed_url="https://example.org/feed")
    assert items[0].canonical_url == "https://example.org/story"
    with pytest.raises(FeedParseError):
        canonicalize_url("https://user:pass@example.org/story")


def test_standing_consent_is_host_bound_and_source_change_invalidates_it(tmp_path: Path) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        digest = news.consent_and_enable()
        assert len(digest) == 64
        assert news.profile()["enabled"] == 1
        assert news.profile()["consent_host_hash"] == digest
        news.add_source(
            name="User alternative source",
            feed_url="https://new-source.invalid/feed.xml",
            site_url="https://new-source.invalid/",
            categories=("media", "politics"),
        )
        assert news.profile()["consent_host_hash"] is None
        with pytest.raises(NewsConsentRequired):
            news.schedule_due(
                now=datetime(2026, 8, 15, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
            )
    finally:
        app.stop()


def test_due_backfill_is_durable_idempotent_and_writes_no_canonical_knowledge(tmp_path: Path) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        news.consent_and_enable()
        before = (
            app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0],
            app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
        )
        now = datetime(2026, 8, 15, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        first = news.schedule_due(now=now)
        second = news.schedule_due(now=now)
        assert len(first) == 7
        assert second == ()
        assert app.database.connection.execute("SELECT COUNT(*) FROM news_runs").fetchone()[0] == 7
        jobs = app.database.connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE job_type = 'news.daily'"
        ).fetchone()[0]
        assert jobs == 7
        after = (
            app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0],
            app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
        )
        assert after == before
    finally:
        app.stop()


def test_discovery_capture_uses_web_snapshots_then_waits_for_research(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        # Keep this test bounded to one fake publisher and one day.
        with app.database.write_transaction() as connection:
            connection.execute("UPDATE news_sources SET active = 0")
            connection.execute(
                """
                UPDATE news_sources SET active = 1, daily_limit = 5
                WHERE slug = 'bbc-world'
                """
            )
            connection.execute(
                """
                UPDATE news_profiles SET backfill_days = 1, max_articles_per_day = 5
                WHERE name = 'default'
                """
            )
        news.consent_and_enable()

        feed = tmp_path / "feed.xml"
        feed.write_text(
            """<?xml version='1.0'?><rss version='2.0'><channel>
            <item><title>One</title><link>https://www.bbc.com/news/one</link>
            <pubDate>Sat, 15 Aug 2026 05:00:00 GMT</pubDate></item>
            <item><title>Two</title><link>https://www.bbc.com/news/two?utm_source=x</link>
            <pubDate>Sat, 15 Aug 2026 06:00:00 GMT</pubDate></item>
            </channel></rss>""",
            encoding="utf-8",
        )
        article = tmp_path / "article.html"
        article.write_text("<html><body>Article evidence</body></html>", encoding="utf-8")

        def fake_capture(_authorization_id: object, url: str, **_kwargs: object):
            path = feed if "rss.xml" in url else article
            return app.sources.capture_external_snapshot(path, source_uri=url)

        monkeypatch.setattr(app.external_access, "capture_url", fake_capture)

        def fake_research(**_kwargs: object):
            return app.jobs.create(
                job_type="research.exhaustive",
                requested_scope={"test": True},
                pinned_configuration={"test": True},
            )

        monkeypatch.setattr(app.research, "enqueue_local", fake_research)
        job_id = news.queue_date("2026-08-15")
        leased = app.jobs.acquire(job_id, worker_id="test-news", lease_seconds=300)
        state = news.process_leased(leased)
        assert state.state is JobState.WAITING
        view = news.run_view("2026-08-15")
        assert view is not None
        assert view.state == "researching"
        assert view.discovered_count == 2
        assert view.captured_count == 1
        rows = app.database.connection.execute(
            """
            SELECT source.source_type, discovery.dedup_state
            FROM news_discoveries AS discovery
            JOIN sources AS source ON source.source_id = discovery.article_source_id
            WHERE discovery.run_id = ?
            ORDER BY discovery.discovery_id
            """,
            (view.run_id.bytes,),
        ).fetchall()
        assert [str(row["source_type"]) for row in rows] == ["web_snapshot", "web_snapshot"]
        assert sorted(str(row["dedup_state"]) for row in rows) == [
            "exact_duplicate",
            "unique",
        ]
        assert app.database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 0
        assert app.database.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
        auth = app.database.connection.execute(
            "SELECT privacy_route, origin FROM external_access_authorizations ORDER BY created_at_us DESC LIMIT 1"
        ).fetchone()
        assert auth is not None
        assert tuple(auth) == ("tor_preferred", "explicit_user")
    finally:
        app.stop()


def test_closed_week_and_month_rollups_are_scheduled_once(tmp_path: Path) -> None:
    app = _app(tmp_path)
    try:
        news = NewsService(app)
        news.start()
        news.consent_and_enable()
        monday = datetime(2026, 8, 17, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        created = news.schedule_due(now=monday)
        assert len(created) == 8  # seven daily backfill jobs + previous closed week
        weekly = app.database.connection.execute(
            "SELECT period_start, period_end FROM news_period_runs WHERE period_kind = 'weekly'"
        ).fetchone()
        assert weekly is not None
        assert tuple(weekly) == ("2026-08-10", "2026-08-16")
        assert news.schedule_due(now=monday) == ()

        first = datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        news.schedule_due(now=first)
        monthly = app.database.connection.execute(
            "SELECT period_start, period_end FROM news_period_runs WHERE period_kind = 'monthly'"
        ).fetchone()
        assert monthly is not None
        assert tuple(monthly) == ("2026-08-01", "2026-08-31")
    finally:
        app.stop()
