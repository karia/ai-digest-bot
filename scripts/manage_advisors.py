"""Manage advisor definitions in DynamoDB (list / add / delete).

An advisor is one Slack thread definition for investment judgments: a target
channel, a headline title, the products to judge, the market news feeds to
crawl, and the scheme's trading characteristics.

Run from the app/ directory so that the `src` package resolves, e.g.:
    cd app && ADVISORS_TABLE_NAME=... JUDGMENTS_TABLE_NAME=... \
      SOURCES_TABLE_NAME=... uv run python ../scripts/manage_advisors.py list

Prefer the Makefile wrappers: make advisors-list / advisors-add / advisors-delete.
"""

import argparse
import json
from typing import Any, cast

from src.advisor_store import (
    DEFAULT_INTERVAL_DAYS,
    NewsFeed,
    Product,
    add_advisor,
    delete_advisor,
    get_all_advisors,
)

_PRODUCT_FIELDS = ("isin", "name", "category", "holding", "assoc_fund_cd")
_FEED_FIELDS = ("url", "name")

# Monday=0 … Sunday=6, matching datetime.date.weekday().
_WEEKDAY_NAMES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _parse_weekday(raw: str) -> int:
    try:
        return _WEEKDAY_NAMES.index(raw.strip().upper())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--post-weekday must be one of {', '.join(_WEEKDAY_NAMES)}"
        ) from None


def _load_json_list(raw: str, label: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"--{label} must be valid JSON: {e}") from e
    if not isinstance(value, list):
        raise argparse.ArgumentTypeError(f"--{label} must be a JSON array")
    return cast(list[dict[str, Any]], value)


def _parse_products(raw: str) -> list[Product]:
    products = _load_json_list(raw, "products-json")
    for product in products:
        missing = [f for f in _PRODUCT_FIELDS if f not in product]
        if missing:
            raise argparse.ArgumentTypeError(
                f"product {product!r} is missing {', '.join(missing)}"
            )
    return cast(list[Product], products)


def _parse_news_feeds(raw: str) -> list[NewsFeed]:
    feeds = _load_json_list(raw, "news-feeds-json")
    for feed in feeds:
        missing = [f for f in _FEED_FIELDS if f not in feed]
        if missing:
            raise argparse.ArgumentTypeError(
                f"news feed {feed!r} is missing {', '.join(missing)}"
            )
    return cast(list[NewsFeed], feeds)


def cmd_list(args: argparse.Namespace) -> None:
    advisors = get_all_advisors()
    if not advisors:
        print("No advisors registered.")
        return
    for advisor in advisors:
        weekday = advisor.get("post_weekday")
        cadence = (
            f"every {_WEEKDAY_NAMES[weekday]}"
            if weekday is not None
            else f"every {advisor['interval_days']}d"
        )
        print(
            f"# {advisor['advisor_id']}  ({advisor['channel_id']})"
            f"  [{advisor['title']}]  {cadence}"
        )
        for product in advisor["products"]:
            mark = "保有" if product.get("holding") else "候補"
            print(
                f"    - [{mark}] {product['name']}"
                f"  {product['isin']} / {product['assoc_fund_cd']}"
                f"  ({product['category']})"
            )
        for feed in advisor["news_feeds"]:
            print(f"    * {feed['name']:<20} {feed['url']}")
        if advisor["trading_notes"]:
            print(f"    notes: {advisor['trading_notes']}")
    print(f"\n{len(advisors)} advisor(s).")


def cmd_add(args: argparse.Namespace) -> None:
    try:
        add_advisor(
            advisor_id=args.advisor_id,
            channel_id=args.channel_id,
            title=args.title,
            products=args.products_json,
            news_feeds=args.news_feeds_json,
            trading_notes=args.trading_notes,
            interval_days=args.interval_days,
            post_weekday=args.post_weekday,
        )
    except ValueError as e:
        raise SystemExit(f"error: {e}") from e
    cadence = (
        f"every {_WEEKDAY_NAMES[args.post_weekday]}"
        if args.post_weekday is not None
        else f"every {args.interval_days}d"
    )
    print(
        f"Added/updated: {args.advisor_id} -> {args.channel_id}"
        f" ({len(args.products_json)} product(s),"
        f" {len(args.news_feeds_json)} feed(s), {cadence})"
    )


def cmd_delete(args: argparse.Namespace) -> None:
    delete_advisor(args.advisor_id)
    print(f"Deleted: {args.advisor_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage advisor records in DynamoDB.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all registered advisors").set_defaults(
        func=cmd_list
    )

    p_add = sub.add_parser("add", help="Add or update an advisor (full upsert)")
    p_add.add_argument(
        "--advisor-id", required=True, help="Advisor ID (partition key), e.g. ideco-sbi"
    )
    p_add.add_argument("--channel-id", required=True, help="Slack channel ID")
    p_add.add_argument(
        "--title",
        required=True,
        help="Headline header; also identifies this advisor's posts in the channel",
    )
    p_add.add_argument(
        "--products-json",
        required=True,
        type=_parse_products,
        metavar='\'[{"isin":..,"name":..,"category":..,"holding":true,"assoc_fund_cd":..}]\'',
        help="Products to judge, as a JSON array",
    )
    p_add.add_argument(
        "--news-feeds-json",
        required=True,
        type=_parse_news_feeds,
        metavar='\'[{"url":..,"name":..}]\'',
        help="Market news sources, as a JSON array",
    )
    p_add.add_argument(
        "--trading-notes",
        required=True,
        help="Free text on the scheme's trading characteristics (settlement lag etc.)",
    )
    p_add.add_argument(
        "--interval-days",
        type=int,
        default=DEFAULT_INTERVAL_DAYS,
        help=(
            f"Minimum days between posts (default: {DEFAULT_INTERVAL_DAYS})."
            " Ignored when --post-weekday is given"
        ),
    )
    p_add.add_argument(
        "--post-weekday",
        type=_parse_weekday,
        default=None,
        metavar="|".join(_WEEKDAY_NAMES),
        help=(
            "Post on this JST weekday instead of on an interval."
            " A missed target day is picked up by a later run"
        ),
    )
    p_add.set_defaults(func=cmd_add)

    p_del = sub.add_parser("delete", help="Delete an advisor by ID")
    p_del.add_argument("--advisor-id", required=True, help="Advisor ID to delete")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
