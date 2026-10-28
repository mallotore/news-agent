from __future__ import annotations

from datetime import date

from news_agent.config import Topic
from news_agent.models import Entry


def _cell(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def render_digest(
    day: date,
    language: str,
    sections: list[tuple[Topic, list[Entry]]],
    warnings: list[str],
) -> str:
    lines = [f"# News digest - {day.isoformat()}", "", f"_Language: {language}_", ""]

    for topic, entries in sections:
        lines += [f"## {topic.title}", ""]
        if not entries:
            lines += ["_No relevant recent news found._", ""]
            continue
        lines += [
            "| Headline | Context | Why it's interesting | Official link |",
            "|---|---|---|---|",
        ]
        for e in entries:
            link = f"[{_cell(e.source)}]({e.url.replace(')', '%29')}) · {e.published:%Y-%m-%d}"
            lines.append(f"| {_cell(e.headline)} | {_cell(e.context)} | {_cell(e.why_interesting)} | {link} |")
        lines.append("")

    if warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]

    return "\n".join(lines)
