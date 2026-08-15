import html
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_sdk import WebClient

from src import config
from src.slack_notifier import HEADER_LIMIT

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30

_bot_user_id_cache: str | None = None


def lookback_days_for(interval_days: int) -> int:
    """How far back to search for the previous post at this posting interval.

    A fixed 30-day window silently caps any interval longer than it: the
    previous post ages out, no match is found, and the advisor posts again
    off-cadence. Searching twice the interval keeps at least one prior post
    inside the window.
    """
    return max(DEFAULT_LOOKBACK_DAYS, interval_days * 2)


def _get_bot_user_id(client: WebClient) -> str:
    global _bot_user_id_cache
    if _bot_user_id_cache is None:
        _bot_user_id_cache = str(client.auth_test()["user_id"])
    return _bot_user_id_cache


def _has_header(message: dict[str, Any], header: str) -> bool:
    """Whether this message is the thread parent carrying ``header``.

    post_message truncates the header to HEADER_LIMIT only in the header
    block; the top-level ``text`` field carries the full, untruncated
    header whenever one is set. So the block branch below is what actually
    matches our own messages (a header block is always present when
    ``header`` is set, and its comparison is truncated-to-truncated on both
    sides). The ``text`` fallback only matters for messages without a
    header block, where ``text`` holds the raw body instead.

    Only what Slack returns is HTML-unescaped, never ``header``: Slack stores
    ``&``, ``<`` and ``>`` escaped and hands them back that way, so a title
    containing one would otherwise never match its own post and the advisor
    would repost every run. Decoding the local ``header`` too would break the
    other direction — a title holding a literal ``&amp;`` decodes to something
    Slack never stored. Both forms are accepted in case Slack ever returns
    block text verbatim.
    """
    truncated = header[:HEADER_LIMIT]

    def matches(found: str) -> bool:
        return found == truncated or html.unescape(found) == truncated

    for block in message.get("blocks") or []:
        if block.get("type") == "header":
            return matches(str(block.get("text", {}).get("text", "")))
    return matches(str(message.get("text", "")))


def find_last_post_time(
    channel: str, header: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> datetime | None:
    """Find when this bot last posted a thread parent with ``header``.

    Unlike the digest's slack_last_bot_post tool, this filters by header, so
    other threads (a digest, another advisor) in the same channel are ignored.

    Args:
        channel: Slack channel ID.
        header: The advisor title used as the headline header.
        lookback_days: How far back to search.

    Returns:
        The post time in UTC, or None when no matching post exists in the
        lookback window.

    Raises:
        Exception: any Slack API failure is propagated. Callers must not
            treat a failure as "not posted yet" — that would double-post.
    """
    logger.info(
        "find_last_post_time: channel=%s header=%r lookback_days=%d",
        channel,
        header,
        lookback_days,
    )
    client = WebClient(token=config.get_slack_token())
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    bot_user_id = _get_bot_user_id(client)

    cursor: str | None = None
    while True:
        # No `oldest`: that would anchor pagination at the old end and make
        # the first match the oldest post. The cutoff is applied client-side.
        response = client.conversations_history(
            channel=channel, limit=200, cursor=cursor
        )
        # Messages arrive newest-first, so the first match is the latest post.
        for message in response["messages"]:
            ts = datetime.fromtimestamp(float(message["ts"]), tz=UTC)
            if ts < cutoff:
                return None
            if message.get("user") != bot_user_id or "subtype" in message:
                continue
            if _has_header(message, header):
                return ts
        metadata: dict[str, Any] = response.get("response_metadata") or {}
        cursor = metadata.get("next_cursor")
        if not cursor:
            return None


WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")


def should_post(
    last_post: datetime | None,
    now: datetime,
    interval_days: int,
    post_weekday: int | None = None,
) -> tuple[bool, str]:
    """Decide whether this run should post, and why.

    Comparison is by JST calendar date, not elapsed hours: the job runs at a
    fixed JST time but invocations can jitter, and an hours-based comparison
    would flip-flop around interval_days=1.

    Args:
        last_post: When this advisor last posted, or None.
        now: This run's time.
        interval_days: Minimum days between posts. Used only when
            ``post_weekday`` is None — a weekday target sets the cadence by
            itself, and applying both would let an off-schedule post (a manual
            recovery, say) push the next scheduled one out by a full period.
        post_weekday: Target JST weekday, Monday=0 … Sunday=6. When set, the
            advisor posts once per occurrence of that weekday: on the day
            itself, or on a later day if that occurrence was missed.

    Returns:
        (should_post, reason in Japanese).
    """
    if last_post is None:
        return True, "前回投稿が見つからないため投稿する"

    today = now.astimezone(config.JST).date()
    last_day = last_post.astimezone(config.JST).date()
    elapsed = (today - last_day).days
    if elapsed <= 0:
        return False, "本日投稿済みのため投稿しない"

    if post_weekday is not None:
        # The most recent occurrence of the target weekday, today included.
        # Posting when it falls after the last post covers both the ordinary
        # case and a missed target day picked up by a later run.
        target = today - timedelta(days=(today.weekday() - post_weekday) % 7)
        label = WEEKDAY_LABELS[post_weekday]
        if target <= last_day:
            return False, f"次の{label}曜まで投稿しない（前回投稿 {last_day}）"
        if target == today:
            return True, f"{label}曜のため投稿する"
        return True, f"{target} の{label}曜を逃したため投稿する"

    if elapsed < interval_days:
        return (
            False,
            f"前回投稿から{elapsed}日（投稿間隔{interval_days}日）のため投稿しない",
        )
    return True, f"前回投稿から{elapsed}日経過したため投稿する"
