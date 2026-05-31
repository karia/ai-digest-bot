import logging
from datetime import date

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


def post_digest(
    channel_id: str,
    digest_text: str,
    token: str,
    title: str = "技術ダイジェスト",
) -> None:
    client = WebClient(token=token)
    today = date.today().strftime("%Y年%m月%d日")
    logger.info("Posting digest to channel %s (title: %s)", channel_id, title)

    try:
        client.chat_postMessage(
            channel=channel_id,
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{title} - {today}",
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": digest_text[:3000],
                    },
                },
            ],
        )
    except SlackApiError as e:
        err = e.response["error"]
        logger.error("Slack API error for channel %s: %s", channel_id, err)
        raise RuntimeError(f"Slack API error: {err}") from e
