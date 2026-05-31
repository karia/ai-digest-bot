from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError


def test_post_digest_calls_chat_post_message():
    from src.slack_notifier import post_digest

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_postMessage.return_value = {"ok": True}

        post_digest("CTEST12345", "テストダイジェスト", "xoxb-test")

        MockClient.assert_called_once_with(token="xoxb-test")
        instance.chat_postMessage.assert_called_once()
        call_kwargs = instance.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "CTEST12345"


def test_post_digest_uses_block_kit():
    from src.slack_notifier import post_digest

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_postMessage.return_value = {"ok": True}

        post_digest("CTEST12345", "テストダイジェスト", "xoxb-test")

        call_kwargs = instance.chat_postMessage.call_args[1]
        blocks = call_kwargs["blocks"]
        block_types = [b["type"] for b in blocks]
        assert "header" in block_types
        assert "section" in block_types


def test_post_digest_uses_title_in_header():
    from src.slack_notifier import post_digest

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_postMessage.return_value = {"ok": True}

        post_digest("CTEST12345", "test", "xoxb-test", title="AWS News Blog")

        call_kwargs = instance.chat_postMessage.call_args[1]
        header = next(b for b in call_kwargs["blocks"] if b["type"] == "header")
        assert header["text"]["text"].startswith("AWS News Blog - ")


def test_post_digest_default_title():
    from src.slack_notifier import post_digest

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_postMessage.return_value = {"ok": True}

        post_digest("CTEST12345", "test", "xoxb-test")

        call_kwargs = instance.chat_postMessage.call_args[1]
        header = next(b for b in call_kwargs["blocks"] if b["type"] == "header")
        assert header["text"]["text"].startswith("技術ダイジェスト - ")


def test_post_digest_truncates_long_text():
    from src.slack_notifier import post_digest

    long_text = "a" * 5000

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_postMessage.return_value = {"ok": True}

        post_digest("CTEST12345", long_text, "xoxb-test")

        call_kwargs = instance.chat_postMessage.call_args[1]
        section = next(b for b in call_kwargs["blocks"] if b["type"] == "section")
        assert len(section["text"]["text"]) <= 3000


def test_post_digest_raises_on_slack_error():
    from src.slack_notifier import post_digest

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        mock_response = MagicMock()
        mock_response.__getitem__ = lambda self, key: (
            "channel_not_found" if key == "error" else None
        )
        instance.chat_postMessage.side_effect = SlackApiError("error", mock_response)

        with pytest.raises(RuntimeError, match="Slack API error"):
            post_digest("CINVALID", "test", "xoxb-test")
