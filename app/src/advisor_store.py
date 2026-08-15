import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict, cast

import boto3
from boto3.dynamodb.conditions import Key

from src import config

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_DAYS = 7


class Product(TypedDict):
    """One fund the advisor judges."""

    isin: str
    name: str
    category: str
    # True: currently held. False: a switching candidate only.
    holding: bool
    # 投資信託協会のファンドコード. Needed alongside the ISIN to download NAV.
    assoc_fund_cd: str


class NewsFeed(TypedDict):
    url: str
    name: str


class Advisor(TypedDict):
    """One advisor definition = one Slack thread per run."""

    advisor_id: str
    channel_id: str
    # Headline header; doubles as the marker used to find the previous post.
    title: str
    interval_days: int
    products: list[Product]
    news_feeds: list[NewsFeed]
    # Free text describing the scheme's trading characteristics; injected
    # into the advice system prompt.
    trading_notes: str
    inserted_at: str
    updated_at: str


class Judgment(TypedDict):
    isin: str
    # "BUY" / "SELL" / "HOLD"
    judgment: str
    reason: str
    # NAV (基準価額, whole yen) at the time the judgment was made.
    nav: int


class JudgmentRecord(TypedDict):
    advisor_id: str
    # JST date, "YYYY-MM-DD".
    run_date: str
    judgments: list[Judgment]


def _get_advisors_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.ADVISORS_TABLE_NAME)


def _get_judgments_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.JUDGMENTS_TABLE_NAME)


def _normalize_advisor(raw: dict[str, Any]) -> Advisor:
    """Coerce DynamoDB Decimals back to int and fill in defaults."""
    raw["interval_days"] = int(raw.get("interval_days", DEFAULT_INTERVAL_DAYS))
    return cast(Advisor, raw)


def _normalize_record(raw: dict[str, Any]) -> JudgmentRecord:
    for judgment in raw.get("judgments", []):
        judgment["nav"] = int(judgment.get("nav", 0))
    return cast(JudgmentRecord, raw)


def get_all_advisors() -> list[Advisor]:
    table = _get_advisors_table()
    items: list[Advisor] = []
    response = table.scan()
    items.extend(_normalize_advisor(i) for i in response["Items"])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(_normalize_advisor(i) for i in response["Items"])
    logger.debug(
        "Scanned %d advisor(s) from %s", len(items), config.ADVISORS_TABLE_NAME
    )
    return items


def add_advisor(
    advisor_id: str,
    channel_id: str,
    title: str,
    products: list[Product],
    news_feeds: list[NewsFeed],
    trading_notes: str,
    interval_days: int = DEFAULT_INTERVAL_DAYS,
) -> None:
    """Full upsert of one advisor definition, preserving ``inserted_at``.

    Raises:
        ValueError: if another advisor already posts ``title`` to
            ``channel_id``. The pair is the idempotency marker the advisor
            looks for in Slack history, so a duplicate would make one of the
            two match the other's post and skip forever.
    """
    clash = next(
        (
            a
            for a in get_all_advisors()
            if a["advisor_id"] != advisor_id
            and a["channel_id"] == channel_id
            and a["title"] == title
        ),
        None,
    )
    if clash is not None:
        raise ValueError(
            f"advisor {clash['advisor_id']!r} already posts {title!r}"
            f" to {channel_id}; titles must be unique per channel"
        )

    table = _get_advisors_table()
    now = datetime.now(UTC).isoformat()
    existing = table.get_item(Key={"advisor_id": advisor_id}).get("Item")
    inserted_at = existing["inserted_at"] if existing else now
    table.put_item(
        Item={
            "advisor_id": advisor_id,
            "channel_id": channel_id,
            "title": title,
            "interval_days": interval_days,
            "products": cast(Any, products),
            "news_feeds": cast(Any, news_feeds),
            "trading_notes": trading_notes,
            "inserted_at": inserted_at,
            "updated_at": now,
        }
    )


def delete_advisor(advisor_id: str) -> None:
    table = _get_advisors_table()
    table.delete_item(Key={"advisor_id": advisor_id})


def put_judgments(advisor_id: str, run_date: str, judgments: list[Judgment]) -> None:
    """Store one run's judgments. Re-running the same JST day overwrites it."""
    table = _get_judgments_table()
    table.put_item(
        Item={
            "advisor_id": advisor_id,
            "run_date": run_date,
            # DynamoDB rejects float, so every number goes in as Decimal.
            "judgments": [
                {
                    "isin": j["isin"],
                    "judgment": j["judgment"],
                    "reason": j["reason"],
                    "nav": Decimal(str(j["nav"])),
                }
                for j in judgments
            ],
            "inserted_at": datetime.now(UTC).isoformat(),
        }
    )


def get_judgment_history(advisor_id: str, limit: int = 8) -> list[JudgmentRecord]:
    """Return the advisor's most recent runs, newest first."""
    table = _get_judgments_table()
    response = table.query(
        KeyConditionExpression=Key("advisor_id").eq(advisor_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_normalize_record(i) for i in response["Items"]]
