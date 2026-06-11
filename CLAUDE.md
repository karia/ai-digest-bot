# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

技術ブログフィードを日次で取得し、Bedrock 上の Strands Agent が自律的に取得・要約して Slack に日本語ダイジェストを投稿する Lambda Bot。EventBridge（毎日 JST 9:00）→ Lambda が起点。投稿は **ソース単位で 1 スレッド**（ヘッドライン親メッセージ + URL ごとのスレッド返信）。

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
make sources-list / sources-add TITLE=.. CHANNEL_ID=.. ITEMS="url|name[|daily] .." [POSTING_SCHEDULE=..] / sources-delete TITLE=..
make migrate               # 旧 feeds テーブル → sources テーブルのデータ移行（冪等。移行済みなら no-op）
```

ツールチェーン（Python 3.14, terraform, tflint, lambroll, aws-cli, pinact）は `mise` 管理。Python 依存は `uv`。`make *-dry` で apply/deploy の差分確認ができる。

## Architecture

実行フロー（`app/src/handler.py:lambda_handler`）:

1. SSM Parameter Store から Slack Bot Token を取得（`config.get_slack_token`、モジュールキャッシュあり）
2. DynamoDB `sources` テーブルを全件 scan（`store.get_all_sources`）。`title` を主キーとし、各アイテムは `channel_id`、`items`（`{url, name}` の配列）、`posting_schedule`（自由テキスト。フィールド未設定は「毎日」扱い）を持つ。1 アイテム = 1 スレッド
3. **ソース単位**でループ。まず `agent.run_plan(channel, posting_schedule, until)` が投稿可否と期間起点を決定: posting_schedule を解釈して本日が対象外なら skip、対象なら `slack_last_bot_post` ツールで bot の前回投稿時刻（最大2週間遡る）を取得して `since` に（見つからなければ `until - 24h`）。`run_plan` 自体の失敗時も `until - 24h` で続行
4. `items` 全件について本文テキストを生成（この時点では投稿しない）。通常itemは `agent.run_digest(url, since, until)` で1本文、`split_by_day: true` のitem（What's New等の多件数フィード）は `agent.run_daily_digests` が**JST日付ごと**の本文リストを構造化出力で返し、1日=1返信になる（記事の無い日は出力されず、期間内ゼロ件なら返信なし）
5. 全本文から `agent.run_headline([(name, body), ...], since, until)` でヘッドライン文を生成（冒頭に対象期間をJSTで明記、注目記事1〜2件に言及、リンクなし。失敗時は空文字にフォールバック）し、`slack_notifier.post_message(channel, text=headline, header=title)` で親メッセージを投稿して `ts` を取得。**対象期間はヘッドラインのみに表示**し、header に日付は入れない・スレッド返信本文にも期間を書かない（run_digest の system prompt で禁止）
6. 生成済みダイジェストを順に `slack_notifier.post_message(channel, text=body, header=name, thread_ts=ts)` でスレッド返信（1 URL = 1 返信、新着なしも返信）。1 件失敗しても続行し、結果は `url`（ヘッドライン投稿失敗時は `title`）ごとに記録する

**投稿は Python（handler）がオーケストレーションし、Agent は本文テキストを返すだけ**。Agent は Slack へ投稿しない（`slack_post` ツールは廃止）。

**Agent の自律ツール選択がこの設計の核心**（`app/src/agent.py`）。`run_digest` は 1 URL と期間を渡すだけで、Strands Agent が system prompt の指示に従い、URL の形式やレスポンスを見て 3 ツールのどれを使うか自分で決める:

- `tools/rss_fetch.py` — RSS/Atom（feedparser）。`since`/`until` で期間フィルタする唯一のツール
- `tools/web_scrape.py` — RSS 非対応サイトの HTML 抽出（BeautifulSoup）
- `tools/api_fetch.py` — JSON API。期間引数を持たず全文を 5000 字で切る（時刻フィールドを持つ API でないと期間外が混ざりうる）

`run_plan` 専用のツール（`run_digest` には登録しない）:

- `tools/slack_history.py` — `slack_last_bot_post(channel, lookback_days=14)`。`conversations.history` で bot の前回投稿（＝前回ヘッドライン。スレッド返信は対象外）の時刻を返す。要 `channels:history` スコープ + チャンネル参加

ツールを追加・変更したら `agent.py` の `tools=[...]` と対応する system prompt も合わせて更新する。

## ログ

`handler` 冒頭で `logging_config.configure_logging()` を呼び、環境変数 `LOG_LEVEL`（既定 `INFO`）からルートロガーのレベルを設定する（`botocore` 等は `WARNING` 固定）。**Bedrock への入力・出力は `agent.py` で INFO ログ**として出すため、DEBUG にしなくても追える。`LOG_LEVEL=DEBUG make deploy-app` で一時的に DEBUG 化できる。

## Deploy の依存関係（重要）

`lambroll deploy` は `app/function.jsonnet` を読み、`LAMBDA_FUNCTION_NAME` / `LAMBDA_ROLE_ARN` / `SOURCES_TABLE_NAME` / `SLACK_BOT_TOKEN_PARAM` を `must_env` で要求する。これらは Makefile が `terraform output` から注入する。よって **terraform apply 済みでないと deploy-app は失敗する**。

Lambda zip は `make build` が生成（`uv pip install -r requirements.txt --target .build/` + `app/src` をコピー）。Lambda は arm64 のため `--python-platform aarch64-manylinux2014 --only-binary :all:` でクロスインストールする（ローカルの OS/arch の wheel が混入すると `Runtime.ImportModuleError` になる。sdist のみの pure Python パッケージ `sgmllib3k` だけ `--no-binary` で例外）。zip に含めない/含めるファイルは `app/.lambdaignore` で制御する（フラットなワイルドカードのみ、`!` や `**` は不可）。`*.dist-info` は opentelemetry の entry_points が実行時に必要なため除外不可。boto3/botocore は Lambda ランタイム同梱なので除外可。

## Tests

`app/tests/conftest.py` が moto (`mock_aws`) で DynamoDB / SSM をモックし、実 AWS には触れない。`env_vars` fixture が autouse で環境変数をセットする。HTTP は `responses` でモック。Bedrock を呼ぶ `run_digest` 本体は統合テストせず、ツール単体と handler のフロー（agent はモック）を検証する方針。
