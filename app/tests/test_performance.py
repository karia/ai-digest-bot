from datetime import date, timedelta

HISTORY = [
    {
        "advisor_id": "ideco-sbi",
        "run_date": "2026-07-18",
        "judgments": [
            {"isin": "A", "judgment": "BUY", "reason": "r1", "nav": 20000},
            {"isin": "B", "judgment": "SELL", "reason": "r2", "nav": 10000},
        ],
    },
    {
        "advisor_id": "ideco-sbi",
        "run_date": "2026-07-11",
        "judgments": [
            {"isin": "A", "judgment": "HOLD", "reason": "r0", "nav": 25000},
        ],
    },
]
NAMES = {"A": "全世界株", "B": "国内債券"}
CURRENT = {"A": 22000, "B": 9500}


def test_pct_change_computes_percent():
    from src.performance import pct_change

    assert pct_change(20000, 22000) == 10.0


def test_pct_change_handles_negative_move():
    from src.performance import pct_change

    assert pct_change(10000, 9500) == -5.0


def test_pct_change_returns_zero_for_zero_base():
    from src.performance import pct_change

    assert pct_change(0, 100) == 0.0


def test_format_pct_always_carries_a_sign():
    from src.performance import format_pct

    assert format_pct(10.0) == "+10.00%"
    assert format_pct(-5.0) == "-5.00%"
    assert format_pct(0.0) == "+0.00%"


def test_build_performance_expands_every_judgment():
    from src.performance import build_performance

    rows = build_performance(HISTORY, CURRENT, NAMES)

    assert len(rows) == 3
    assert rows[0].run_date == "2026-07-18"
    assert rows[0].isin == "A"
    assert rows[0].name == "全世界株"
    assert rows[0].nav_then == 20000
    assert rows[0].nav_now == 22000
    assert rows[0].change_pct == 10.0


def test_build_performance_skips_products_without_a_current_nav():
    from src.performance import build_performance

    rows = build_performance(HISTORY, {"A": 22000}, NAMES)

    assert [r.isin for r in rows] == ["A", "A"]


def test_build_performance_falls_back_to_the_isin_when_name_is_unknown():
    from src.performance import build_performance

    rows = build_performance(HISTORY, CURRENT, {})

    assert rows[0].name == "A"


def test_format_performance_summary_lists_one_bullet_per_row():
    from src.performance import build_performance, format_performance_summary

    text = format_performance_summary(build_performance(HISTORY, CURRENT, NAMES))

    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[0] == "• 2026-07-18 全世界株: 🟢 買い → +10.00%"
    assert lines[1] == "• 2026-07-18 国内債券: 🔴 売り → -5.00%"
    assert lines[2] == "• 2026-07-11 全世界株: 🟡 ホールド → -12.00%"


def test_format_performance_summary_handles_no_history():
    from src.performance import format_performance_summary

    assert format_performance_summary([]) == "過去の判断履歴はまだありません。"


def test_latest_judgment_by_isin_uses_the_newest_record():
    from src.performance import latest_judgment_by_isin

    assert latest_judgment_by_isin(HISTORY) == {"A": "BUY", "B": "SELL"}


def test_latest_judgment_by_isin_is_empty_without_history():
    from src.performance import latest_judgment_by_isin

    assert latest_judgment_by_isin([]) == {}


def _series(latest_nav: int) -> list:
    from src.nav import NavPoint

    today = date(2026, 7, 24)
    # 200 daily points so every trailing window has data.
    return [
        NavPoint(date=today - timedelta(days=200 - i), nav=10000 + i * 50)
        for i in range(200)
    ] + [NavPoint(date=today, nav=latest_nav)]


def test_summarize_nav_reports_the_latest_value_and_trailing_returns():
    from src.performance import summarize_nav

    text = summarize_nav(_series(30000))

    assert text.startswith("最新 2026-07-24 30,000円")
    assert "7日 " in text
    assert "180日 " in text


def test_summarize_nav_handles_an_empty_series():
    from src.performance import summarize_nav

    assert summarize_nav([]) == "基準価額データなし"


def test_summarize_nav_omits_windows_without_data():
    from src.nav import NavPoint
    from src.performance import summarize_nav

    text = summarize_nav([NavPoint(date=date(2026, 7, 24), nav=30000)])

    assert text == "最新 2026-07-24 30,000円"
