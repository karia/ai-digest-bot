from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(
        "src.tools.slack_history.config.get_slack_token", lambda: "xoxb-test"
    )


@pytest.fixture(autouse=True)
def _reset_bot_user_id_cache():
    import src.tools.slack_history as slack_history

    slack_history._bot_user_id_cache = None
    yield
    slack_history._bot_user_id_cache = None


def _ts(days_ago: float) -> str:
    return f"{(datetime.now(UTC) - timedelta(days=days_ago)).timestamp():.4f}"


def _expected(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _client(MockClient, messages, user_id="UBOT", next_cursor=""):
    instance = MockClient.return_value
    instance.auth_test.return_value = {"ok": True, "user_id": user_id}
    instance.conversations_history.return_value = {
        "ok": True,
        "messages": messages,
        "response_metadata": {"next_cursor": next_cursor},
    }
    return instance


def test_returns_latest_bot_post_skipping_other_users():
    from src.tools.slack_history import slack_last_bot_post

    latest_bot_ts = _ts(2)
    with patch("src.tools.slack_history.WebClient") as MockClient:
        _client(
            MockClient,
            [
                {"user": "UHUMAN", "ts": _ts(1)},
                {"user": "UBOT", "ts": latest_bot_ts},
                {"user": "UBOT", "ts": _ts(3)},
            ],
        )

        result = slack_last_bot_post("C123")

        assert result == _expected(latest_bot_ts)


def test_skips_bot_system_messages_like_channel_join():
    from src.tools.slack_history import slack_last_bot_post

    post_ts = _ts(2)
    with patch("src.tools.slack_history.WebClient") as MockClient:
        _client(
            MockClient,
            [
                {"user": "UBOT", "ts": _ts(1), "subtype": "channel_join"},
                {"user": "UBOT", "ts": post_ts},
            ],
        )

        result = slack_last_bot_post("C123")

        assert result == _expected(post_ts)


def test_no_bot_post_returns_not_found_message():
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.tools.slack_history.WebClient") as MockClient:
        _client(MockClient, [{"user": "UHUMAN", "ts": _ts(1)}])

        result = slack_last_bot_post("C123")

        assert result == "No bot post found in the last 14 days."


def test_oldest_is_not_passed_to_api():
    # Passing `oldest` anchors pagination at the old end of the range, so the
    # lookback window must be enforced client-side instead (see tool source).
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.tools.slack_history.WebClient") as MockClient:
        instance = _client(MockClient, [])

        slack_last_bot_post("C123", lookback_days=7)

        kwargs = instance.conversations_history.call_args[1]
        assert kwargs["channel"] == "C123"
        assert "oldest" not in kwargs


def test_bot_post_older_than_lookback_is_not_returned():
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.tools.slack_history.WebClient") as MockClient:
        _client(MockClient, [{"user": "UBOT", "ts": _ts(8)}])

        result = slack_last_bot_post("C123", lookback_days=7)

        assert result == "No bot post found in the last 7 days."


def test_stops_at_lookback_cutoff_without_following_cursor():
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.tools.slack_history.WebClient") as MockClient:
        instance = _client(
            MockClient,
            [{"user": "UHUMAN", "ts": _ts(15)}],
            next_cursor="cursor-1",
        )

        result = slack_last_bot_post("C123")

        assert result == "No bot post found in the last 14 days."
        assert instance.conversations_history.call_count == 1


def test_paginates_until_bot_post_found():
    from src.tools.slack_history import slack_last_bot_post

    bot_ts = _ts(2)
    with patch("src.tools.slack_history.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.auth_test.return_value = {"ok": True, "user_id": "UBOT"}
        instance.conversations_history.side_effect = [
            {
                "ok": True,
                "messages": [{"user": "UHUMAN", "ts": _ts(1)}],
                "response_metadata": {"next_cursor": "cursor-1"},
            },
            {
                "ok": True,
                "messages": [{"user": "UBOT", "ts": bot_ts}],
                "response_metadata": {"next_cursor": ""},
            },
        ]

        result = slack_last_bot_post("C123")

        assert result == _expected(bot_ts)
        assert instance.conversations_history.call_count == 2
        assert instance.conversations_history.call_args[1]["cursor"] == "cursor-1"


def test_bot_user_id_is_cached_across_calls():
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.tools.slack_history.WebClient") as MockClient:
        instance = _client(MockClient, [{"user": "UBOT", "ts": _ts(1)}])

        slack_last_bot_post("C123")
        slack_last_bot_post("C123")

        assert instance.auth_test.call_count == 1


def test_api_error_returns_error_message():
    from src.tools.slack_history import slack_last_bot_post

    with patch("src.tools.slack_history.WebClient") as MockClient:
        instance = MockClient.return_value
        instance.auth_test.side_effect = RuntimeError("missing_scope")

        result = slack_last_bot_post("C123")

        assert result.startswith("Error fetching Slack history:")
        assert "missing_scope" in result
