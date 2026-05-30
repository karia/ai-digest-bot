"""Seed initial feed records into DynamoDB."""

import os
from datetime import datetime, timezone

import boto3

TABLE_NAME = os.environ.get("FEEDS_TABLE_NAME", "aws-blog-digest-feeds")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

INITIAL_FEEDS = [
    {
        "feed_url": "https://aws.amazon.com/blogs/aws/feed/",
        "name": "AWS News Blog",
        "category": "aws",
        "channel_id": "CXXXXXXXXXX",  # 要設定
    },
]


def main() -> None:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc).isoformat()

    for feed in INITIAL_FEEDS:
        item = {**feed, "inserted_at": now, "updated_at": now}
        table.put_item(Item=item)
        print(f"Seeded: {feed['feed_url']}")

    print(f"Done. {len(INITIAL_FEEDS)} feed(s) seeded into {TABLE_NAME}.")


if __name__ == "__main__":
    main()
