from datetime import UTC, date, datetime

from news_agent.config import Topic
from news_agent.models import Entry
from news_agent.render import render_digest


def entry(**overrides):
    data = dict(
        headline="Java 26 | released",
        context="Line one\nline two",
        why_interesting="Matters",
        url="https://openjdk.org/projects/jdk/26/",
        source="Inside Java",
        published=datetime(2026, 10, 27, tzinfo=UTC),
    )
    data.update(overrides)
    return Entry(**data)


def test_table_structure_and_escaping():
    topic = Topic("java", "Java", ("https://x.test/f",))
    md = render_digest(date(2026, 10, 28), "en", [(topic, [entry()])], [])
    assert md.startswith("# News digest - 2026-10-28")
    assert "## Java" in md
    assert "| Headline | Context | Why it's interesting | Official link |" in md
    assert "Java 26 \\| released" in md  # pipe escaped
    assert "Line one line two" in md  # newline flattened
    assert "[Inside Java](https://openjdk.org/projects/jdk/26/) · 2026-10-27" in md


def test_empty_topic_and_warnings():
    topic = Topic("ai", "AI", ("https://x.test/f",))
    md = render_digest(date(2026, 10, 28), "en", [(topic, [])], ["[AI] https://x.test/f: timeout"])
    assert "_No relevant recent news found._" in md
    assert "## Warnings" in md and "timeout" in md
