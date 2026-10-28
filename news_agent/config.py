from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    feeds: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    language: str
    model: str
    lookback_hours: int
    max_items_per_topic: int
    max_candidates_per_topic: int
    max_items_per_feed: int
    output_dir: Path
    topics: dict[str, Topic]


def _positive_int(raw: dict, key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"'{key}' must be a positive integer, got {value!r}")
    return value


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("The config file must contain a YAML mapping")

    topics_raw = raw.get("topics")
    if not isinstance(topics_raw, dict) or not topics_raw:
        raise ConfigError("'topics' must be a non-empty mapping")

    topics: dict[str, Topic] = {}
    for key, value in topics_raw.items():
        feeds = value.get("feeds") if isinstance(value, dict) else None
        if not isinstance(feeds, list) or not feeds or not all(isinstance(f, str) for f in feeds):
            raise ConfigError(f"Topic '{key}' needs a non-empty 'feeds' list of URLs")
        topics[str(key)] = Topic(
            key=str(key),
            title=str(value.get("title", key)),
            feeds=tuple(feeds),
        )

    return Config(
        language=str(raw.get("language", "en")),
        model=str(raw.get("model", "haiku")),
        lookback_hours=_positive_int(raw, "lookback_hours", 48),
        max_items_per_topic=_positive_int(raw, "max_items_per_topic", 5),
        max_candidates_per_topic=_positive_int(raw, "max_candidates_per_topic", 30),
        max_items_per_feed=_positive_int(raw, "max_items_per_feed", 10),
        # Relative paths are resolved against the config file, not the current directory.
        output_dir=(path.parent / str(raw.get("output_dir", "news"))).resolve(),
        topics=topics,
    )


def select_topics(config: Config, keys: list[str] | None) -> list[Topic]:
    """Return the requested topics (all of them when `keys` is empty)."""
    if not keys:
        return list(config.topics.values())
    unknown = [k for k in keys if k not in config.topics]
    if unknown:
        available = ", ".join(config.topics)
        raise ConfigError(f"Unknown topic(s): {', '.join(unknown)}. Available: {available}")
    return [config.topics[k] for k in keys]
