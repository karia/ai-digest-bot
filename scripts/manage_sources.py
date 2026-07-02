"""Manage source records in DynamoDB (list / add / delete).

A source is one Slack thread definition: a title (the daily headline), a target
channel, and a list of items (url + display name). One crawl posts a headline
message and one threaded reply per item.

Run from the app/ directory so that the `src` package resolves, e.g.:
    cd app && SOURCES_TABLE_NAME=... uv run python ../scripts/manage_sources.py list

Prefer the Makefile wrappers: make sources-list / sources-add / sources-delete.
"""

import argparse

from src.store import SourceItem, add_source, delete_source, get_all_sources


def _parse_item(raw: str) -> SourceItem:
    url, _, rest = raw.partition("|")
    name, _, option = rest.partition("|")
    if not url or not name:
        raise argparse.ArgumentTypeError(
            f'--item must be "url|name" or "url|name|daily", got {raw!r}'
        )
    item: SourceItem = {"url": url.strip(), "name": name.strip()}
    if option:
        if option.strip() != "daily":
            raise argparse.ArgumentTypeError(
                f'--item option must be "daily", got {option.strip()!r}'
            )
        item["split_by_day"] = True
    return item


def _parse_items(raw: str) -> list[SourceItem]:
    items = [_parse_item(part.strip()) for part in raw.split(";") if part.strip()]
    if not items:
        raise argparse.ArgumentTypeError(f"--item must not be empty, got {raw!r}")
    return items


def _parse_schedule(raw: str) -> str:
    schedule = raw.strip()
    if not schedule:
        raise argparse.ArgumentTypeError("--posting-schedule must not be empty")
    return schedule


def cmd_list(args: argparse.Namespace) -> None:
    sources = get_all_sources()
    if not sources:
        print("No sources registered.")
        return
    for source in sources:
        schedule = source.get("posting_schedule", "毎日")
        print(
            f"# {source['title']}  ({source['channel_id']})"
            f"  [{schedule}]  {source['inserted_at']}"
        )
        for item in source["items"]:
            mark = "  [daily]" if item.get("split_by_day") else ""
            print(f"    - {item['name']:<25} {item['url']}{mark}")
    print(f"\n{len(sources)} source(s).")


def cmd_add(args: argparse.Namespace) -> None:
    add_source(args.title, args.channel_id, args.item, args.posting_schedule)
    print(
        f"Added/updated: {args.title} -> {args.channel_id}"
        f" ({len(args.item)} item(s), schedule: {args.posting_schedule})"
    )


def cmd_delete(args: argparse.Namespace) -> None:
    delete_source(args.title)
    print(f"Deleted: {args.title}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage source records in DynamoDB.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all registered sources").set_defaults(
        func=cmd_list
    )

    p_add = sub.add_parser("add", help="Add or update a source (full upsert)")
    p_add.add_argument("--title", required=True, help="Headline title (partition key)")
    p_add.add_argument("--channel-id", required=True, help="Slack channel ID")
    p_add.add_argument(
        "--item",
        required=True,
        action="extend",
        type=_parse_items,
        metavar='"URL|NAME[|daily][; URL|NAME[|daily] ...]"',
        help='Feed items as "url|name", separated by ";" (also repeatable).'
        ' Append "|daily" to post one threaded reply per JST day instead of'
        " a single reply",
    )
    p_add.add_argument(
        "--posting-schedule",
        type=_parse_schedule,
        default="毎日",
        help='Free-text posting schedule interpreted by the agent, e.g. "毎日", "月曜と木曜" (default: 毎日)',
    )
    p_add.set_defaults(func=cmd_add)

    p_del = sub.add_parser("delete", help="Delete a source by title")
    p_del.add_argument("--title", required=True, help="Title to delete")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
