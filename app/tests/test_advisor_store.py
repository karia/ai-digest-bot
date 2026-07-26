import importlib
from datetime import UTC, datetime

import pytest


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.advisor_store as advisor_store

    importlib.reload(advisor_store)


def test_get_all_advisors_returns_registered_advisor(advisor_tables):
    from src.advisor_store import get_all_advisors

    advisors = get_all_advisors()

    assert len(advisors) == 1
    advisor = advisors[0]
    assert advisor["advisor_id"] == "ideco-sbi"
    assert advisor["channel_id"] == "CADVISOR01"
    assert advisor["title"] == "iDeCo 投資判断"
    assert advisor["products"][0]["isin"] == "JP90C000H1T1"
    assert advisor["news_feeds"][0]["name"] == "市況ニュース"


def test_get_all_advisors_returns_interval_days_as_int(advisor_tables):
    """DynamoDB hands numbers back as Decimal; callers need a plain int."""
    from src.advisor_store import get_all_advisors

    interval = get_all_advisors()[0]["interval_days"]

    assert interval == 7
    assert isinstance(interval, int)


def test_get_all_advisors_defaults_interval_days_to_7(advisor_tables):
    advisors_table, _ = advisor_tables
    advisors_table.put_item(
        Item={
            "advisor_id": "no-interval",
            "channel_id": "C1",
            "title": "T",
            "products": [],
            "news_feeds": [],
            "trading_notes": "",
            "inserted_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    from src.advisor_store import get_all_advisors

    advisor = next(a for a in get_all_advisors() if a["advisor_id"] == "no-interval")
    assert advisor["interval_days"] == 7


def test_add_advisor_preserves_inserted_at_on_update(advisor_tables):
    from src.advisor_store import add_advisor, get_all_advisors

    add_advisor(
        advisor_id="ideco-sbi",
        channel_id="CNEW",
        title="iDeCo 投資判断",
        products=[],
        news_feeds=[],
        trading_notes="updated",
    )

    advisor = next(a for a in get_all_advisors() if a["advisor_id"] == "ideco-sbi")
    assert advisor["channel_id"] == "CNEW"
    assert advisor["inserted_at"] == "2026-01-01T00:00:00+00:00"
    assert advisor["updated_at"] != "2026-01-01T00:00:00+00:00"


def test_delete_advisor_removes_the_item(advisor_tables):
    from src.advisor_store import delete_advisor, get_all_advisors

    delete_advisor("ideco-sbi")

    assert get_all_advisors() == []


def test_put_judgments_then_history_returns_newest_first(advisor_tables):
    from src.advisor_store import get_judgment_history, put_judgments

    put_judgments(
        "ideco-sbi",
        "2026-07-11",
        [
            {
                "isin": "JP90C000H1T1",
                "judgment": "HOLD",
                "reason": "様子見",
                "nav": 37000,
            }
        ],
    )
    put_judgments(
        "ideco-sbi",
        "2026-07-18",
        [
            {
                "isin": "JP90C000H1T1",
                "judgment": "BUY",
                "reason": "円高一服",
                "nav": 38000,
            }
        ],
    )

    history = get_judgment_history("ideco-sbi")

    assert [r["run_date"] for r in history] == ["2026-07-18", "2026-07-11"]
    assert history[0]["judgments"][0]["judgment"] == "BUY"


def test_get_judgment_history_returns_nav_as_int(advisor_tables):
    from src.advisor_store import get_judgment_history, put_judgments

    put_judgments(
        "ideco-sbi",
        "2026-07-18",
        [{"isin": "JP90C000H1T1", "judgment": "BUY", "reason": "r", "nav": 38243}],
    )

    nav = get_judgment_history("ideco-sbi")[0]["judgments"][0]["nav"]

    assert nav == 38243
    assert isinstance(nav, int)


def test_get_judgment_history_honours_limit(advisor_tables):
    from src.advisor_store import get_judgment_history, put_judgments

    for day in range(11, 20):
        put_judgments("ideco-sbi", f"2026-07-{day}", [])

    assert len(get_judgment_history("ideco-sbi", limit=3)) == 3


def test_get_judgment_history_is_empty_for_unknown_advisor(advisor_tables):
    from src.advisor_store import get_judgment_history

    assert get_judgment_history("nope") == []


def test_put_judgments_records_inserted_at(advisor_tables):
    _, judgments_table = advisor_tables

    from src.advisor_store import put_judgments

    before = datetime.now(UTC)
    put_judgments("ideco-sbi", "2026-07-18", [])
    item = judgments_table.get_item(
        Key={"advisor_id": "ideco-sbi", "run_date": "2026-07-18"}
    )["Item"]

    assert datetime.fromisoformat(item["inserted_at"]) >= before
