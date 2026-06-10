import importlib

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.store as store

    importlib.reload(store)


def _create_sources_table(dynamodb):
    return dynamodb.create_table(
        TableName="test-sources",
        KeySchema=[{"AttributeName": "title", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "title", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_feeds_table(dynamodb, rows):
    table = dynamodb.create_table(
        TableName="test-feeds",
        KeySchema=[{"AttributeName": "feed_url", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "feed_url", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    for row in rows:
        table.put_item(Item=row)
    return table


def _feed_row(url, name, channel_id, inserted_at="2026-01-01T00:00:00+00:00"):
    return {
        "feed_url": url,
        "name": name,
        "channel_id": channel_id,
        "inserted_at": inserted_at,
        "updated_at": inserted_at,
    }


def test_migrate_noop_when_sources_not_empty():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)
        sources.put_item(
            Item={
                "title": "Existing",
                "channel_id": "C1",
                "items": [{"url": "https://x.example", "name": "X"}],
                "inserted_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        )
        _create_feeds_table(dynamodb, [_feed_row("https://a.example", "A", "C1")])

        from src.migrate import migrate

        migrate()

        items = sources.scan()["Items"]
        assert len(items) == 1
        assert items[0]["title"] == "Existing"


def test_migrate_noop_when_feeds_table_missing(capsys):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)

        from src.migrate import migrate

        migrate()

        assert "nothing to migrate" in capsys.readouterr().out
        assert sources.scan()["Items"] == []


def test_migrate_aggregates_single_channel_into_one_source():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)
        _create_feeds_table(
            dynamodb,
            [
                _feed_row("https://b.example", "B", "C1", "2026-01-02T00:00:00+00:00"),
                _feed_row("https://a.example", "A", "C1", "2026-01-01T00:00:00+00:00"),
            ],
        )

        from src.migrate import migrate

        migrate()

        items = sources.scan()["Items"]
        assert len(items) == 1
        source = items[0]
        assert source["title"] == "技術ブログダイジェスト"
        assert source["channel_id"] == "C1"
        # Ordered by inserted_at (oldest first)
        assert source["items"] == [
            {"url": "https://a.example", "name": "A"},
            {"url": "https://b.example", "name": "B"},
        ]


def test_migrate_creates_one_source_per_channel():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)
        _create_feeds_table(
            dynamodb,
            [
                _feed_row("https://a.example", "A", "C1"),
                _feed_row("https://b.example", "B", "C2"),
            ],
        )

        from src.migrate import migrate

        migrate()

        items = {s["title"]: s for s in sources.scan()["Items"]}
        assert set(items) == {
            "技術ブログダイジェスト (C1)",
            "技術ブログダイジェスト (C2)",
        }
        assert items["技術ブログダイジェスト (C1)"]["channel_id"] == "C1"


def test_migrate_is_idempotent_on_second_run():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)
        _create_feeds_table(dynamodb, [_feed_row("https://a.example", "A", "C1")])

        from src.migrate import migrate

        migrate()
        first = sources.scan()["Items"]
        migrate()
        second = sources.scan()["Items"]

        assert first == second
        assert len(second) == 1


def test_migrate_respects_title_override(monkeypatch):
    monkeypatch.setenv("MIGRATE_TITLE", "Custom Title")
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)
        _create_feeds_table(dynamodb, [_feed_row("https://a.example", "A", "C1")])

        from src.migrate import migrate

        migrate()

        assert sources.scan()["Items"][0]["title"] == "Custom Title"


def test_migrate_uses_explicit_feeds_table_name(monkeypatch):
    monkeypatch.setenv("FEEDS_TABLE_NAME", "legacy-table")
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        sources = _create_sources_table(dynamodb)
        table = dynamodb.create_table(
            TableName="legacy-table",
            KeySchema=[{"AttributeName": "feed_url", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "feed_url", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.put_item(Item=_feed_row("https://a.example", "A", "C1"))

        from src.migrate import migrate

        migrate()

        assert len(sources.scan()["Items"]) == 1
