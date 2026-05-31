import importlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.store as store

    importlib.reload(store)


def test_handler_returns_ok_with_no_feeds(integrated_aws_mock):
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-feeds")
    table.delete_item(Key={"feed_url": "https://aws.amazon.com/blogs/aws/feed/"})

    from src.handler import lambda_handler

    result = lambda_handler({}, None)
    assert result["status"] == "ok"
    assert result["feeds"] == 0


def test_handler_processes_feed_via_run_digest(integrated_aws_mock):
    from src.handler import lambda_handler

    scheduled_time = "2026-06-01T00:00:00Z"
    expected_until = datetime.fromisoformat(scheduled_time)
    expected_since = expected_until - timedelta(hours=24)

    with patch("src.handler.run_digest", return_value="digest") as mock_run:
        result = lambda_handler({"scheduled_time": scheduled_time}, None)

    assert result["status"] == "ok"
    assert result["feeds"] == 1
    feed_url = "https://aws.amazon.com/blogs/aws/feed/"
    mock_run.assert_called_once_with(
        [feed_url],
        since=expected_since,
        until=expected_until,
        channel="CTEST12345",
        title="AWS News Blog",
    )
    assert result["results"][feed_url] == "success"


def test_handler_processes_each_feed(integrated_aws_mock):
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-feeds")
    table.put_item(
        Item={
            "feed_url": "https://example.com/feed/",
            "name": "Example",
            "channel_id": "CTEST12345",
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    from src.handler import lambda_handler

    with patch("src.handler.run_digest", return_value="digest") as mock_run:
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    assert result["feeds"] == 2
    assert mock_run.call_count == 2


def test_handler_continues_on_feed_error(integrated_aws_mock):
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-feeds")
    table.put_item(
        Item={
            "feed_url": "https://example.com/feed/",
            "name": "Example",
            "channel_id": "COTHER999",
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    from src.handler import lambda_handler

    def fail_for_feed(urls, since, until, channel, title):
        if title == "AWS News Blog":
            raise RuntimeError("boom")
        return "digest"

    with patch("src.handler.run_digest", side_effect=fail_for_feed):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    assert result["status"] == "ok"
    assert result["feeds"] == 2
    assert "error" in result["results"]["https://aws.amazon.com/blogs/aws/feed/"]
    assert result["results"]["https://example.com/feed/"] == "success"


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
