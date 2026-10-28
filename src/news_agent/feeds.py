from __future__ import annotations

import html
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx

from news_agent.models import Item

USER_AGENT = "news-agent/0.1 (personal local use)"
MAX_WORKERS = 8
# Tolerate small clock differences, but drop items dated in the future.
_FUTURE_TOLERANCE = timedelta(hours=1)
_TAG_RE = re.compile(r"<[^>]+>")


def _by_date(item: Item) -> datetime:
    return item.published


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
    feed_urls: Sequence[str],
    *,
    lookback_hours: int,
    max_candidates: int,
    max_items_per_feed: int,
    now: datetime,
    client: httpx.Client,
) -> tuple[list[Item], list[str]]:
    """Fetch all feeds of a topic and return (recent de-duplicated candidates, error messages).

    A failing feed never aborts the run: it is reported and the others continue.
    """
    cutoff = now - timedelta(hours=lookback_hours)
    latest = now + _FUTURE_TOLERANCE
    errors: list[str] = []
    candidates: list[Item] = []

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(feed_urls) or 1)) as pool:
        futures = [(url, pool.submit(fetch_feed, url, client)) for url in feed_urls]
        for url, future in futures:
            try:
                items = future.result()
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            recent = sorted((i for i in items if cutoff <= i.published <= latest), key=_by_date, reverse=True)
            # Cap per feed so one very chatty source cannot crowd out the others.
            candidates += recent[:max_items_per_feed]

    # Newest first; the first occurrence of each canonical URL wins.
    unique: dict[str, Item] = {}
    for item in sorted(candidates, key=_by_date, reverse=True):
        unique.setdefault(normalize_url(item.url), item)
    return list(unique.values())[:max_candidates], errors
