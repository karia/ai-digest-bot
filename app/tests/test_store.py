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

    dynamodb_table.delete_item(
        Key={"feed_url": "https://aws.amazon.com/blogs/aws/feed/"}
    )
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
            "channel_id": "COTHER999",
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    feeds = get_all_feeds()
    groups = group_by_channel(feeds)
    assert "CTEST12345" in groups
    assert "COTHER999" in groups


def test_add_feed_creates_new_record(dynamodb_table):
    from src.store import add_feed, get_all_feeds

    add_feed("https://example.com/new/", "New Blog", "CNEW999")
    feeds = {f["feed_url"]: f for f in get_all_feeds()}
    assert "https://example.com/new/" in feeds
    new = feeds["https://example.com/new/"]
    assert new["name"] == "New Blog"
    assert new["channel_id"] == "CNEW999"
    assert new["inserted_at"] == new["updated_at"]


def test_add_feed_preserves_inserted_at_on_update(dynamodb_table):
    from src.store import add_feed, get_all_feeds

    url = "https://aws.amazon.com/blogs/aws/feed/"
    add_feed(url, "Renamed", "CCHANGED")
    feed = next(f for f in get_all_feeds() if f["feed_url"] == url)
    assert feed["name"] == "Renamed"
    assert feed["channel_id"] == "CCHANGED"
    # inserted_at is preserved from the fixture record, updated_at is refreshed
    assert feed["inserted_at"] == "2026-01-01T00:00:00+00:00"
    assert feed["updated_at"] != "2026-01-01T00:00:00+00:00"


def test_delete_feed_removes_record(dynamodb_table):
    from src.store import delete_feed, get_all_feeds

    delete_feed("https://aws.amazon.com/blogs/aws/feed/")
    assert get_all_feeds() == []
