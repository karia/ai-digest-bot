import calendar
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import boto3

from src import config, slack_notifier

logger = logging.getLogger(__name__)

# Services under this are folded into one trailing line. Roughly half the
# services on an account bill sub-cent amounts daily, and listing them pushes
# the movers off the first screen.
MIN_SERVICE_COST = Decimal("0.01")

# Service names run to 40 characters ("Claude Sonnet 5 (Amazon Bedrock Edition)"),
# which wraps the monospace table on a phone.
NAME_WIDTH = 30

_CENT = Decimal("0.01")


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month_start(day: date) -> date:
    # +32 days from the 1st always lands in the following month, whatever its
    # length, so this needs no month-length table.
    return _month_start(_month_start(day) + timedelta(days=32))


def _same_day_last_month(day: date) -> date:
    """Return the same day one month earlier, clamped to that month's last day."""
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _fetch_daily_costs(
    client: Any, start: date, end: date
) -> dict[date, dict[str, Decimal]]:
    """Fetch per-service unblended cost for each day in ``[start, end]``.

    Args:
        client: A Cost Explorer client.
        start: First day to include.
        end: Last day to include (inclusive, unlike the API's own End).

    Returns:
        ``{day: {service name: cost}}``. A day missing from the mapping has
        no data; a service missing from a present day cost nothing that day.
    """
    costs: dict[date, dict[str, Decimal]] = {}
    next_token: str | None = None
    while True:
        # Cost Explorer treats End as exclusive.
        response = client.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": (end + timedelta(days=1)).isoformat(),
            },
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            **({"NextPageToken": next_token} if next_token else {}),
        )
        for result in response["ResultsByTime"]:
            # A day CE has not filled in yet comes back with no groups, and so
            # does a day that genuinely cost nothing. One grouped response
            # cannot tell them apart, so neither is recorded: reporting a
            # missing day as $0.00 is the worse of the two mistakes.
            if not result["Groups"]:
                continue
            day = date.fromisoformat(result["TimePeriod"]["Start"])
            # Total is empty whenever GroupBy is set, so the groups are the
            # only source of truth here.
            day_costs = costs.setdefault(day, {})
            for group in result["Groups"]:
                amount = Decimal(group["Metrics"]["UnblendedCost"]["Amount"])
                day_costs[group["Keys"][0]] = (
                    day_costs.get(group["Keys"][0], Decimal(0)) + amount
                )
        next_token = response.get("NextPageToken")
        if not next_token:
            return costs


def _fetch_month_forecast(client: Any, today: date) -> Decimal | None:
    """Forecast the current month's total spend, or None when CE declines.

    A MONTHLY forecast starting mid-month is normalized by the API to the whole
    month, so the returned total is the month's landing figure and must not be
    added to month-to-date. Accounts without enough history get an error rather
    than a forecast, which is not worth failing the whole report over.
    """
    try:
        response = client.get_cost_forecast(
            TimePeriod={
                "Start": today.isoformat(),
                "End": _next_month_start(today).isoformat(),
            },
            Granularity="MONTHLY",
            Metric="UNBLENDED_COST",
        )
    except Exception as e:
        logger.warning("Cost forecast unavailable: %s", e)
        return None
    return Decimal(response["Total"]["Amount"])


def _usd(amount: Decimal) -> str:
    return f"${amount.quantize(_CENT, rounding=ROUND_HALF_UP)}"


def _service_cost(
    costs: dict[date, dict[str, Decimal]], day: date, service: str
) -> Decimal | None:
    """Cost of one service on one day, or None when that day has no data."""
    if day not in costs:
        return None
    return costs[day].get(service, Decimal(0))


def _delta(current: Decimal, baseline: Decimal | None) -> str:
    if baseline is None:
        return "n/a"
    diff = (current - baseline).quantize(_CENT, rounding=ROUND_HALF_UP)
    if diff == 0:
        return "±0"
    return f"{'+' if diff > 0 else '-'}${abs(diff)}"


def _day_total(costs: dict[date, dict[str, Decimal]], day: date) -> Decimal | None:
    if day not in costs:
        return None
    return sum(costs[day].values(), Decimal(0))


def _service_table(
    costs: dict[date, dict[str, Decimal]],
    target: date,
    previous: date,
    last_month: date,
) -> str:
    rows = sorted(costs[target].items(), key=lambda kv: kv[1], reverse=True)
    # abs(), so a refund or credit is never folded away as if it were noise.
    listed = [(name, cost) for name, cost in rows if abs(cost) >= MIN_SERVICE_COST]
    folded = [cost for _, cost in rows if abs(cost) < MIN_SERVICE_COST]

    lines = []
    for name, cost in listed:
        label = name if len(name) <= NAME_WIDTH else name[: NAME_WIDTH - 1] + "…"
        lines.append(
            f"{label:<{NAME_WIDTH}} {_usd(cost):>8}"
            f"  前日 {_delta(cost, _service_cost(costs, previous, name)):>7}"
            f"  前月同日 {_delta(cost, _service_cost(costs, last_month, name)):>7}"
        )
    table = "```\n" + "\n".join(lines) + "\n```" if lines else ""
    if folded:
        tail = f"他 {len(folded)} サービス {_usd(sum(folded, Decimal(0)))}"
        table = f"{table}\n{tail}" if table else tail
    return table


def _build_report(
    costs: dict[date, dict[str, Decimal]], forecast: Decimal | None, today: date
) -> str:
    month_to_date = sum(
        (
            sum(day_costs.values(), Decimal(0))
            for day, day_costs in costs.items()
            if day >= _month_start(today)
        ),
        Decimal(0),
    )
    lines = [f"*当月累計* {_usd(month_to_date)}"]
    if forecast is not None:
        lines[0] += f"  →  *着地見込み* {_usd(forecast)}"

    target = today - timedelta(days=1)
    target_total = _day_total(costs, target)
    if target_total is None:
        # CE can lag a day. Saying so beats silently reporting the day before
        # as if it were yesterday.
        lines.append(f"{target:%m/%d} 分はまだ Cost Explorer に反映されていません。")
        return "\n".join(lines)

    previous = target - timedelta(days=1)
    last_month = _same_day_last_month(target)
    lines.append(
        f"*前日 {target:%m/%d}* {_usd(target_total)}"
        f" (前々日比 {_delta(target_total, _day_total(costs, previous))}"
        f" / 前月同日比 {_delta(target_total, _day_total(costs, last_month))})"
    )
    table = _service_table(costs, target, previous, last_month)
    if table:
        lines.append("")
        lines.append(table)
    return "\n".join(lines)


def run_cost_job(now: datetime) -> dict[str, Any]:
    """Post the daily AWS cost report to Slack.

    Args:
        now: The scheduled invocation time.

    Returns:
        ``{"status": "ok", "date": "YYYY-MM-DD"}``.
    """
    # AWS bills by UTC days and Cost Explorer's daily buckets follow them, so
    # every window below is UTC. Taking the day before the current UTC day is
    # what guarantees the target has closed: the JST calendar rolls over nine
    # hours early, and its "yesterday" is still open until 09:00 JST.
    today = now.astimezone(UTC).date()
    target = today - timedelta(days=1)
    # One call covers every window the report needs: month-to-date, the last
    # two days, and the same day of the previous month.
    start = min(
        _same_day_last_month(target), target - timedelta(days=1), _month_start(today)
    )

    client = boto3.client("ce", region_name=config.AWS_REGION)
    costs = _fetch_daily_costs(client, start, today)
    logger.info("Fetched %d day(s) of cost data from %s", len(costs), start)
    forecast = _fetch_month_forecast(client, today)

    channel = config.get_cost_channel_id()
    slack_notifier.post_message(
        channel,
        text=_build_report(costs, forecast, today),
        # The heading is the reader's own date, not the billing calendar's.
        header=f"AWS コスト {now.astimezone(config.JST).date():%Y-%m-%d}",
    )
    logger.info("Cost report for %s posted to %s", target, channel)
    return {"status": "ok", "date": target.isoformat()}
