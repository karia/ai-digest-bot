import importlib
from unittest.mock import MagicMock, patch

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
    assert result["channels"] == 0


def test_handler_processes_feeds_and_posts(integrated_aws_mock):
    from src.handler import lambda_handler

    mock_digest = "テストダイジェスト"
    with (
        patch("src.handler.run_digest", return_value=mock_digest) as mock_run,
        patch("src.handler.post_digest") as mock_post,
    ):
        result = lambda_handler({}, None)

    assert result["status"] == "ok"
    assert result["channels"] == 1
    mock_run.assert_called_once()
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "CTEST12345"
    assert call_args[0][1] == mock_digest


def test_handler_continues_on_channel_error(integrated_aws_mock):
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-feeds")
    table.put_item(
        Item={
            "feed_url": "https://example.com/feed/",
            "name": "Example",
            "category": "other",
            "channel_id": "COTHER999",
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    from src.handler import lambda_handler

    def fail_for_channel(channel_id: str, digest: str, token: str) -> None:
        if channel_id == "CTEST12345":
            raise RuntimeError("Slack error")

    with (
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.post_digest", side_effect=fail_for_channel),
    ):
        result = lambda_handler({}, None)

    assert result["status"] == "ok"
    assert result["channels"] == 2
    assert "error" in result["results"]["CTEST12345"]
    assert result["results"]["COTHER999"] == "success"
