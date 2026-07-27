import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

PRODUCTS = json.dumps(
    [
        {
            "isin": "JP90C000H1T1",
            "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
            "category": "全世界株",
            "holding": True,
            "assoc_fund_cd": "0331418A",
        }
    ],
    ensure_ascii=False,
)
FEEDS = json.dumps([{"url": "https://example.com/rss", "name": "市況"}])


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.advisor_store as advisor_store

    importlib.reload(advisor_store)
    import manage_advisors

    importlib.reload(manage_advisors)


def test_add_registers_the_advisor(advisor_tables, monkeypatch, capsys):
    import manage_advisors
    from src.advisor_store import delete_advisor, get_all_advisors

    delete_advisor("ideco-sbi")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "manage_advisors.py",
            "add",
            "--advisor-id",
            "ideco-sbi",
            "--channel-id",
            "CADVISOR01",
            "--title",
            "iDeCo 投資判断",
            "--products-json",
            PRODUCTS,
            "--news-feeds-json",
            FEEDS,
            "--trading-notes",
            "スイッチングは1週間から10日",
            "--interval-days",
            "7",
        ],
    )

    manage_advisors.main()

    advisors = get_all_advisors()
    assert len(advisors) == 1
    assert advisors[0]["products"][0]["assoc_fund_cd"] == "0331418A"
    assert advisors[0]["interval_days"] == 7
    assert "ideco-sbi" in capsys.readouterr().out


def test_add_rejects_malformed_products_json(advisor_tables, monkeypatch):
    import manage_advisors

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "manage_advisors.py",
            "add",
            "--advisor-id",
            "x",
            "--channel-id",
            "C",
            "--title",
            "T",
            "--products-json",
            "not json",
            "--news-feeds-json",
            FEEDS,
            "--trading-notes",
            "",
        ],
    )

    with pytest.raises(SystemExit):
        manage_advisors.main()


def test_add_rejects_a_product_missing_assoc_fund_cd(advisor_tables, monkeypatch):
    import manage_advisors

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "manage_advisors.py",
            "add",
            "--advisor-id",
            "x",
            "--channel-id",
            "C",
            "--title",
            "T",
            "--products-json",
            '[{"isin": "JP1", "name": "n", "category": "c"}]',
            "--news-feeds-json",
            FEEDS,
            "--trading-notes",
            "",
        ],
    )

    with pytest.raises(SystemExit):
        manage_advisors.main()


def test_list_prints_the_registered_advisor(advisor_tables, monkeypatch, capsys):
    import manage_advisors

    monkeypatch.setattr(sys, "argv", ["manage_advisors.py", "list"])

    manage_advisors.main()

    out = capsys.readouterr().out
    assert "ideco-sbi" in out
    assert "eMAXIS Slim 全世界株式" in out


def test_list_reports_an_empty_table(advisor_tables, monkeypatch, capsys):
    import manage_advisors
    from src.advisor_store import delete_advisor

    delete_advisor("ideco-sbi")
    monkeypatch.setattr(sys, "argv", ["manage_advisors.py", "list"])

    manage_advisors.main()

    assert "No advisors registered." in capsys.readouterr().out


def test_delete_removes_the_advisor(advisor_tables, monkeypatch, capsys):
    import manage_advisors
    from src.advisor_store import get_all_advisors

    monkeypatch.setattr(
        sys, "argv", ["manage_advisors.py", "delete", "--advisor-id", "ideco-sbi"]
    )

    manage_advisors.main()

    assert get_all_advisors() == []
    assert "ideco-sbi" in capsys.readouterr().out
