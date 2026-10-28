import pytest

from news_agent.config import ConfigError, load_config, select_topics

VALID = """
language: en
topics:
  ai:
    title: AI
    feeds: [https://example.com/a.xml]
  java:
    feeds: [https://example.com/j.xml]
"""


def write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_config_with_defaults(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.language == "en"
    assert config.lookback_hours == 48
    assert config.output_dir == (tmp_path / "news").resolve()
    assert config.topics["java"].title == "java"  # title defaults to the key


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    "text",
    [
        "topics: {}",
        "topics:\n  ai:\n    feeds: []",
        "topics:\n  ai: {title: x}",
        "lookback_hours: 0\ntopics:\n  ai:\n    feeds: [https://x.test/f]",
        "- just a list",
    ],
)
def test_invalid_configs(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_select_topics(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert [t.key for t in select_topics(config, None)] == ["ai", "java"]
    assert [t.key for t in select_topics(config, ["java"])] == ["java"]
    with pytest.raises(ConfigError, match="Unknown topic"):
        select_topics(config, ["nope"])
