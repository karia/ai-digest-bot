import logging
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import boto3

from src import config

logger = logging.getLogger(__name__)


class FeedItem(TypedDict):
    feed_url: str
    name: str
    channel_id: str
    inserted_at: str
    updated_at: str


def _get_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.FEEDS_TABLE_NAME)


def get_all_feeds() -> list[FeedItem]:
    table = _get_table()
    items: list[FeedItem] = []
    response = table.scan()
    items.extend(cast(list[FeedItem], response["Items"]))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(cast(list[FeedItem], response["Items"]))
    logger.debug("Scanned %d feed(s) from %s", len(items), config.FEEDS_TABLE_NAME)
    return items


def add_feed(feed_url: str, name: str, channel_id: str) -> None:
    table = _get_table()
    now = datetime.now(UTC).isoformat()
    existing = table.get_item(Key={"feed_url": feed_url}).get("Item")
    inserted_at = existing["inserted_at"] if existing else now
    table.put_item(
        Item={
            "feed_url": feed_url,
            "name": name,
            "channel_id": channel_id,
            "inserted_at": inserted_at,
            "updated_at": now,
        }
    )


def delete_feed(feed_url: str) -> None:
    table = _get_table()
    table.delete_item(Key={"feed_url": feed_url})
