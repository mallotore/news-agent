from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Item:
    """A raw item read from a feed. The URL always comes from the feed itself."""

    title: str
    url: str
    source: str
    published: datetime
    summary: str


@dataclass(frozen=True)
class Entry:
    """A summarized row of the final table. The URL is copied from the source Item."""

    headline: str
    context: str
    why_interesting: str
    url: str
    source: str
    published: datetime
