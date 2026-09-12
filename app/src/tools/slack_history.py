import logging
from datetime import UTC

from strands import tool

from src import slack_reader

logger = logging.getLogger(__name__)


@tool
def slack_last_bot_post(channel: str, header: str, lookback_days: int = 14) -> str:
    """Find the timestamp of this bot's most recent post with a Slack header.

    Only top-level channel messages matching ``header`` are searched.

    Args:
        channel: Slack channel ID (e.g. "C01ASPS8MBP").
        header: Exact header of the digest headline post.
        lookback_days: How many days back to search. Defaults to 14.

    Returns:
        The post time as an ISO 8601 UTC datetime string, a message saying
        no bot post was found in the lookback window, or an error message.
    """
    logger.debug(
        "slack_last_bot_post: channel=%s header=%r lookback_days=%d",
        channel,
        header,
        lookback_days,
    )
    not_found = f"No bot post found in the last {lookback_days} days."

    try:
        posted_at = slack_reader.find_last_post_time(channel, header, lookback_days)
        if posted_at is None:
            return not_found
        return posted_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        logger.warning("slack_last_bot_post failed for %s: %s", channel, e)
        return f"Error fetching Slack history: {e}"
