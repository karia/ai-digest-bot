from unittest.mock import MagicMock, patch


def test_run_digest_returns_string():
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="テストダイジェスト本文")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        result = run_digest(["https://aws.amazon.com/blogs/aws/feed/"])

    assert isinstance(result, str)
    assert result == "テストダイジェスト本文"


def test_run_digest_passes_urls_to_agent():
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="ダイジェスト")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        run_digest(["https://example.com/feed1/", "https://example.com/feed2/"])

        call_args = instance.call_args[0][0]
        assert "https://example.com/feed1/" in call_args
        assert "https://example.com/feed2/" in call_args


def test_run_digest_creates_new_agent_per_call():
    from src.agent import run_digest

    mock_result = MagicMock()
    mock_result.__str__ = MagicMock(return_value="ダイジェスト")

    with patch("src.agent.Agent") as MockAgent:
        instance = MockAgent.return_value
        instance.return_value = mock_result
        run_digest(["https://example.com/feed/"])
        run_digest(["https://example.com/feed/"])

    assert MockAgent.call_count == 2
