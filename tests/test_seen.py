from datetime import UTC, date, datetime

from news_agent.models import Item
from news_agent.seen import filter_unseen, load_seen, record_and_save


def make_item(url):
    return Item("T", url, "S", datetime.now(UTC), "x")


def test_missing_or_corrupt_state_is_empty(tmp_path):
    assert load_seen(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_seen(bad) == {}


def test_filter_uses_normalized_urls(tmp_path):
    seen = {"https://example.com/p": date(2026, 11, 1)}
    items = [make_item("https://Example.com/p/?utm_source=x#frag"), make_item("https://example.com/other")]
    assert [i.url for i in filter_unseen(items, seen)] == ["https://example.com/other"]


def test_record_keeps_first_seen_and_prunes_old(tmp_path):
    path = tmp_path / "sub" / ".seen.json"
    seen = {"https://example.com/old": date(2026, 10, 1), "https://example.com/a": date(2026, 11, 2)}
    record_and_save(path, seen, ["https://example.com/a", "https://example.com/b"], date(2026, 11, 4), 72)
    loaded = load_seen(path)
    assert loaded == {"https://example.com/a": date(2026, 11, 2), "https://example.com/b": date(2026, 11, 4)}
