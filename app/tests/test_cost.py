from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

JST = timezone(timedelta(hours=9))

S3 = "Amazon Simple Storage Service"
SONNET = "Claude Sonnet 5 (Amazon Bedrock Edition)"
GLUE = "AWS Glue"


def _group(service, amount):
    return {
        "Keys": [service],
        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
    }


def _day(day, groups):
    return {
        "TimePeriod": {"Start": day, "End": day},
        "Total": {},
        "Groups": groups,
    }


class FakeCostExplorer:
    """Minimal Cost Explorer stand-in that records the requests it receives."""

    def __init__(self, pages, forecast="52.00"):
        self.pages = list(pages)
        self.forecast = forecast
        self.usage_calls = []
        self.forecast_calls = []

    def get_cost_and_usage(self, **kwargs):
        self.usage_calls.append(kwargs)
        page = self.pages[len(self.usage_calls) - 1]
        response = {"ResultsByTime": page}
        if len(self.usage_calls) < len(self.pages):
            response["NextPageToken"] = f"page-{len(self.usage_calls)}"
        return response

    def get_cost_forecast(self, **kwargs):
        self.forecast_calls.append(kwargs)
        if isinstance(self.forecast, Exception):
            raise self.forecast
        return {"Total": {"Amount": self.forecast, "Unit": "USD"}}


def test_same_day_last_month_clamps_to_a_shorter_month():
    from src import cost

    assert cost._same_day_last_month(date(2026, 3, 31)) == date(2026, 2, 28)
    assert cost._same_day_last_month(date(2024, 3, 31)) == date(2024, 2, 29)
    assert cost._same_day_last_month(date(2026, 1, 15)) == date(2025, 12, 15)
    assert cost._same_day_last_month(date(2026, 9, 11)) == date(2026, 8, 11)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 31), date(2026, 2, 1)),
        (date(2026, 2, 1), date(2026, 3, 1)),
        (date(2024, 2, 29), date(2024, 3, 1)),
        (date(2026, 12, 5), date(2027, 1, 1)),
    ],
)
def test_next_month_start_handles_every_month_length(day, expected):
    from src import cost

    assert cost._next_month_start(day) == expected


def test_fetch_daily_costs_asks_for_an_exclusive_end_and_follows_pages():
    from src import cost

    client = FakeCostExplorer(
        pages=[
            [_day("2026-09-10", [_group(S3, "1.00")])],
            [_day("2026-09-11", [_group(S3, "1.01"), _group(SONNET, "0.15")])],
        ]
    )

    costs = cost._fetch_daily_costs(client, date(2026, 9, 10), date(2026, 9, 11))

    # The API's End is exclusive, so the last day asked for is one past the range.
    assert client.usage_calls[0]["TimePeriod"] == {
        "Start": "2026-09-10",
        "End": "2026-09-12",
    }
    assert client.usage_calls[1]["NextPageToken"] == "page-1"
    assert costs == {
        date(2026, 9, 10): {S3: Decimal("1.00")},
        date(2026, 9, 11): {S3: Decimal("1.01"), SONNET: Decimal("0.15")},
    }


def test_fetch_month_forecast_covers_the_whole_month_and_survives_a_refusal():
    from src import cost

    client = FakeCostExplorer(pages=[[]], forecast="52.00")
    assert cost._fetch_month_forecast(client, date(2026, 9, 12)) == Decimal("52.00")
    assert client.forecast_calls[0]["TimePeriod"] == {
        "Start": "2026-09-12",
        "End": "2026-10-01",
    }

    refusing = FakeCostExplorer(pages=[[]], forecast=RuntimeError("not enough data"))
    assert cost._fetch_month_forecast(refusing, date(2026, 9, 12)) is None


def _sample_costs():
    return {
        # Same day last month, for the month-over-month column.
        date(2026, 8, 11): {S3: Decimal("0.91"), GLUE: Decimal("0.004")},
        # Two days before the target, unused except as filler.
        date(2026, 9, 1): {S3: Decimal("1.00")},
        # The day before the target, for the day-over-day column.
        date(2026, 9, 10): {S3: Decimal("0.99"), SONNET: Decimal("0.18")},
        # The target day.
        date(2026, 9, 11): {
            S3: Decimal("1.01"),
            SONNET: Decimal("0.15"),
            GLUE: Decimal("0.002"),
        },
    }


def test_build_report_shows_month_to_date_forecast_and_both_deltas():
    from src import cost

    report = cost._build_report(
        _sample_costs(), Decimal("52.00"), date(2026, 9, 12), date(2026, 9, 11)
    )

    # Month to date counts only days in the current month: 1.00 + 1.17 + 1.162
    assert "*当月累計* $3.33" in report
    assert "*着地見込み* $52.00" in report
    # Target day total 1.162 vs 1.17 the day before and 0.914 a month earlier
    assert "*09/11 の利用* $1.16" in report
    assert "前日比 -$0.01" in report
    assert "前月同日比 +$0.25" in report
    # S3 rose a cent day over day and a dime month over month
    assert "前日  +$0.02" in report
    assert "前月同日  +$0.10" in report
    # Sonnet had no cost a month ago, so the whole amount is the increase
    assert "前月同日  +$0.15" in report


def test_build_report_folds_sub_cent_services_into_one_line():
    from src import cost

    report = cost._build_report(
        _sample_costs(), None, date(2026, 9, 12), date(2026, 9, 11)
    )

    assert GLUE not in report
    assert "他 1 サービス $0.00" in report
    # No forecast available means no landing figure is claimed
    assert "着地見込み" not in report


def test_build_report_marks_a_baseline_day_with_no_data_as_unknown():
    from src import cost

    costs = _sample_costs()
    del costs[date(2026, 8, 11)]

    report = cost._build_report(costs, None, date(2026, 9, 12), date(2026, 9, 11))

    assert "前月同日比 n/a" in report
    assert "前月同日     n/a" in report


def test_build_report_says_so_when_the_target_day_has_not_landed_yet():
    from src import cost

    costs = {date(2026, 9, 1): {S3: Decimal("2.00")}}

    report = cost._build_report(
        costs, Decimal("52.00"), date(2026, 9, 12), date(2026, 9, 11)
    )

    assert "*当月累計* $2.00" in report
    assert "09/11 分はまだ Cost Explorer に反映されていません。" in report
    # Without the day's data there is nothing to break down
    assert "```" not in report


@pytest.mark.parametrize(
    ("now", "expected_target"),
    [
        # 12h after the day closed: the earliest moment the margin allows it.
        (datetime(2026, 9, 12, 12, 0, tzinfo=UTC), date(2026, 9, 11)),
        # One minute earlier the margin is not met, so it drops back a day.
        (datetime(2026, 9, 12, 11, 59, tzinfo=UTC), date(2026, 9, 10)),
        # JST 23:00, the scheduled hour.
        (datetime(2026, 9, 12, 14, 0, tzinfo=UTC), date(2026, 9, 11)),
        # JST 08:00: the JST calendar already calls the 11th "yesterday" while
        # that UTC day has an hour left to run.
        (datetime(2026, 9, 11, 23, 0, tzinfo=UTC), date(2026, 9, 10)),
        # Just past UTC midnight, when the day that closed is still landing.
        (datetime(2026, 9, 12, 0, 30, tzinfo=UTC), date(2026, 9, 10)),
        # A JST-expressed instant resolves through its UTC equivalent.
        (datetime(2026, 9, 12, 23, 0, tzinfo=JST), date(2026, 9, 11)),
    ],
)
def test_target_day_depends_on_the_settling_margin_not_the_launch_hour(
    now, expected_target
):
    from src import cost

    assert cost._target_day(now) == expected_target


def test_target_day_is_always_a_day_that_closed_before_the_margin():
    from src import cost

    # Sweep a full day of launch hours: whatever the schedule, the reported
    # day must have closed at least SETTLING_MARGIN ago.
    for hour in range(24):
        for minute in (0, 31):
            now = datetime(2026, 3, 2, hour, minute, tzinfo=UTC)
            target = cost._target_day(now)
            closed_at = datetime(
                target.year, target.month, target.day, tzinfo=UTC
            ) + timedelta(days=1)
            assert now - closed_at >= cost.SETTLING_MARGIN


def test_run_cost_job_reads_one_month_of_data_and_posts_to_the_cost_channel():
    from src import cost

    client = FakeCostExplorer(
        pages=[
            [
                _day("2026-08-11", [_group(S3, "0.91")]),
                _day("2026-09-10", [_group(S3, "0.99")]),
                _day("2026-09-11", [_group(S3, "1.01")]),
            ]
        ]
    )

    with (
        patch("src.cost.boto3.client", return_value=client),
        patch("src.cost.config.get_cost_channel_id", return_value="CCOST00001"),
        patch("src.cost.slack_notifier.post_message", return_value="1.2") as mock_post,
    ):
        # JST 23:00 on 2026-09-12.
        result = cost.run_cost_job(datetime(2026, 9, 12, 14, 0, tzinfo=UTC))

    assert result == {"status": "ok", "date": "2026-09-11"}
    assert client.usage_calls[0]["TimePeriod"] == {
        "Start": "2026-08-11",
        "End": "2026-09-13",
    }
    assert len(client.usage_calls) == 1
    assert len(client.forecast_calls) == 1
    assert mock_post.call_args[0][0] == "CCOST00001"
    assert mock_post.call_args.kwargs["header"] == "AWS コスト 2026-09-12"
    # Every figure is preliminary, and the message has to say so.
    assert cost.PRELIMINARY_NOTE in mock_post.call_args.kwargs["text"]


def test_run_cost_job_skips_a_day_that_has_not_settled_yet():
    from src import cost

    client = FakeCostExplorer(
        pages=[
            [
                _day("2026-09-10", [_group(S3, "0.99")]),
                # The 11th closed half an hour ago and has barely landed.
                _day("2026-09-11", [_group(S3, "0.04")]),
            ]
        ]
    )

    with (
        patch("src.cost.boto3.client", return_value=client),
        patch("src.cost.config.get_cost_channel_id", return_value="CCOST00001"),
        patch("src.cost.slack_notifier.post_message", return_value="1.2") as mock_post,
    ):
        result = cost.run_cost_job(datetime(2026, 9, 12, 0, 30, tzinfo=UTC))

    # Quoting the 11th here would understate it by an order of magnitude.
    assert result == {"status": "ok", "date": "2026-09-10"}
    assert "09/10 の利用" in mock_post.call_args.kwargs["text"]
    assert "$0.04" not in mock_post.call_args.kwargs["text"]


def test_fetch_daily_costs_leaves_out_a_day_cost_explorer_has_not_filled_in():
    from src import cost

    client = FakeCostExplorer(
        pages=[
            [
                _day("2026-09-11", [_group(S3, "1.01")]),
                # CE returns the current day with no groups until it lands.
                _day("2026-09-12", []),
            ]
        ]
    )

    costs = cost._fetch_daily_costs(client, date(2026, 9, 11), date(2026, 9, 12))

    # Recording it as {} would make _day_total report a confident $0.00.
    assert date(2026, 9, 12) not in costs
    assert costs[date(2026, 9, 11)] == {S3: Decimal("1.01")}


def test_build_report_reports_an_empty_target_day_as_not_landed_yet():
    from src import cost

    client = FakeCostExplorer(
        pages=[[_day("2026-09-10", [_group(S3, "0.99")]), _day("2026-09-11", [])]]
    )
    costs = cost._fetch_daily_costs(client, date(2026, 9, 10), date(2026, 9, 11))

    report = cost._build_report(costs, None, date(2026, 9, 12), date(2026, 9, 11))

    assert "09/11 分はまだ Cost Explorer に反映されていません。" in report
    assert "$0.00" not in report


def test_service_table_keeps_a_refund_out_of_the_folded_line():
    from src import cost

    costs = {
        date(2026, 9, 10): {S3: Decimal("1.00")},
        date(2026, 9, 11): {
            S3: Decimal("1.01"),
            # A credit is small by value but is exactly what needs surfacing.
            "Refund": Decimal("-10.00"),
            GLUE: Decimal("0.002"),
        },
    }

    report = cost._build_report(costs, None, date(2026, 9, 12), date(2026, 9, 11))

    assert "Refund" in report
    assert "-$10.00" in report
    # Only the sub-cent service is folded away
    assert "他 1 サービス" in report
