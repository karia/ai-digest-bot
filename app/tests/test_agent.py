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
