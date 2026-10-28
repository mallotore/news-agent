from datetime import datetime, timedelta, timezone

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("feedparser")

from news_agent.feeds import clean_text, collect_items, fetch_feed, normalize_url  # noqa: E402

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def rfc822(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def rss(items):
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link><pubDate>{rfc822(d)}</pubDate>"
        f"<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>"
        for t, link, d in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>{body}</channel></rss>'


def client_for(feeds):
    def handler(request):
        url = str(request.url)
        if url in feeds:
            return httpx.Response(200, content=feeds[url].encode())
        return httpx.Response(500)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_clean_text_and_normalize_url():
    assert clean_text("<p>Hello&nbsp;<b>world</b></p>\n  ok") == "Hello world ok"
    assert normalize_url("https://A.test/post/?utm_source=x&id=1#frag") == "https://a.test/post?id=1"


def test_fetch_feed_parses_and_strips_html():
    feeds = {"https://a.test/f": rss([("Post", "https://a.test/p", NOW)])}
    items = fetch_feed("https://a.test/f", client_for(feeds))
    assert items[0].title == "Post"
    assert items[0].summary == "Hello world"
    assert items[0].source == "Feed"


def test_collect_filters_dedupes_caps_and_survives_failures():
    old = NOW - timedelta(days=10)
    feeds = {
        "https://a.test/f": rss([
            ("New", "https://a.test/new", NOW - timedelta(hours=1)),
            ("Dup", "https://a.test/same?utm_source=x", NOW - timedelta(hours=2)),
            ("Old", "https://a.test/old", old),
        ]),
        "https://b.test/f": rss([("Dup again", "https://a.test/same", NOW - timedelta(hours=3))]),
    }
    items, errors = collect_items(
        ["https://a.test/f", "https://b.test/f", "https://broken.test/f"],
        lookback_hours=48,
        max_candidates=10,
        max_items_per_feed=10,
        now=NOW,
        client=client_for(feeds),
    )
    assert [i.title for i in items] == ["New", "Dup"]
    assert len(errors) == 1 and "broken.test" in errors[0]
