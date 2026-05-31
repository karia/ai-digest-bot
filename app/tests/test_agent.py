import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

SINCE = datetime(2026, 5, 31, 0, 0, 0, tzinfo=UTC)
UNTIL = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def test_run_digest_returns_string():
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="テストダイジェスト本文")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        result = run_digest(
            ["https://aws.amazon.com/blogs/aws/feed/"], since=SINCE, until=UNTIL
        )

    assert isinstance(result, str)
    assert result == "テストダイジェスト本文"


def test_run_digest_passes_urls_to_agent():
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="ダイジェスト")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        run_digest(
            ["https://example.com/feed1/", "https://example.com/feed2/"],
            since=SINCE,
            until=UNTIL,
        )

        call_args = instance.call_args[0][0]
        assert "https://example.com/feed1/" in call_args
        assert "https://example.com/feed2/" in call_args
        assert "2026-05-31T00:00:00Z" in call_args
        assert "2026-06-01T00:00:00Z" in call_args


def test_run_digest_logs_bedrock_io_at_info(caplog: pytest.LogCaptureFixture):
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="ダイジェスト出力")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        with caplog.at_level(logging.INFO, logger="src.agent"):
            run_digest(
                ["https://aws.amazon.com/blogs/aws/feed/"], since=SINCE, until=UNTIL
            )

    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "Bedrock input:" in messages
    assert "Bedrock output:" in messages
    assert "ダイジェスト出力" in messages


def test_run_digest_creates_new_agent_per_call():
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="ダイジェスト")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        run_digest(["https://example.com/feed/"], since=SINCE, until=UNTIL)
        run_digest(["https://example.com/feed/"], since=SINCE, until=UNTIL)

    assert MockAgent.call_count == 2
