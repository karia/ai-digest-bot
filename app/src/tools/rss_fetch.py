import logging
from datetime import UTC, datetime

import feedparser
from strands import tool

logger = logging.getLogger(__name__)


@tool
def rss_fetch(url: str, since: str, until: str) -> str:
    """Fetch an RSS/Atom feed and return articles published between since and until.

    Args:
        url: The URL of the RSS or Atom feed to fetch.
        since: ISO 8601 UTC datetime string (inclusive lower bound).
        until: ISO 8601 UTC datetime string (inclusive upper bound).

    Returns:
        A formatted string with title, link, and description for each article in range,
        or a message indicating no articles were found in the range.
    """
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        return f"Error fetching RSS feed: {e}"

    since_dt = datetime.fromisoformat(since)
    until_dt = datetime.fromisoformat(until)
    results: list[str] = []

    for entry in feed.entries:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            t = entry.published_parsed
            pub = datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=UTC)
            if pub < since_dt or pub > until_dt:
                continue
        results.append(
            f"Title: {entry.get('title', 'N/A')}\n"
            f"Link: {entry.get('link', 'N/A')}\n"
            f"Summary: {entry.get('summary', entry.get('description', 'N/A'))[:500]}"
        )

    if not results:
        return "No recent articles found."
    return "\n---\n".join(results)
