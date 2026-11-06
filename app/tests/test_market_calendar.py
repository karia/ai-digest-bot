from datetime import UTC, date, datetime, timedelta, timezone

import responses


def _row(time: str, importance: int, country: str, name: str) -> str:
    return (
        f'<tr class="fs-s" data_importance="{importance}" data_country="{country}">'
        f"<td><span>{time}</span></td><td></td>"
        f'<td><a><p class="flexbox__grow fbd">{name}</p></a></td>'
        "<td>stars</td><td>-2.9pips</td><td>48.0</td></tr>"
    )


def _page(*days: tuple[str, list[str]]) -> str:
    tables = "".join(
        f"<table><caption>{caption}</caption>{''.join(rows)}</table>"
        for caption, rows in days
    )
    return f"<html><body><table><tr><td>layout</td></tr></table>{tables}</body></html>"


NOW = datetime(2026, 11, 7, 17, 0, tzinfo=timezone(timedelta(hours=9)))

PAGE = _page(
    (
        "2026年11月10日(火)",
        [
            _row("22:30", 4, "US", "アメリカ・消費者物価指数（CPI） 10月 [前月比]"),
            _row("22:30", 4, "US", "アメリカ・消費者物価指数（CPI） 10月 [前年比]"),
            _row("08:50", 3, "JP", "日本・国際収支 09月 [経常収支]"),
            _row("10:30", 3, "CN", "中国・消費者物価指数（CPI） 10月 [前年比]"),
        ],
    ),
    (
        "2026年11月19日(木)",
        [_row("22:00", 4, "ZA", "南ア・中銀政策金利 11月")],
    ),
)


def test_parse_reads_date_time_importance_country_and_base_name():
    from src.market_calendar import MarketEvent, parse_calendar_html

    events = parse_calendar_html(PAGE)

    assert events[0] == MarketEvent(
        date(2026, 11, 10), "22:30", 4, "US", "アメリカ・消費者物価指数（CPI） 10月"
    )
    assert len(events) == 5


def test_select_keeps_major_releases_once_and_drops_minor_or_foreign_ones():
    from src.market_calendar import parse_calendar_html, select_major_events

    events = select_major_events(parse_calendar_html(PAGE), NOW, 14)

    assert [(e.time, e.name) for e in events] == [
        ("08:50", "日本・国際収支 09月"),
        ("22:30", "アメリカ・消費者物価指数（CPI） 10月"),
    ]


def test_select_drops_events_outside_the_window():
    from src.market_calendar import MarketEvent, select_major_events

    events = [
        MarketEvent(date(2026, 11, 6), "22:30", 5, "US", "before"),
        MarketEvent(date(2026, 11, 7), "22:30", 5, "US", "first day"),
        MarketEvent(date(2026, 11, 20), "22:30", 5, "US", "last day"),
        MarketEvent(date(2026, 11, 21), "22:30", 5, "US", "after"),
    ]

    selected = select_major_events(events, NOW, 14)

    assert [e.name for e in selected] == ["first day", "last day"]


def test_select_drops_releases_already_out_today_but_keeps_undated_ones():
    from src.market_calendar import MarketEvent, select_major_events

    events = [
        MarketEvent(date(2026, 11, 7), "00:00", 5, "US", "released"),
        MarketEvent(date(2026, 11, 7), "17:00", 5, "US", "releasing now"),
        MarketEvent(date(2026, 11, 7), "未定", 5, "US", "undated today"),
        MarketEvent(date(2026, 11, 7), "22:30", 5, "US", "tonight"),
    ]

    selected = select_major_events(events, datetime(2026, 11, 7, 8, 0, tzinfo=UTC), 14)

    assert [e.name for e in selected] == ["tonight", "undated today"]


@responses.activate
def test_fetch_requests_one_page_per_week_from_the_start_date():
    from src.market_calendar import CALENDAR_URL, fetch_upcoming_events

    responses.add(responses.GET, CALENDAR_URL, body=PAGE)
    responses.add(responses.GET, CALENDAR_URL, body=_page())

    events = fetch_upcoming_events(NOW, 14)

    assert [c.request.params["date"] for c in responses.calls] == [
        "2026-11-07",
        "2026-11-14",
    ]
    assert len(events) == 2


def test_format_lists_one_line_per_event_with_weekday():
    from src.market_calendar import MarketEvent, format_events

    text = format_events(
        [MarketEvent(date(2026, 11, 10), "22:30", 4, "US", "アメリカ・CPI 10月")]
    )

    assert text == "- 2026-11-10(火) 22:30 ★4 アメリカ・CPI 10月"


def test_format_says_so_when_nothing_is_scheduled():
    from src.market_calendar import format_events

    assert "予定なし" in format_events([])
