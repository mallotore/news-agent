from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from news_agent.config import Config, ConfigError, Topic, load_config, select_topics
from news_agent.feeds import collect_items, fetch_feed, make_client
from news_agent.llm import ClaudeCli
from news_agent.render import render_digest
from news_agent.summarize import summarize_topic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="news-agent",
        description="Generate a Markdown news digest from official feeds, summarized by an LLM.",
    )
    parser.add_argument("-c", "--config", type=Path, default=Path("config.yaml"), help="Path to config.yaml")
    parser.add_argument("-t", "--topics", help="Comma-separated topic keys (default: all topics in the config)")
    parser.add_argument("-l", "--language", help="Output language, e.g. es, en (overrides the config)")
    parser.add_argument("-m", "--model", help="Claude model alias or name, e.g. haiku, sonnet (overrides the config)")
    parser.add_argument("--hours", type=int, help="Look-back window in hours (overrides the config)")
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: <output_dir>/YYYY-MM-DD.md)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch feeds and list candidates; no LLM call, no file")
    parser.add_argument("--check-feeds", action="store_true", help="Test every configured feed URL and exit")
    return parser


def _check_feeds(topics: list[Topic], http) -> int:
    failures = 0
    for topic in topics:
        print(f"[{topic.title}]")
        for url in topic.feeds:
            try:
                items = fetch_feed(url, http)
                latest = max((i.published for i in items), default=None)
                print(f"  OK    {url}  ({len(items)} entries, latest: {latest:%Y-%m-%d})" if latest
                      else f"  OK    {url}  (0 usable entries)")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {url}  ({exc})")
    return 1 if failures else 0


def _run(config: Config, topics: list[Topic], args: argparse.Namespace) -> int:
    language = args.language or config.language
    hours = args.hours or config.lookback_hours
    now = datetime.now(timezone.utc)

    llm = None
    if not (args.dry_run or args.check_feeds):
        if shutil.which("claude") is None:
            print(
                "Error: the 'claude' CLI was not found. Install Claude Code and run `claude` once "
                "to log in with your account (or use --dry-run).",
                file=sys.stderr,
            )
            return 2
        llm = ClaudeCli(model=args.model or config.model)

    sections: list[tuple[Topic, list]] = []
    warnings: list[str] = []
    failed_topics = 0

    with make_client() as http:
        if args.check_feeds:
            return _check_feeds(topics, http)

        for topic in topics:
            print(f"- {topic.title}: fetching {len(topic.feeds)} feed(s)...", file=sys.stderr)
            items, errors = collect_items(
                topic.feeds,
                lookback_hours=hours,
                max_candidates=config.max_candidates_per_topic,
                max_items_per_feed=config.max_items_per_feed,
                now=now,
                client=http,
            )
            warnings += [f"[{topic.title}] {e}" for e in errors]

            if args.dry_run:
                print(f"\n## {topic.title} ({len(items)} candidates)")
                for item in items:
                    print(f"  {item.published:%Y-%m-%d %H:%M}  {item.source}: {item.title}\n    {item.url}")
                continue

            try:
                entries = summarize_topic(
                    llm,
                    topic_title=topic.title,
                    items=items,
                    language=language,
                    max_items=config.max_items_per_topic,
                )
            except Exception as exc:  # noqa: BLE001 - keep the other topics going
                failed_topics += 1
                warnings.append(f"[{topic.title}] summarization failed: {exc}")
                entries = []
            sections.append((topic, entries))

    if args.dry_run:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        return 0

    day = datetime.now().astimezone().date()
    path = args.output or config.output_dir / f"{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_digest(day, language, sections, warnings), encoding="utf-8")
    print(f"Digest written to {path}")
    return 1 if failed_topics == len(topics) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        keys = [k.strip() for k in args.topics.split(",") if k.strip()] if args.topics else None
        topics = select_topics(config, keys)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return _run(config, topics, args)
