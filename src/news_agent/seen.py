from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from news_agent.feeds import normalize_url
from news_agent.models import Item

STATE_FILENAME = ".seen.json"


def load_seen(path: Path) -> dict[str, date]:
    """Read the URL -> first-seen date map. A missing or corrupt file means 'nothing seen yet'."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(url): date.fromisoformat(day) for url, day in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def filter_unseen(items: list[Item], seen: dict[str, date]) -> list[Item]:
    return [item for item in items if normalize_url(item.url) not in seen]


def record_and_save(path: Path, seen: dict[str, date], urls: list[str], today: date, lookback_hours: int) -> None:
    """Add the digest URLs, prune entries older than the lookback window and write the file."""
    updated = dict(seen)
    for url in urls:
        updated.setdefault(normalize_url(url), today)
    cutoff = today - timedelta(hours=lookback_hours, days=1)  # +1 day: first-seen dates have day granularity
    pruned = {url: day for url, day in updated.items() if day >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({u: d.isoformat() for u, d in sorted(pruned.items())}, indent=2), encoding="utf-8")
