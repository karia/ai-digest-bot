import logging
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import boto3

from src import config

logger = logging.getLogger(__name__)


class SourceItem(TypedDict):
    url: str
    name: str


class Source(TypedDict):
    title: str
    channel_id: str
    items: list[SourceItem]
    inserted_at: str
    updated_at: str


def _get_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.SOURCES_TABLE_NAME)


def get_all_sources() -> list[Source]:
    table = _get_table()
    items: list[Source] = []
    response = table.scan()
    items.extend(cast(list[Source], response["Items"]))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(cast(list[Source], response["Items"]))
    logger.debug("Scanned %d source(s) from %s", len(items), config.SOURCES_TABLE_NAME)
    return items


def add_source(title: str, channel_id: str, items: list[SourceItem]) -> None:
    table = _get_table()
    now = datetime.now(UTC).isoformat()
    existing = table.get_item(Key={"title": title}).get("Item")
    inserted_at = existing["inserted_at"] if existing else now
    table.put_item(
        Item={
            "title": title,
            "channel_id": channel_id,
            "items": cast(Any, items),
            "inserted_at": inserted_at,
            "updated_at": now,
        }
    )


def delete_source(title: str) -> None:
    table = _get_table()
    table.delete_item(Key={"title": title})
