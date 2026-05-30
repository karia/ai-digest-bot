from typing import TypedDict, cast

import boto3

from src import config


class FeedItem(TypedDict):
    feed_url: str
    name: str
    category: str
    channel_id: str
    inserted_at: str
    updated_at: str


def get_all_feeds() -> list[FeedItem]:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    table = dynamodb.Table(config.FEEDS_TABLE_NAME)
    items: list[FeedItem] = []
    response = table.scan()
    items.extend(cast(list[FeedItem], response["Items"]))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(cast(list[FeedItem], response["Items"]))
    return items


def group_by_channel(feeds: list[FeedItem]) -> dict[str, list[FeedItem]]:
    result: dict[str, list[FeedItem]] = {}
    for feed in feeds:
        ch = feed["channel_id"]
        result.setdefault(ch, []).append(feed)
    return result
