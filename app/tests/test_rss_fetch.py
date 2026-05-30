from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def make_entry(title: str, link: str, published_parsed: tuple | None) -> MagicMock:
    entry = MagicMock()
    entry.get = lambda key, default="N/A": {"title": title, "link": link}.get(key, default)
    entry.title = title
    entry.link = link
    entry.summary = "Test summary"
    if published_parsed is not None:
        entry.published_parsed = published_parsed
    else:
        del entry.published_parsed
    return entry


@pytest.fixture
def recent_entry():
    dt = datetime(2026, 5, 30, 1, 0, 0, tzinfo=timezone.utc)
    return make_entry("Recent Article", "https://example.com/recent", dt.timetuple()[:6])


@pytest.fixture
def old_entry():
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return make_entry("Old Article", "https://example.com/old", dt.timetuple()[:6])


def test_rss_fetch_returns_recent_articles(recent_entry):
    from src.tools.rss_fetch import rss_fetch

    mock_feed = MagicMock()
    mock_feed.entries = [recent_entry]

    with patch("feedparser.parse", return_value=mock_feed):
        result = rss_fetch("https://example.com/feed/")

    assert "Recent Article" in result
    assert "https://example.com/recent" in result


def test_rss_fetch_excludes_old_articles(old_entry):
    from src.tools.rss_fetch import rss_fetch

    mock_feed = MagicMock()
    mock_feed.entries = [old_entry]

    with patch("feedparser.parse", return_value=mock_feed):
        result = rss_fetch("https://example.com/feed/")

    assert result == "No recent articles found."


def test_rss_fetch_no_articles():
    from src.tools.rss_fetch import rss_fetch

    mock_feed = MagicMock()
    mock_feed.entries = []

    with patch("feedparser.parse", return_value=mock_feed):
        result = rss_fetch("https://example.com/feed/")

    assert result == "No recent articles found."


def test_rss_fetch_handles_error():
    from src.tools.rss_fetch import rss_fetch

    with patch("feedparser.parse", side_effect=Exception("Network error")):
        result = rss_fetch("https://example.com/feed/")

    assert "Error" in result
