from datetime import date

import pytest
import requests
import responses

SAMPLE_CSV = (
    "年月日,基準価額(円),純資産総額（百万円）,分配金,決算期\n"
    "2026年07月22日,37980,13100000,,\n"
    "2026年07月23日,38100,13150000,,\n"
    "2026年07月24日,38243,13205500,,\n"
)


def test_parse_nav_csv_reads_cp932_rows():
    from src.nav import parse_nav_csv

    points = parse_nav_csv(SAMPLE_CSV.encode("cp932"))

    assert len(points) == 3
    assert points[0].date == date(2026, 7, 22)
    assert points[0].nav == 37980


def test_parse_nav_csv_keeps_ascending_order():
    from src.nav import parse_nav_csv

    points = parse_nav_csv(SAMPLE_CSV.encode("cp932"))

    assert [p.date for p in points] == [
        date(2026, 7, 22),
        date(2026, 7, 23),
        date(2026, 7, 24),
    ]


def test_parse_nav_csv_skips_the_header_row():
    from src.nav import parse_nav_csv

    points = parse_nav_csv(SAMPLE_CSV.encode("cp932"))

    assert all(isinstance(p.nav, int) for p in points)


def test_parse_nav_csv_skips_rows_without_a_date():
    from src.nav import parse_nav_csv

    raw = (SAMPLE_CSV + "\n,,,,\n合計,1,2,,\n").encode("cp932")

    assert len(parse_nav_csv(raw)) == 3


def test_parse_nav_csv_returns_empty_for_garbage():
    from src.nav import parse_nav_csv

    assert parse_nav_csv(b"not a csv at all") == []


@responses.activate
def test_fetch_nav_series_requests_the_csv_endpoint():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(
        responses.GET,
        NAV_CSV_URL,
        body=SAMPLE_CSV.encode("cp932"),
        status=200,
    )

    points = fetch_nav_series("JP90C000H1T1", "0331418A")

    assert len(points) == 3
    request = responses.calls[0].request
    assert "isinCd=JP90C000H1T1" in request.url
    assert "associFundCd=0331418A" in request.url


@responses.activate
def test_fetch_nav_series_keeps_only_the_last_n_points():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(
        responses.GET, NAV_CSV_URL, body=SAMPLE_CSV.encode("cp932"), status=200
    )

    points = fetch_nav_series("JP90C000H1T1", "0331418A", days=2)

    assert [p.date for p in points] == [date(2026, 7, 23), date(2026, 7, 24)]


@responses.activate
def test_fetch_nav_series_clamps_zero_days_to_one_point():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(
        responses.GET, NAV_CSV_URL, body=SAMPLE_CSV.encode("cp932"), status=200
    )

    points = fetch_nav_series("JP90C000H1T1", "0331418A", days=0)

    assert [p.date for p in points] == [date(2026, 7, 24)]


@responses.activate
def test_fetch_nav_series_clamps_negative_days_to_one_point():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(
        responses.GET, NAV_CSV_URL, body=SAMPLE_CSV.encode("cp932"), status=200
    )

    points = fetch_nav_series("JP90C000H1T1", "0331418A", days=-5)

    assert [p.date for p in points] == [date(2026, 7, 24)]


@responses.activate
def test_fetch_nav_series_raises_on_http_error():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(responses.GET, NAV_CSV_URL, status=500)

    with pytest.raises(requests.RequestException):
        fetch_nav_series("JP90C000H1T1", "0331418A")
