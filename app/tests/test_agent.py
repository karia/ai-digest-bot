import logging
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

SINCE = datetime(2026, 5, 31, 0, 0, 0, tzinfo=UTC)
UNTIL = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def _mock_result(text: str = "ダイジェスト"):
    result = MagicMock()
    result.__str__ = MagicMock(return_value=text)
    return result


def test_run_digest_returns_string():
    from src.agent import run_digest

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result("テストダイジェスト本文")
        result = run_digest(
            "https://aws.amazon.com/blogs/aws/feed/", since=SINCE, until=UNTIL
        )

    assert result == "テストダイジェスト本文"


def test_run_digest_passes_url_and_period_to_agent():
    from src.agent import run_digest

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = _mock_result()
        run_digest("https://example.com/feed1/", since=SINCE, until=UNTIL)

        prompt = instance.call_args[0][0]
        assert "https://example.com/feed1/" in prompt
        assert "2026-05-31T00:00:00Z" in prompt
        assert "2026-06-01T00:00:00Z" in prompt


def test_run_digest_does_not_register_a_slack_tool():
    from src.agent import run_digest

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result()
        run_digest("https://example.com/feed/", since=SINCE, until=UNTIL)

        tools = MockAgent.call_args.kwargs["tools"]
        tool_names = {getattr(t, "__name__", "") for t in tools}
        assert not any("slack" in n for n in tool_names)


def test_run_digest_logs_bedrock_io_at_info(caplog: pytest.LogCaptureFixture):
    from src.agent import run_digest

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result("ダイジェスト出力")
        with caplog.at_level(logging.INFO, logger="src.agent"):
            run_digest(
                "https://aws.amazon.com/blogs/aws/feed/", since=SINCE, until=UNTIL
            )

    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "Bedrock input:" in messages
    assert "Bedrock output:" in messages
    assert "ダイジェスト出力" in messages


def test_run_digest_creates_new_agent_per_call():
    from src.agent import run_digest

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result()
        run_digest("https://example.com/feed/", since=SINCE, until=UNTIL)
        run_digest("https://example.com/feed/", since=SINCE, until=UNTIL)

    assert MockAgent.call_count == 2


def test_run_headline_returns_string():
    from src.agent import run_headline

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result("注目のヘッドライン")
        result = run_headline(
            [("AWS", "本文A"), ("InfoQ", "本文B")], since=SINCE, until=UNTIL
        )

    assert result == "注目のヘッドライン"


def test_run_headline_passes_names_and_bodies_to_agent():
    from src.agent import run_headline

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = _mock_result()
        run_headline(
            [("AWS Blogs", "新サービス発表"), ("Publickey", "障害レポート")],
            since=SINCE,
            until=UNTIL,
        )

        prompt = instance.call_args[0][0]
        assert "AWS Blogs" in prompt
        assert "新サービス発表" in prompt
        assert "Publickey" in prompt
        assert "障害レポート" in prompt


def test_run_headline_passes_period_to_agent():
    from src.agent import run_headline

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = _mock_result()
        run_headline([("AWS", "本文")], since=SINCE, until=UNTIL)

        prompt = instance.call_args[0][0]
        assert "2026-05-31T00:00:00Z" in prompt
        assert "2026-06-01T00:00:00Z" in prompt


def test_run_headline_uses_no_tools():
    from src.agent import run_headline

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result()
        run_headline([("AWS", "本文")], since=SINCE, until=UNTIL)

        assert MockAgent.call_args.kwargs["tools"] == []


def _mock_plan_result(plan):
    result = MagicMock()
    result.structured_output = plan
    return result


def test_run_daily_digests_returns_days():
    from src.agent import DailyDigest, DailyDigests, run_daily_digests

    days = [
        DailyDigest(date=date(2026, 5, 31), body="本文31"),
        DailyDigest(date=date(2026, 6, 1), body="本文1"),
    ]
    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_plan_result(DailyDigests(days=days))
        result = run_daily_digests("https://example.com/feed", since=SINCE, until=UNTIL)

    assert result == days


def test_run_daily_digests_passes_url_period_and_output_model():
    from src.agent import DailyDigests, run_daily_digests

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = _mock_plan_result(DailyDigests(days=[]))
        run_daily_digests("https://example.com/feed", since=SINCE, until=UNTIL)

        prompt = instance.call_args[0][0]
        assert "https://example.com/feed" in prompt
        assert "2026-05-31T00:00:00Z" in prompt
        assert "2026-06-01T00:00:00Z" in prompt
        assert instance.call_args.kwargs["structured_output_model"] is DailyDigests


def test_run_daily_digests_raises_without_structured_output():
    from src.agent import run_daily_digests

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_plan_result(None)
        with pytest.raises(ValueError):
            run_daily_digests("https://example.com/feed", since=SINCE, until=UNTIL)


def test_run_plan_returns_structured_plan():
    from src.agent import DigestPlan, run_plan

    plan = DigestPlan(should_post=True, since=SINCE, reason="毎日のため投稿")
    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_plan_result(plan)
        result = run_plan("C123", "毎日", UNTIL)

    assert result is plan


def test_run_plan_passes_channel_schedule_and_time_to_agent():
    from src.agent import DigestPlan, run_plan

    plan = DigestPlan(should_post=True, since=None, reason="判定")
    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = _mock_plan_result(plan)
        run_plan("C123", "月曜と木曜", UNTIL)

        prompt = instance.call_args[0][0]
        assert "C123" in prompt
        assert "月曜と木曜" in prompt
        assert "2026-06-01T00:00:00Z" in prompt
        # 2026-06-01 00:00 UTC = 09:00 JST, a Monday
        assert "2026-06-01 09:00" in prompt
        assert "Monday" in prompt
        assert instance.call_args.kwargs["structured_output_model"] is DigestPlan


def test_run_plan_registers_only_the_slack_tool():
    from src.agent import DigestPlan, run_plan

    plan = DigestPlan(should_post=True, since=None, reason="判定")
    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_plan_result(plan)
        run_plan("C123", "毎日", UNTIL)

        tools = MockAgent.call_args.kwargs["tools"]
        assert len(tools) == 1
        assert "slack_last_bot_post" in str(tools[0].tool_name)


def test_run_plan_raises_without_structured_output():
    from src.agent import run_plan

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_plan_result(None)
        with pytest.raises(ValueError):
            run_plan("C123", "毎日", UNTIL)


def test_run_advice_returns_the_structured_output():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, ProductAdvice, run_advice

    expected = AdviceResult(
        summary="USD/JPY は 163 円台。",
        advices=[ProductAdvice(isin="JP90C000H1T1", judgment="HOLD", reason="様子見")],
    )
    result = MagicMock()
    result.structured_output = expected

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        advice = run_advice(
            context="商品一覧...",
            trading_notes="スイッチングは1週間から10日",
            news_feeds=[{"url": "https://example.com/rss", "name": "市況"}],
            now=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        )

    assert advice is expected


def test_run_advice_injects_trading_notes_into_the_system_prompt():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice(
            context="ctx",
            trading_notes="配分変更は翌月拠出分から反映",
            news_feeds=[],
            now=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        )

    system_prompt = mock_agent.call_args.kwargs["system_prompt"]
    assert "配分変更は翌月拠出分から反映" in system_prompt


def test_run_advice_prompt_carries_context_news_feeds_and_jst_now():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice(
            context="商品一覧と基準価額",
            trading_notes="",
            news_feeds=[{"url": "https://example.com/rss", "name": "市況ニュース"}],
            now=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        )

    prompt = mock_agent.return_value.call_args[0][0]
    assert "商品一覧と基準価額" in prompt
    assert "https://example.com/rss" in prompt
    assert "市況ニュース" in prompt
    # 08:00 UTC = 17:00 JST
    assert "2026-07-24 17:00 JST" in prompt


def test_run_advice_registers_the_advisor_tools():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice("ctx", "", [], datetime(2026, 7, 24, 8, 0, tzinfo=UTC))

    tools = mock_agent.call_args.kwargs["tools"]
    # api_fetch is what fetches the USD/JPY rate, so it must be registered.
    assert len(tools) == 4


def test_run_advice_raises_without_structured_output():
    from unittest.mock import MagicMock, patch

    import pytest
    from src.agent import run_advice

    result = MagicMock()
    result.structured_output = None

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        with pytest.raises(ValueError, match="structured output"):
            run_advice("ctx", "", [], datetime(2026, 7, 24, 8, 0, tzinfo=UTC))


def test_run_advice_uses_the_heavier_advice_model():
    """The judgment call runs on its own model, not the digest one."""
    from unittest.mock import MagicMock, patch

    from src import config
    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel") as mock_model,
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice("ctx", "", [], datetime(2026, 7, 24, 8, 0, tzinfo=UTC))

    assert mock_model.call_args.kwargs["model_id"] == config.BEDROCK_ADVICE_MODEL_ID
    assert config.BEDROCK_ADVICE_MODEL_ID != config.BEDROCK_MODEL_ID


def test_run_digest_uses_the_lighter_digest_model():
    from unittest.mock import MagicMock, patch

    from src import config
    from src.agent import run_digest

    with (
        patch("src.agent.BedrockModel") as mock_model,
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = MagicMock(__str__=lambda s: "body")
        run_digest(
            "https://example.com/rss",
            since=datetime(2026, 7, 23, 0, 0, tzinfo=UTC),
            until=datetime(2026, 7, 24, 0, 0, tzinfo=UTC),
        )

    assert mock_model.call_args.kwargs["model_id"] == config.BEDROCK_MODEL_ID
