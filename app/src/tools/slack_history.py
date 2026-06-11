import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_sdk import WebClient
from strands import tool

from src import config

logger = logging.getLogger(__name__)

_bot_user_id_cache: str | None = None


def _get_bot_user_id(client: WebClient) -> str:
    global _bot_user_id_cache
    if _bot_user_id_cache is None:
        _bot_user_id_cache = str(client.auth_test()["user_id"])
    return _bot_user_id_cache


@tool
def slack_last_bot_post(channel: str, lookback_days: int = 14) -> str:
    """Find the timestamp of this bot's most recent post in a Slack channel.

    Only top-level channel messages are searched; thread replies are not,
    so the result marks the bot's last digest headline post.

    Args:
        channel: Slack channel ID (e.g. "C01ASPS8MBP").
        lookback_days: How many days back to search. Defaults to 14.

    Returns:
        The post time as an ISO 8601 UTC datetime string, a message saying
        no bot post was found in the lookback window, or an error message.
    """
    logger.debug(
        "slack_last_bot_post: channel=%s lookback_days=%d", channel, lookback_days
    )
    client = WebClient(token=config.get_slack_token())
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    not_found = f"No bot post found in the last {lookback_days} days."

    try:
        bot_user_id = _get_bot_user_id(client)
        cursor: str | None = None
        while True:
            # Passing `oldest` anchors pagination at the old end of the range
            # (the first page holds the oldest messages), which would make the
            # first match the bot's *oldest* post in a busy channel. Leaving it
            # out keeps pagination anchored at the newest message and the
            # lookback window is enforced client-side via `cutoff` instead.
            response = client.conversations_history(
                channel=channel,
                limit=200,
                cursor=cursor,
            )
            # Messages come newest-first, so the first match is the latest post.
            # System messages (e.g. channel_join) carry a subtype and also have
            # user == bot, so only subtype-less ones count as real posts.
            for message in response["messages"]:
                ts = datetime.fromtimestamp(float(message["ts"]), tz=UTC)
                if ts < cutoff:
                    return not_found
                if message.get("user") == bot_user_id and "subtype" not in message:
                    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
            metadata: dict[str, Any] = response.get("response_metadata") or {}
            cursor = metadata.get("next_cursor")
            if not cursor:
                return not_found
    except Exception as e:
        logger.warning("slack_last_bot_post failed for %s: %s", channel, e)
        return f"Error fetching Slack history: {e}"
