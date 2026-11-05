from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from news_agent.config import Config, ConfigError, Topic, load_config, select_topics
from news_agent.feeds import collect_items, fetch_feed, make_client
from news_agent.llm import ClaudeCli
from news_agent.models import Entry, Item
from news_agent.render import render_digest
from news_agent.seen import STATE_FILENAME, filter_unseen, load_seen, record_and_save
from news_agent.summarize import summarize_topic


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="news-agent",
        description="Generate a Markdown news digest from official feeds, summarized by an LLM.",
    )
    parser.add_argument("-c", "--config", type=Path, default=Path("config.yaml"), help="Path to config.yaml")
    parser.add_argument("-t", "--topics", help="Comma-separated topic keys (default: all topics in the config)")
    parser.add_argument("-l", "--language", help="Output language, e.g. es, en (overrides the config)")
    parser.add_argument("-m", "--model", help="Claude model alias or name, e.g. haiku, sonnet (overrides the config)")
    parser.add_argument("--hours", type=_positive_int, help="Look-back window in hours (overrides the config)")
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: <output_dir>/YYYY-MM-DD.md)")
    parser.add_argument("--no-dedup", action="store_true", help="Ignore and don't update the seen-URLs state file")
    parser.add_argument("--dry-run", action="store_true", help="Fetch feeds and list candidates; no LLM call, no file")
    parser.add_argument("--check-feeds", action="store_true", help="Test every configured feed URL and exit")
    return parser


def _check_feeds(topics: list[Topic], http: httpx.Client) -> int:
    failures = 0
    for topic in topics:
        print(f"[{topic.title}]")
        for url in topic.feeds:
            try:
                items = fetch_feed(url, http)
            except Exception as exc:
                failures += 1
                print(f"  FAIL  {url}  ({exc})")
                continue
            latest = max((i.published for i in items), default=None)
            detail = f"{len(items)} entries, latest: {latest:%Y-%m-%d}" if latest else "0 usable entries"
            print(f"  OK    {url}  ({detail})")
    return 1 if failures else 0


def _lookback(topic: Topic, config: Config, override: int | None) -> int:
    """Look-back window in hours: --hours beats the topic's own value, which beats the global one."""
    return override or topic.lookback_hours or config.lookback_hours


def _collect(
    topic: Topic, config: Config, override: int | None, now: datetime, http: httpx.Client
) -> tuple[list[Item], list[str]]:
    print(f"- {topic.title}: fetching {len(topic.feeds)} feed(s)...", file=sys.stderr)
    items, errors = collect_items(
        topic.feeds,
        lookback_hours=_lookback(topic, config, override),
        max_candidates=config.max_candidates_per_topic,
        max_items_per_feed=config.max_items_per_feed,
        now=now,
        client=http,
    )
    return items, [f"[{topic.title}] {error}" for error in errors]


def _dry_run(config: Config, topics: list[Topic], override: int | None, http: httpx.Client) -> int:
    now = datetime.now(UTC)
    warnings: list[str] = []
    for topic in topics:
        items, errors = _collect(topic, config, override, now, http)
        warnings += errors
        print(f"\n## {topic.title} ({len(items)} candidates)")
        for item in items:
            print(f"  {item.published:%Y-%m-%d %H:%M}  {item.source}: {item.title}\n    {item.url}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _digest(
    config: Config,
    topics: list[Topic],
    override: int | None,
    language: str,
    output: Path | None,
    http: httpx.Client,
    llm: ClaudeCli,
    dedup: bool = True,
) -> int:
    now = datetime.now(UTC)
    day = now.astimezone().date()  # fixed at start so a slow run can't roll into the next day

    sections: list[tuple[Topic, list[Entry]]] = []
    warnings: list[str] = []
    failed_topics = 0
    state_path = config.output_dir / STATE_FILENAME
    seen = load_seen(state_path) if dedup else {}

    for topic in topics:
        items, errors = _collect(topic, config, override, now, http)
        warnings += errors
        all_failed = bool(errors) and not items  # judged before dedup: "all seen" is not a failure
        items = filter_unseen(items, seen)
        if all_failed:
            # Every feed failed (e.g. offline): count it as failed without calling the LLM.
            failed_topics += 1
            sections.append((topic, []))
            continue
        try:
            entries = summarize_topic(
                llm,
                topic_title=topic.title,
                items=items,
                language=language,
                max_items=config.max_items_per_topic,
                max_per_source=config.max_items_per_source,
            )
        except Exception as exc:
            failed_topics += 1
            warnings.append(f"[{topic.title}] summarization failed: {exc}")
            entries = []
        sections.append((topic, entries))

    path = output or config.output_dir / f"{day.isoformat()}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_digest(day, language, sections, warnings), encoding="utf-8")
    except OSError as exc:
        print(f"Error: could not write {path}: {exc}", file=sys.stderr)
        return 2
    print(f"Digest written to {path}")
    if dedup:
        try:
            urls = [entry.url for _, entries in sections for entry in entries]
            # Keep entries for the longest window in use, so no topic's seen URLs are pruned too early.
            hours = max(_lookback(topic, config, override) for topic in topics)
            record_and_save(state_path, seen, urls, day, hours)
        except OSError as exc:
            print(f"warning: could not update {state_path}: {exc}", file=sys.stderr)
    return 1 if failed_topics == len(topics) else 0


def _run(config: Config, topics: list[Topic], args: argparse.Namespace) -> int:
    language = args.language or config.language

    if args.check_feeds or args.dry_run:
        with make_client() as http:
            return _check_feeds(topics, http) if args.check_feeds else _dry_run(config, topics, args.hours, http)

    if shutil.which("claude") is None:
        print(
            "Error: the 'claude' CLI was not found. Install Claude Code and run `claude` once "
            "to log in with your account (or use --dry-run).",
            file=sys.stderr,
        )
        return 2
    with make_client() as http:
        return _digest(
            config,
            topics,
            args.hours,
            language,
            args.output,
            http,
            ClaudeCli(model=args.model or config.model),
            not args.no_dedup,
        )


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
