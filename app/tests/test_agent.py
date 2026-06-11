import logging
from datetime import UTC, datetime
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
        result = run_headline([("AWS", "本文A"), ("InfoQ", "本文B")])

    assert result == "注目のヘッドライン"


def test_run_headline_passes_names_and_bodies_to_agent():
    from src.agent import run_headline

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = _mock_result()
        run_headline([("AWS Blogs", "新サービス発表"), ("Publickey", "障害レポート")])

        prompt = instance.call_args[0][0]
        assert "AWS Blogs" in prompt
        assert "新サービス発表" in prompt
        assert "Publickey" in prompt
        assert "障害レポート" in prompt


def test_run_headline_uses_no_tools():
    from src.agent import run_headline

    with patch("src.agent.Agent") as MockAgent:
        MockAgent.return_value.return_value = _mock_result()
        run_headline([("AWS", "本文")])

        assert MockAgent.call_args.kwargs["tools"] == []


def _mock_plan_result(plan):
    result = MagicMock()
    result.structured_output = plan
    return result


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
