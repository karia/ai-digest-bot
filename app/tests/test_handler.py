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


@pytest.fixture(autouse=True)
def mock_run_plan():
    """Allow posting with the 24h-fallback window unless a test overrides it."""
    from src.agent import DigestPlan

    with patch(
        "src.handler.run_plan",
        return_value=DigestPlan(should_post=True, since=None, reason="毎日"),
    ) as mock:
        yield mock


def _put_source(title, channel_id, items, posting_schedule=None):
    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    table = dynamodb.Table("test-sources")
    item = {
        "title": title,
        "channel_id": channel_id,
        "items": items,
        "inserted_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    if posting_schedule is not None:
        item["posting_schedule"] = posting_schedule
    table.put_item(Item=item)


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

    # The headline is generated from every completed digest body and the window
    mock_headline.assert_called_once_with(
        [("AWS News Blog", "digest body")], since=expected_since, until=expected_until
    )

    # First post is the thread parent: generated summary + date-less header
    # (the digest window is shown in the headline body instead)
    headline = mock_post.call_args_list[0]
    assert headline.kwargs.get("thread_ts") is None
    assert headline.kwargs["text"] == "headline summary"
    assert headline.kwargs["header"] == "Tech Digest"

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
    until = datetime.fromisoformat("2026-06-01T00:00:00Z")
    mock_headline.assert_called_once_with(
        [("OK", "digest")], since=until - timedelta(hours=24), until=until
    )
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
    assert headline.kwargs["header"] == "Tech Digest"
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


def test_handler_uses_plan_since_for_digest(integrated_aws_mock, mock_run_plan):
    from datetime import UTC

    from src.agent import DigestPlan
    from src.handler import lambda_handler

    plan_since = datetime(2026, 5, 28, 1, 23, 45, tzinfo=UTC)
    mock_run_plan.return_value = DigestPlan(
        should_post=True, since=plan_since, reason="前回投稿から"
    )

    with (
        patch("src.handler.run_digest", return_value="digest") as mock_run,
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t"),
    ):
        lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    mock_run.assert_called_once_with(
        "https://aws.amazon.com/blogs/aws/feed/",
        since=plan_since,
        until=datetime.fromisoformat("2026-06-01T00:00:00Z"),
    )


def test_handler_skips_source_not_scheduled_today(integrated_aws_mock, mock_run_plan):
    from src.agent import DigestPlan
    from src.handler import lambda_handler

    mock_run_plan.return_value = DigestPlan(
        should_post=False, since=None, reason="本日は投稿対象日ではない"
    )

    with (
        patch("src.handler.run_digest") as mock_run,
        patch("src.handler.slack_notifier.post_message") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    assert result["results"]["Tech Digest"] == "skipped: 本日は投稿対象日ではない"
    mock_run.assert_not_called()
    mock_post.assert_not_called()


def test_handler_falls_back_to_24h_when_plan_fails(integrated_aws_mock, mock_run_plan):
    from src.handler import lambda_handler

    mock_run_plan.side_effect = RuntimeError("bedrock down")
    scheduled_time = "2026-06-01T00:00:00Z"
    expected_until = datetime.fromisoformat(scheduled_time)

    with (
        patch("src.handler.run_digest", return_value="digest") as mock_run,
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t"),
    ):
        result = lambda_handler({"scheduled_time": scheduled_time}, None)

    # The digest still runs, degraded to the fixed 24h window
    mock_run.assert_called_once_with(
        "https://aws.amazon.com/blogs/aws/feed/",
        since=expected_until - timedelta(hours=24),
        until=expected_until,
    )
    assert result["results"]["https://aws.amazon.com/blogs/aws/feed/"] == "success"


def test_handler_passes_schedule_to_plan(integrated_aws_mock, mock_run_plan):
    _put_source(
        "Tech Digest",
        "CTEST12345",
        [{"url": "https://example.com/a", "name": "A"}],
        posting_schedule="月曜と木曜",
    )

    from src.handler import lambda_handler

    with (
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t"),
    ):
        lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    mock_run_plan.assert_called_once_with(
        "CTEST12345", "月曜と木曜", datetime.fromisoformat("2026-06-01T00:00:00Z")
    )


def test_handler_passes_default_schedule_when_field_missing(
    integrated_aws_mock, mock_run_plan
):
    # SAMPLE_SOURCE in conftest has no posting_schedule (pre-#28 record)
    from src.handler import lambda_handler

    with (
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t"),
    ):
        lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    assert mock_run_plan.call_args[0][1] == "毎日"


def test_handler_splits_daily_item_into_one_reply_per_day(integrated_aws_mock):
    from datetime import date

    from src.agent import DailyDigest
    from src.handler import lambda_handler

    _put_source(
        "Tech Digest",
        "CTEST12345",
        [
            {
                "url": "https://example.com/whatsnew",
                "name": "What's New",
                "split_by_day": True,
            }
        ],
    )
    days = [
        DailyDigest(date=date(2026, 6, 9), body="day1 body"),
        DailyDigest(date=date(2026, 6, 10), body="day2 body"),
    ]

    with (
        patch("src.handler.run_daily_digests", return_value=days),
        patch("src.handler.run_headline", return_value="summary") as mock_headline,
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-11T00:00:00Z"}, None)

    # 1 headline + 1 reply per day
    assert mock_post.call_count == 3
    day1, day2 = mock_post.call_args_list[1], mock_post.call_args_list[2]
    assert day1.kwargs["header"] == "What's New (06/09)"
    assert day1.kwargs["text"] == "day1 body"
    assert day2.kwargs["header"] == "What's New (06/10)"
    assert day2.kwargs["text"] == "day2 body"
    assert result["results"]["https://example.com/whatsnew"] == "success"
    # The headline input carries the per-day names
    assert mock_headline.call_args[0][0] == [
        ("What's New (06/09)", "day1 body"),
        ("What's New (06/10)", "day2 body"),
    ]


def test_handler_posts_no_reply_for_daily_item_without_articles(integrated_aws_mock):
    from src.handler import lambda_handler

    _put_source(
        "Tech Digest",
        "CTEST12345",
        [
            {
                "url": "https://example.com/whatsnew",
                "name": "What's New",
                "split_by_day": True,
            },
            {"url": "https://example.com/a", "name": "A"},
        ],
    )

    with (
        patch("src.handler.run_daily_digests", return_value=[]),
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-11T00:00:00Z"}, None)

    # headline + the normal item's reply only; nothing for the empty daily item
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[1].kwargs["header"] == "A"
    assert result["results"]["https://example.com/whatsnew"] == "no articles"
    assert result["results"]["https://example.com/a"] == "success"


def test_handler_records_error_when_daily_digest_fails(integrated_aws_mock):
    from src.handler import lambda_handler

    _put_source(
        "Tech Digest",
        "CTEST12345",
        [
            {
                "url": "https://example.com/whatsnew",
                "name": "What's New",
                "split_by_day": True,
            },
            {"url": "https://example.com/a", "name": "A"},
        ],
    )

    with (
        patch("src.handler.run_daily_digests", side_effect=RuntimeError("boom")),
        patch("src.handler.run_digest", return_value="digest"),
        patch("src.handler.run_headline", return_value="summary"),
        patch("src.handler.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        result = lambda_handler({"scheduled_time": "2026-06-11T00:00:00Z"}, None)

    # The failed daily item is skipped; the normal item is still posted
    assert "error" in result["results"]["https://example.com/whatsnew"]
    assert result["results"]["https://example.com/a"] == "success"
    assert mock_post.call_count == 2


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
