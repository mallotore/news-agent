from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

from news_agent import cli
from news_agent.models import Item

CONFIG = """
language: en
output_dir: out
topics:
  ai:
    title: AI
    feeds: [https://example.com/a.xml]
  java:
    title: Java
    feeds: [https://example.com/j.xml]
"""


@pytest.fixture(autouse=True)
def no_real_http_client(monkeypatch):
    """Network calls are stubbed per test; don't build a real client (loads the system CA bundle)."""
    monkeypatch.setattr(cli, "make_client", lambda: nullcontext(None))


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def item():
    return Item("Title", "https://example.com/p", "Blog", datetime.now(UTC), "Excerpt")


@pytest.fixture
def stub_network(monkeypatch, item):
    monkeypatch.setattr(cli, "collect_items", lambda *a, **kw: ([item], []))
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")


def fake_llm(monkeypatch, *, fail_topics=()):
    class Llm:
        def __init__(self, model):
            self.model = model

        def complete_json(self, *, system, prompt, schema):
            if any(f"Topic: {title}" in prompt for title in fail_topics):
                raise RuntimeError("boom")
            return {"entries": [{"id": 0, "headline": "H", "context": "C", "why_interesting": "W"}]}

    monkeypatch.setattr(cli, "ClaudeCli", Llm)


def test_unknown_topic_and_missing_config_exit_with_2(config_path, tmp_path, capsys):
    assert cli.main(["-c", str(config_path), "-t", "nope"]) == 2
    assert cli.main(["-c", str(tmp_path / "missing.yaml")]) == 2
    assert "Unknown topic" in capsys.readouterr().err


def test_hours_must_be_positive(config_path):
    with pytest.raises(SystemExit):
        cli.main(["-c", str(config_path), "--hours", "0"])


def test_dry_run_lists_candidates_and_writes_nothing(config_path, stub_network, tmp_path, capsys):
    assert cli.main(["-c", str(config_path), "--dry-run"]) == 0
    assert "## AI (1 candidates)" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_missing_claude_cli_exits_with_2(config_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.main(["-c", str(config_path)]) == 2
    assert "'claude' CLI was not found" in capsys.readouterr().err


def test_digest_is_written_to_output_file(config_path, stub_network, monkeypatch, tmp_path):
    fake_llm(monkeypatch)
    target = tmp_path / "digest.md"
    assert cli.main(["-c", str(config_path), "-o", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert "## AI" in text and "## Java" in text
    assert "[Blog](https://example.com/p)" in text


def test_one_failing_topic_is_reported_but_run_succeeds(config_path, stub_network, monkeypatch, tmp_path):
    fake_llm(monkeypatch, fail_topics=("AI",))
    target = tmp_path / "digest.md"
    assert cli.main(["-c", str(config_path), "-o", str(target)]) == 0
    assert "[AI] summarization failed: boom" in target.read_text(encoding="utf-8")


def test_all_topics_failing_returns_1(config_path, stub_network, monkeypatch, tmp_path):
    fake_llm(monkeypatch, fail_topics=("AI", "Java"))
    assert cli.main(["-c", str(config_path), "-o", str(tmp_path / "digest.md")]) == 1


def test_hours_rejects_non_numeric(config_path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["-c", str(config_path), "--hours", "abc"])
    assert "must be a positive integer" in capsys.readouterr().err


def test_hours_and_model_overrides_reach_collaborators(config_path, monkeypatch, item, tmp_path):
    seen = {}

    def collect(*a, **kw):
        seen["hours"] = kw["lookback_hours"]
        return [item], []

    class Llm:
        def __init__(self, model):
            seen["model"] = model

        def complete_json(self, **kw):
            return {"entries": []}

    monkeypatch.setattr(cli, "collect_items", collect)
    monkeypatch.setattr(cli, "ClaudeCli", Llm)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert cli.main(["-c", str(config_path), "--hours", "7", "-m", "haiku", "-o", str(tmp_path / "d.md")]) == 0
    assert seen == {"hours": 7, "model": "haiku"}


def test_check_feeds_reports_ok_and_fail(config_path, monkeypatch, item, capsys):
    def fetch(url, http):
        if url.endswith("j.xml"):
            raise RuntimeError("down")
        return [item]

    monkeypatch.setattr(cli, "fetch_feed", fetch)
    assert cli.main(["-c", str(config_path), "--check-feeds"]) == 1
    out = capsys.readouterr().out
    assert "OK    https://example.com/a.xml" in out and "latest:" in out
    assert "FAIL  https://example.com/j.xml" in out


def test_all_feeds_failing_returns_1_without_calling_llm(config_path, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "collect_items", lambda *a, **kw: ([], ["feed: offline"]))
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    fake_llm(monkeypatch, fail_topics=("AI", "Java"))  # would fail the run if it were called
    target = tmp_path / "digest.md"
    assert cli.main(["-c", str(config_path), "-o", str(target)]) == 1
    assert "feed: offline" in target.read_text(encoding="utf-8")


def test_unwritable_output_exits_with_2(config_path, stub_network, monkeypatch, tmp_path, capsys):
    fake_llm(monkeypatch)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert cli.main(["-c", str(config_path), "-o", str(blocker / "digest.md")]) == 2
    assert "could not write" in capsys.readouterr().err


def test_seen_urls_are_skipped_on_next_run_unless_no_dedup(config_path, stub_network, monkeypatch, tmp_path):
    fake_llm(monkeypatch)
    target = tmp_path / "digest.md"
    args = ["-c", str(config_path), "-o", str(target)]
    assert cli.main(args) == 0
    assert (tmp_path / "out" / ".seen.json").exists()
    assert "[Blog](" in target.read_text(encoding="utf-8")

    assert cli.main(args) == 0  # same candidates: all already seen
    assert "[Blog](" not in target.read_text(encoding="utf-8")

    assert cli.main([*args, "--no-dedup"]) == 0
    assert "[Blog](" in target.read_text(encoding="utf-8")


def test_partially_failed_topic_with_only_seen_items_is_not_a_failure(config_path, monkeypatch, item, tmp_path):
    monkeypatch.setattr(cli, "collect_items", lambda *a, **kw: ([item], ["feed down"]))
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    fake_llm(monkeypatch)
    args = ["-c", str(config_path), "-o", str(tmp_path / "digest.md")]
    assert cli.main(args) == 0  # first run records the URL
    assert cli.main(args) == 0  # second run: item seen, one feed failed -> still not a total failure


def test_topic_lookback_beats_global_and_hours_flag_beats_both(tmp_path, monkeypatch, item):
    config = tmp_path / "config.yaml"
    config.write_text(
        CONFIG.replace("language: en", "language: en\nlookback_hours: 48").replace(
            "feeds: [https://example.com/j.xml]", "feeds: [https://example.com/j.xml]\n    lookback_hours: 240"
        ),
        encoding="utf-8",
    )
    used = []
    monkeypatch.setattr(cli, "collect_items", lambda feeds, **kw: used.append(kw["lookback_hours"]) or ([item], []))
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    fake_llm(monkeypatch)
    out = ["-o", str(tmp_path / "d.md")]

    assert cli.main(["-c", str(config), *out]) == 0
    assert used == [48, 240]  # ai: global, java: its own

    used.clear()
    assert cli.main(["-c", str(config), "--hours", "5", *out]) == 0
    assert used == [5, 5]


def test_seen_state_keeps_urls_for_the_longest_topic_window(tmp_path, monkeypatch, item):
    config = tmp_path / "config.yaml"
    config.write_text(
        CONFIG.replace(
            "feeds: [https://example.com/j.xml]", "feeds: [https://example.com/j.xml]\n    lookback_hours: 240"
        ),
        encoding="utf-8",
    )
    saved = []
    monkeypatch.setattr(cli, "record_and_save", lambda path, seen, urls, today, hours: saved.append(hours))
    monkeypatch.setattr(cli, "collect_items", lambda *a, **kw: ([item], []))
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    fake_llm(monkeypatch)
    assert cli.main(["-c", str(config), "-o", str(tmp_path / "d.md")]) == 0
    assert saved == [240]
