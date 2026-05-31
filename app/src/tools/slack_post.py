import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from strands import tool

from src import config

logger = logging.getLogger(__name__)

_SECTION_LIMIT = 3000
_HEADER_LIMIT = 150


def _section_blocks(text: str) -> list[dict[str, Any]]:
    """Split text into mrkdwn section blocks under Slack's 3000-char limit."""
    chunks = [
        text[i : i + _SECTION_LIMIT] for i in range(0, len(text), _SECTION_LIMIT)
    ] or [""]
    return [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks]


@tool
def slack_post(channel: str, text: str, header: str = "", unfurl: bool = False) -> str:
    """Post a message to a Slack channel.

    Args:
        channel: Slack channel ID to post to (e.g. "C01ASPS8MBP").
        text: Message body in Slack mrkdwn. Use *bold*, _italic_, `code`,
            bullets with "•", and links as <https://example.com|label>.
            Do NOT use Markdown headings ("#") or "**" — Slack does not render them.
        header: Optional short plain-text title shown as a header block above the body.
        unfurl: Whether to expand link/media previews. Defaults to False to keep
            posts compact.

    Returns:
        "ok: <ts>" on success, or "error: <reason>" if the Slack API call fails.
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

    logger.info("slack_post: channel=%s header=%r unfurl=%s", channel, header, unfurl)
    try:
        response = client.chat_postMessage(
            channel=channel,
            text=header or text[:200],
            blocks=blocks,
            unfurl_links=unfurl,
            unfurl_media=unfurl,
        )
    except SlackApiError as e:
        error = e.response["error"]
        logger.error("slack_post failed for channel %s: %s", channel, error)
        return f"error: {error}"

    return f"ok: {response['ts']}"
