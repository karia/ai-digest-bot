from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(
        "src.tools.slack_post.config.get_slack_token", lambda: "xoxb-test"
    )


def _ok_client(MockClient):
    instance = MockClient.return_value
    instance.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.0001"}
    return instance


def test_slack_post_sends_mrkdwn_section_without_unfurl():
    from src.tools.slack_post import slack_post

    with patch("src.tools.slack_post.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        result = slack_post(
            "C123", "*hello* <https://example.com|link>", header="Title"
        )

        assert result.startswith("ok: ")
        kwargs = instance.chat_postMessage.call_args[1]
        assert kwargs["channel"] == "C123"
        assert kwargs["unfurl_links"] is False
        assert kwargs["unfurl_media"] is False
        blocks = kwargs["blocks"]
        assert blocks[0]["type"] == "header"
        section = next(b for b in blocks if b["type"] == "section")
        assert section["text"]["type"] == "mrkdwn"
        assert section["text"]["text"] == "*hello* <https://example.com|link>"


def test_slack_post_without_header_has_no_header_block():
    from src.tools.slack_post import slack_post

    with patch("src.tools.slack_post.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        slack_post("C123", "body only")

        blocks = instance.chat_postMessage.call_args[1]["blocks"]
        assert all(b["type"] != "header" for b in blocks)


def test_slack_post_splits_long_text_into_multiple_sections():
    from src.tools.slack_post import slack_post

    with patch("src.tools.slack_post.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        slack_post("C123", "a" * 7000)

        sections = [
            b
            for b in instance.chat_postMessage.call_args[1]["blocks"]
            if b["type"] == "section"
        ]
        assert len(sections) == 3
        assert all(len(s["text"]["text"]) <= 3000 for s in sections)


def test_slack_post_truncates_header():
    from src.tools.slack_post import slack_post

    with patch("src.tools.slack_post.WebClient") as MockClient:
        instance = _ok_client(MockClient)

        slack_post("C123", "body", header="h" * 200)

        header = instance.chat_postMessage.call_args[1]["blocks"][0]
        assert len(header["text"]["text"]) <= 150


def test_slack_post_returns_error_on_slack_failure():
    from src.tools.slack_post import slack_post

    with patch("src.tools.slack_post.WebClient") as MockClient:
        instance = MockClient.return_value
        mock_response = MagicMock()
        mock_response.__getitem__ = lambda self, key: (
            "channel_not_found" if key == "error" else None
        )
        instance.chat_postMessage.side_effect = SlackApiError("boom", mock_response)

        result = slack_post("CBAD", "body")

        assert result == "error: channel_not_found"
