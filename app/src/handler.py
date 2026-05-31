import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src import config
from src.agent import run_digest
from src.slack_notifier import post_digest
from src.store import get_all_feeds

logger = logging.getLogger(__name__)


def _parse_scheduled_time(event: dict[str, Any]) -> datetime:
    raw = event.get("scheduled_time")
    if raw:
        return datetime.fromisoformat(raw)
    return datetime.now(UTC)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    token = config.get_slack_token()
    feeds = get_all_feeds()

    if not feeds:
        logger.info("No feeds found in DynamoDB")
        return {"status": "ok", "feeds": 0}

    until = _parse_scheduled_time(event)
    since = until - timedelta(hours=24)

    results: dict[str, str] = {}

    for feed in feeds:
        try:
            digest = run_digest([feed["feed_url"]], since=since, until=until)
            post_digest(feed["channel_id"], digest, token, title=feed["name"])
            results[feed["feed_url"]] = "success"
        except Exception as e:
            logger.error("Failed for feed %s: %s", feed["feed_url"], e)
            results[feed["feed_url"]] = f"error: {e}"

    return {"status": "ok", "feeds": len(feeds), "results": results}
