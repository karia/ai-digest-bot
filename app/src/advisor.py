import logging
from datetime import date, datetime
from typing import Any

from src import config, slack_notifier
from src.advisor_store import (
    Advisor,
    Judgment,
    Product,
    get_all_advisors,
    get_judgment_history,
    put_judgments,
)
from src.agent import run_advice
from src.nav import fetch_nav_series
from src.performance import (
    JUDGMENT_LABELS,
    build_performance,
    format_performance_summary,
    latest_judgment_by_isin,
    summarize_nav,
)
from src.slack_reader import find_last_post_time, lookback_days_for, should_post

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "※ 本投稿は投資判断のための情報提供であり、投資助言ではありません。"
    "最終的な投資判断はご自身の責任で行ってください。"
)

# Keep the performance summary concise while retaining the full history in DynamoDB.
HISTORY_LIMIT = 2


def _product_line(product: Product, nav_summary: str, previous: str | None) -> str:
    holding = "保有中" if product.get("holding") else "乗り換え候補"
    prev = f" / 前回判断: {previous}" if previous else " / 前回判断: なし"
    return (
        f"- {product['name']}（ISIN: {product['isin']},"
        f" 協会コード: {product['assoc_fund_cd']}, {product['category']}, {holding}）\n"
        f"  基準価額: {nav_summary}{prev}"
    )


def _build_context(
    products: list[Product],
    nav_summaries: dict[str, str],
    previous: dict[str, str],
    performance_text: str,
) -> str:
    lines = [
        _product_line(
            p,
            nav_summaries.get(p["isin"], "基準価額データなし"),
            previous.get(p["isin"]),
        )
        for p in products
    ]
    return (
        "## 判断対象商品\n"
        + "\n".join(lines)
        + "\n\n## 過去の判断とその後の騰落率\n"
        + performance_text
    )


def _process_advisor(advisor: Advisor, now: datetime) -> str:
    """Run one advisor end to end; returns its result string."""
    advisor_id = advisor["advisor_id"]
    channel = advisor["channel_id"]
    title = advisor["title"]
    products = advisor["products"]
    interval_days = advisor["interval_days"]

    # Idempotency: a read failure must never be treated as "not posted yet",
    # so it aborts this advisor instead of risking a duplicate post.
    try:
        last_post = find_last_post_time(
            channel, title, lookback_days=lookback_days_for(interval_days)
        )
    except Exception as e:
        logger.error(
            "Cannot read Slack history for %s: %s", advisor_id, e, exc_info=True
        )
        return f"error: slack history unreadable: {e}"

    posting, reason = should_post(
        last_post, now, interval_days, advisor.get("post_weekday")
    )
    logger.info("Posting decision for %s: %s (%s)", advisor_id, posting, reason)
    if not posting:
        return f"skipped: {reason}"

    current_navs: dict[str, int] = {}
    nav_summaries: dict[str, str] = {}
    nav_dates: list[date] = []
    for product in products:
        try:
            series = fetch_nav_series(product["isin"], product["assoc_fund_cd"])
        except Exception as e:
            # Not fatal: the agent still has the nav_fetch tool.
            logger.warning("NAV fetch failed for %s: %s", product["isin"], e)
            continue
        if not series:
            continue
        current_navs[product["isin"]] = series[-1].nav
        nav_summaries[product["isin"]] = summarize_nav(series)
        nav_dates.append(series[-1].date)

    history = get_judgment_history(advisor_id, limit=HISTORY_LIMIT)
    product_names = {p["isin"]: p["name"] for p in products}
    performance_rows = build_performance(history, current_navs, product_names)
    # The oldest of the series, not the newest: one fresh product must not
    # mask a stale one, which is the whole point of showing the date.
    performance_text = format_performance_summary(
        performance_rows, as_of=min(nav_dates) if nav_dates else None
    )
    previous_codes = latest_judgment_by_isin(history)
    previous_labels = {
        isin: JUDGMENT_LABELS.get(code, code) for isin, code in previous_codes.items()
    }

    context = _build_context(products, nav_summaries, previous_labels, performance_text)
    try:
        advice = run_advice(
            context=context,
            trading_notes=advisor["trading_notes"],
            news_feeds=advisor["news_feeds"],
            now=now,
        )
    except Exception as e:
        logger.error("Advice failed for %s: %s", advisor_id, e, exc_info=True)
        return f"error: {e}"

    # The prompt demands one judgment per product, but a silent omission would
    # otherwise cost that product its reply and its history row unnoticed.
    wanted = {p["isin"] for p in products}
    judged = {a.isin for a in advice.advices}
    if missing := wanted - judged:
        logger.warning(
            "Advice for %s omitted %d product(s): %s",
            advisor_id,
            len(missing),
            ", ".join(sorted(missing)),
        )
    # An invented ISIN still gets a reply headed with the raw code and a
    # history row scored at nav 0, so it should not pass unnoticed either.
    if unexpected := judged - wanted:
        logger.warning(
            "Advice for %s judged %d unregistered product(s): %s",
            advisor_id,
            len(unexpected),
            ", ".join(sorted(unexpected)),
        )

    parent_text = (
        f"{advice.summary}\n\n*過去推奨の成績*\n{performance_text}\n\n{DISCLAIMER}"
    )
    try:
        thread_ts = slack_notifier.post_message(channel, text=parent_text, header=title)
    except Exception as e:
        logger.error("Failed to post parent for %s: %s", advisor_id, e, exc_info=True)
        return f"error: {e}"

    for item in advice.advices:
        label = JUDGMENT_LABELS.get(item.judgment, item.judgment)
        name = product_names.get(item.isin, item.isin)
        previous_label = previous_labels.get(item.isin)
        change = (
            f"前回: {previous_label} → 今回: {label}"
            if previous_label
            else f"今回: {label}（初回判断）"
        )
        try:
            slack_notifier.post_message(
                channel,
                text=f"{item.reason}\n\n{change}",
                header=f"{label} {name}",
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error("Failed to post reply for %s: %s", item.isin, e, exc_info=True)

    run_date = now.astimezone(config.JST).strftime("%Y-%m-%d")
    judgments: list[Judgment] = [
        {
            "isin": item.isin,
            "judgment": item.judgment,
            "reason": item.reason,
            "nav": current_navs.get(item.isin, 0),
        }
        for item in advice.advices
    ]
    put_judgments(advisor_id, run_date, judgments)
    return "success"


def run_advisor_job(now: datetime) -> dict[str, Any]:
    """Run the investment advisor job for every registered advisor.

    Args:
        now: The scheduled invocation time; also the JST run date key.

    Returns:
        ``{"status": "ok", "advisors": N, "results": {...}}``; ``results`` is
        omitted when no advisor is registered.
    """
    advisors = get_all_advisors()
    logger.info("Fetched %d advisor(s) from DynamoDB", len(advisors))

    if not advisors:
        logger.info("No advisors found in DynamoDB")
        return {"status": "ok", "advisors": 0}

    results: dict[str, str] = {}
    for advisor in advisors:
        advisor_id = advisor["advisor_id"]
        # Outer safety net: one advisor's uncaught exception (e.g. DynamoDB
        # throttling in get_judgment_history/put_judgments, which are not
        # individually guarded like the Slack/agent calls above) must not
        # abort the remaining advisors in this run.
        try:
            results[advisor_id] = _process_advisor(advisor, now)
        except Exception as e:
            logger.error(
                "Unhandled error processing %s: %s", advisor_id, e, exc_info=True
            )
            results[advisor_id] = f"error: {e}"

    logger.info("Advisor run complete: %s", results)
    return {"status": "ok", "advisors": len(advisors), "results": results}
