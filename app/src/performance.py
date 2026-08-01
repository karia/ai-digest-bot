from datetime import date, timedelta
from typing import NamedTuple

from src.advisor_store import JudgmentRecord
from src.nav import NavPoint

# The single place judgment codes turn into user-facing labels.
JUDGMENT_LABELS = {"BUY": "🟢 買い", "SELL": "🔴 売り", "HOLD": "🟡 ホールド"}

# Trailing windows shown in the NAV summary handed to the advice agent.
NAV_WINDOW_DAYS = (7, 30, 90, 180)

NO_HISTORY_TEXT = "過去の判断履歴はまだありません。"


class PerformanceRow(NamedTuple):
    """How one past judgment has fared against the current NAV."""

    run_date: str
    isin: str
    name: str
    judgment: str
    nav_then: int
    nav_now: int
    change_pct: float


def pct_change(base: int, current: int) -> float:
    """Percent change from ``base`` to ``current``; 0.0 when base is 0."""
    if base == 0:
        return 0.0
    return (current - base) / base * 100


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def build_performance(
    history: list[JudgmentRecord],
    current_navs: dict[str, int],
    product_names: dict[str, str],
) -> list[PerformanceRow]:
    """Flatten judgment history into rows scored against today's NAV.

    Args:
        history: Past runs, newest first.
        current_navs: isin -> today's NAV. Products missing here are skipped
            (a fund can be dropped from the advisor after being judged).
        product_names: isin -> display name; unknown isins show the isin.
    """
    rows: list[PerformanceRow] = []
    for record in history:
        for judgment in record["judgments"]:
            isin = judgment["isin"]
            nav_now = current_navs.get(isin)
            nav_then = judgment["nav"]
            if nav_now is None or nav_then <= 0:
                continue
            rows.append(
                PerformanceRow(
                    run_date=record["run_date"],
                    isin=isin,
                    name=product_names.get(isin, isin),
                    judgment=judgment["judgment"],
                    nav_then=nav_then,
                    nav_now=nav_now,
                    change_pct=pct_change(nav_then, nav_now),
                )
            )
    return rows


def format_performance_summary(rows: list[PerformanceRow]) -> str:
    """Render performance rows as Slack mrkdwn bullets."""
    if not rows:
        return NO_HISTORY_TEXT
    return "\n".join(
        f"• {row.run_date} {row.name}:"
        f" {JUDGMENT_LABELS.get(row.judgment, row.judgment)}"
        f" → {format_pct(row.change_pct)}"
        for row in rows
    )


def latest_judgment_by_isin(history: list[JudgmentRecord]) -> dict[str, str]:
    """isin -> the most recent judgment code for it.

    ``history`` must be newest first; the first record holding an isin wins.
    """
    latest: dict[str, str] = {}
    for record in history:
        for judgment in record["judgments"]:
            latest.setdefault(judgment["isin"], judgment["judgment"])
    return latest


def _nav_on_or_before(points: list[NavPoint], target: date) -> NavPoint | None:
    """Last point at or before ``target`` (points must be ascending)."""
    earlier = [p for p in points if p.date <= target]
    return earlier[-1] if earlier else None


def summarize_nav(points: list[NavPoint]) -> str:
    """One-line NAV summary: latest value plus trailing returns.

    Passing the whole series into the prompt would be wasteful, so the agent
    gets this digest and can call the nav_fetch tool when it needs more.
    """
    if not points:
        return "基準価額データなし"
    latest = points[-1]
    parts = [f"最新 {latest.date:%Y-%m-%d} {latest.nav:,}円"]
    for days in NAV_WINDOW_DAYS:
        past = _nav_on_or_before(points, latest.date - timedelta(days=days))
        if past is None or past.date == latest.date:
            continue
        parts.append(f"{days}日 {format_pct(pct_change(past.nav, latest.nav))}")
    return " / ".join(parts)
