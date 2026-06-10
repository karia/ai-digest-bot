"""One-off migration from the legacy feeds table to the sources table.

The legacy schema held one row per feed (PK ``feed_url`` + name/channel_id).
The sources schema holds one row per Slack thread (PK ``title`` +
items[{url, name}]). This tool groups legacy feeds by channel and writes one
source per channel.

Idempotent: exits without writing when the sources table already has data or
when the feeds table no longer exists. Run via ``make migrate`` (optionally
``TITLE=...`` to override the default headline title).
"""

import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src import config
from src.store import SourceItem, add_source, get_all_sources

DEFAULT_TITLE = "技術ブログダイジェスト"


def _feeds_table_name() -> str:
    explicit = os.environ.get("FEEDS_TABLE_NAME")
    if explicit:
        return explicit
    if config.SOURCES_TABLE_NAME.endswith("-sources"):
        return config.SOURCES_TABLE_NAME.removesuffix("-sources") + "-feeds"
    raise SystemExit(
        "Cannot derive the feeds table name: set FEEDS_TABLE_NAME explicitly."
    )


def _scan_feeds(table_name: str) -> list[dict[str, Any]] | None:
    """Return all legacy feed rows, or None if the table does not exist."""
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    table = dynamodb.Table(table_name)
    items: list[dict[str, Any]] = []
    try:
        response = table.scan()
        items.extend(response["Items"])
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response["Items"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise
    return items


def migrate() -> None:
    if get_all_sources():
        print("Already migrated (sources table is not empty); nothing to do.")
        return

    feeds_table = _feeds_table_name()
    feeds = _scan_feeds(feeds_table)
    if feeds is None:
        print(f"Feeds table {feeds_table} not found; nothing to migrate.")
        return
    if not feeds:
        print(f"Feeds table {feeds_table} is empty; nothing to migrate.")
        return

    base_title = os.environ.get("MIGRATE_TITLE") or DEFAULT_TITLE

    by_channel: dict[str, list[dict[str, Any]]] = {}
    for feed in feeds:
        by_channel.setdefault(feed["channel_id"], []).append(feed)

    for channel_id, rows in sorted(by_channel.items()):
        rows.sort(key=lambda r: (r.get("inserted_at", ""), r["name"]))
        items: list[SourceItem] = [
            {"url": r["feed_url"], "name": r["name"]} for r in rows
        ]
        title = base_title if len(by_channel) == 1 else f"{base_title} ({channel_id})"
        add_source(title, channel_id, items)
        print(f"Migrated: {title} -> {channel_id} ({len(items)} item(s))")

    print(
        f"Done. Verify the digest, then delete the old table manually:\n"
        f"  aws dynamodb delete-table --table-name {feeds_table}"
    )


if __name__ == "__main__":
    migrate()
