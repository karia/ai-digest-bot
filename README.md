# AWS Blog Digest Bot

AWS Blog などの技術ブログフィードを日次で取得し、Bedrock 上の LLM エージェントが自律的に取得・要約を行い、Slack チャンネルへ日本語ダイジェストを投稿する Lambda Bot です。投稿は **ソース単位で 1 スレッド**にまとまり、ヘッドラインを親メッセージ、URL ごとの要約をスレッド返信として届けます。

## アーキテクチャ

```
EventBridge Schedule (cron: 毎日 JST 9:00)
  │
  ▼
Lambda (Python 3.14 / uv)
  ├─ DynamoDB: sources テーブル → 購読ソース一覧を取得
  │   （1 ソース = title + channel_id + items[{url, name}]）
  └─ ソースごとに以下を実行（1 ソース = 1 スレッド）:
      ├─ ヘッドライン（title + 日付）のみのメッセージを投稿し ts を取得
      └─ items の URL ごとに:
          ├─ Strands Agents SDK でエージェントを起動
          │   エージェントは以下のツールを自律的に選択して記事を取得:
          │   ├─ rss_fetch: RSSフィードの取得・パース
          │   ├─ web_scrape: RSS非対応ソースのWebページ取得
          │   └─ api_fetch: API経由の取得
          ├─ 過去24時間以内の記事を日本語ダイジェストに要約
          └─ Slack API (chat.postMessage, thread_ts) でスレッド返信
              （見出しは item の name。新着が無い URL も「新着なし」を返信）
```

## セットアップ

```bash
mise install
uv sync
uv run pre-commit install
```

## Slack App の作成

1. https://api.slack.com/apps → **Create New App** → **From scratch**
2. **OAuth & Permissions** → **Bot Token Scopes** に以下を追加:
   - `chat:write`: メッセージ投稿（スレッド返信もこのスコープで可能）
   - `chat:write.public`: チャンネル未参加でも投稿する場合（任意）
3. **Install App to Workspace** でワークスペースにインストール
4. **Bot User OAuth Token**（`xoxb-...`）をコピーし、SSM Parameter Store に登録:

```bash
aws ssm put-parameter \
  --name "/karia-ai-digest-bot/slack-bot-token" \
  --value "xoxb-..." \
  --type SecureString \
  --overwrite
```

## デプロイ

```bash
# 1. インフラ構築
make deploy-infra

# 2. Slack Bot Token を SSM に登録（上記手順参照）

# 3. 配信するソースを DynamoDB に登録（ITEMS は "url|name" を空白区切りで複数指定可）
make sources-add TITLE="技術ブログダイジェスト" CHANNEL_ID="CXXXXXXXXXX" \
  ITEMS="https://aws.amazon.com/blogs/aws/feed/|AWS News Blog"

# 4. Lambda にソースコードをデプロイ
make deploy-app
```

## 静的検査

```bash
make lint
```

## ローカルテスト

```bash
make test
```

## Lambda テスト実行

現在時刻を `scheduled_time` として Lambda を手動 invoke する:

```bash
make invoke
```

特定の日時を指定する場合は `app/events/test_event.json` を編集してから:

```bash
aws lambda invoke \
  --function-name <関数名> \
  --invocation-type Event \
  --cli-binary-format raw-in-base64-out \
  --payload file://app/events/test_event.json \
  /dev/stdout
```

> 非同期（`--invocation-type Event`）で起動します。実行に約1分かかり同期だとCLIの読み取りタイムアウト→リトライで多重起動するため、非同期にしています。結果（ダイジェスト・投稿状況）は標準出力ではなく CloudWatch Logs / Slack で確認してください。
>
> `scheduled_time` を省略した空の `{}` で invoke した場合は、実行時刻を基準にフォールバックします。

## ログ

ログレベルは環境変数 `LOG_LEVEL`（既定 `INFO`）で制御します。`INFO` ではフィード処理状況と Bedrock への入力・出力が出力されます。`DEBUG` にすると各取得ツール（rss_fetch / web_scrape / api_fetch）の詳細も出ます（`botocore` などのライブラリは `WARNING` 固定で抑制）。

デプロイ時に一時的に DEBUG へ切り替える:

```bash
LOG_LEVEL=DEBUG make deploy-app
```

INFO に戻す:

```bash
make deploy-app
```

ログ確認（CloudWatch Logs）:

```bash
aws logs tail "/aws/lambda/$(terraform -chdir=terraform output -raw lambda_function_name)" --since 10m --format short
```

## ソース管理

`sources` テーブルの一覧・追加・削除は Make ターゲットで行います（内部で `scripts/manage_sources.py` を実行）。1 ソースは `title`（スレッドのヘッドライン＝パーティションキー）、`channel_id`、`items`（`{url, name}` の配列）から成り、1 スレッドに対応します。

### 一覧表示

```bash
make sources-list
```

### 追加・更新

```bash
make sources-add TITLE="技術ブログダイジェスト" CHANNEL_ID="CXXXXXXXXXX" \
  ITEMS="https://example.com/feed/|Example Blog https://aws.amazon.com/blogs/aws/feed/|AWS News Blog"
```

`ITEMS` は `url|name` を空白区切りで複数指定します。同じ `TITLE` で再実行すると `items` ごと上書き更新されます（`inserted_at` は保持、`updated_at` のみ更新）。

### 削除

```bash
make sources-delete TITLE="技術ブログダイジェスト"
```

## How to Contribute

### ローカル開発環境のセットアップ

1. **mise のインストール**（未インストールの場合）:

```bash
# macOS
brew install mise

# Linux / その他
curl https://mise.run | sh
```

2. **ツール一式のインストール**（Python 3.14, Terraform, tflint, lambroll, aws-cli, pinact）:

```bash
mise install
```

3. **Python 依存パッケージのインストール**:

```bash
uv sync
```

4. **Git hooks の登録**（pre-commit + pinact による GitHub Actions ハッシュ固定）:

```bash
uv run pre-commit install
```

5. **テストの実行**:

```bash
make test
```

### GitHub Actions のバージョン更新

GitHub Actions のアクション参照はセキュリティのためコミットハッシュで固定されています。最新版に更新するには:

```bash
make update-actions
```
