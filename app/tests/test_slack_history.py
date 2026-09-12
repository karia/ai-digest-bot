from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

HEADER = "Tech Digest"


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr("src.slack_reader.config.get_slack_token", lambda: "xoxb-test")


@pytest.fixture(autouse=True)
def _reset_bot_user_id_cache():
    import src.slack_reader as slack_reader

    slack_reader._bot_user_id_cache = None
    yield
    slack_reader._bot_user_id_cache = None


def _message(header: str, posted_at: datetime) -> dict:
    return {
        "user": "UBOT",
        "ts": str(posted_at.timestamp()),
        "blocks": [{"type": "header", "text": {"text": header}}],
    }


def test_returns_latest_post_with_matching_header_and_ignores_other_jobs():
    from src.tools.slack_history import slack_last_bot_post

    digest_post = datetime.now(UTC) - timedelta(days=2)
    cost_post = datetime.now(UTC) - timedelta(hours=1)
    with patch("src.slack_reader.WebClient") as client:
        instance = client.return_value
        instance.auth_test.return_value = {"user_id": "UBOT"}
        instance.conversations_history.return_value = {
            "messages": [
                _message("AWS コスト 2026-09-13", cost_post),
                _message(HEADER, digest_post),
            ],
            "response_metadata": {"next_cursor": ""},
        }

        result = slack_last_bot_post("C123", HEADER)

    assert result == digest_post.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_no_matching_header_returns_existing_not_found_message():
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.slack_reader.WebClient") as client:
        instance = client.return_value
        instance.auth_test.return_value = {"user_id": "UBOT"}
        instance.conversations_history.return_value = {
            "messages": [
                _message("AWS コスト 2026-09-13", datetime.now(UTC)),
            ],
            "response_metadata": {"next_cursor": ""},
        }

        result = slack_last_bot_post("C123", HEADER, lookback_days=7)

    assert result == "No bot post found in the last 7 days."


def test_api_error_returns_existing_error_message():
    from src.tools.slack_history import slack_last_bot_post

    with patch(
        "src.tools.slack_history.slack_reader.find_last_post_time",
        side_effect=RuntimeError("missing_scope"),
    ):
        result = slack_last_bot_post("C123", HEADER)

    assert result == "Error fetching Slack history: missing_scope"
