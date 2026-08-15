from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

HEADER = "iDeCo 投資判断"


def _message(ts: datetime, header: str | None, user: str = "U_BOT") -> dict:
    message: dict = {"ts": str(ts.timestamp()), "user": user}
    if header is not None:
        message["text"] = header
        message["blocks"] = [
            {"type": "header", "text": {"type": "plain_text", "text": header}},
            {"type": "divider"},
        ]
    return message


def _client(messages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.auth_test.return_value = {"user_id": "U_BOT"}
    client.conversations_history.return_value = {
        "messages": messages,
        "response_metadata": {},
    }
    return client


@pytest.fixture(autouse=True)
def reset_bot_user_cache():
    import src.slack_reader as slack_reader

    slack_reader._bot_user_id_cache = None
    yield
    slack_reader._bot_user_id_cache = None


def test_find_last_post_time_matches_the_advisor_header(ssm_parameter):
    from src.slack_reader import find_last_post_time

    posted = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)

    with patch(
        "src.slack_reader.WebClient", return_value=_client([_message(posted, HEADER)])
    ):
        found = find_last_post_time("C1", HEADER)

    assert found == posted


def test_find_last_post_time_ignores_other_headers(ssm_parameter):
    """A digest thread in the same channel must not count as our post."""
    from src.slack_reader import find_last_post_time

    messages = [_message(datetime(2026, 7, 20, 0, 0, tzinfo=UTC), "Tech Digest")]

    with patch("src.slack_reader.WebClient", return_value=_client(messages)):
        assert find_last_post_time("C1", HEADER) is None


def test_find_last_post_time_returns_the_newest_match(ssm_parameter):
    from src.slack_reader import find_last_post_time

    newest = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    older = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    messages = [_message(newest, HEADER), _message(older, HEADER)]

    with patch("src.slack_reader.WebClient", return_value=_client(messages)):
        assert find_last_post_time("C1", HEADER) == newest


def test_find_last_post_time_ignores_other_users(ssm_parameter):
    from src.slack_reader import find_last_post_time

    messages = [_message(datetime(2026, 7, 18, tzinfo=UTC), HEADER, user="U_HUMAN")]

    with patch("src.slack_reader.WebClient", return_value=_client(messages)):
        assert find_last_post_time("C1", HEADER) is None


def test_find_last_post_time_stops_at_the_lookback_cutoff(ssm_parameter):
    from src.slack_reader import find_last_post_time

    ancient = datetime.now(UTC) - timedelta(days=90)

    with patch(
        "src.slack_reader.WebClient", return_value=_client([_message(ancient, HEADER)])
    ):
        assert find_last_post_time("C1", HEADER, lookback_days=30) is None


def test_find_last_post_time_falls_back_to_the_text_field(ssm_parameter):
    """post_message sets text=header, so a block-less message still matches."""
    from src.slack_reader import find_last_post_time

    posted = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    message = {"ts": str(posted.timestamp()), "user": "U_BOT", "text": HEADER}

    with patch("src.slack_reader.WebClient", return_value=_client([message])):
        assert find_last_post_time("C1", HEADER) == posted


def test_find_last_post_time_raises_on_api_error(ssm_parameter):
    """Never silently degrade to None: that would double-post."""
    from src.slack_reader import find_last_post_time

    client = MagicMock()
    client.auth_test.side_effect = RuntimeError("slack down")

    with patch("src.slack_reader.WebClient", return_value=client):
        with pytest.raises(RuntimeError):
            find_last_post_time("C1", HEADER)


def test_should_post_when_there_is_no_previous_post():
    from src.slack_reader import should_post

    ok, reason = should_post(None, datetime(2026, 7, 24, 8, 0, tzinfo=UTC), 7)

    assert ok is True
    assert "前回投稿が見つからない" in reason


def test_should_not_post_twice_on_the_same_jst_day():
    from src.slack_reader import should_post

    # 2026-07-24 00:30 JST and 2026-07-24 17:00 JST are the same JST day.
    last = datetime(2026, 7, 23, 15, 30, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, reason = should_post(last, now, 1)

    assert ok is False
    assert "本日投稿済み" in reason


def test_should_post_the_next_jst_day_when_interval_is_one():
    from src.slack_reader import should_post

    last = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, _ = should_post(last, now, 1)

    assert ok is True


def test_should_not_post_before_the_interval_elapses():
    from src.slack_reader import should_post

    last = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, reason = should_post(last, now, 7)

    assert ok is False
    assert "3日" in reason


def test_should_post_once_the_interval_elapses():
    from src.slack_reader import should_post

    last = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, _ = should_post(last, now, 7)

    assert ok is True


def test_should_post_compares_jst_dates_not_elapsed_hours():
    """23:00 JST -> next day 17:00 JST is only 18h but is a new JST day."""
    from src.slack_reader import should_post

    last = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)  # 2026-07-23 23:00 JST
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)  # 2026-07-24 17:00 JST

    ok, _ = should_post(last, now, 1)

    assert ok is True


def test_lookback_days_for_keeps_the_default_floor():
    from src.slack_reader import lookback_days_for

    assert lookback_days_for(7) == 30
    assert lookback_days_for(14) == 30


def test_lookback_days_for_grows_with_a_long_interval():
    """A 30-day window would age out the previous post and repost off-cadence."""
    from src.slack_reader import lookback_days_for

    assert lookback_days_for(45) == 90
    assert lookback_days_for(60) == 120


def test_find_last_post_time_matches_a_header_slack_html_escaped(ssm_parameter):
    """Slack stores & < > escaped; an exact compare would never match."""
    from src.slack_reader import find_last_post_time

    header = "S&P500 <重要> 投資判断"
    posted = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    escaped = _message(posted, "S&amp;P500 &lt;重要&gt; 投資判断")

    with patch("src.slack_reader.WebClient", return_value=_client([escaped])):
        assert find_last_post_time("C1", header) == posted


# 2026-08-07 is a Friday; 08-14 the next one.
_FRI = 4


def _at(day: int, hour: int = 8) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)  # 08:00 UTC = 17:00 JST


def test_weekday_target_posts_on_the_target_day():
    from src.slack_reader import should_post

    ok, reason = should_post(_at(7), _at(14), 7, _FRI)

    assert ok is True
    assert "金曜のため投稿する" in reason


def test_weekday_target_skips_the_days_between():
    from src.slack_reader import should_post

    for day in (8, 10, 13):
        ok, _ = should_post(_at(7), _at(day), 7, _FRI)
        assert ok is False, day


def test_weekday_target_picks_up_a_missed_target_day():
    """A failed Friday must be retried by a later run, not wait a week."""
    from src.slack_reader import should_post

    ok, reason = should_post(_at(7), _at(15), 7, _FRI)

    assert ok is True
    assert "逃したため投稿する" in reason


def test_weekday_target_does_not_repost_the_same_day():
    from src.slack_reader import should_post

    ok, reason = should_post(_at(14, 8), _at(14, 9), 7, _FRI)

    assert ok is False
    assert "本日投稿済み" in reason


def test_weekday_target_resumes_on_friday_after_an_off_day_post():
    """An off-schedule recovery must not push the next Friday out a week."""
    from src.slack_reader import should_post

    # Posted Monday 08-10 by hand; Friday 08-14 is only 4 days later.
    ok, _ = should_post(_at(10), _at(14), 7, _FRI)

    assert ok is True


def test_interval_still_governs_without_a_weekday_target():
    from src.slack_reader import should_post

    assert should_post(_at(7), _at(10), 7)[0] is False
    assert should_post(_at(7), _at(14), 7)[0] is True


def test_find_last_post_time_matches_a_title_holding_a_literal_entity(ssm_parameter):
    """Unescaping the local title too would decode what Slack never stored."""
    from src.slack_reader import find_last_post_time

    header = "A &amp; B"
    posted = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)

    with patch(
        "src.slack_reader.WebClient",
        return_value=_client([_message(posted, "A &amp;amp; B")]),
    ):
        assert find_last_post_time("C1", header) == posted
