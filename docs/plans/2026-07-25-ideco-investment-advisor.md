# iDeCo Investment Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ADR 0001 の iDeCo 投資判断アドバイザーを実装し、EventBridge（毎日 JST 17:00）から Lambda を起動して、登録済みアドバイザー定義に沿った BUY/SELL/HOLD 判断を Slack スレッドへ冪等に投稿する。

**Architecture:** 既存の digest 実行系統を `src/digest.py` に切り出し、`handler.py` を event の `job` フィールドで digest / advisor を振り分ける薄いディスパッチャにする。advisor 系統は DynamoDB の `advisors`（定義）と `advisor-judgments`（判断履歴）を読み書きし、基準価額の取得と騰落率計算は Python の純関数、市況の解釈と 3 値判断は Strands Agent（`agent.run_advice`）が担う。冪等性は Slack 履歴からアドバイザー `title` を header に持つ前回投稿を探して JST 日付で判定する。

**Tech Stack:** Python 3.14 / AWS Lambda (arm64) / Strands Agents SDK + Bedrock / DynamoDB / EventBridge Scheduler / Terraform / lambroll / pytest + moto + responses / ruff + mypy strict

## Global Constraints

- ADR は `docs/adr/0001-ideco-investment-advisor.md`。この計画は ADR の Decision 節を実装するものであり、ADR と矛盾する実装をしてはならない。
- Python 3.14、mypy は `strict = true`。すべての新規関数に型注釈を付ける。ruff の lint 対象は `["E", "F", "I", "B", "UP"]`。
- テストは実 AWS に触れない。DynamoDB / SSM は moto の `mock_aws`、HTTP は `responses` でモックする。Bedrock を呼ぶ `run_advice` 本体は統合テストしない。
- Slack 本文はすべて Slack mrkdwn（強調は `*太字*`、箇条書きは行頭 `•`、リンクは `<url|表示名>`）。
- JST は `src.config.JST`（固定 +9、DST なし）を使う。新たに `zoneinfo` を導入しない。
- コミットメッセージは英語 1 行（このリポジトリは `karia/` 配下）。Co-Authored-By 等は 2 行目以降。
- 各タスクの最後に `uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/` が通ることを確認してからコミットする。
- リポジトリルートは `/home/karia/ghq/github.com/karia/ai-digest-bot`。すべてのコマンドはルートで実行する（pytest の `testpaths` は `app/tests`、`app/tests/__init__.py` があるため `app/` が sys.path に入り `src` が解決される）。
- 新しい環境変数の追加は `app/src/config.py`・`app/tests/conftest.py`・`app/function.jsonnet`・`Makefile` の 4 箇所が揃って初めて動く。片方だけ変更しない。
- 判断の 3 値は文字列リテラル `"BUY"` / `"SELL"` / `"HOLD"` で統一する。表示ラベルは `performance.JUDGMENT_LABELS` の 1 箇所だけで定義する。

---

## File Structure

新規作成:

| ファイル | 責務 |
|---|---|
| `app/src/digest.py` | 既存 digest ジョブ本体（handler から切り出し） |
| `app/src/advisor_store.py` | `advisors` / `advisor-judgments` テーブルの読み書き |
| `app/src/nav.py` | 投信協会 CSV の取得とパース（純ロジック + HTTP） |
| `app/src/tools/nav_fetch.py` | `nav.py` を包む Strands `@tool` |
| `app/src/performance.py` | 騰落率・成績サマリ・基準価額サマリの純関数 |
| `app/src/slack_reader.py` | Slack 履歴から header 一致の前回投稿を探す + 投稿可否判定 |
| `app/src/advisor.py` | advisor ジョブのオーケストレーション |
| `scripts/manage_advisors.py` | `advisors` の CLI 管理 |
| `app/tests/test_digest.py` 他 | 各モジュールのテスト |

変更:

| ファイル | 変更内容 |
|---|---|
| `app/src/handler.py` | ジョブディスパッチャに縮小 |
| `app/src/config.py` | `ADVISORS_TABLE_NAME` / `JUDGMENTS_TABLE_NAME` |
| `app/src/agent.py` | `ADVICE_SYSTEM_PROMPT` / `ProductAdvice` / `AdviceResult` / `run_advice` |
| `app/src/slack_notifier.py` | `_HEADER_LIMIT` → `HEADER_LIMIT`（slack_reader が参照） |
| `app/tests/conftest.py` | advisor 用の環境変数・テーブル・サンプルデータ |
| `app/tests/test_handler.py` | patch 先を `src.digest.*` へ、ジョブ分岐のテスト追加 |
| `terraform/dynamodb.tf` / `lambda.tf` / `eventbridge.tf` / `outputs.tf` | 2 テーブル・IAM・スケジュール・output |
| `app/function.jsonnet` / `Makefile` | 新環境変数の注入、advisors 管理ターゲット |
| `CLAUDE.md` / `README.md` | advisor 系統の記述 |

---

## Task 1: digest ジョブを `src/digest.py` に切り出す

advisor を足す前に、handler を「ジョブを選ぶだけ」に縮められる形へ整える純粋なリファクタ。振る舞いは一切変えない。

**Files:**
- Create: `app/src/digest.py`
- Modify: `app/src/handler.py`（全面書き換え）
- Test: `app/tests/test_handler.py`（patch 先の付け替え）

**Interfaces:**
- Consumes: 既存 `src.agent.run_plan / run_digest / run_daily_digests / run_headline`、`src.store.get_all_sources`、`src.slack_notifier.post_message`
- Produces:
  - `src.digest.run_digest_job(until: datetime) -> dict[str, Any]` — 戻り値は従来 `lambda_handler` と同じ `{"status": "ok", "sources": int, "results": dict[str, str]}`（ソース 0 件時は `results` なしで `{"status": "ok", "sources": 0}`）
  - `src.handler._parse_scheduled_time(event: dict[str, Any]) -> datetime`（現状のまま handler に残す）
  - `src.handler.lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]`

- [ ] **Step 1: `app/src/digest.py` を作る**

`app/src/handler.py:23-120` の `lambda_handler` 本体を、`configure_logging()` の呼び出しと `_parse_scheduled_time` を除いてそのまま移す。`until` は引数で受け取る。

```python
import logging
from datetime import datetime, timedelta
from typing import Any

from src import slack_notifier
from src.agent import run_daily_digests, run_digest, run_headline, run_plan
from src.store import get_all_sources

logger = logging.getLogger(__name__)


def run_digest_job(until: datetime) -> dict[str, Any]:
    """Run the tech-blog digest job for every registered source.

    Args:
        until: End of the digest window (the scheduled invocation time).

    Returns:
        ``{"status": "ok", "sources": N, "results": {...}}``; ``results`` is
        omitted when no source is registered.
    """
    sources = get_all_sources()
    logger.info("Fetched %d source(s) from DynamoDB", len(sources))

    if not sources:
        logger.info("No sources found in DynamoDB")
        return {"status": "ok", "sources": 0}

    results: dict[str, str] = {}

    for source in sources:
        title = source["title"]
        channel = source["channel_id"]
        items = source["items"]
        # No date in the header: the headline body always carries the digest
        # window, which would make a date here redundant.
        header = title

        # The plan agent interprets the free-text schedule and derives `since`
        # from the bot's last post in the channel (24h ago when unavailable).
        try:
            plan = run_plan(channel, source.get("posting_schedule", "毎日"), until)
        except Exception as e:
            logger.error("Plan failed for %s: %s", title, e, exc_info=True)
            plan = None
        if plan and not plan.should_post:
            logger.info("Skipping %s: %s", title, plan.reason)
            results[title] = f"skipped: {plan.reason}"
            continue
        since = (plan and plan.since) or (until - timedelta(hours=24))

        # Generate every digest first: the headline must summarize the whole
        # thread, so nothing is posted until all bodies are ready.
        digests: list[tuple[str, str, str]] = []  # (url, reply header, body)
        for item in items:
            url = item["url"]
            name = item["name"]
            logger.info(
                "Processing %s (%s) for %s..%s",
                name,
                url,
                since.isoformat(),
                until.isoformat(),
            )
            try:
                if item.get("split_by_day"):
                    days = run_daily_digests(url, since=since, until=until)
                    if not days:
                        # Days without articles get no reply, so an empty
                        # window posts nothing for this item.
                        results[url] = "no articles"
                        continue
                    for day in days:
                        digests.append((url, f"{name} ({day.date:%m/%d})", day.body))
                else:
                    body = run_digest(url, since=since, until=until)
                    digests.append((url, name, body))
            except Exception as e:
                logger.error("Failed for %s: %s", url, e, exc_info=True)
                results[url] = f"error: {e}"

        try:
            headline_body = run_headline(
                [(h, body) for _, h, body in digests], since=since, until=until
            )
        except Exception as e:
            logger.error(
                "Headline generation failed for %s: %s", title, e, exc_info=True
            )
            headline_body = ""

        logger.info("Posting headline for source %s to %s", title, channel)
        try:
            thread_ts = slack_notifier.post_message(
                channel, text=headline_body, header=header
            )
        except Exception as e:
            logger.error("Failed to post headline for %s: %s", title, e, exc_info=True)
            results[title] = f"error: {e}"
            continue

        for url, reply_header, body in digests:
            try:
                slack_notifier.post_message(
                    channel, text=body, header=reply_header, thread_ts=thread_ts
                )
                results[url] = "success"
                logger.info("Reply for %s done", reply_header)
            except Exception as e:
                logger.error("Failed to post reply for %s: %s", url, e, exc_info=True)
                results[url] = f"error: {e}"

    logger.info("Digest run complete: %s", results)
    return {"status": "ok", "sources": len(sources), "results": results}
```

- [ ] **Step 2: `app/src/handler.py` を書き換える**

ファイル全体を次で置き換える。

```python
import logging
from datetime import UTC, datetime
from typing import Any

from src.digest import run_digest_job
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _parse_scheduled_time(event: dict[str, Any]) -> datetime:
    raw = event.get("scheduled_time")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Invalid scheduled_time %r; falling back to now()", raw)
    return datetime.now(UTC)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    configure_logging()
    now = _parse_scheduled_time(event)
    return run_digest_job(now)
```

- [ ] **Step 3: `app/tests/test_handler.py` の patch 先を付け替える**

`src.handler.run_plan` / `src.handler.run_digest` / `src.handler.run_daily_digests` / `src.handler.run_headline` / `src.handler.slack_notifier.post_message` の 5 つを、すべて `src.digest.` 始まりに置換する。テストのアサーションは一切変えない。

```bash
sed -i \
  -e 's/"src\.handler\.run_plan"/"src.digest.run_plan"/g' \
  -e 's/"src\.handler\.run_digest"/"src.digest.run_digest"/g' \
  -e 's/"src\.handler\.run_daily_digests"/"src.digest.run_daily_digests"/g' \
  -e 's/"src\.handler\.run_headline"/"src.digest.run_headline"/g' \
  -e 's/"src\.handler\.slack_notifier\.post_message"/"src.digest.slack_notifier.post_message"/g' \
  app/tests/test_handler.py
```

さらに `reload_modules` fixture に `src.digest` の reload を足す（`src.config` を reload すると `src.digest` が掴んだ `config` 参照が古くなるため）。`app/tests/test_handler.py:9-16` を次に置き換える。

```python
@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.store as store

    importlib.reload(store)
    import src.digest as digest

    importlib.reload(digest)
```

- [ ] **Step 4: テストを流して全部通ることを確認する**

Run: `uv run pytest app/tests/test_handler.py -v`
Expected: PASS（16 件すべて。1 件も落ちない = 振る舞いが変わっていない証拠）

- [ ] **Step 5: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add app/src/digest.py app/src/handler.py app/tests/test_handler.py
git commit -m "refactor: extract the digest job into src/digest.py"
```

---

## Task 2: advisor 用の設定とストア

**Files:**
- Create: `app/src/advisor_store.py`
- Modify: `app/src/config.py`, `app/tests/conftest.py`
- Test: `app/tests/test_advisor_store.py`

**Interfaces:**
- Consumes: `src.config.AWS_REGION`, `src.config.JST`
- Produces:
  - `src.config.ADVISORS_TABLE_NAME: str`, `src.config.JUDGMENTS_TABLE_NAME: str`
  - `src.advisor_store.Product` TypedDict — `{isin: str, name: str, category: str, holding: bool, assoc_fund_cd: str}`
  - `src.advisor_store.NewsFeed` TypedDict — `{url: str, name: str}`
  - `src.advisor_store.Advisor` TypedDict — `{advisor_id, channel_id, title, interval_days: int, products: list[Product], news_feeds: list[NewsFeed], trading_notes: str, inserted_at, updated_at}`
  - `src.advisor_store.Judgment` TypedDict — `{isin: str, judgment: str, reason: str, nav: int}`
  - `src.advisor_store.JudgmentRecord` TypedDict — `{advisor_id: str, run_date: str, judgments: list[Judgment]}`
  - `get_all_advisors() -> list[Advisor]`
  - `add_advisor(advisor_id, channel_id, title, products, news_feeds, trading_notes, interval_days=7) -> None`
  - `delete_advisor(advisor_id: str) -> None`
  - `put_judgments(advisor_id: str, run_date: str, judgments: list[Judgment]) -> None`
  - `get_judgment_history(advisor_id: str, limit: int = 8) -> list[JudgmentRecord]`（新しい順）
- テスト用の定数（conftest）: `ADVISORS_TABLE = "test-advisors"`, `JUDGMENTS_TABLE = "test-advisor-judgments"`, `SAMPLE_ADVISOR`

- [ ] **Step 1: `app/tests/conftest.py` に advisor 用の環境変数・テーブル・サンプルを足す**

`TABLE_NAME` の定義（`app/tests/conftest.py:24`）の直後に追記する。

```python
ADVISORS_TABLE = "test-advisors"
JUDGMENTS_TABLE = "test-advisor-judgments"

SAMPLE_ADVISOR = {
    "advisor_id": "ideco-sbi",
    "channel_id": "CADVISOR01",
    "title": "iDeCo 投資判断",
    "interval_days": 7,
    "products": [
        {
            "isin": "JP90C000H1T1",
            "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
            "category": "全世界株",
            "holding": True,
            "assoc_fund_cd": "0331418A",
        },
    ],
    "news_feeds": [
        {"url": "https://example.com/market.rss", "name": "市況ニュース"},
    ],
    "trading_notes": "スイッチングは指示から完了まで概ね1週間から10日。",
    "inserted_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


def _create_advisor_tables(dynamodb):
    advisors = dynamodb.create_table(
        TableName=ADVISORS_TABLE,
        KeySchema=[{"AttributeName": "advisor_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "advisor_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    judgments = dynamodb.create_table(
        TableName=JUDGMENTS_TABLE,
        KeySchema=[
            {"AttributeName": "advisor_id", "KeyType": "HASH"},
            {"AttributeName": "run_date", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "advisor_id", "AttributeType": "S"},
            {"AttributeName": "run_date", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return advisors, judgments
```

`env_vars` fixture（`app/tests/conftest.py:48-58`）の末尾に 2 行足す。

```python
    monkeypatch.setenv("ADVISORS_TABLE_NAME", ADVISORS_TABLE)
    monkeypatch.setenv("JUDGMENTS_TABLE_NAME", JUDGMENTS_TABLE)
```

新しい fixture を末尾に足す。

```python
@pytest.fixture
def advisor_tables():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        advisors, judgments = _create_advisor_tables(dynamodb)
        advisors.put_item(Item=SAMPLE_ADVISOR)
        yield advisors, judgments
```

`integrated_aws_mock` fixture の `ssm.put_parameter(...)` の直前に advisor テーブル作成を足す（advisor の結合テストが同じ fixture で書けるようにするため）。

```python
        _create_advisor_tables(dynamodb)[0].put_item(Item=SAMPLE_ADVISOR)
```

- [ ] **Step 2: `app/src/config.py` に環境変数を足す**

`SOURCES_TABLE_NAME` の直後（`app/src/config.py:24`）に追記する。

```python
ADVISORS_TABLE_NAME: str = os.environ["ADVISORS_TABLE_NAME"]
JUDGMENTS_TABLE_NAME: str = os.environ["JUDGMENTS_TABLE_NAME"]
```

- [ ] **Step 3: 失敗するテストを書く**

`app/tests/test_advisor_store.py` を新規作成する。

```python
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
        [{"isin": "JP90C000H1T1", "judgment": "HOLD", "reason": "様子見", "nav": 37000}],
    )
    put_judgments(
        "ideco-sbi",
        "2026-07-18",
        [{"isin": "JP90C000H1T1", "judgment": "BUY", "reason": "円高一服", "nav": 38000}],
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
```

- [ ] **Step 4: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_advisor_store.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.advisor_store'`）

- [ ] **Step 5: `app/src/advisor_store.py` を実装する**

```python
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict, cast

import boto3
from boto3.dynamodb.conditions import Key

from src import config

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_DAYS = 7


class Product(TypedDict):
    """One fund the advisor judges."""

    isin: str
    name: str
    category: str
    # True: currently held. False: a switching candidate only.
    holding: bool
    # 投資信託協会のファンドコード. Needed alongside the ISIN to download NAV.
    assoc_fund_cd: str


class NewsFeed(TypedDict):
    url: str
    name: str


class Advisor(TypedDict):
    """One advisor definition = one Slack thread per run."""

    advisor_id: str
    channel_id: str
    # Headline header; doubles as the marker used to find the previous post.
    title: str
    interval_days: int
    products: list[Product]
    news_feeds: list[NewsFeed]
    # Free text describing the scheme's trading characteristics; injected
    # into the advice system prompt.
    trading_notes: str
    inserted_at: str
    updated_at: str


class Judgment(TypedDict):
    isin: str
    # "BUY" / "SELL" / "HOLD"
    judgment: str
    reason: str
    # NAV (基準価額, whole yen) at the time the judgment was made.
    nav: int


class JudgmentRecord(TypedDict):
    advisor_id: str
    # JST date, "YYYY-MM-DD".
    run_date: str
    judgments: list[Judgment]


def _get_advisors_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.ADVISORS_TABLE_NAME)


def _get_judgments_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    return dynamodb.Table(config.JUDGMENTS_TABLE_NAME)


def _normalize_advisor(raw: dict[str, Any]) -> Advisor:
    """Coerce DynamoDB Decimals back to int and fill in defaults."""
    raw["interval_days"] = int(raw.get("interval_days", DEFAULT_INTERVAL_DAYS))
    return cast(Advisor, raw)


def _normalize_record(raw: dict[str, Any]) -> JudgmentRecord:
    for judgment in raw.get("judgments", []):
        judgment["nav"] = int(judgment.get("nav", 0))
    return cast(JudgmentRecord, raw)


def get_all_advisors() -> list[Advisor]:
    table = _get_advisors_table()
    items: list[Advisor] = []
    response = table.scan()
    items.extend(_normalize_advisor(i) for i in response["Items"])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(_normalize_advisor(i) for i in response["Items"])
    logger.debug(
        "Scanned %d advisor(s) from %s", len(items), config.ADVISORS_TABLE_NAME
    )
    return items


def add_advisor(
    advisor_id: str,
    channel_id: str,
    title: str,
    products: list[Product],
    news_feeds: list[NewsFeed],
    trading_notes: str,
    interval_days: int = DEFAULT_INTERVAL_DAYS,
) -> None:
    """Full upsert of one advisor definition, preserving ``inserted_at``."""
    table = _get_advisors_table()
    now = datetime.now(UTC).isoformat()
    existing = table.get_item(Key={"advisor_id": advisor_id}).get("Item")
    inserted_at = existing["inserted_at"] if existing else now
    table.put_item(
        Item={
            "advisor_id": advisor_id,
            "channel_id": channel_id,
            "title": title,
            "interval_days": interval_days,
            "products": cast(Any, products),
            "news_feeds": cast(Any, news_feeds),
            "trading_notes": trading_notes,
            "inserted_at": inserted_at,
            "updated_at": now,
        }
    )


def delete_advisor(advisor_id: str) -> None:
    table = _get_advisors_table()
    table.delete_item(Key={"advisor_id": advisor_id})


def put_judgments(
    advisor_id: str, run_date: str, judgments: list[Judgment]
) -> None:
    """Store one run's judgments. Re-running the same JST day overwrites it."""
    table = _get_judgments_table()
    table.put_item(
        Item={
            "advisor_id": advisor_id,
            "run_date": run_date,
            # DynamoDB rejects float, so every number goes in as Decimal.
            "judgments": [
                {
                    "isin": j["isin"],
                    "judgment": j["judgment"],
                    "reason": j["reason"],
                    "nav": Decimal(str(j["nav"])),
                }
                for j in judgments
            ],
            "inserted_at": datetime.now(UTC).isoformat(),
        }
    )


def get_judgment_history(advisor_id: str, limit: int = 8) -> list[JudgmentRecord]:
    """Return the advisor's most recent runs, newest first."""
    table = _get_judgments_table()
    response = table.query(
        KeyConditionExpression=Key("advisor_id").eq(advisor_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_normalize_record(i) for i in response["Items"]]
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_advisor_store.py -v`
Expected: PASS（10 件）

- [ ] **Step 7: 既存テストを壊していないことと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 8: コミット**

```bash
git add app/src/config.py app/src/advisor_store.py app/tests/conftest.py app/tests/test_advisor_store.py
git commit -m "feat: add DynamoDB store for advisor definitions and judgment history"
```

---

## Task 3: 基準価額の取得（`nav.py` + `tools/nav_fetch.py`）

投資信託協会「投信総合検索ライブラリー」の CSV ダウンロードを叩く。**実測済みの仕様**（この通りに実装すること）:

- URL: `https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download?isinCd=<ISIN>&associFundCd=<協会ファンドコード>`
- レスポンスヘッダは `charset=utf-8` を名乗るが、**実バイト列は cp932**。UTF-8 でデコードすると必ず化ける
- 1 行目はヘッダ `年月日,基準価額(円),純資産総額（百万円）,分配金,決算期`
- データ行は `2026年07月24日,38243,13205500,,` 形式。**古い順（昇順）**で、eMAXIS Slim 全世界株式で約 1885 行
- 基準価額は円単位の整数

**Files:**
- Create: `app/src/nav.py`, `app/src/tools/nav_fetch.py`
- Test: `app/tests/test_nav.py`, `app/tests/test_nav_fetch.py`

**Interfaces:**
- Consumes: なし（外部 HTTP のみ）
- Produces:
  - `src.nav.NavPoint` NamedTuple — `date: datetime.date`, `nav: int`
  - `src.nav.NAV_CSV_URL: str`
  - `src.nav.parse_nav_csv(raw: bytes) -> list[NavPoint]`（昇順、パースできない行は捨てる）
  - `src.nav.fetch_nav_series(isin: str, assoc_fund_cd: str, days: int = 180) -> list[NavPoint]`（末尾 `days` 件。HTTP 失敗時は `requests.RequestException` を送出）
  - `src.tools.nav_fetch.nav_fetch` — Strands `@tool`、シグネチャ `nav_fetch(isin_cd: str, assoc_fund_cd: str, days: int = 90) -> str`

- [ ] **Step 1: 失敗するテストを書く（パーサ）**

`app/tests/test_nav.py` を新規作成する。

```python
from datetime import date

import pytest
import requests
import responses

SAMPLE_CSV = (
    "年月日,基準価額(円),純資産総額（百万円）,分配金,決算期\n"
    "2026年07月22日,37980,13100000,,\n"
    "2026年07月23日,38100,13150000,,\n"
    "2026年07月24日,38243,13205500,,\n"
)


def test_parse_nav_csv_reads_cp932_rows():
    from src.nav import parse_nav_csv

    points = parse_nav_csv(SAMPLE_CSV.encode("cp932"))

    assert len(points) == 3
    assert points[0].date == date(2026, 7, 22)
    assert points[0].nav == 37980


def test_parse_nav_csv_keeps_ascending_order():
    from src.nav import parse_nav_csv

    points = parse_nav_csv(SAMPLE_CSV.encode("cp932"))

    assert [p.date for p in points] == [
        date(2026, 7, 22),
        date(2026, 7, 23),
        date(2026, 7, 24),
    ]


def test_parse_nav_csv_skips_the_header_row():
    from src.nav import parse_nav_csv

    points = parse_nav_csv(SAMPLE_CSV.encode("cp932"))

    assert all(isinstance(p.nav, int) for p in points)


def test_parse_nav_csv_skips_rows_without_a_date():
    from src.nav import parse_nav_csv

    raw = (SAMPLE_CSV + "\n,,,,\n合計,1,2,,\n").encode("cp932")

    assert len(parse_nav_csv(raw)) == 3


def test_parse_nav_csv_returns_empty_for_garbage():
    from src.nav import parse_nav_csv

    assert parse_nav_csv(b"not a csv at all") == []


@responses.activate
def test_fetch_nav_series_requests_the_csv_endpoint():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(
        responses.GET,
        NAV_CSV_URL,
        body=SAMPLE_CSV.encode("cp932"),
        status=200,
    )

    points = fetch_nav_series("JP90C000H1T1", "0331418A")

    assert len(points) == 3
    request = responses.calls[0].request
    assert "isinCd=JP90C000H1T1" in request.url
    assert "associFundCd=0331418A" in request.url


@responses.activate
def test_fetch_nav_series_keeps_only_the_last_n_points():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(
        responses.GET, NAV_CSV_URL, body=SAMPLE_CSV.encode("cp932"), status=200
    )

    points = fetch_nav_series("JP90C000H1T1", "0331418A", days=2)

    assert [p.date for p in points] == [date(2026, 7, 23), date(2026, 7, 24)]


@responses.activate
def test_fetch_nav_series_raises_on_http_error():
    from src.nav import NAV_CSV_URL, fetch_nav_series

    responses.add(responses.GET, NAV_CSV_URL, status=500)

    with pytest.raises(requests.RequestException):
        fetch_nav_series("JP90C000H1T1", "0331418A")
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_nav.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.nav'`）

- [ ] **Step 3: `app/src/nav.py` を実装する**

```python
import csv
import io
import logging
import re
from datetime import date
from typing import NamedTuple

import requests

logger = logging.getLogger(__name__)

# 投資信託協会「投信総合検索ライブラリー」の CSV ダウンロード。
# Not a documented API; if it changes, this module is the only thing to fix.
NAV_CSV_URL = "https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download"

# Rows look like "2026年07月24日,38243,13205500,,"; the header row does not match.
_DATE_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


class NavPoint(NamedTuple):
    """One day's NAV (基準価額) in whole yen."""

    date: date
    nav: int


def parse_nav_csv(raw: bytes) -> list[NavPoint]:
    """Parse the association's NAV CSV into ascending NavPoints.

    The response advertises charset=utf-8 but the bytes are actually cp932,
    so the declared charset must be ignored. Rows that are not dated data
    rows (header, blank, totals) are dropped.
    """
    text = raw.decode("cp932", errors="replace")
    points: list[NavPoint] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        matched = _DATE_PATTERN.fullmatch(row[0].strip())
        if not matched:
            continue
        try:
            nav = int(row[1].strip())
        except ValueError:
            continue
        points.append(
            NavPoint(
                date=date(
                    int(matched.group(1)), int(matched.group(2)), int(matched.group(3))
                ),
                nav=nav,
            )
        )
    return points


def fetch_nav_series(
    isin: str, assoc_fund_cd: str, days: int = 180
) -> list[NavPoint]:
    """Download a fund's NAV history and return the most recent ``days`` points.

    Args:
        isin: ISIN code, e.g. "JP90C000H1T1".
        assoc_fund_cd: 協会ファンドコード, e.g. "0331418A".
        days: How many trailing rows to keep (rows are business days).

    Raises:
        requests.RequestException: if the download fails.
    """
    logger.debug("fetch_nav_series: isin=%s assoc_fund_cd=%s", isin, assoc_fund_cd)
    response = requests.get(
        NAV_CSV_URL,
        params={"isinCd": isin, "associFundCd": assoc_fund_cd},
        timeout=30,
    )
    response.raise_for_status()
    points = parse_nav_csv(response.content)
    return points[-days:]
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_nav.py -v`
Expected: PASS（8 件）

- [ ] **Step 5: ツールの失敗するテストを書く**

`app/tests/test_nav_fetch.py` を新規作成する。

```python
import responses

SAMPLE_CSV = (
    "年月日,基準価額(円),純資産総額（百万円）,分配金,決算期\n"
    "2026年07月23日,38100,13150000,,\n"
    "2026年07月24日,38243,13205500,,\n"
)


@responses.activate
def test_nav_fetch_returns_csv_text():
    from src.nav import NAV_CSV_URL
    from src.tools.nav_fetch import nav_fetch

    responses.add(
        responses.GET, NAV_CSV_URL, body=SAMPLE_CSV.encode("cp932"), status=200
    )

    result = nav_fetch("JP90C000H1T1", "0331418A")

    assert result.startswith("date,nav\n")
    assert "2026-07-24,38243" in result


@responses.activate
def test_nav_fetch_reports_no_data():
    from src.nav import NAV_CSV_URL
    from src.tools.nav_fetch import nav_fetch

    responses.add(responses.GET, NAV_CSV_URL, body=b"", status=200)

    assert nav_fetch("JP90C000H1T1", "0331418A") == "No NAV data found."


@responses.activate
def test_nav_fetch_returns_error_string_instead_of_raising():
    from src.nav import NAV_CSV_URL
    from src.tools.nav_fetch import nav_fetch

    responses.add(responses.GET, NAV_CSV_URL, status=503)

    result = nav_fetch("JP90C000H1T1", "0331418A")

    assert result.startswith("Error fetching NAV:")
```

`nav_fetch` は `@tool` で装飾されているが、Strands の `@tool` は元の関数をそのまま呼び出せる形で公開するため、テストから直接呼べる（既存の `app/tests/test_rss_fetch.py` と同じ扱い方）。もし直接呼べない場合は `nav_fetch.original_function(...)` ではなく、既存テストがどう呼んでいるかに合わせること。

- [ ] **Step 6: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_nav_fetch.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.tools.nav_fetch'`）

- [ ] **Step 7: `app/src/tools/nav_fetch.py` を実装する**

HTTP とパースは `src.nav` に閉じ、このツールは整形だけ行う（ロジックを二重に持たない）。

```python
import logging

from strands import tool

from src.nav import fetch_nav_series

logger = logging.getLogger(__name__)


@tool
def nav_fetch(isin_cd: str, assoc_fund_cd: str, days: int = 90) -> str:
    """Fetch a Japanese mutual fund's NAV (基準価額) history.

    Args:
        isin_cd: The fund's ISIN code, e.g. "JP90C000H1T1".
        assoc_fund_cd: 投資信託協会のファンドコード, e.g. "0331418A".
        days: How many trailing business days to return (default: 90).

    Returns:
        CSV text with a "date,nav" header, one row per business day in
        ascending date order, or an error message.
    """
    logger.debug("nav_fetch: isin_cd=%s assoc_fund_cd=%s", isin_cd, assoc_fund_cd)
    try:
        points = fetch_nav_series(isin_cd, assoc_fund_cd, days=days)
    except Exception as e:
        logger.warning("nav_fetch failed for %s: %s", isin_cd, e)
        return f"Error fetching NAV: {e}"

    if not points:
        return "No NAV data found."

    rows = "\n".join(f"{p.date:%Y-%m-%d},{p.nav}" for p in points)
    return f"date,nav\n{rows}"
```

- [ ] **Step 8: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_nav.py app/tests/test_nav_fetch.py -v`
Expected: PASS（11 件）

- [ ] **Step 9: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 10: コミット**

```bash
git add app/src/nav.py app/src/tools/nav_fetch.py app/tests/test_nav.py app/tests/test_nav_fetch.py
git commit -m "feat: add NAV fetching from the fund association CSV endpoint"
```

---

## Task 4: 成績計算と表示の純関数（`performance.py`）

外部依存を持たない純関数だけを置く。Slack 表示ラベルもここに 1 箇所だけ定義する。

**Files:**
- Create: `app/src/performance.py`
- Test: `app/tests/test_performance.py`

**Interfaces:**
- Consumes: `src.nav.NavPoint`, `src.advisor_store.JudgmentRecord`
- Produces:
  - `src.performance.JUDGMENT_LABELS: dict[str, str]` — `{"BUY": "🟢 買い", "SELL": "🔴 売り", "HOLD": "🟡 ホールド"}`
  - `pct_change(base: int, current: int) -> float`（百分率。`base == 0` は `0.0`）
  - `format_pct(value: float) -> str` — `"+3.21%"` 形式
  - `PerformanceRow` NamedTuple — `run_date: str, isin: str, name: str, judgment: str, nav_then: int, nav_now: int, change_pct: float`
  - `build_performance(history: list[JudgmentRecord], current_navs: dict[str, int], product_names: dict[str, str]) -> list[PerformanceRow]`
  - `format_performance_summary(rows: list[PerformanceRow]) -> str`
  - `latest_judgment_by_isin(history: list[JudgmentRecord]) -> dict[str, str]`
  - `summarize_nav(points: list[NavPoint]) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_performance.py` を新規作成する。

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_performance.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.performance'`）

- [ ] **Step 3: `app/src/performance.py` を実装する**

```python
from datetime import date, timedelta
from typing import NamedTuple

from src.advisor_store import JudgmentRecord
from src.nav import NavPoint

# The single place judgment codes turn into user-facing labels.
JUDGMENT_LABELS = {"BUY": "🟢 買い", "SELL": "🔴 売り", "HOLD": "🟡 ホールド"}

# Trailing windows shown in the NAV summary handed to the advice agent.
NAV_WINDOW_DAYS = (7, 30, 90, 180)

NO_HISTORY_TEXT = "過去の判断履歴はまだありません。"


class PerformanceRow(NamedTuple):
    """How one past judgment has fared against the current NAV."""

    run_date: str
    isin: str
    name: str
    judgment: str
    nav_then: int
    nav_now: int
    change_pct: float


def pct_change(base: int, current: int) -> float:
    """Percent change from ``base`` to ``current``; 0.0 when base is 0."""
    if base == 0:
        return 0.0
    return (current - base) / base * 100


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def build_performance(
    history: list[JudgmentRecord],
    current_navs: dict[str, int],
    product_names: dict[str, str],
) -> list[PerformanceRow]:
    """Flatten judgment history into rows scored against today's NAV.

    Args:
        history: Past runs, newest first.
        current_navs: isin -> today's NAV. Products missing here are skipped
            (a fund can be dropped from the advisor after being judged).
        product_names: isin -> display name; unknown isins show the isin.
    """
    rows: list[PerformanceRow] = []
    for record in history:
        for judgment in record["judgments"]:
            isin = judgment["isin"]
            nav_now = current_navs.get(isin)
            nav_then = judgment["nav"]
            if nav_now is None or nav_then <= 0:
                continue
            rows.append(
                PerformanceRow(
                    run_date=record["run_date"],
                    isin=isin,
                    name=product_names.get(isin, isin),
                    judgment=judgment["judgment"],
                    nav_then=nav_then,
                    nav_now=nav_now,
                    change_pct=pct_change(nav_then, nav_now),
                )
            )
    return rows


def format_performance_summary(rows: list[PerformanceRow]) -> str:
    """Render performance rows as Slack mrkdwn bullets."""
    if not rows:
        return NO_HISTORY_TEXT
    return "\n".join(
        f"• {row.run_date} {row.name}:"
        f" {JUDGMENT_LABELS.get(row.judgment, row.judgment)}"
        f" → {format_pct(row.change_pct)}"
        for row in rows
    )


def latest_judgment_by_isin(history: list[JudgmentRecord]) -> dict[str, str]:
    """isin -> the most recent judgment code for it.

    ``history`` must be newest first; the first record holding an isin wins.
    """
    latest: dict[str, str] = {}
    for record in history:
        for judgment in record["judgments"]:
            latest.setdefault(judgment["isin"], judgment["judgment"])
    return latest


def _nav_on_or_before(points: list[NavPoint], target: date) -> NavPoint | None:
    """Last point at or before ``target`` (points must be ascending)."""
    earlier = [p for p in points if p.date <= target]
    return earlier[-1] if earlier else None


def summarize_nav(points: list[NavPoint]) -> str:
    """One-line NAV summary: latest value plus trailing returns.

    Passing the whole series into the prompt would be wasteful, so the agent
    gets this digest and can call the nav_fetch tool when it needs more.
    """
    if not points:
        return "基準価額データなし"
    latest = points[-1]
    parts = [f"最新 {latest.date:%Y-%m-%d} {latest.nav:,}円"]
    for days in NAV_WINDOW_DAYS:
        past = _nav_on_or_before(points, latest.date - timedelta(days=days))
        if past is None or past.date == latest.date:
            continue
        parts.append(f"{days}日 {format_pct(pct_change(past.nav, latest.nav))}")
    return " / ".join(parts)
```

`NavPoint.date` は属性アクセスなので、モジュールレベルの `date` 型名とは衝突しない。`type: ignore` を書かずに mypy strict が通るはずである。もし通らなければ、`type: ignore` を足すのではなく型注釈を直すこと。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_performance.py -v`
Expected: PASS（15 件）

- [ ] **Step 5: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add app/src/performance.py app/tests/test_performance.py
git commit -m "feat: add performance and NAV summary helpers for the advisor"
```

---

## Task 5: 判断エージェント（`agent.run_advice`）

**Files:**
- Modify: `app/src/agent.py`（末尾に追記。既存の 4 関数は触らない）
- Test: `app/tests/test_agent.py`（末尾に追記）

**Interfaces:**
- Consumes: `src.advisor_store.NewsFeed`、`src.tools.nav_fetch.nav_fetch`、既存 `rss_fetch` / `web_scrape` / `api_fetch`
- Produces:
  - `src.agent.ADVICE_SYSTEM_PROMPT: str`
  - `src.agent.ProductAdvice(BaseModel)` — `isin: str`, `judgment: Literal["BUY", "SELL", "HOLD"]`, `reason: str`
  - `src.agent.AdviceResult(BaseModel)` — `summary: str`, `advices: list[ProductAdvice]`
  - `src.agent.run_advice(context: str, trading_notes: str, news_feeds: list[NewsFeed], now: datetime) -> AdviceResult`

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_agent.py` の末尾に追記する。既存テストと同じく Bedrock は呼ばず、`Agent` をモックしてプロンプト組み立てと構造化出力の扱いだけを検証する。

```python
def test_run_advice_returns_the_structured_output():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, ProductAdvice, run_advice

    expected = AdviceResult(
        summary="USD/JPY は 163 円台。",
        advices=[ProductAdvice(isin="JP90C000H1T1", judgment="HOLD", reason="様子見")],
    )
    result = MagicMock()
    result.structured_output = expected

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        advice = run_advice(
            context="商品一覧...",
            trading_notes="スイッチングは1週間から10日",
            news_feeds=[{"url": "https://example.com/rss", "name": "市況"}],
            now=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        )

    assert advice is expected


def test_run_advice_injects_trading_notes_into_the_system_prompt():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice(
            context="ctx",
            trading_notes="配分変更は翌月拠出分から反映",
            news_feeds=[],
            now=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        )

    system_prompt = mock_agent.call_args.kwargs["system_prompt"]
    assert "配分変更は翌月拠出分から反映" in system_prompt


def test_run_advice_prompt_carries_context_news_feeds_and_jst_now():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice(
            context="商品一覧と基準価額",
            trading_notes="",
            news_feeds=[{"url": "https://example.com/rss", "name": "市況ニュース"}],
            now=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        )

    prompt = mock_agent.return_value.call_args[0][0]
    assert "商品一覧と基準価額" in prompt
    assert "https://example.com/rss" in prompt
    assert "市況ニュース" in prompt
    # 08:00 UTC = 17:00 JST
    assert "2026-07-24 17:00 JST" in prompt


def test_run_advice_registers_the_advisor_tools():
    from unittest.mock import MagicMock, patch

    from src.agent import AdviceResult, run_advice

    result = MagicMock()
    result.structured_output = AdviceResult(summary="s", advices=[])

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        run_advice("ctx", "", [], datetime(2026, 7, 24, 8, 0, tzinfo=UTC))

    tools = mock_agent.call_args.kwargs["tools"]
    # api_fetch is what fetches the USD/JPY rate, so it must be registered.
    assert len(tools) == 4


def test_run_advice_raises_without_structured_output():
    from unittest.mock import MagicMock, patch

    import pytest

    from src.agent import run_advice

    result = MagicMock()
    result.structured_output = None

    with (
        patch("src.agent.BedrockModel"),
        patch("src.agent.Agent") as mock_agent,
    ):
        mock_agent.return_value.return_value = result
        with pytest.raises(ValueError, match="structured output"):
            run_advice("ctx", "", [], datetime(2026, 7, 24, 8, 0, tzinfo=UTC))
```

`app/tests/test_agent.py` の import 節に `from datetime import UTC, datetime` が無ければ足す（既存の import を確認してから）。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_agent.py -k advice -v`
Expected: FAIL（`ImportError: cannot import name 'run_advice'`）

- [ ] **Step 3: `app/src/agent.py` の import と system prompt を足す**

import 節を次に差し替える（`Literal` と `nav_fetch`、`NewsFeed` を追加）。

```python
import logging
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel
from strands import Agent
from strands.models import BedrockModel

from src import config
from src.advisor_store import NewsFeed
from src.tools.api_fetch import api_fetch
from src.tools.nav_fetch import nav_fetch
from src.tools.rss_fetch import rss_fetch
from src.tools.slack_history import slack_last_bot_post
from src.tools.web_scrape import web_scrape
```

`PLAN_SYSTEM_PROMPT` の定義の直後に、advisor 共通ルールだけを書いた system prompt テンプレートを足す。制度固有の事情は `trading_notes` から注入するため、ここには書かない。

```python
ADVICE_SYSTEM_PROMPT = """\
あなたは個人投資家向けの投資判断アドバイザーです。
与えられた商品ごとに「買い」「売り」「ホールド」のいずれかを判定し、
その理由と全体の市況サマリを日本語で作成してください。
実際の売買は利用者本人が行います。あなたの役割は判断材料の提供です。

# 判定の規則（重要）
- 判定は BUY / SELL / HOLD の3値のいずれか。あいまいな表現で逃げない。
  「やや強気」「中立寄り」のような中間表現は禁止。必ず3値のどれかに決める。
- 与えられた商品すべてについて、漏れなく1つずつ判定を出す。
  advices の isin は入力で与えられた ISIN をそのまま使う。

# 売買特性の前提（重要）
{trading_notes}

上記の売買特性により、指示から約定までに時間がかかる。
その期間内の値動きで無効になるような判断をしてはならない。
日中や数日の値動きではなく、数週間以上のトレンドと構造的な材料に基づいて判断する。

# 為替（重要）
- api_fetch で USD/JPY の現在値と直近の推移を必ず取得する。
  例: https://api.frankfurter.dev/v1/latest?base=USD&symbols=JPY
  推移: https://api.frankfurter.dev/v1/<YYYY-MM-DD>..?base=USD&symbols=JPY
- 為替ヘッジのない海外資産ファンド（全世界株式・先進国株式など）の判断では、
  為替要因と現地資産要因を切り分けて理由を述べる。
  円安による基準価額の上昇を、現地資産の上昇と混同しない。

# 前回判断との比較
- 入力には前回までの判断履歴が含まれる。
- 前回から判定を変更する場合は、何が変わったのかを理由に必ず含める。
- 変更しない場合も、なぜ維持するのかを一言添える。

# 調査
- nav_fetch: 商品の基準価額の推移。入力のサマリで足りなければ呼ぶ。
- rss_fetch / web_scrape: 与えられた市況ニュースのフィードから相場材料を集める。
- api_fetch: 為替やその他の数値データ。

# 出力
- summary: 今回の市況サマリ（Slack mrkdwn）。USD/JPY の現在値と変動見通しを必ず含め、
  主要な相場材料と、判断を変更した商品があればその要点に触れる。3〜5文程度。
- advices: 商品ごとの {{isin, judgment, reason}}。reason は2〜4文の日本語。
- 本文は Slack の mrkdwn で書く。強調は `*太字*`（アスタリスク1つ）。
  `#` や `**` は使わない。箇条書きは行頭に `•`。
  リンクは `<https://example.com|表示名>` の形式にする。
- 免責文は呼び出し側が付けるので、あなたは書かない。
- ツールで Slack へ投稿してはいけない。
"""
```

`{trading_notes}` を `str.format` で埋めるため、prompt 内の JSON 風の中括弧は `{{` `}}` にエスケープしてある。ここを崩さないこと。

- [ ] **Step 4: モデルと `run_advice` を実装する**

`app/src/agent.py` の末尾に追記する。

```python
class ProductAdvice(BaseModel):
    """The judgment for one product."""

    isin: str
    judgment: Literal["BUY", "SELL", "HOLD"]
    reason: str


class AdviceResult(BaseModel):
    """One advisor run: the market summary plus a judgment per product."""

    summary: str
    advices: list[ProductAdvice]


def run_advice(
    context: str,
    trading_notes: str,
    news_feeds: list[NewsFeed],
    now: datetime,
) -> AdviceResult:
    """Produce BUY/SELL/HOLD judgments for every product in ``context``.

    Args:
        context: Products, NAV summaries, past judgments and their scored
            performance, prepared by the caller.
        trading_notes: The scheme's trading characteristics (settlement lag
            etc.), injected into the system prompt.
        news_feeds: Market news sources the agent may crawl.
        now: The run time; shown to the agent in both UTC and JST.

    Raises:
        ValueError: if the agent returns no structured output.
    """
    model = BedrockModel(
        model_id=config.BEDROCK_MODEL_ID,
        region_name=config.AWS_REGION,
    )
    agent = Agent(
        model=model,
        tools=[nav_fetch, rss_fetch, web_scrape, api_fetch],
        system_prompt=ADVICE_SYSTEM_PROMPT.format(
            trading_notes=trading_notes or "（特記なし）"
        ),
    )
    now_utc = now.astimezone(UTC)
    now_jst = now.astimezone(config.JST)
    feeds = "\n".join(f"- {f['name']}: {f['url']}" for f in news_feeds) or "- （なし）"
    prompt = (
        f"現在日時: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}（UTC）"
        f" = {now_jst.strftime('%Y-%m-%d %H:%M')} JST\n\n"
        f"# 判断対象と直近の状況\n{context}\n\n"
        f"# 市況ニュースの取得元\n{feeds}\n\n"
        f"上記すべての商品について判定と理由、および市況サマリを作成してください。"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt, structured_output_model=AdviceResult)
    advice = result.structured_output
    if not isinstance(advice, AdviceResult):
        raise ValueError(f"advice agent returned no structured output: {result}")
    logger.info("Bedrock output: %s", advice)
    return advice
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_agent.py -v`
Expected: PASS（新規 5 件を含め既存もすべて）

- [ ] **Step 6: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 7: コミット**

```bash
git add app/src/agent.py app/tests/test_agent.py
git commit -m "feat: add run_advice agent producing BUY/SELL/HOLD judgments"
```

---

## Task 6: 冪等性の判定（`slack_reader.py`）

既存の `tools/slack_history.py` は「bot の前回投稿」を header を見ずに探すため、同一チャンネルに複数のスレッドが混在すると誤判定する。advisor は `title` を header に持つ投稿だけを探す専用モジュールを持つ。ツール（`@tool`）ではなく Python から直接呼ぶ純関数として実装する。

**重要な設計判断:** `find_last_post_time` は「見つからなかった」ときだけ `None` を返し、Slack API エラーでは**例外を送出する**。エラーを「見つからなかった」に丸めると重複投稿してしまうため、ADR の「誤って重複投稿するより安全側に倒す」に従う。

**Files:**
- Create: `app/src/slack_reader.py`
- Modify: `app/src/slack_notifier.py`（`_HEADER_LIMIT` → `HEADER_LIMIT`）
- Test: `app/tests/test_slack_reader.py`

**Interfaces:**
- Consumes: `src.config.get_slack_token`, `src.config.JST`, `src.slack_notifier.HEADER_LIMIT`
- Produces:
  - `src.slack_notifier.HEADER_LIMIT: int`（`_HEADER_LIMIT` から改名。`slack_notifier` 内の参照も置換する）
  - `src.slack_reader.find_last_post_time(channel: str, header: str, lookback_days: int = 30) -> datetime | None`
  - `src.slack_reader.should_post(last_post: datetime | None, now: datetime, interval_days: int) -> tuple[bool, str]`

- [ ] **Step 1: `slack_notifier` の定数を公開名にする**

```bash
sed -i 's/_HEADER_LIMIT/HEADER_LIMIT/g' app/src/slack_notifier.py
```

Run: `uv run pytest app/tests/test_slack_notifier.py -v`
Expected: PASS（テストが `_HEADER_LIMIT` を参照していた場合は同様に置換する）

- [ ] **Step 2: 失敗するテストを書く**

`app/tests/test_slack_reader.py` を新規作成する。

```python
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

HEADER = "iDeCo 投資判断"


def _message(ts: datetime, header: str | None, user: str = "U_BOT") -> dict:
    message: dict = {"ts": str(ts.timestamp()), "user": user}
    if header is not None:
        message["text"] = header
        message["blocks"] = [
            {"type": "header", "text": {"type": "plain_text", "text": header}},
            {"type": "divider"},
        ]
    return message


def _client(messages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.auth_test.return_value = {"user_id": "U_BOT"}
    client.conversations_history.return_value = {
        "messages": messages,
        "response_metadata": {},
    }
    return client


@pytest.fixture(autouse=True)
def reset_bot_user_cache():
    import src.slack_reader as slack_reader

    slack_reader._bot_user_id_cache = None
    yield
    slack_reader._bot_user_id_cache = None


def test_find_last_post_time_matches_the_advisor_header(ssm_parameter):
    from src.slack_reader import find_last_post_time

    posted = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)

    with patch("src.slack_reader.WebClient", return_value=_client([_message(posted, HEADER)])):
        found = find_last_post_time("C1", HEADER)

    assert found == posted


def test_find_last_post_time_ignores_other_headers(ssm_parameter):
    """A digest thread in the same channel must not count as our post."""
    from src.slack_reader import find_last_post_time

    messages = [_message(datetime(2026, 7, 20, 0, 0, tzinfo=UTC), "Tech Digest")]

    with patch("src.slack_reader.WebClient", return_value=_client(messages)):
        assert find_last_post_time("C1", HEADER) is None


def test_find_last_post_time_returns_the_newest_match(ssm_parameter):
    from src.slack_reader import find_last_post_time

    newest = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    older = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    messages = [_message(newest, HEADER), _message(older, HEADER)]

    with patch("src.slack_reader.WebClient", return_value=_client(messages)):
        assert find_last_post_time("C1", HEADER) == newest


def test_find_last_post_time_ignores_other_users(ssm_parameter):
    from src.slack_reader import find_last_post_time

    messages = [_message(datetime(2026, 7, 18, tzinfo=UTC), HEADER, user="U_HUMAN")]

    with patch("src.slack_reader.WebClient", return_value=_client(messages)):
        assert find_last_post_time("C1", HEADER) is None


def test_find_last_post_time_stops_at_the_lookback_cutoff(ssm_parameter):
    from src.slack_reader import find_last_post_time

    ancient = datetime.now(UTC) - timedelta(days=90)

    with patch("src.slack_reader.WebClient", return_value=_client([_message(ancient, HEADER)])):
        assert find_last_post_time("C1", HEADER, lookback_days=30) is None


def test_find_last_post_time_falls_back_to_the_text_field(ssm_parameter):
    """post_message sets text=header, so a block-less message still matches."""
    from src.slack_reader import find_last_post_time

    posted = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    message = {"ts": str(posted.timestamp()), "user": "U_BOT", "text": HEADER}

    with patch("src.slack_reader.WebClient", return_value=_client([message])):
        assert find_last_post_time("C1", HEADER) == posted


def test_find_last_post_time_raises_on_api_error(ssm_parameter):
    """Never silently degrade to None: that would double-post."""
    from src.slack_reader import find_last_post_time

    client = MagicMock()
    client.auth_test.side_effect = RuntimeError("slack down")

    with patch("src.slack_reader.WebClient", return_value=client):
        with pytest.raises(RuntimeError):
            find_last_post_time("C1", HEADER)


def test_should_post_when_there_is_no_previous_post():
    from src.slack_reader import should_post

    ok, reason = should_post(None, datetime(2026, 7, 24, 8, 0, tzinfo=UTC), 7)

    assert ok is True
    assert "前回投稿が見つからない" in reason


def test_should_not_post_twice_on_the_same_jst_day():
    from src.slack_reader import should_post

    # 2026-07-24 00:30 JST and 2026-07-24 17:00 JST are the same JST day.
    last = datetime(2026, 7, 23, 15, 30, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, reason = should_post(last, now, 1)

    assert ok is False
    assert "本日投稿済み" in reason


def test_should_post_the_next_jst_day_when_interval_is_one():
    from src.slack_reader import should_post

    last = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, _ = should_post(last, now, 1)

    assert ok is True


def test_should_not_post_before_the_interval_elapses():
    from src.slack_reader import should_post

    last = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, reason = should_post(last, now, 7)

    assert ok is False
    assert "3日" in reason


def test_should_post_once_the_interval_elapses():
    from src.slack_reader import should_post

    last = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    ok, _ = should_post(last, now, 7)

    assert ok is True


def test_should_post_compares_jst_dates_not_elapsed_hours():
    """23:00 JST -> next day 17:00 JST is only 18h but is a new JST day."""
    from src.slack_reader import should_post

    last = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)  # 2026-07-23 23:00 JST
    now = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)  # 2026-07-24 17:00 JST

    ok, _ = should_post(last, now, 1)

    assert ok is True
```

- [ ] **Step 3: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_slack_reader.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.slack_reader'`）

- [ ] **Step 4: `app/src/slack_reader.py` を実装する**

```python
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_sdk import WebClient

from src import config
from src.slack_notifier import HEADER_LIMIT

logger = logging.getLogger(__name__)

_bot_user_id_cache: str | None = None


def _get_bot_user_id(client: WebClient) -> str:
    global _bot_user_id_cache
    if _bot_user_id_cache is None:
        _bot_user_id_cache = str(client.auth_test()["user_id"])
    return _bot_user_id_cache


def _has_header(message: dict[str, Any], header: str) -> bool:
    """Whether this message is the thread parent carrying ``header``.

    post_message renders the header both as a header block (truncated to
    HEADER_LIMIT) and as the fallback ``text`` field, so either can match.
    """
    truncated = header[:HEADER_LIMIT]
    for block in message.get("blocks") or []:
        if block.get("type") == "header":
            return str(block.get("text", {}).get("text", "")) == truncated
    return str(message.get("text", "")) == truncated


def find_last_post_time(
    channel: str, header: str, lookback_days: int = 30
) -> datetime | None:
    """Find when this bot last posted a thread parent with ``header``.

    Unlike the digest's slack_last_bot_post tool, this filters by header, so
    other threads (a digest, another advisor) in the same channel are ignored.

    Args:
        channel: Slack channel ID.
        header: The advisor title used as the headline header.
        lookback_days: How far back to search.

    Returns:
        The post time in UTC, or None when no matching post exists in the
        lookback window.

    Raises:
        Exception: any Slack API failure is propagated. Callers must not
            treat a failure as "not posted yet" — that would double-post.
    """
    logger.info(
        "find_last_post_time: channel=%s header=%r lookback_days=%d",
        channel,
        header,
        lookback_days,
    )
    client = WebClient(token=config.get_slack_token())
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    bot_user_id = _get_bot_user_id(client)

    cursor: str | None = None
    while True:
        # No `oldest`: that would anchor pagination at the old end and make
        # the first match the oldest post. The cutoff is applied client-side.
        response = client.conversations_history(
            channel=channel, limit=200, cursor=cursor
        )
        # Messages arrive newest-first, so the first match is the latest post.
        for message in response["messages"]:
            ts = datetime.fromtimestamp(float(message["ts"]), tz=UTC)
            if ts < cutoff:
                return None
            if message.get("user") != bot_user_id or "subtype" in message:
                continue
            if _has_header(message, header):
                return ts
        metadata: dict[str, Any] = response.get("response_metadata") or {}
        cursor = metadata.get("next_cursor")
        if not cursor:
            return None


def should_post(
    last_post: datetime | None, now: datetime, interval_days: int
) -> tuple[bool, str]:
    """Decide whether this run should post, and why.

    Comparison is by JST calendar date, not elapsed hours: the job runs at a
    fixed JST time but invocations can jitter, and an hours-based comparison
    would flip-flop around interval_days=1.

    Returns:
        (should_post, reason in Japanese).
    """
    if last_post is None:
        return True, "前回投稿が見つからないため投稿する"

    today = now.astimezone(config.JST).date()
    last_day = last_post.astimezone(config.JST).date()
    elapsed = (today - last_day).days
    if elapsed <= 0:
        return False, "本日投稿済みのため投稿しない"
    if elapsed < interval_days:
        return (
            False,
            f"前回投稿から{elapsed}日（投稿間隔{interval_days}日）のため投稿しない",
        )
    return True, f"前回投稿から{elapsed}日経過したため投稿する"
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_slack_reader.py -v`
Expected: PASS（13 件）

- [ ] **Step 6: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 7: コミット**

```bash
git add app/src/slack_reader.py app/src/slack_notifier.py app/tests/test_slack_reader.py app/tests/test_slack_notifier.py
git commit -m "feat: add header-filtered Slack reader and idempotent posting check"
```

---

## Task 7: advisor ジョブ本体とハンドラの分岐

**Files:**
- Create: `app/src/advisor.py`
- Modify: `app/src/handler.py`
- Test: `app/tests/test_advisor.py`, `app/tests/test_handler.py`（分岐テストを追加）

**Interfaces:**
- Consumes: `src.advisor_store` の全関数と型、`src.performance` の全関数、`src.nav.fetch_nav_series`、`src.slack_reader.find_last_post_time / should_post`、`src.agent.run_advice`、`src.slack_notifier.post_message`
- Produces:
  - `src.advisor.DISCLAIMER: str`
  - `src.advisor.run_advisor_job(now: datetime) -> dict[str, Any]` — `{"status": "ok", "advisors": int, "results": dict[str, str]}`
  - `src.handler.lambda_handler` が `event["job"] == "advisor"` で `run_advisor_job` を呼ぶ（既定は digest）

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_advisor.py` を新規作成する。Bedrock・Slack・HTTP はすべてモックし、オーケストレーションの分岐だけを検証する。

```python
import importlib
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from src.nav import NavPoint

NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)  # 2026-07-24 17:00 JST
ISIN = "JP90C000H1T1"
SERIES = [
    NavPoint(date=date(2026, 7, 23), nav=38000),
    NavPoint(date=date(2026, 7, 24), nav=38243),
]


@pytest.fixture(autouse=True)
def reload_modules():
    import src.config as cfg

    importlib.reload(cfg)
    import src.advisor_store as advisor_store

    importlib.reload(advisor_store)
    import src.advisor as advisor

    importlib.reload(advisor)


def _advice(judgment: str = "HOLD", summary: str = "USD/JPY は 163 円台。"):
    from src.agent import AdviceResult, ProductAdvice

    return AdviceResult(
        summary=summary,
        advices=[ProductAdvice(isin=ISIN, judgment=judgment, reason="円安一服のため")],
    )


def test_skips_when_already_posted_today(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=NOW),
        patch("src.advisor.run_advice") as mock_advice,
        patch("src.advisor.slack_notifier.post_message") as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert "skipped" in result["results"]["ideco-sbi"]
    mock_advice.assert_not_called()
    mock_post.assert_not_called()


def test_skips_before_the_interval_elapses(integrated_aws_mock):
    from src.advisor import run_advisor_job

    last = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

    with (
        patch("src.advisor.find_last_post_time", return_value=last),
        patch("src.advisor.run_advice") as mock_advice,
        patch("src.advisor.slack_notifier.post_message"),
    ):
        result = run_advisor_job(NOW)

    assert "skipped" in result["results"]["ideco-sbi"]
    mock_advice.assert_not_called()


def test_posts_a_thread_when_due(integrated_aws_mock):
    from src.advisor import DISCLAIMER, run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()),
        patch(
            "src.advisor.slack_notifier.post_message", return_value="111.222"
        ) as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert result["status"] == "ok"
    assert result["advisors"] == 1
    assert result["results"]["ideco-sbi"] == "success"

    # 1 parent + 1 reply per product
    assert mock_post.call_count == 2
    parent = mock_post.call_args_list[0]
    assert parent.kwargs["header"] == "iDeCo 投資判断"
    assert parent.kwargs.get("thread_ts") is None
    assert "USD/JPY は 163 円台。" in parent.kwargs["text"]
    assert DISCLAIMER in parent.kwargs["text"]

    reply = mock_post.call_args_list[1]
    assert reply.kwargs["thread_ts"] == "111.222"
    assert reply.kwargs["header"].startswith("🟡 ホールド")
    assert "eMAXIS Slim 全世界株式" in reply.kwargs["header"]
    assert "円安一服のため" in reply.kwargs["text"]


def test_reply_states_the_change_from_the_previous_judgment(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import put_judgments

    put_judgments(
        "ideco-sbi",
        "2026-07-11",
        [{"isin": ISIN, "judgment": "BUY", "reason": "r", "nav": 37000}],
    )

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice("SELL")),
        patch("src.advisor.slack_notifier.post_message", return_value="t") as mock_post,
    ):
        run_advisor_job(NOW)

    reply_text = mock_post.call_args_list[1].kwargs["text"]
    assert "前回: 🟢 買い" in reply_text
    assert "今回: 🔴 売り" in reply_text


def test_persists_the_judgments_under_the_jst_run_date(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import get_judgment_history

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice("BUY")),
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        run_advisor_job(NOW)

    history = get_judgment_history("ideco-sbi")
    assert history[0]["run_date"] == "2026-07-24"
    assert history[0]["judgments"][0]["judgment"] == "BUY"
    # The NAV at judgment time is stored so performance can be scored later.
    assert history[0]["judgments"][0]["nav"] == 38243


def test_does_not_post_when_slack_history_is_unreadable(integrated_aws_mock):
    """Failing to read history must not lead to a duplicate post."""
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", side_effect=RuntimeError("no scope")),
        patch("src.advisor.run_advice") as mock_advice,
        patch("src.advisor.slack_notifier.post_message") as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert "error" in result["results"]["ideco-sbi"]
    mock_advice.assert_not_called()
    mock_post.assert_not_called()


def test_continues_when_one_products_nav_fetch_fails(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", side_effect=RuntimeError("csv down")),
        patch("src.advisor.run_advice", return_value=_advice()) as mock_advice,
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        result = run_advisor_job(NOW)

    # The advice still runs; the agent can fall back to the nav_fetch tool.
    mock_advice.assert_called_once()
    assert result["results"]["ideco-sbi"] == "success"


def test_records_an_error_when_advice_fails(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", side_effect=RuntimeError("bedrock down")),
        patch("src.advisor.slack_notifier.post_message") as mock_post,
    ):
        result = run_advisor_job(NOW)

    assert "error" in result["results"]["ideco-sbi"]
    mock_post.assert_not_called()


def test_passes_trading_notes_and_news_feeds_to_the_agent(integrated_aws_mock):
    from src.advisor import run_advisor_job

    with (
        patch("src.advisor.find_last_post_time", return_value=None),
        patch("src.advisor.fetch_nav_series", return_value=SERIES),
        patch("src.advisor.run_advice", return_value=_advice()) as mock_advice,
        patch("src.advisor.slack_notifier.post_message", return_value="t"),
    ):
        run_advisor_job(NOW)

    kwargs = mock_advice.call_args.kwargs
    assert "スイッチング" in kwargs["trading_notes"]
    assert kwargs["news_feeds"][0]["url"] == "https://example.com/market.rss"
    assert kwargs["now"] == NOW
    # The context carries the products and their NAV summary
    assert ISIN in kwargs["context"]
    assert "38,243円" in kwargs["context"]


def test_returns_ok_with_no_advisors(integrated_aws_mock):
    from src.advisor import run_advisor_job
    from src.advisor_store import delete_advisor

    delete_advisor("ideco-sbi")

    result = run_advisor_job(NOW)

    assert result == {"status": "ok", "advisors": 0}
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_advisor.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.advisor'`）

- [ ] **Step 3: `app/src/advisor.py` を実装する**

```python
import logging
from datetime import datetime
from typing import Any

from src import config, slack_notifier
from src.advisor_store import (
    Advisor,
    Judgment,
    Product,
    get_all_advisors,
    get_judgment_history,
    put_judgments,
)
from src.agent import run_advice
from src.nav import fetch_nav_series
from src.performance import (
    JUDGMENT_LABELS,
    build_performance,
    format_performance_summary,
    latest_judgment_by_isin,
    summarize_nav,
)
from src.slack_reader import find_last_post_time, should_post

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "※ 本投稿は投資判断のための情報提供であり、投資助言ではありません。"
    "最終的な投資判断はご自身の責任で行ってください。"
)

# How many past runs to score and show. Roughly two months at weekly cadence.
HISTORY_LIMIT = 8


def _product_line(product: Product, nav_summary: str, previous: str | None) -> str:
    holding = "保有中" if product.get("holding") else "乗り換え候補"
    prev = f" / 前回判断: {previous}" if previous else " / 前回判断: なし"
    return (
        f"- {product['name']}（ISIN: {product['isin']},"
        f" 協会コード: {product['assoc_fund_cd']}, {product['category']}, {holding}）\n"
        f"  基準価額: {nav_summary}{prev}"
    )


def _build_context(
    products: list[Product],
    nav_summaries: dict[str, str],
    previous: dict[str, str],
    performance_text: str,
) -> str:
    lines = [
        _product_line(p, nav_summaries.get(p["isin"], "基準価額データなし"),
                      previous.get(p["isin"]))
        for p in products
    ]
    return (
        "## 判断対象商品\n"
        + "\n".join(lines)
        + "\n\n## 過去の判断とその後の騰落率\n"
        + performance_text
    )


def _process_advisor(advisor: Advisor, now: datetime) -> str:
    """Run one advisor end to end; returns its result string."""
    advisor_id = advisor["advisor_id"]
    channel = advisor["channel_id"]
    title = advisor["title"]
    products = advisor["products"]

    # Idempotency: a read failure must never be treated as "not posted yet",
    # so it aborts this advisor instead of risking a duplicate post.
    try:
        last_post = find_last_post_time(channel, title)
    except Exception as e:
        logger.error(
            "Cannot read Slack history for %s: %s", advisor_id, e, exc_info=True
        )
        return f"error: slack history unreadable: {e}"

    posting, reason = should_post(last_post, now, advisor["interval_days"])
    logger.info("Posting decision for %s: %s (%s)", advisor_id, posting, reason)
    if not posting:
        return f"skipped: {reason}"

    current_navs: dict[str, int] = {}
    nav_summaries: dict[str, str] = {}
    for product in products:
        try:
            series = fetch_nav_series(product["isin"], product["assoc_fund_cd"])
        except Exception as e:
            # Not fatal: the agent still has the nav_fetch tool.
            logger.warning("NAV fetch failed for %s: %s", product["isin"], e)
            continue
        if not series:
            continue
        current_navs[product["isin"]] = series[-1].nav
        nav_summaries[product["isin"]] = summarize_nav(series)

    history = get_judgment_history(advisor_id, limit=HISTORY_LIMIT)
    product_names = {p["isin"]: p["name"] for p in products}
    performance_rows = build_performance(history, current_navs, product_names)
    performance_text = format_performance_summary(performance_rows)
    previous_codes = latest_judgment_by_isin(history)
    previous_labels = {
        isin: JUDGMENT_LABELS.get(code, code) for isin, code in previous_codes.items()
    }

    context = _build_context(
        products, nav_summaries, previous_labels, performance_text
    )
    try:
        advice = run_advice(
            context=context,
            trading_notes=advisor["trading_notes"],
            news_feeds=advisor["news_feeds"],
            now=now,
        )
    except Exception as e:
        logger.error("Advice failed for %s: %s", advisor_id, e, exc_info=True)
        return f"error: {e}"

    parent_text = (
        f"{advice.summary}\n\n"
        f"*過去推奨の成績*\n{performance_text}\n\n"
        f"{DISCLAIMER}"
    )
    try:
        thread_ts = slack_notifier.post_message(
            channel, text=parent_text, header=title
        )
    except Exception as e:
        logger.error("Failed to post parent for %s: %s", advisor_id, e, exc_info=True)
        return f"error: {e}"

    for item in advice.advices:
        label = JUDGMENT_LABELS.get(item.judgment, item.judgment)
        name = product_names.get(item.isin, item.isin)
        previous_label = previous_labels.get(item.isin)
        change = (
            f"前回: {previous_label} → 今回: {label}"
            if previous_label
            else f"今回: {label}（初回判断）"
        )
        try:
            slack_notifier.post_message(
                channel,
                text=f"{item.reason}\n\n{change}",
                header=f"{label} {name}",
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error("Failed to post reply for %s: %s", item.isin, e, exc_info=True)

    run_date = now.astimezone(config.JST).strftime("%Y-%m-%d")
    judgments: list[Judgment] = [
        {
            "isin": item.isin,
            "judgment": item.judgment,
            "reason": item.reason,
            "nav": current_navs.get(item.isin, 0),
        }
        for item in advice.advices
    ]
    put_judgments(advisor_id, run_date, judgments)
    return "success"


def run_advisor_job(now: datetime) -> dict[str, Any]:
    """Run the investment advisor job for every registered advisor.

    Args:
        now: The scheduled invocation time; also the JST run date key.

    Returns:
        ``{"status": "ok", "advisors": N, "results": {...}}``; ``results`` is
        omitted when no advisor is registered.
    """
    advisors = get_all_advisors()
    logger.info("Fetched %d advisor(s) from DynamoDB", len(advisors))

    if not advisors:
        logger.info("No advisors found in DynamoDB")
        return {"status": "ok", "advisors": 0}

    results: dict[str, str] = {}
    for advisor in advisors:
        results[advisor["advisor_id"]] = _process_advisor(advisor, now)

    logger.info("Advisor run complete: %s", results)
    return {"status": "ok", "advisors": len(advisors), "results": results}
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_advisor.py -v`
Expected: PASS（10 件）

- [ ] **Step 5: ハンドラ分岐の失敗するテストを書く**

`app/tests/test_handler.py` の末尾に追記する。

```python
def test_handler_dispatches_to_the_advisor_job(integrated_aws_mock):
    from src.handler import lambda_handler

    with (
        patch(
            "src.handler.run_advisor_job", return_value={"status": "ok", "advisors": 1}
        ) as mock_advisor,
        patch("src.handler.run_digest_job") as mock_digest,
    ):
        result = lambda_handler(
            {"job": "advisor", "scheduled_time": "2026-07-24T08:00:00Z"}, None
        )

    assert result == {"status": "ok", "advisors": 1}
    mock_digest.assert_not_called()
    mock_advisor.assert_called_once_with(
        datetime.fromisoformat("2026-07-24T08:00:00Z")
    )


def test_handler_defaults_to_the_digest_job(integrated_aws_mock):
    from src.handler import lambda_handler

    with (
        patch("src.handler.run_advisor_job") as mock_advisor,
        patch(
            "src.handler.run_digest_job", return_value={"status": "ok", "sources": 0}
        ) as mock_digest,
    ):
        lambda_handler({"scheduled_time": "2026-06-01T00:00:00Z"}, None)

    mock_advisor.assert_not_called()
    mock_digest.assert_called_once()


def test_handler_treats_an_unknown_job_as_digest(integrated_aws_mock):
    from src.handler import lambda_handler

    with (
        patch("src.handler.run_advisor_job") as mock_advisor,
        patch(
            "src.handler.run_digest_job", return_value={"status": "ok", "sources": 0}
        ) as mock_digest,
    ):
        lambda_handler({"job": "nonsense"}, None)

    mock_advisor.assert_not_called()
    mock_digest.assert_called_once()
```

- [ ] **Step 6: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_handler.py -k dispatch -v`
Expected: FAIL（`AttributeError: <module 'src.handler'> does not have the attribute 'run_advisor_job'`）

- [ ] **Step 7: `app/src/handler.py` に分岐を足す**

`from src.digest import run_digest_job` の下に import を足し、`lambda_handler` を差し替える。

```python
from src.advisor import run_advisor_job
```

```python
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    configure_logging()
    now = _parse_scheduled_time(event)
    # EventBridge picks the job; anything unrecognized falls back to digest so
    # a malformed schedule input never silently does nothing.
    job = event.get("job", "digest")
    logger.info("Dispatching job=%s at %s", job, now.isoformat())
    if job == "advisor":
        return run_advisor_job(now)
    return run_digest_job(now)
```

- [ ] **Step 8: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_handler.py -v`
Expected: PASS（既存 16 件 + 新規 3 件）

- [ ] **Step 9: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/`
Expected: すべて PASS

- [ ] **Step 10: コミット**

```bash
git add app/src/advisor.py app/src/handler.py app/tests/test_advisor.py app/tests/test_handler.py
git commit -m "feat: add the advisor job and dispatch it from the Lambda handler"
```

---

## Task 8: インフラ・CLI・ドキュメント

コードは動く状態なので、あとはデプロイできる形に揃える。

**Files:**
- Create: `scripts/manage_advisors.py`
- Modify: `terraform/dynamodb.tf`, `terraform/lambda.tf`, `terraform/eventbridge.tf`, `terraform/outputs.tf`, `app/function.jsonnet`, `Makefile`, `CLAUDE.md`, `README.md`
- Test: `app/tests/test_manage_advisors.py`

**Interfaces:**
- Consumes: `src.advisor_store.add_advisor / delete_advisor / get_all_advisors`
- Produces:
  - terraform outputs `advisors_table_name`, `judgments_table_name`
  - Lambda env `ADVISORS_TABLE_NAME`, `JUDGMENTS_TABLE_NAME`
  - `make advisors-list / advisors-add / advisors-delete / invoke-advisor`

- [ ] **Step 1: DynamoDB テーブルを 2 つ足す**

`terraform/dynamodb.tf` の末尾に追記する。

```hcl
resource "aws_dynamodb_table" "advisors" {
  name         = "${var.project_name}-advisors"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "advisor_id"

  attribute {
    name = "advisor_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "advisor_judgments" {
  name         = "${var.project_name}-advisor-judgments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "advisor_id"
  range_key    = "run_date"

  attribute {
    name = "advisor_id"
    type = "S"
  }

  attribute {
    name = "run_date"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
```

- [ ] **Step 2: IAM を広げる**

`terraform/lambda.tf:34-45` の `aws_iam_policy.lambda_dynamodb` を次に置き換える。判断履歴には Query と PutItem が要る。

```hcl
resource "aws_iam_policy" "lambda_dynamodb" {
  name = "${var.project_name}-lambda-dynamodb"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["dynamodb:Scan", "dynamodb:GetItem"]
      Resource = [
        aws_dynamodb_table.sources.arn,
        aws_dynamodb_table.advisors.arn,
      ]
      }, {
      Effect   = "Allow"
      Action   = ["dynamodb:Query", "dynamodb:PutItem"]
      Resource = aws_dynamodb_table.advisor_judgments.arn
    }]
  })
}
```

- [ ] **Step 3: EventBridge スケジュールを足す**

`terraform/eventbridge.tf` の末尾に追記する。既存の JST 9:00 ルールは digest 専用のまま変更しない。

```hcl
resource "aws_scheduler_schedule" "advisor" {
  name       = "${var.project_name}-advisor"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # JST 17:00 (timezone Asia/Tokyo). Runs daily; posting cadence is decided
  # in-app from interval_days plus the Slack history check, so shortening the
  # interval needs no infra change.
  schedule_expression          = "cron(0 17 * * ? *)"
  schedule_expression_timezone = "Asia/Tokyo"

  target {
    arn      = aws_lambda_function.main.arn
    role_arn = aws_iam_role.scheduler.arn
    # NOTE: do not use jsonencode() here. It escapes < and >, which breaks
    # the <aws.scheduler.scheduled-time> context attribute substitution.
    input = "{\"job\": \"advisor\", \"scheduled_time\": \"<aws.scheduler.scheduled-time>\"}"
  }
}
```

- [ ] **Step 4: output を足す**

`terraform/outputs.tf` の末尾に追記する。

```hcl
output "advisors_table_name" {
  description = "DynamoDB advisors table name"
  value       = aws_dynamodb_table.advisors.name
}

output "judgments_table_name" {
  description = "DynamoDB advisor judgments table name"
  value       = aws_dynamodb_table.advisor_judgments.name
}
```

- [ ] **Step 5: terraform を検証する**

Run: `cd terraform && terraform fmt -recursive && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

`-backend=false` はローカル検証用。tfstate バケットの認証情報が無くても通る。終わったら `cd ..` でルートに戻る。

- [ ] **Step 6: Lambda の環境変数を足す**

`app/function.jsonnet` の `Environment.Variables` に 2 行足す。

```jsonnet
      ADVISORS_TABLE_NAME: must_env('ADVISORS_TABLE_NAME'),
      JUDGMENTS_TABLE_NAME: must_env('JUDGMENTS_TABLE_NAME'),
```

`Description` も実態に合わせて更新する。

```jsonnet
  Description: 'AI Digest Bot - tech digest + investment advisor via Strands Agent + Bedrock',
```

- [ ] **Step 7: Makefile に env 注入と管理ターゲットを足す**

`deploy-app` と `deploy-app-dry` の両方で、`SLACK_BOT_TOKEN_PARAM=` の行の直後に 2 行足す（**両方に入れること**。片方だけだと dry run が must_env で落ちる）。

```make
	  ADVISORS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw advisors_table_name)" \
	  JUDGMENTS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw judgments_table_name)" \
```

`sources-delete` ターゲットの後ろに advisor 管理ターゲットを足す。

```make
advisors-list:
	cd app && PYTHONPATH=. \
	  ADVISORS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw advisors_table_name)" \
	  JUDGMENTS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw judgments_table_name)" \
	  SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  uv run python ../scripts/manage_advisors.py list

# Usage: make advisors-add ADVISOR_ID=ideco-sbi CHANNEL_ID=CXXXX TITLE="iDeCo 投資判断" \
#          PRODUCTS='[{"isin":"JP90C000H1T1","name":"eMAXIS Slim 全世界株式(オール・カントリー)","category":"全世界株","holding":true,"assoc_fund_cd":"0331418A"}]' \
#          NEWS_FEEDS='[{"url":"https://example.com/rss","name":"市況ニュース"}]' \
#          TRADING_NOTES="スイッチングは指示から完了まで概ね1週間から10日。掛金の配分変更は翌月拠出分から反映。" \
#          [INTERVAL_DAYS=7]
# Note: full upsert — omitting a field on re-add clears it.
advisors-add:
	cd app && PYTHONPATH=. \
	  ADVISORS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw advisors_table_name)" \
	  JUDGMENTS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw judgments_table_name)" \
	  SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  uv run python ../scripts/manage_advisors.py add --advisor-id "$(ADVISOR_ID)" --channel-id "$(CHANNEL_ID)" --title "$(TITLE)" --products-json '$(PRODUCTS)' --news-feeds-json '$(NEWS_FEEDS)' --trading-notes "$(TRADING_NOTES)" $(if $(INTERVAL_DAYS),--interval-days "$(INTERVAL_DAYS)")

advisors-delete:
	cd app && PYTHONPATH=. \
	  ADVISORS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw advisors_table_name)" \
	  JUDGMENTS_TABLE_NAME="$$(terraform -chdir=../terraform output -raw judgments_table_name)" \
	  SOURCES_TABLE_NAME="$$(terraform -chdir=../terraform output -raw sources_table_name)" \
	  uv run python ../scripts/manage_advisors.py delete --advisor-id "$(ADVISOR_ID)"

invoke-advisor:
	aws lambda invoke \
	  --function-name "$$(terraform -chdir=terraform output -raw lambda_function_name)" \
	  --invocation-type Event \
	  --cli-binary-format raw-in-base64-out \
	  --payload "$$(python3 -c "from datetime import UTC,datetime; print('{\"job\":\"advisor\",\"scheduled_time\":\"' + datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ') + '\"}')")" \
	  /dev/stdout
	@echo "Invoked asynchronously (StatusCode 202 = accepted). Check results in CloudWatch Logs / Slack."
```

`sources-*` / `migrate` の各ターゲットにも `ADVISORS_TABLE_NAME` / `JUDGMENTS_TABLE_NAME` を足す。`src.config` はモジュール読み込み時に `os.environ[...]` で全テーブル名を要求するため、advisor と無関係なスクリプトでも未設定だと `KeyError` で落ちる。

1 行目の `.PHONY` に `advisors-list advisors-add advisors-delete invoke-advisor` を追加する。

- [ ] **Step 8: CLI の失敗するテストを書く**

`app/tests/test_manage_advisors.py` を新規作成する。既存の `app/tests/test_manage_sources.py` と同じ流儀（`scripts/` を sys.path に足して import）にそろえること。既存ファイルを読んでから書く。

```python
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
            "manage_advisors.py", "add",
            "--advisor-id", "ideco-sbi",
            "--channel-id", "CADVISOR01",
            "--title", "iDeCo 投資判断",
            "--products-json", PRODUCTS,
            "--news-feeds-json", FEEDS,
            "--trading-notes", "スイッチングは1週間から10日",
            "--interval-days", "7",
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
            "manage_advisors.py", "add",
            "--advisor-id", "x", "--channel-id", "C", "--title", "T",
            "--products-json", "not json",
            "--news-feeds-json", FEEDS,
            "--trading-notes", "",
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
            "manage_advisors.py", "add",
            "--advisor-id", "x", "--channel-id", "C", "--title", "T",
            "--products-json", '[{"isin": "JP1", "name": "n", "category": "c"}]',
            "--news-feeds-json", FEEDS,
            "--trading-notes", "",
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
```

- [ ] **Step 9: テストが失敗することを確認する**

Run: `uv run pytest app/tests/test_manage_advisors.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'manage_advisors'`）

- [ ] **Step 10: `scripts/manage_advisors.py` を実装する**

products は 5 フィールド持つため、`url|name` 形式では表現しきれない。JSON 引数で受ける。

```python
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
        print(
            f"# {advisor['advisor_id']}  ({advisor['channel_id']})"
            f"  [{advisor['title']}]  every {advisor['interval_days']}d"
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
    add_advisor(
        advisor_id=args.advisor_id,
        channel_id=args.channel_id,
        title=args.title,
        products=args.products_json,
        news_feeds=args.news_feeds_json,
        trading_notes=args.trading_notes,
        interval_days=args.interval_days,
    )
    print(
        f"Added/updated: {args.advisor_id} -> {args.channel_id}"
        f" ({len(args.products_json)} product(s),"
        f" {len(args.news_feeds_json)} feed(s),"
        f" every {args.interval_days}d)"
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
        help=f"Minimum days between posts (default: {DEFAULT_INTERVAL_DAYS})",
    )
    p_add.set_defaults(func=cmd_add)

    p_del = sub.add_parser("delete", help="Delete an advisor by ID")
    p_del.add_argument("--advisor-id", required=True, help="Advisor ID to delete")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 11: テストが通ることを確認する**

Run: `uv run pytest app/tests/test_manage_advisors.py -v`
Expected: PASS（6 件）

- [ ] **Step 12: ドキュメントを更新する**

`CLAUDE.md` の "What this is" を、digest と advisor の 2 系統がある旨に書き換える。`Commands` に advisor 系ターゲットを足し、`Architecture` に advisor の実行フロー（Slack 履歴による冪等性判定 → 基準価額取得 → `run_advice` → 親 + 商品ごとの返信 → 判断保存）を digest と同じ粒度で追記する。`Deploy の依存関係` の must_env 一覧に `ADVISORS_TABLE_NAME` / `JUDGMENTS_TABLE_NAME` を足す。

`README.md` にも advisor の概要・登録方法（`make advisors-add`）・必要な Slack スコープ（`channels:history` とチャンネル参加）を追記する。**digest と advisor は別チャンネルに分けること**を運用上の前提として明記する（ADR の Consequences 参照。同一チャンネルだと digest の `slack_last_bot_post` が advisor の投稿を拾って期間計算が狂う）。

`docs/adr/0001-ideco-investment-advisor.md` の Status を `Proposed` から `Accepted` に変更する。

- [ ] **Step 13: 全テストと lint**

Run: `uv run pytest && uv run ruff check app/ && uv run ruff format app/ && uv run mypy app/src/ && make lint-tf`
Expected: すべて PASS

- [ ] **Step 14: コミット（テーマごとに分ける）**

```bash
git add terraform/ app/function.jsonnet
git commit -m "feat: provision advisor tables, schedule and Lambda env"

git add Makefile scripts/manage_advisors.py app/tests/test_manage_advisors.py
git commit -m "feat: add make targets and CLI for managing advisors"

git add CLAUDE.md README.md docs/adr/0001-ideco-investment-advisor.md
git commit -m "docs: document the advisor job and accept ADR 0001"
```

- [ ] **Step 15: デプロイ前の確認事項を人間に渡す**

デプロイは自動で行わない。次を利用者に伝えて判断を仰ぐ。

1. `make deploy-infra-dry` の差分（新規テーブル 2 つ、IAM ポリシー差し替え、スケジュール 1 つ）
2. terraform apply 後に `make deploy-app`（先に apply していないと must_env で落ちる）
3. `make advisors-add` で `ideco-sbi` を登録（`TRADING_NOTES` は ADR の「スイッチングは指示から完了まで概ね1週間から10日、掛金の配分変更は翌月拠出分から反映」を入れる）
4. Slack App に `channels:history` スコープがあり、bot が対象チャンネルに参加していること
5. `make invoke-advisor` で手動実行し、CloudWatch Logs と Slack を確認

---

## Self-Review Notes

ADR の要件と各タスクの対応:

| ADR の要件 | 実装タスク |
|---|---|
| 保有商品 + カテゴリ代表候補の登録制 | Task 2（`Product.holding` / `category`）, Task 8（CLI） |
| 基準価額（定量）による判断 | Task 3（`nav.py`）, Task 4（`summarize_nav`） |
| 市況ニュース・マクロ（定性） | Task 5（`news_feeds` をプロンプトへ、rss_fetch / web_scrape 登録） |
| USD/JPY の現在値と変動見通し | Task 5（system prompt の為替節 + `api_fetch` 登録） |
| 判断履歴の保存と前回からの変化 | Task 2（`put_judgments`）, Task 7（返信の「前回 → 今回」） |
| 過去推奨の成績検証 | Task 4（`build_performance`）, Task 7（親メッセージの成績サマリ） |
| 3値をハッキリ表示 | Task 5（`Literal["BUY","SELL","HOLD"]`）, Task 4（`JUDGMENT_LABELS`） |
| 週1基本・1日単位まで短縮可 | Task 2（`interval_days`）, Task 6（`should_post`） |
| 同日冪等性（Slack read で判定） | Task 6（`find_last_post_time` + `should_post`）, Task 7 |
| iDeCo の売買日数をプロンプトへ | Task 2（`trading_notes`）, Task 5（system prompt へ注入） |
| 投稿先 ch id を DynamoDB 管理 | Task 2（`advisors.channel_id`） |
| JST 17:00 起動 | Task 8（`cron(0 17 * * ? *)` / Asia/Tokyo） |
| 別アドバイザーの追加が容易 | Task 2（PK は `advisor_id`、テーブル追加不要） |
| ニュースソース追加が容易 | Task 2（`news_feeds` 属性、デプロイ不要） |
