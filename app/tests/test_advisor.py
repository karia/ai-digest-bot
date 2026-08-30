import importlib
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from src.nav import NavPoint

NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)  # 2026-07-24 17:00 JST
ISIN = "JP90C000H1T1"
SERIES = [
    NavPoint(date=date(2026, 7, 23), nav=38000),
    NavPoint(date=date(2026, 7, 24), nav=38243),
]


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.advisor_store as advisor_store

    importlib.reload(advisor_store)
    import src.advisor as advisor

    importlib.reload(advisor)


def _advice(judgment: str = "HOLD", summary: str = "USD/JPY は 163 円台。"):
    from src.agent import AdviceResult, ProductAdvice

    return AdviceResult(
        summary=summary,
        advices=[ProductAdvice(isin=ISIN, judgment=judgment, reason="円安一服のため")],
    )


def test_skips_when_already_posted_today(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=NOW),
        patch("src.advisor.run_advice") as mock_advice,
        patch("src.advisor.slack_notifier.post_message") as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert "skipped" in result["results"]["ideco-sbi"]
    mock_advice.assert_not_called()
    mock_post.assert_not_called()


def test_skips_before_the_interval_elapses(integrated_aws_mock):
    from src.advisor import run_advisor_job

    last = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

    with (
        patch("src.advisor.find_last_post_time", return_value=last),
        patch("src.advisor.run_advice") as mock_advice,
        patch("src.advisor.slack_notifier.post_message"),
    ):
        result = run_advisor_job(NOW)

    assert "skipped" in result["results"]["ideco-sbi"]
    mock_advice.assert_not_called()


def test_posts_a_thread_when_due(integrated_aws_mock):
    from src.advisor import DISCLAIMER, run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch(
            "src.advisor.slack_notifier.post_message", return_value="111.222"
        ) as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert result["status"] == "ok"
    assert result["advisors"] == 1
    assert result["results"]["ideco-sbi"] == "success"

    # 1 parent + 1 reply per product
    assert mock_post.call_count == 2
    parent = mock_post.call_args_list[0]
    assert parent.kwargs["header"] == "iDeCo 投資判断"
    assert parent.kwargs.get("thread_ts") is None
    assert "USD/JPY は 163 円台。" in parent.kwargs["text"]
    assert DISCLAIMER in parent.kwargs["text"]

    reply = mock_post.call_args_list[1]
    assert reply.kwargs["thread_ts"] == "111.222"
    assert reply.kwargs["header"].startswith("🟡 ホールド")
    assert "eMAXIS Slim 全世界株式" in reply.kwargs["header"]
    assert "円安一服のため" in reply.kwargs["text"]


def test_uses_only_two_recent_runs_for_performance(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.get_judgment_history", return_value=[]) as mock_history,
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        run_advisor_job(NOW)

    mock_history.assert_called_once_with("ideco-sbi", limit=2)


def test_reply_states_the_change_from_the_previous_judgment(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import put_judgments

    put_judgments(
        "ideco-sbi",
        "2026-07-11",
        [{"isin": ISIN, "judgment": "BUY", "reason": "r", "nav": 37000}],
    )

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice("SELL")),
        patch("src.advisor.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        run_advisor_job(NOW)

    reply_text = mock_post.call_args_list[1].kwargs["text"]
    assert "前回: 🟢 買い" in reply_text
    assert "今回: 🔴 売り" in reply_text


def test_persists_the_judgments_under_the_jst_run_date(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import get_judgment_history

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice("BUY")),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        run_advisor_job(NOW)

    history = get_judgment_history("ideco-sbi")
    assert history[0]["run_date"] == "2026-07-24"
    assert history[0]["judgments"][0]["judgment"] == "BUY"
    # The NAV at judgment time is stored so performance can be scored later.
    assert history[0]["judgments"][0]["nav"] == 38243


def test_does_not_post_when_slack_history_is_unreadable(integrated_aws_mock):
    """Failing to read history must not lead to a duplicate post."""
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", side_effect=RuntimeError("no scope")),
        patch("src.advisor.run_advice") as mock_advice,
        patch("src.advisor.slack_notifier.post_message") as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert "error" in result["results"]["ideco-sbi"]
    mock_advice.assert_not_called()
    mock_post.assert_not_called()


def test_continues_when_one_products_nav_fetch_fails(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", side_effect=RuntimeError("csv down")),
        patch("src.advisor.run_advice", return_value=_advice()) as mock_advice,
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        result = run_advisor_job(NOW)

    # The advice still runs; the agent can fall back to the nav_fetch tool.
    mock_advice.assert_called_once()
    assert result["results"]["ideco-sbi"] == "success"


def test_records_an_error_when_advice_fails(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", side_effect=RuntimeError("bedrock down")),
        patch("src.advisor.slack_notifier.post_message") as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert "error" in result["results"]["ideco-sbi"]
    mock_post.assert_not_called()


def test_passes_trading_notes_and_news_feeds_to_the_agent(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()) as mock_advice,
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        run_advisor_job(NOW)

    kwargs = mock_advice.call_args.kwargs
    assert "スイッチング" in kwargs["trading_notes"]
    assert kwargs["news_feeds"][0]["url"] == "https://example.com/market.rss"
    assert kwargs["now"] == NOW
    # The context carries the products and their NAV summary
    assert ISIN in kwargs["context"]
    assert "38,243円" in kwargs["context"]


def test_returns_ok_with_no_advisors(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import delete_advisor

    delete_advisor("ideco-sbi")

    result = run_advisor_job(NOW)

    assert result == {"status": "ok", "advisors": 0}


def test_continues_to_the_next_advisor_when_one_raises_unexpectedly(
    integrated_aws_mock,
):
    """An uncaught exception from one advisor (e.g. put_judgments throttled
    after its Slack thread already posted) must not abort the whole run —
    the loop in run_advisor_job must still process the remaining advisors.
    """
    from src.advisor import run_advisor_job
    from src.advisor_store import add_advisor

    add_advisor(
        "ideco-rakuten",
        "CADVISOR02",
        "iDeCo 投資判断(楽天)",
        [
            {
                "isin": "JP90C000ABC1",
                "name": "楽天・全世界株式インデックス・ファンド",
                "category": "全世界株",
                "holding": True,
                "assoc_fund_cd": "0331419A",
            }
        ],
        [{"url": "https://example.com/market2.rss", "name": "市況ニュース2"}],
        "スイッチングは即日。",
    )

    def fail_for_sbi(advisor_id: str, run_date: str, judgments: list[object]) -> None:
        if advisor_id == "ideco-sbi":
            raise RuntimeError("throttled")

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
        patch("src.advisor.put_judgments", side_effect=fail_for_sbi) as mock_put,
    ):
        result = run_advisor_job(NOW)

    assert result["advisors"] == 2
    assert "error" in result["results"]["ideco-sbi"]
    # The advisor after the one that raised is still processed and succeeds.
    assert result["results"]["ideco-rakuten"] == "success"
    assert mock_put.call_count == 2


def test_derives_the_slack_lookback_from_interval_days(integrated_aws_mock):
    """A fixed 30-day window would age out the previous post at long intervals."""
    from src.advisor import run_advisor_job
    from src.advisor_store import add_advisor, get_all_advisors

    existing = next(a for a in get_all_advisors() if a["advisor_id"] == "ideco-sbi")
    add_advisor(
        advisor_id="ideco-sbi",
        channel_id=existing["channel_id"],
        title=existing["title"],
        products=existing["products"],
        news_feeds=existing["news_feeds"],
        trading_notes=existing["trading_notes"],
        interval_days=60,
    )

    with (
        patch("src.advisor.find_last_post_time", return_value=None) as mock_find,
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        run_advisor_job(NOW)

    assert mock_find.call_args.kwargs["lookback_days"] == 120


def test_warns_when_the_agent_omits_a_product(integrated_aws_mock, caplog):
    from src.advisor import run_advisor_job
    from src.agent import AdviceResult

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch(
            "src.advisor.run_advice",
            return_value=AdviceResult(summary="s", advices=[]),
        ),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        with caplog.at_level("WARNING"):
            result = run_advisor_job(NOW)

    assert result["results"]["ideco-sbi"] == "success"
    assert "omitted 1 product(s)" in caplog.text
    assert ISIN in caplog.text


def test_parent_message_states_the_nav_as_of_date(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import put_judgments

    put_judgments(
        "ideco-sbi",
        "2026-07-11",
        [{"isin": ISIN, "judgment": "BUY", "reason": "r", "nav": 37000}],
    )

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        run_advisor_job(NOW)

    # SERIES ends 2026-07-24, so that is the date the performance is scored at.
    assert "（基準価額 2026-07-24 時点）" in mock_post.call_args_list[0].kwargs["text"]


def test_uses_the_advisors_post_weekday(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import add_advisor, get_all_advisors

    existing = next(a for a in get_all_advisors() if a["advisor_id"] == "ideco-sbi")
    add_advisor(
        advisor_id="ideco-sbi",
        channel_id=existing["channel_id"],
        title=existing["title"],
        products=existing["products"],
        news_feeds=existing["news_feeds"],
        trading_notes=existing["trading_notes"],
        post_weekday=4,  # Friday
    )

    # 2026-07-24 is a Friday; the previous post was the Friday before.
    last = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    with (
        patch("src.advisor.find_last_post_time", return_value=last),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        friday = run_advisor_job(NOW)

    # Saturday, having already posted on the Friday: nothing to pick up.
    with (
        patch("src.advisor.find_last_post_time", return_value=NOW),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        saturday = run_advisor_job(datetime(2026, 7, 25, 8, 0, tzinfo=UTC))

    assert friday["results"]["ideco-sbi"] == "success"
    assert "skipped" in saturday["results"]["ideco-sbi"]


def test_as_of_date_reports_the_oldest_series_not_the_newest(integrated_aws_mock):
    """One fresh product must not mask a stale one."""
    from src.advisor import run_advisor_job
    from src.advisor_store import put_judgments

    put_judgments(
        "ideco-sbi",
        "2026-07-11",
        [{"isin": ISIN, "judgment": "BUY", "reason": "r", "nav": 37000}],
    )
    stale = [NavPoint(date=date(2025, 11, 2), nav=30000)]

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", side_effect=[stale]),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch("src.advisor.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        run_advisor_job(NOW)

    assert "（基準価額 2025-11-02 時点）" in mock_post.call_args_list[0].kwargs["text"]
