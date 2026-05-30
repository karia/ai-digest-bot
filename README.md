# AWS Blog Digest Bot

AWS Blog などの技術ブログフィードを日次で取得し、Bedrock 上の LLM エージェントが自律的にソースの取得・要約を行い、Slack チャンネルに日本語ダイジェストを 1 日 1 投稿する Lambda Bot です。

## アーキテクチャ

```
EventBridge Schedule (cron: 毎日 JST 8:00)
  │
  ▼
Lambda (Python 3.14 / uv)
  ├─ DynamoDB: feeds テーブル → 購読URL一覧を取得
  ├─ Strands Agents SDK でエージェントを起動
  │   エージェントは以下のツールを自律的に選択して記事を取得:
  │   ├─ rss_fetch: RSSフィードの取得・パース
  │   ├─ web_scrape: RSS非対応ソースのWebページ取得
  │   └─ api_fetch: API経由の取得
  ├─ 取得した記事のうち過去24時間以内のものを抽出
  ├─ エージェントが日本語ダイジェスト1本にまとめて要約
  └─ Slack API (chat.postMessage) で投稿
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
   - `chat:write`: メッセージ投稿
   - `chat:write.public`: チャンネル未参加でも投稿する場合（任意）
3. **Install App to Workspace** でワークスペースにインストール
4. **Bot User OAuth Token**（`xoxb-...`）をコピーし、SSM Parameter Store に登録:

```bash
aws ssm put-parameter \
  --name "/aws-blog-digest/slack-bot-token" \
  --value "xoxb-..." \
  --type SecureString \
  --overwrite
```

## デプロイ

```bash
# 1. インフラ構築
make deploy-infra

# 2. Slack Bot Token を SSM に登録（上記手順参照）

# 3. 初期フィードデータを DynamoDB に投入
make seed

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

## フィード追加方法

DynamoDB の `aws-blog-digest-feeds` テーブルにレコードを追加します:

```bash
aws dynamodb put-item \
  --table-name aws-blog-digest-feeds \
  --item '{
    "feed_url": {"S": "https://example.com/feed/"},
    "name": {"S": "Example Blog"},
    "category": {"S": "aws"},
    "channel_id": {"S": "CXXXXXXXXXX"},
    "inserted_at": {"S": "2026-01-01T00:00:00+00:00"},
    "updated_at": {"S": "2026-01-01T00:00:00+00:00"}
  }'
```

## フィード削除方法

DynamoDB からレコードを物理削除します:

```bash
aws dynamodb delete-item \
  --table-name aws-blog-digest-feeds \
  --key '{"feed_url": {"S": "https://example.com/feed/"}}'
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
