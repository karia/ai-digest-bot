import logging
from typing import Any

from src import config
from src.agent import run_digest
from src.slack_notifier import post_digest
from src.store import get_all_feeds, group_by_channel

logger = logging.getLogger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    token = config.get_slack_token()
    feeds = get_all_feeds()

    if not feeds:
        logger.info("No feeds found in DynamoDB")
        return {"status": "ok", "channels": 0}

    groups = group_by_channel(feeds)
    results: dict[str, str] = {}

    for channel_id, channel_feeds in groups.items():
        urls = [f["feed_url"] for f in channel_feeds]
        try:
            digest = run_digest(urls)
            post_digest(channel_id, digest, token)
            results[channel_id] = "success"
        except Exception as e:
            logger.error("Failed for channel %s: %s", channel_id, e)
            results[channel_id] = f"error: {e}"

    return {"status": "ok", "channels": len(groups), "results": results}
