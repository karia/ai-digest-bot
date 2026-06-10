import importlib

import pytest


@pytest.fixture(autouse=True)
def reload_config():
    import src.config as cfg

    importlib.reload(cfg)


def test_get_all_sources_returns_items(dynamodb_table):
    from src.store import get_all_sources

    sources = get_all_sources()
    assert len(sources) == 1
    assert sources[0]["title"] == "Tech Digest"
    assert sources[0]["channel_id"] == "CTEST12345"
    assert sources[0]["items"][0]["url"] == "https://aws.amazon.com/blogs/aws/feed/"
    assert sources[0]["items"][0]["name"] == "AWS News Blog"


def test_get_all_sources_returns_empty_when_no_items(dynamodb_table):
    from src.store import get_all_sources

    dynamodb_table.delete_item(Key={"title": "Tech Digest"})
    sources = get_all_sources()
    assert sources == []


def test_add_source_creates_new_record(dynamodb_table):
    from src.store import add_source, get_all_sources

    items = [
        {"url": "https://example.com/a", "name": "A"},
        {"url": "https://example.com/b", "name": "B"},
    ]
    add_source("New Digest", "CNEW999", items)
    sources = {s["title"]: s for s in get_all_sources()}
    assert "New Digest" in sources
    new = sources["New Digest"]
    assert new["channel_id"] == "CNEW999"
    assert new["items"] == items
    assert new["inserted_at"] == new["updated_at"]


def test_add_source_preserves_inserted_at_on_update(dynamodb_table):
    from src.store import add_source, get_all_sources

    add_source("Tech Digest", "CCHANGED", [{"url": "https://x.example", "name": "X"}])
    source = next(s for s in get_all_sources() if s["title"] == "Tech Digest")
    assert source["channel_id"] == "CCHANGED"
    assert source["items"] == [{"url": "https://x.example", "name": "X"}]
    # inserted_at is preserved from the fixture record, updated_at is refreshed
    assert source["inserted_at"] == "2026-01-01T00:00:00+00:00"
    assert source["updated_at"] != "2026-01-01T00:00:00+00:00"


def test_delete_source_removes_record(dynamodb_table):
    from src.store import delete_source, get_all_sources

    delete_source("Tech Digest")
    assert get_all_sources() == []
