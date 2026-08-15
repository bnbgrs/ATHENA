"""Standalone ATHENA News operations without bypassing Core services."""

from __future__ import annotations

import argparse
import json
import uuid

from athena.core.application import AthenaApplication
from athena.news.runner import NewsRunner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m athena.news")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap")
    commands.add_parser("categories")
    sources = commands.add_parser("sources")
    sources.add_argument("--all", action="store_true")

    add = commands.add_parser("source-add")
    add.add_argument("name")
    add.add_argument("feed_url")
    add.add_argument("site_url")
    add.add_argument("--category", action="append", required=True)
    add.add_argument("--class", dest="source_class", default="alternative")
    add.add_argument("--region", default="global")
    add.add_argument("--language", default="en")
    add.add_argument("--perspective", default="user configured")
    add.add_argument("--independence-group")
    add.add_argument("--priority", type=int, default=50)
    add.add_argument("--daily-limit", type=int, default=12)

    source_enable = commands.add_parser("source-enable")
    source_enable.add_argument("source_id", type=uuid.UUID)
    source_disable = commands.add_parser("source-disable")
    source_disable.add_argument("source_id", type=uuid.UUID)

    category_set = commands.add_parser("category-set")
    category_set.add_argument("category_key")
    category_state = category_set.add_mutually_exclusive_group()
    category_state.add_argument("--enable", action="store_true")
    category_state.add_argument("--disable", action="store_true")
    category_set.add_argument("--weight", type=float)

    profile_set = commands.add_parser("profile-set")
    profile_set.add_argument("--timezone")
    profile_set.add_argument("--hour", type=int)
    profile_set.add_argument("--minute", type=int)
    profile_set.add_argument("--backfill-days", type=int)
    profile_set.add_argument("--max-articles", type=int)
    profile_set.add_argument("--max-bytes", type=int)
    profile_set.add_argument("--output-language")
    profile_set.add_argument("--source-language", action="append")

    commands.add_parser("consent-enable")
    commands.add_parser("disable")
    commands.add_parser("profile")
    queue = commands.add_parser("queue")
    queue.add_argument("date")
    tick = commands.add_parser("tick")
    tick.add_argument("--worker-id", default="news-runner")
    run = commands.add_parser("run")
    run.add_argument("--max-ticks", type=int)
    status = commands.add_parser("status")
    status.add_argument("date")
    commands.add_parser("digest")
    return parser


def main() -> int:
    args = _parser().parse_args()
    app = AthenaApplication()
    app.start()
    try:
        news = app.news
        if args.command == "bootstrap":
            print("ATHENA News defaults ready.")
        elif args.command == "categories":
            print(json.dumps(news.categories(), ensure_ascii=False, indent=2))
        elif args.command == "sources":
            print(json.dumps(news.sources(active_only=not args.all), ensure_ascii=False, indent=2))
        elif args.command == "source-add":
            source_id = news.add_source(
                name=args.name,
                feed_url=args.feed_url,
                site_url=args.site_url,
                categories=args.category,
                source_class=args.source_class,
                region=args.region,
                language=args.language,
                perspective=args.perspective,
                independence_group=args.independence_group,
                priority=args.priority,
                daily_limit=args.daily_limit,
            )
            print(f"News source: {source_id}")
            print("Standing network consent was invalidated; run consent-enable explicitly.")
        elif args.command == "source-enable":
            news.set_source_active(args.source_id, active=True)
            print(f"Enabled News source: {args.source_id}")
            print("Standing network consent was invalidated; run consent-enable explicitly.")
        elif args.command == "source-disable":
            news.set_source_active(args.source_id, active=False)
            print(f"Disabled News source: {args.source_id}")
            print("Standing network consent was invalidated; run consent-enable explicitly.")
        elif args.command == "category-set":
            enabled = True if args.enable else False if args.disable else None
            news.configure_category(
                args.category_key,
                enabled=enabled,
                weight=args.weight,
            )
            print(json.dumps(news.categories(), ensure_ascii=False, indent=2))
        elif args.command == "profile-set":
            profile = news.configure_profile(
                timezone_name=args.timezone,
                local_hour=args.hour,
                local_minute=args.minute,
                backfill_days=args.backfill_days,
                max_articles_per_day=args.max_articles,
                max_bytes_per_day=args.max_bytes,
                output_language=args.output_language,
                source_languages=args.source_language,
            )
            print(json.dumps(profile, ensure_ascii=False, indent=2, default=str))
        elif args.command == "consent-enable":
            print(f"Consented host-set SHA-256: {news.consent_and_enable()}")
            print("News profile enabled. New/changed source hosts require explicit consent again.")
        elif args.command == "disable":
            news.disable()
            print("News profile disabled.")
        elif args.command == "profile":
            print(json.dumps(news.profile(), ensure_ascii=False, indent=2, default=str))
        elif args.command == "queue":
            print(f"News job: {news.queue_date(args.date)}")
        elif args.command == "tick":
            runner = NewsRunner(app, news)
            print(runner.tick(worker_id=args.worker_id))
        elif args.command == "run":
            runner = NewsRunner(app, news)
            print(f"Ticks: {runner.run(max_ticks=args.max_ticks)}")
        elif args.command == "status":
            print(news.run_view(args.date))
        elif args.command == "digest":
            print(json.dumps(news.latest_digest(), ensure_ascii=False, indent=2))
        else:
            raise RuntimeError(f"Unsupported News command {args.command!r}.")
        return 0
    finally:
        app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
