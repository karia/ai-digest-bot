import importlib
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

UNTIL = datetime(2026, 8, 19, 0, 0, tzinfo=UTC)

SOURCE = {
    "title": "Tech Digest",
    "channel_id": "CTEST12345",
    "items": [
        {"url": "https://example.com/a.rss", "name": "Feed A"},
        {"url": "https://example.com/b.rss", "name": "Feed B"},
    ],
}


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.digest as digest

    importlib.reload(digest)


@pytest.fixture
def posted():
    calls: list[dict] = []

    def fake_post(channel, text, header=None, thread_ts=None, **kwargs):
        calls.append({"text": text, "header": header, "thread_ts": thread_ts})
        return "1234.5678"

    with patch("src.digest.slack_notifier.post_message", side_effect=fake_post):
        yield calls


def test_posts_failure_notice_when_every_item_fails(posted, caplog):
    from src.digest import run_digest_job

    boom = RuntimeError("AccessDeniedException: Model access is denied")

    with (
        patch("src.digest.get_all_sources", return_value=[SOURCE]),
        patch("src.digest.run_plan", side_effect=boom),
        patch("src.digest.run_digest", side_effect=boom),
        patch("src.digest.run_headline", side_effect=boom),
        caplog.at_level("ERROR"),
    ):
        run_digest_job(UNTIL)

    assert len(posted) == 1
    body = posted[0]["text"]
    assert "失敗" in body
    assert "Feed A" in body and "Feed B" in body
    assert "AccessDeniedException" in body
    assert "ダイジェストを生成できませんでした" in caplog.text


def test_normal_run_posts_headline_and_replies(posted):
    from src.digest import run_digest_job

    with (
        patch("src.digest.get_all_sources", return_value=[SOURCE]),
        patch("src.digest.run_plan", side_effect=RuntimeError("no plan")),
        patch("src.digest.run_digest", return_value="body"),
        patch("src.digest.run_headline", return_value="headline"),
    ):
        run_digest_job(UNTIL)

    assert [c["text"] for c in posted] == ["headline", "body", "body"]
    assert posted[0]["thread_ts"] is None
    assert all(c["thread_ts"] == "1234.5678" for c in posted[1:])


def test_partial_failure_still_posts_headline(posted):
    from src.digest import run_digest_job

    with (
        patch("src.digest.get_all_sources", return_value=[SOURCE]),
        patch("src.digest.run_plan", side_effect=RuntimeError("no plan")),
        patch("src.digest.run_digest", side_effect=[RuntimeError("nope"), "body"]),
        patch("src.digest.run_headline", return_value="headline"),
    ):
        run_digest_job(UNTIL)

    assert [c["text"] for c in posted] == ["headline", "body"]
