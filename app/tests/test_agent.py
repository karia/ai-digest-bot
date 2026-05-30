from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

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
