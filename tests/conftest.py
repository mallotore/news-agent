from datetime import UTC, datetime

import pytest

from news_agent.models import Item


@pytest.fixture
def make_items():
    """Factory for `n` consecutive feed items with predictable titles and URLs."""

    def factory(n: int = 3) -> list[Item]:
        return [
            Item(
                title=f"Title {i}",
                url=f"https://official.example/{i}",
                source="Official Blog",
                published=datetime(2026, 10, 28, 8, i, tzinfo=UTC),
                summary=f"Excerpt {i}",
            )
            for i in range(n)
        ]

    return factory
