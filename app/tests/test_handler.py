import importlib
from datetime import datetime, timedelta
from unittest.mock import patch

import boto3
import pytest


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.store as store

    importlib.reload(store)


def _put_source(title, channel_id, items):
    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-sources")
    table.put_item(
        Item={
            "title": title,
            "channel_id": channel_id,
            "items": items,
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )


def test_handler_returns_ok_with_no_sources(integrated_aws_mock):
    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-sources")
    table.delete_item(Key={"title": "Tech Digest"})

    from src.handler import lambda_handler

    result = lambda_handler({}, None)
    assert result["status"] == "ok"
    assert result["sources"] == 0


def test_handler_posts_headline_then_threaded_reply(integrated_aws_mock):
    from src.handler import lambda_handler

    scheduled_time = "2026-06-01T00:00:00Z"
    expected_until = datetime.fromisoformat(scheduled_time)
    expected_since = expected_until - timedelta(hours=24)
    url = "https://aws.amazon.com/blogs/aws/feed/"

    with (
        patch("src.handler.run_digest", return_value="digest body") as mock_run,
        patch(
            "src.handler.slack_notifier.post_message", return_value="111.222"
        ) as mock_post,
    ):
        result = lambda_handler({"scheduled_time": scheduled_time}, None)

    assert result["status"] == "ok"
    assert result["sources"] == 1
    assert result["results"][url] == "success"

    # First call is the headline-only message (header set, no body, no thread_ts)
    headline = mock_post.call_args_list[0]
    assert headline.kwargs.get("thread_ts") is None
    assert headline.kwargs["header"].startswith("Tech Digest - ")

    # run_digest is called per item with the single URL and period
    mock_run.assert_called_once_with(url, since=expected_since, until=expected_until)

    # Second call is the reply into the thread returned by the headline post
    reply = mock_post.call_args_list[1]
    assert reply.kwargs["thread_ts"] == "111.222"
    assert reply.kwargs["text"] == "digest body"
    assert reply.kwargs["header"] == "AWS News Blog"


def test_handler_posts_one_reply_per_item(integrated_aws_mock):
    _put_source(
        "Tech Digest",
        "CTEST12345",
        [
            {"url": "https://example.com/a", "name": "A"},
            {"url": "https://example.com/b", "name": "B"},
        ],
    )

    from src.handler import lambda_handler

    with (
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    # 1 headline + 2 replies
    assert mock_post.call_count == 3
    assert result["results"]["https://example.com/a"] == "success"
    assert result["results"]["https://example.com/b"] == "success"


def test_handler_continues_on_item_error(integrated_aws_mock):
    _put_source(
        "Tech Digest",
        "CTEST12345",
        [
            {"url": "https://example.com/ok", "name": "OK"},
            {"url": "https://example.com/bad", "name": "BAD"},
        ],
    )

    from src.handler import lambda_handler

    def fail_for_bad(url, since, until):
        if url == "https://example.com/bad":
            raise RuntimeError("boom")
        return "digest"

    with (
        patch("src.handler.run_digest", side_effect=fail_for_bad),
        patch("src.handler.slack_notifier.post_message", return_value="t"),
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    assert result["status"] == "ok"
    assert result["results"]["https://example.com/ok"] == "success"
    assert "error" in result["results"]["https://example.com/bad"]


def test_handler_records_error_when_headline_fails(integrated_aws_mock):
    from src.handler import lambda_handler

    with (
        patch("src.handler.run_digest", return_value="digest") as mock_run,
        patch(
            "src.handler.slack_notifier.post_message",
            side_effect=RuntimeError("slack down"),
        ),
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    # Headline failed, so no items are processed for that source
    assert "error" in result["results"]["Tech Digest"]
    mock_run.assert_not_called()


def test_parse_scheduled_time_valid_iso():
    from datetime import UTC

    from src.handler import _parse_scheduled_time

    dt = _parse_scheduled_time({"scheduled_time": "2026-06-01T00:00:00Z"})
    assert dt == datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def test_parse_scheduled_time_invalid_falls_back_to_now():
    from datetime import UTC

    from src.handler import _parse_scheduled_time

    before = datetime.now(UTC)
    dt = _parse_scheduled_time({"scheduled_time": "<aws.scheduler.scheduled-time>"})
    after = datetime.now(UTC)
    assert before <= dt <= after
