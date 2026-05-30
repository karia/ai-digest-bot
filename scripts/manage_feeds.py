"""Manage feed records in DynamoDB (list / add / delete).

Run from the app/ directory so that the `src` package resolves, e.g.:
    cd app && FEEDS_TABLE_NAME=... uv run python ../scripts/manage_feeds.py list

Prefer the Makefile wrappers: make feeds-list / feeds-add / feeds-delete.
"""

import argparse

from src.store import add_feed, delete_feed, get_all_feeds


def cmd_list(args: argparse.Namespace) -> None:
    feeds = get_all_feeds()
    if not feeds:
        print("No feeds registered.")
        return
    header = f"{'feed_url':<50} {'name':<25} {'channel_id':<15} inserted_at"
    print(header)
    print("-" * len(header))
    for feed in feeds:
        print(
            f"{feed['feed_url']:<50} {feed['name']:<25} "
            f"{feed['channel_id']:<15} {feed['inserted_at']}"
        )
    print(f"\n{len(feeds)} feed(s).")


def cmd_add(args: argparse.Namespace) -> None:
    add_feed(args.feed_url, args.name, args.channel_id)
    print(f"Added/updated: {args.feed_url} -> {args.channel_id}")


def cmd_delete(args: argparse.Namespace) -> None:
    delete_feed(args.feed_url)
    print(f"Deleted: {args.feed_url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage feed records in DynamoDB.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all registered feeds").set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="Add or update a feed")
    p_add.add_argument("--feed-url", required=True, help="Feed URL (partition key)")
    p_add.add_argument("--name", required=True, help="Display name")
    p_add.add_argument("--channel-id", required=True, help="Slack channel ID")
    p_add.set_defaults(func=cmd_add)

    p_del = sub.add_parser("delete", help="Delete a feed by URL")
    p_del.add_argument("--feed-url", required=True, help="Feed URL to delete")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
