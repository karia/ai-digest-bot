import importlib

import pytest


@pytest.fixture(autouse=True)
def reload_config():
    import src.config as cfg
    importlib.reload(cfg)


def test_get_all_feeds_returns_items(dynamodb_table):
    from src.store import get_all_feeds

    feeds = get_all_feeds()
    assert len(feeds) == 1
    assert feeds[0]["feed_url"] == "https://aws.amazon.com/blogs/aws/feed/"
    assert feeds[0]["channel_id"] == "CTEST12345"


def test_get_all_feeds_returns_empty_when_no_items(dynamodb_table):
    from src.store import get_all_feeds

    dynamodb_table.delete_item(Key={"feed_url": "https://aws.amazon.com/blogs/aws/feed/"})
    feeds = get_all_feeds()
    assert feeds == []


def test_group_by_channel_single_channel(dynamodb_table):
    from src.store import get_all_feeds, group_by_channel

    feeds = get_all_feeds()
    groups = group_by_channel(feeds)
    assert "CTEST12345" in groups
    assert len(groups["CTEST12345"]) == 1


def test_group_by_channel_multiple_channels(dynamodb_table):
    from src.store import get_all_feeds, group_by_channel

    dynamodb_table.put_item(
        Item={
            "feed_url": "https://example.com/feed/",
            "name": "Example Blog",
            "category": "other",
            "channel_id": "COTHER999",
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    feeds = get_all_feeds()
    groups = group_by_channel(feeds)
    assert "CTEST12345" in groups
    assert "COTHER999" in groups
