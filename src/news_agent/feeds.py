from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx

from news_agent.models import Item

USER_AGENT = "news-agent/0.1 (personal local use)"
_TAG_RE = re.compile(r"<[^>]+>")


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def clean_text(raw: str | None, limit: int = 500) -> str:
    """Strip HTML tags, collapse whitespace and truncate."""
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def normalize_url(url: str) -> str:
    """Canonical form used for de-duplication (drops fragments, utm_* params, trailing slash)."""
    parts = urlparse(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")])
    path = parts.path.rstrip("/") or "/"
    return urlunparse((parts.scheme, parts.netloc.lower(), path, "", query, ""))


def _entry_datetime(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=UTC)  # type: ignore[misc]
    return None


def fetch_feed(url: str, client: httpx.Client) -> list[Item]:
    """Download and parse one RSS/Atom feed. Items without a date or http(s) link are skipped."""
    response = client.get(url)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed ({parsed.bozo_exception})")

    source = clean_text(parsed.feed.get("title"), 80) or urlparse(url).hostname or url
    items: list[Item] = []
    for entry in parsed.entries:
        link = entry.get("link") or ""
        title = clean_text(entry.get("title"), 300)
        published = _entry_datetime(entry)
        if urlparse(link).scheme not in ("http", "https") or not title or published is None:
            continue
        summary = clean_text(entry.get("summary") or entry.get("description"))
        items.append(Item(title=title, url=link, source=source, published=published, summary=summary))
    return items


def collect_items(
    feed_urls: tuple[str, ...] | list[str],
    *,
    lookback_hours: int,
    max_candidates: int,
    max_items_per_feed: int,
    now: datetime,
    client: httpx.Client,
) -> tuple[list[Item], list[str]]:
    """Fetch all feeds of a topic and return (recent, de-duplicated candidates, error messages).

    A failing feed never aborts the run: it is reported and the others continue.
    """
    cutoff = now - timedelta(hours=lookback_hours)
    errors: list[str] = []
    per_feed: list[list[Item]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [(url, pool.submit(fetch_feed, url, client)) for url in feed_urls]
        for url, future in futures:
            try:
                recent = [i for i in future.result() if cutoff <= i.published <= now + timedelta(hours=1)]
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            recent.sort(key=lambda i: i.published, reverse=True)
            # Cap per feed so one very chatty source cannot crowd out the others.
            per_feed.append(recent[:max_items_per_feed])

    seen: set[str] = set()
    merged: list[Item] = []
    for item in sorted((i for feed in per_feed for i in feed), key=lambda i: i.published, reverse=True):
        key = normalize_url(item.url)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:max_candidates], errors
