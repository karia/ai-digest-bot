import responses

SAMPLE_CSV = (
    "年月日,基準価額(円),純資産総額（百万円）,分配金,決算期\n"
    "2026年07月23日,38100,13150000,,\n"
    "2026年07月24日,38243,13205500,,\n"
)


@responses.activate
def test_nav_fetch_returns_csv_text():
    from src.nav import NAV_CSV_URL
    from src.tools.nav_fetch import nav_fetch

    responses.add(
        responses.GET, NAV_CSV_URL, body=SAMPLE_CSV.encode("cp932"), status=200
    )

    result = nav_fetch("JP90C000H1T1", "0331418A")

    assert result.startswith("date,nav\n")
    assert "2026-07-24,38243" in result


@responses.activate
def test_nav_fetch_reports_no_data():
    from src.nav import NAV_CSV_URL
    from src.tools.nav_fetch import nav_fetch

    responses.add(responses.GET, NAV_CSV_URL, body=b"", status=200)

    assert nav_fetch("JP90C000H1T1", "0331418A") == "No NAV data found."


@responses.activate
def test_nav_fetch_returns_error_string_instead_of_raising():
    from src.nav import NAV_CSV_URL
    from src.tools.nav_fetch import nav_fetch

    responses.add(responses.GET, NAV_CSV_URL, status=503)

    result = nav_fetch("JP90C000H1T1", "0331418A")

    assert result.startswith("Error fetching NAV:")
