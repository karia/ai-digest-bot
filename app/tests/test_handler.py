import importlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

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


def test_handler_posts_summary_headline_then_threaded_reply(integrated_aws_mock):
    from src.handler import lambda_handler

    scheduled_time = "2026-06-01T00:00:00Z"
    expected_until = datetime.fromisoformat(scheduled_time)
    expected_since = expected_until - timedelta(hours=24)
    url = "https://aws.amazon.com/blogs/aws/feed/"

    with (
        patch("src.handler.run_digest", return_value="digest body") as mock_run,
        patch(
            "src.handler.run_headline", return_value="headline summary"
        ) as mock_headline,
        patch(
            "src.handler.slack_notifier.post_message", return_value="111.222"
        ) as mock_post,
    ):
        result = lambda_handler({"scheduled_time": scheduled_time}, None)

    assert result["status"] == "ok"
    assert result["sources"] == 1
    assert result["results"][url] == "success"

    # run_digest is called per item with the single URL and period
    mock_run.assert_called_once_with(url, since=expected_since, until=expected_until)

    # The headline is generated from every completed digest body
    mock_headline.assert_called_once_with([("AWS News Blog", "digest body")])

    # First post is the thread parent: generated summary + dated header
    headline = mock_post.call_args_list[0]
    assert headline.kwargs.get("thread_ts") is None
    assert headline.kwargs["text"] == "headline summary"
    assert headline.kwargs["header"].startswith("Tech Digest - ")

    # Second post is the reply into the thread returned by the headline post
    reply = mock_post.call_args_list[1]
    assert reply.kwargs["thread_ts"] == "111.222"
    assert reply.kwargs["text"] == "digest body"
    assert reply.kwargs["header"] == "AWS News Blog"


def test_handler_generates_all_digests_before_posting(integrated_aws_mock):
    _put_source(
        "Tech Digest",
        "CTEST12345",
        [
            {"url": "https://example.com/a", "name": "A"},
            {"url": "https://example.com/b", "name": "B"},
        ],
    )

    from src.handler import lambda_handler

    manager = MagicMock()
    with (
        patch("src.handler.run_digest", return_value="digest") as mock_run,
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        manager.attach_mock(mock_run, "run_digest")
        manager.attach_mock(mock_post, "post_message")
        lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    # Every digest is generated before the first Slack post (the headline
    # must summarize the whole thread).
    names = [c[0] for c in manager.mock_calls]
    first_post = names.index("post_message")
    assert names[:first_post].count("run_digest") == 2


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
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    # 1 headline + 2 replies
    assert mock_post.call_count == 3
    assert result["results"]["https://example.com/a"] == "success"
    assert result["results"]["https://example.com/b"] == "success"


def test_handler_excludes_failed_digest_from_headline_and_replies(
    integrated_aws_mock,
):
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
        patch("src.handler.run_headline", return_value="summary") as mock_headline,
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    assert result["status"] == "ok"
    assert result["results"]["https://example.com/ok"] == "success"
    assert "error" in result["results"]["https://example.com/bad"]
    # The failed item is excluded from the headline input and gets no reply
    mock_headline.assert_called_once_with([("OK", "digest")])
    assert mock_post.call_count == 2  # headline + 1 reply


def test_handler_falls_back_to_empty_headline_on_generation_error(
    integrated_aws_mock,
):
    from src.handler import lambda_handler

    with (
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.run_headline", side_effect=RuntimeError("bedrock down")),
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    # The thread is still posted, with a header-only parent message
    headline = mock_post.call_args_list[0]
    assert headline.kwargs["text"] == ""
    assert headline.kwargs["header"].startswith("Tech Digest - ")
    assert result["results"]["https://aws.amazon.com/blogs/aws/feed/"] == "success"


def test_handler_records_error_when_headline_post_fails(integrated_aws_mock):
    from src.handler import lambda_handler

    with (
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.run_headline", return_value="summary"),
        patch(
            "src.handler.slack_notifier.post_message",
            side_effect=RuntimeError("slack down"),
        ) as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    # Headline post failed, so no replies are attempted for that source
    assert "error" in result["results"]["Tech Digest"]
    assert mock_post.call_count == 1


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
