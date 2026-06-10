from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(
        "src.slack_notifier.config.get_slack_token", lambda: "xoxb-test"
    )


def _ok_client(MockClient):
    instance = MockClient.return_value
    instance.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.0001"}
    return instance


def test_post_message_returns_ts_and_sends_mrkdwn_section():
    from src.slack_notifier import post_message

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        result = post_message(
            "C123", "*hello* <https://example.com|link>", header="Title"
        )

        assert result == "1700000000.0001"
        kwargs = instance.chat_postMessage.call_args[1]
        assert kwargs["channel"] == "C123"
        assert kwargs["thread_ts"] is None
        assert kwargs["unfurl_links"] is False
        blocks = kwargs["blocks"]
        assert blocks[0]["type"] == "header"
        section = next(b for b in blocks if b["type"] == "section")
        assert section["text"]["text"] == "*hello* <https://example.com|link>"


def test_post_message_headline_only_has_no_section():
    from src.slack_notifier import post_message

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        post_message("C123", header="Headline")

        blocks = instance.chat_postMessage.call_args[1]["blocks"]
        assert blocks[0]["type"] == "header"
        assert all(b["type"] != "section" for b in blocks)


def test_post_message_passes_thread_ts():
    from src.slack_notifier import post_message

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        post_message("C123", "body", thread_ts="111.222")

        assert instance.chat_postMessage.call_args[1]["thread_ts"] == "111.222"


def test_post_message_splits_long_text_into_multiple_sections():
    from src.slack_notifier import post_message

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        post_message("C123", "a" * 7000)

        sections = [
            b
            for b in instance.chat_postMessage.call_args[1]["blocks"]
            if b["type"] == "section"
        ]
        assert len(sections) == 3
        assert all(len(s["text"]["text"]) <= 3000 for s in sections)


def test_post_message_truncates_header():
    from src.slack_notifier import post_message

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        post_message("C123", "body", header="h" * 200)

        header = instance.chat_postMessage.call_args[1]["blocks"][0]
        assert len(header["text"]["text"]) <= 150


def test_post_message_raises_on_slack_failure():
    from src.slack_notifier import post_message

    with patch("src.slack_notifier.WebClient") as MockClient:
        instance = MockClient.return_value
        mock_response = MagicMock()
        mock_response.__getitem__ = lambda self, key: (
            "channel_not_found" if key == "error" else None
        )
        instance.chat_postMessage.side_effect = SlackApiError("boom", mock_response)

        with pytest.raises(SlackApiError):
            post_message("CBAD", "body")
