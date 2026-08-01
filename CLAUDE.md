# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bedrock 上の Strands Agent を使って Slack に日本語で情報配信する Lambda Bot。1 つの Lambda に **digest** と **advisor** の 2 系統のジョブがあり、EventBridge の `job` フィールド（`app/src/handler.py:lambda_handler`）で分岐する。

- **digest**: 技術ブログフィードを日次で取得し、自律的に要約してダイジェストを投稿する。EventBridge（毎日 JST 9:00、`job` なし）→ Lambda が起点。投稿は **ソース単位で 1 スレッド**（ヘッドライン親メッセージ + URL ごとのスレッド返信）
- **advisor**: iDeCo 等の保有商品について基準価額と市況ニュースから BUY/SELL/HOLD を判断し、投資判断情報を投稿する。EventBridge（毎日 JST 17:00、`job: "advisor"`）→ Lambda が起点。投稿は **アドバイザー単位で 1 スレッド**（市況サマリ + 成績サマリの親メッセージ + 商品ごとのスレッド返信）

## Commands

```bash
make test                  # uv run pytest (全テスト)
uv run pytest app/tests/test_agent.py::test_name   # 単一テスト
make lint                  # lint-app (ruff check / ruff format --check / mypy strict) + lint-tf (terraform fmt/validate, tflint)
make build                 # requirements.txt を export → .build/ に依存+src を展開（Lambda zip の中身）
make deploy-infra          # terraform apply（先に実行する必要がある。lambroll が terraform output を参照するため）
make deploy-app            # build → lambroll deploy
make deploy                # deploy-infra + deploy-app
make invoke                # 現在時刻を scheduled_time として本番 Lambda を手動 invoke（digest ジョブ）
make sources-list / sources-add TITLE=.. CHANNEL_ID=.. ITEMS="url|name[|daily]; .." [POSTING_SCHEDULE=..] / sources-delete TITLE=..
make migrate               # 旧 feeds テーブル → sources テーブルのデータ移行（冪等。移行済みなら no-op）
make advisors-list / advisors-add ADVISOR_ID=.. CHANNEL_ID=.. TITLE=.. PRODUCTS=.. NEWS_FEEDS=.. TRADING_NOTES=.. [INTERVAL_DAYS=..] / advisors-delete ADVISOR_ID=..
make invoke-advisor         # 現在時刻を scheduled_time として本番 Lambda を手動 invoke（advisor ジョブ）
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

advisor の実行フロー（`app/src/advisor.py:run_advisor_job`）:

1. DynamoDB `advisors` テーブルを全件 scan（`advisor_store.get_all_advisors`）。主キーは `advisor_id`、各アイテムは `channel_id`、`title`（ヘッドライン兼投稿識別子）、`interval_days`、`products`（`{isin, name, category, holding, assoc_fund_cd}` の配列）、`news_feeds`（`{url, name}` の配列）、`trading_notes` を持つ。1 アイテム = 1 スレッド
2. アドバイザーごとにループ（`_process_advisor`）。まず `slack_reader.find_last_post_time(channel, title)` で **`title` をヘッダーに持つ** bot の前回投稿時刻を検索（最大30日遡る）。digest の `slack_last_bot_post` と違い header でフィルタするため、同一チャンネルに digest や他アドバイザーの投稿があっても混同しない。読み取り自体が失敗した場合は「未投稿」とみなさず処理を中断する（誤って重複投稿するより安全側に倒す）
3. `slack_reader.should_post(last_post, now, interval_days)` で投稿可否を判定: 前回投稿が同日（JST）、または前回投稿から `interval_days` 日未満なら skip。これにより同日複数回実行しても投稿は1回で、間隔短縮は `interval_days` の変更のみで済む
4. 投稿対象なら `products` ごとに `nav.fetch_nav_series(isin, assoc_fund_cd)` で投信協会 CSV から基準価額の時系列を取得し（失敗した商品は summary なしで続行）、`performance.summarize_nav` で直近の推移テキストを作る
5. `advisor_store.get_judgment_history(advisor_id)` で過去の判断履歴（最大8件）を取得し、`performance.build_performance` で前回判断時点の基準価額に対する現在の騰落率を計算、`format_performance_summary` で成績サマリ文にする。`latest_judgment_by_isin` で商品ごとの前回判断も取り出す
6. 商品一覧・基準価額サマリ・前回判断・成績サマリをまとめたコンテキストを `agent.run_advice(context, trading_notes, news_feeds, now)` に渡す。Agent は `nav_fetch` / `rss_fetch` / `web_scrape` / `api_fetch` を自律選択して市況ニュースと USD/JPY 為替を調査し、商品ごとの `{isin, judgment(BUY/SELL/HOLD), reason}` と市況サマリを構造化出力で返す
7. `slack_notifier.post_message(channel, text=市況サマリ+成績サマリ+免責, header=title)` で親メッセージを投稿して `thread_ts` を取得。商品ごとに `performance.JUDGMENT_LABELS` のラベルと「前回 → 今回」の変化を添えてスレッド返信（1 件失敗しても他の商品の返信は続行）
8. 今回の判断を `advisor_store.put_judgments(advisor_id, run_date, judgments)` に保存する（`run_date` は JST 日付。同日に再実行すると上書き）

digest と同様、**投稿は Python（`advisor.py`）がオーケストレーションし、`agent.run_advice` は判断と市況サマリを返すだけ**で Slack へは投稿しない。

## ログ

`handler` 冒頭で `logging_config.configure_logging()` を呼び、環境変数 `LOG_LEVEL`（既定 `INFO`）からルートロガーのレベルを設定する（`botocore` 等は `WARNING` 固定）。**Bedrock への入力・出力は `agent.py` で INFO ログ**として出すため、DEBUG にしなくても追える。`LOG_LEVEL=DEBUG make deploy-app` で一時的に DEBUG 化できる。

## Deploy の依存関係（重要）

`lambroll deploy` は `app/function.jsonnet` を読み、`LAMBDA_FUNCTION_NAME` / `LAMBDA_ROLE_ARN` / `SOURCES_TABLE_NAME` / `ADVISORS_TABLE_NAME` / `JUDGMENTS_TABLE_NAME` / `SLACK_BOT_TOKEN_PARAM` を `must_env` で要求する。これらは Makefile が `terraform output` から注入する。よって **terraform apply 済みでないと deploy-app は失敗する**。

Lambda zip は `make build` が生成（`uv pip install -r requirements.txt --target .build/` + `app/src` をコピー）。Lambda は arm64 のため `--python-platform aarch64-manylinux2014 --only-binary :all:` でクロスインストールする（ローカルの OS/arch の wheel が混入すると `Runtime.ImportModuleError` になる。sdist のみの pure Python パッケージ `sgmllib3k` だけ `--no-binary` で例外）。zip に含めない/含めるファイルは `app/.lambdaignore` で制御する（フラットなワイルドカードのみ、`!` や `**` は不可）。`*.dist-info` は opentelemetry の entry_points が実行時に必要なため除外不可。boto3/botocore は Lambda ランタイム同梱なので除外可。

## Tests

`app/tests/conftest.py` が moto (`mock_aws`) で DynamoDB / SSM をモックし、実 AWS には触れない。`env_vars` fixture が autouse で環境変数をセットする。HTTP は `responses` でモック。Bedrock を呼ぶ `run_digest` 本体は統合テストせず、ツール単体と handler のフロー（agent はモック）を検証する方針。
