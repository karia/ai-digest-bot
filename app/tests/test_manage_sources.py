import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


@pytest.fixture
def parse_items(env_vars):
    # src.config reads env vars at import time, so import after env_vars is set
    from manage_sources import _parse_items

    return _parse_items


def test_parse_items_single(parse_items):
    items = parse_items("https://example.com/feed|Example Blog")
    assert items == [{"url": "https://example.com/feed", "name": "Example Blog"}]


def test_parse_items_multiple_with_spaces_in_names(parse_items):
    items = parse_items(
        "https://b.hatena.ne.jp/hotentry/it.rss|はてブ テクノロジー;"
        " https://example.com/feed|AWS What's New (EN)|daily"
    )
    assert items == [
        {
            "url": "https://b.hatena.ne.jp/hotentry/it.rss",
            "name": "はてブ テクノロジー",
        },
        {
            "url": "https://example.com/feed",
            "name": "AWS What's New (EN)",
            "split_by_day": True,
        },
    ]


def test_parse_items_ignores_trailing_separator_and_whitespace(parse_items):
    items = parse_items(" https://example.com/feed|Example ; ")
    assert items == [{"url": "https://example.com/feed", "name": "Example"}]


def test_parse_items_rejects_empty(parse_items):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_items(" ; ")


def test_parse_items_rejects_missing_name(parse_items):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_items("https://example.com/feed")


def test_parse_items_rejects_unknown_option(parse_items):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_items("https://example.com/feed|Example|weekly")
