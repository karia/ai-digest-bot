import re
from datetime import date, datetime, timedelta
from typing import NamedTuple

import requests
from bs4 import BeautifulSoup

from src import config

CALENDAR_URL = "https://fx.minkabu.jp/indicators"
PAGE_DAYS = 7
MIN_IMPORTANCE = 4
MIN_IMPORTANCE_JP = 3
COUNTRIES = frozenset({"US", "JP", "EU", "CN"})

_DATE_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_DETAIL_SUFFIX = re.compile(r"\s*\[[^\]]*\]$")
_TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2})")


class MarketEvent(NamedTuple):
    """One scheduled economic release; ``time`` is JST as shown, or 未定."""

    date: date
    time: str
    importance: int
    country: str
    name: str


def parse_calendar_html(html: str) -> list[MarketEvent]:
    """Extract every release from one calendar page, in page order.

    Each day is a table whose caption holds the date, and each release row
    carries its importance (1-5) and country code as attributes.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: list[MarketEvent] = []
    for table in soup.find_all("table"):
        caption = table.find("caption")
        matched = _DATE_PATTERN.search(caption.get_text()) if caption else None
        if not matched:
            continue
        day = date(int(matched.group(1)), int(matched.group(2)), int(matched.group(3)))
        for row in table.find_all("tr", attrs={"data_importance": True}):
            cells = row.find_all("td")
            title = row.find("p")
            if not cells or title is None:
                continue
            events.append(
                MarketEvent(
                    date=day,
                    time=cells[0].get_text(strip=True),
                    importance=int(str(row["data_importance"])),
                    country=str(row.get("data_country", "")),
                    name=_DETAIL_SUFFIX.sub("", title.get_text(strip=True)),
                )
            )
    return events


def _is_major(event: MarketEvent) -> bool:
    if event.country not in COUNTRIES:
        return False
    if event.country == "JP":
        return event.importance >= MIN_IMPORTANCE_JP
    return event.importance >= MIN_IMPORTANCE


def _is_after(event: MarketEvent, now: datetime) -> bool:
    matched = _TIME_PATTERN.fullmatch(event.time)
    if not matched:
        return event.date >= now.date()
    released = datetime(
        event.date.year,
        event.date.month,
        event.date.day,
        int(matched.group(1)),
        int(matched.group(2)),
        tzinfo=config.JST,
    )
    return released > now


def select_major_events(
    events: list[MarketEvent], now: datetime, days: int
) -> list[MarketEvent]:
    """Keep major releases after ``now`` within ``days`` JST calendar days.

    A release with no fixed time (未定) is kept for the whole of its day. A
    release such as CPI is listed once per sub-figure; those collapse into one
    row keeping the highest importance.
    """
    now = now.astimezone(config.JST)
    end = now.date() + timedelta(days=days)
    selected: dict[tuple[date, str, str], MarketEvent] = {}
    for event in events:
        if event.date >= end or not _is_after(event, now) or not _is_major(event):
            continue
        key = (event.date, event.time, event.name)
        kept = selected.get(key)
        if kept is None or event.importance > kept.importance:
            selected[key] = event
    return sorted(selected.values(), key=lambda e: (e.date, e.time))


def fetch_upcoming_events(now: datetime, days: int) -> list[MarketEvent]:
    """Download the calendar pages covering ``days`` JST days from ``now``.

    Raises:
        requests.RequestException: if any page fails to download.
    """
    start = now.astimezone(config.JST).date()
    events: list[MarketEvent] = []
    for offset in range(0, days, PAGE_DAYS):
        page_date = start + timedelta(days=offset)
        response = requests.get(
            CALENDAR_URL,
            params={"date": page_date.isoformat()},
            headers={"User-Agent": "Mozilla/5.0 (compatible; DigestBot/1.0)"},
            timeout=30,
        )
        response.raise_for_status()
        events.extend(parse_calendar_html(response.text))
    return select_major_events(events, now, days)


def format_events(events: list[MarketEvent]) -> str:
    """Render events as one line each for the agent's context."""
    if not events:
        return "（期間内に主要な指標の予定なし）"
    weekdays = "月火水木金土日"
    return "\n".join(
        f"- {e.date.isoformat()}({weekdays[e.date.weekday()]}) {e.time}"
        f" ★{e.importance} {e.name}"
        for e in events
    )
