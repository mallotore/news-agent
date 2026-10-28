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
