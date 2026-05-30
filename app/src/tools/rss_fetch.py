import logging
from datetime import UTC, datetime, timedelta

import feedparser
from strands import tool

logger = logging.getLogger(__name__)


@tool
def rss_fetch(url: str) -> str:
    """Fetch an RSS/Atom feed and return articles published in the last 24 hours.

    Args:
        url: The URL of the RSS or Atom feed to fetch.

    Returns:
        A formatted string with title, link, and description for each recent article,
        or a message indicating no recent articles were found.
    """
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        return f"Error fetching RSS feed: {e}"

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    results: list[str] = []

    for entry in feed.entries:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            pub = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            if pub < cutoff:
                continue
        results.append(
            f"Title: {entry.get('title', 'N/A')}\n"
            f"Link: {entry.get('link', 'N/A')}\n"
            f"Summary: {entry.get('summary', entry.get('description', 'N/A'))[:500]}"
        )

    if not results:
        return "No recent articles found."
    return "\n---\n".join(results)
