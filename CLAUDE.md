# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

技術ブログフィードを日次で取得し、Bedrock 上の Strands Agent が自律的に取得・要約して Slack に日本語ダイジェストを投稿する Lambda Bot。EventBridge（毎日 JST 8:00）→ Lambda が起点。

## Commands

```bash
make test                  # uv run pytest (全テスト)
uv run pytest app/tests/test_agent.py::test_name   # 単一テスト
make lint                  # lint-app (ruff check / ruff format --check / mypy strict) + lint-tf (terraform fmt/validate, tflint)
make build                 # requirements.txt を export → .build/ に依存+src を展開（Lambda zip の中身）
make deploy-infra          # terraform apply（先に実行する必要がある。lambroll が terraform output を参照するため）
make deploy-app            # build → lambroll deploy
make deploy                # deploy-infra + deploy-app
make invoke                # 現在時刻を scheduled_time として本番 Lambda を手動 invoke
make feeds-list / feeds-add FEED_URL=.. NAME=.. CHANNEL_ID=.. / feeds-delete FEED_URL=..
```

ツールチェーン（Python 3.14, terraform, tflint, lambroll, aws-cli, pinact）は `mise` 管理。Python 依存は `uv`。`make *-dry` で apply/deploy の差分確認ができる。

## Architecture

実行フロー（`app/src/handler.py:lambda_handler`）:

1. SSM Parameter Store から Slack Bot Token を取得（`config.get_slack_token`、モジュールキャッシュあり）
2. DynamoDB `feeds` テーブルを全件 scan（`store.get_all_feeds`）。テーブルは `feed_url` を主キーとする単一テーブル
3. **フィード単位**でループし、1 フィードごとに `agent.run_digest([feed_url], since, until)` を呼ぶ。`since = scheduled_time - 24h`
4. フィードごとに `slack_notifier.post_digest` で Slack 投稿（title はそのフィードの `name`）。1 フィード = 1 投稿。1 フィードが失敗しても他は続行し、結果は `feed_url` ごとに記録する

**Agent の自律ツール選択がこの設計の核心**（`app/src/agent.py`）。`run_digest` は URL リストと期間を渡すだけで、Strands Agent が system prompt の指示に従い、URL の形式やレスポンスを見て 3 ツールのどれを使うか自分で決める:

- `tools/rss_fetch.py` — RSS/Atom（feedparser）。`since`/`until` で期間フィルタする唯一のツール
- `tools/web_scrape.py` — RSS 非対応サイトの HTML 抽出（BeautifulSoup）
- `tools/api_fetch.py` — JSON API。期間引数を持たず全文を 5000 字で切る（時刻フィールドを持つ API でないと期間外が混ざりうる）

ツールを追加・変更したら `agent.py` の `tools=[...]` と SYSTEM_PROMPT も合わせて更新する。

## ログ

`handler` 冒頭で `logging_config.configure_logging()` を呼び、環境変数 `LOG_LEVEL`（既定 `INFO`）からルートロガーのレベルを設定する（`botocore` 等は `WARNING` 固定）。**Bedrock への入力・出力は `agent.py` で INFO ログ**として出すため、DEBUG にしなくても追える。`LOG_LEVEL=DEBUG make deploy-app` で一時的に DEBUG 化できる。

## Deploy の依存関係（重要）

`lambroll deploy` は `app/function.jsonnet` を読み、`LAMBDA_FUNCTION_NAME` / `LAMBDA_ROLE_ARN` / `FEEDS_TABLE_NAME` / `SLACK_BOT_TOKEN_PARAM` を `must_env` で要求する。これらは Makefile が `terraform output` から注入する。よって **terraform apply 済みでないと deploy-app は失敗する**。

Lambda zip は `make build` が生成（`uv pip install -r requirements.txt --target .build/` + `app/src` をコピー）。zip に含めない/含めるファイルは `app/.lambdaignore` で制御する（フラットなワイルドカードのみ、`!` や `**` は不可）。`*.dist-info` は opentelemetry の entry_points が実行時に必要なため除外不可。boto3/botocore は Lambda ランタイム同梱なので除外可。

## Tests

`app/tests/conftest.py` が moto (`mock_aws`) で DynamoDB / SSM をモックし、実 AWS には触れない。`env_vars` fixture が autouse で環境変数をセットする。HTTP は `responses` でモック。Bedrock を呼ぶ `run_digest` 本体は統合テストせず、ツール単体と handler のフロー（agent はモック）を検証する方針。
