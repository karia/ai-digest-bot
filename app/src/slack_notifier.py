import logging
from typing import Any

from slack_sdk import WebClient

from src import config

logger = logging.getLogger(__name__)

_SECTION_LIMIT = 3000
_HEADER_LIMIT = 150


def _section_blocks(text: str) -> list[dict[str, Any]]:
    """Split text into mrkdwn section blocks under Slack's 3000-char limit."""
    chunks = [text[i : i + _SECTION_LIMIT] for i in range(0, len(text), _SECTION_LIMIT)]
    return [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks]


def post_message(
    channel: str,
    text: str = "",
    header: str = "",
    thread_ts: str | None = None,
    unfurl: bool = False,
) -> str:
    """Post a message to a Slack channel and return its timestamp (``ts``).

    Args:
        channel: Slack channel ID (e.g. "C01ASPS8MBP").
        text: Message body in Slack mrkdwn. Empty for a headline-only message
            (header block with no section).
        header: Optional short plain-text title shown as a header block.
        thread_ts: When set, posts as a reply in that thread.
        unfurl: Whether to expand link/media previews. Defaults to False.

    Returns:
        The posted message ``ts``.

    Raises:
        slack_sdk.errors.SlackApiError: if the Slack API call fails.
    """
    client = WebClient(token=config.get_slack_token())

    blocks: list[dict[str, Any]] = []
    if header:
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header[:_HEADER_LIMIT]},
            }
        )
        blocks.append({"type": "divider"})
    blocks.extend(_section_blocks(text))

    logger.info(
        "post_message: channel=%s header=%r thread_ts=%s unfurl=%s",
        channel,
        header,
        thread_ts,
        unfurl,
    )
    response = client.chat_postMessage(
        channel=channel,
        text=header or text[:200],
        blocks=blocks,
        thread_ts=thread_ts,
        unfurl_links=unfurl,
        unfurl_media=unfurl,
    )
    return str(response["ts"])
