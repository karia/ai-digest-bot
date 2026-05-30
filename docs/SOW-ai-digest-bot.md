# AWS Blog Digest Bot - プロジェクト生成指示

以下の仕様でプロジェクトの雛形を一式生成してください。

## プロジェクト概要

AWS Blogなどの技術ブログフィードを日次で取得し、Bedrock上のLLMエージェントが自律的にソースの取得・要約を行い、Slack Appで社内チャンネルに日本語ダイジェストを1日1投稿するLambda botです。

## アーキテクチャ

```
EventBridge Schedule (cron: 毎日 JST 8:00)
  │
  ▼
Lambda (Python 3.12 / uv)
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

## 技術スタック

- **言語**: Python 3.12
- **パッケージ管理**: uv (pyproject.toml + uv.lock)
- **ツールバージョン管理**: mise (.mise.toml)
- **エージェント**: Strands Agents SDK (strands-agents, strands-agents-tools)
- **LLM**: Amazon Bedrock (Claude Sonnet)
- **IaC**: Terraform (インフラのみ)
- **Lambdaデプロイ**: lambroll (コードのみ、高頻度デプロイ用)
- **テスト**: pytest + moto + responses
- **静的検査**: ruff (lint + format), mypy (型チェック), tflint, trivy
- **Git hooks**: pre-commit
- **CI**: GitHub Actions

## ディレクトリ構成

以下の構成で厳密に生成すること:

```
aws-blog-digest/
├── .github/
│   └── workflows/
│       └── ci.yml            # push/PR時の静的検査・テスト
├── terraform/
│   ├── main.tf              # provider, backend設定
│   ├── variables.tf          # 変数定義
│   ├── outputs.tf            # 出力値
│   ├── lambda.tf             # Lambda関数の箱, IAM Role, 必要なポリシー
│   ├── dynamodb.tf           # feeds テーブル
│   ├── eventbridge.tf        # スケジュールルール (JST 8:00)
│   ├── ssm.tf               # Slack Bot Token用 SecureStringパラメータ
│   └── .tflint.hcl           # tflint設定
├── app/
│   ├── function.jsonnet      # lambroll定義ファイル
│   ├── src/
│   │   ├── __init__.py
│   │   ├── handler.py        # Lambdaエントリポイント
│   │   ├── agent.py          # Strands Agent定義 (プロンプト, ツール登録)
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── rss_fetch.py      # RSSフィード取得・パース (feedparser)
│   │   │   ├── web_scrape.py     # Webページ取得 (requests + BeautifulSoup)
│   │   │   └── api_fetch.py      # 汎用API呼び出し
│   │   ├── slack_notifier.py # Slack API投稿 (chat.postMessage)
│   │   ├── store.py          # DynamoDB操作 (feeds読み取り)
│   │   └── config.py         # 環境変数・SSMパラメータ読み込み
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py       # 共通fixture (moto, mock, サンプルRSS等)
│       ├── test_rss_fetch.py
│       ├── test_web_scrape.py
│       ├── test_agent.py
│       ├── test_slack_notifier.py
│       ├── test_store.py
│       └── test_handler.py   # 結合テスト
├── scripts/
│   └── seed_feeds.py         # feedsテーブル初期データ投入スクリプト
├── pyproject.toml
├── uv.lock                   # (uv syncで生成されるので空ファイルでよい)
├── .mise.toml
├── .pre-commit-config.yaml
├── Makefile
├── .gitignore
└── README.md
```

## DynamoDB テーブル設計

### feeds テーブル

- テーブル名: `aws-blog-digest-feeds`
- パーティションキー: `feed_url` (S)
- 属性:
  - `name` (S): フィードの表示名 (例: "AWS News Blog")
  - `category` (S): 任意の分類タグ (例: "aws", "security")
  - `channel_id` (S): Slack投稿先チャンネルID
  - `inserted_at` (S): レコード作成日時 (ISO 8601)
  - `updated_at` (S): 最終更新日時 (ISO 8601)
- enabledフラグは持たない。購読停止 = レコードの物理削除。
- source_type等のヒント列は不要。エージェントがURLから自律判断する。
- TTLは不要。

## Strands Agent の設計

### agent.py

- `strands.Agent` を使ってエージェントを定義する
- モデルは Bedrock の Claude Sonnet を使用
- 以下のカスタムツールを `@tool` デコレータで定義して登録:
  - `rss_fetch(url: str) -> str`: feedparserでRSSを取得し、過去24時間以内の記事のタイトル・URL・descriptionを返す
  - `web_scrape(url: str) -> str`: requestsでページを取得し、BeautifulSoupでメインコンテンツを抽出して返す
  - `api_fetch(url: str, headers: dict | None) -> str`: 汎用HTTPリクエストでJSONレスポンスを返す
- エージェントのシステムプロンプトには以下を含める:
  - 「与えられたURLリストから記事を取得し、日本語でダイジェストを1本にまとめること」
  - 「URLの形式やレスポンスの内容から適切な取得方法を自律的に選択すること」
  - 「各記事はタイトル・要約(2-3文)・リンクの形式でまとめること」

### ツール定義

各ツールは `app/src/tools/` 配下に個別ファイルで実装する。Strands の `@tool` デコレータを使い、docstringでツールの説明を記述する。

## handler.py の処理フロー

```python
def lambda_handler(event, context):
    # 1. DynamoDBからフィード一覧を全件取得 (enabledフラグなし、存在するレコード=有効)
    # 2. channel_idごとにフィードをグルーピング
    # 3. 各グループに対してStrands Agentを実行
    #    - フィードURL一覧をエージェントに渡す
    #    - エージェントが自律的に取得・要約
    # 4. 要約結果をSlack chat.postMessageで各チャンネルに投稿
```

## config.py

- 環境変数から以下を読み込む:
  - `FEEDS_TABLE_NAME`: DynamoDBテーブル名
  - `SLACK_BOT_TOKEN_PARAM`: SSMパラメータ名
  - `BEDROCK_MODEL_ID`: Bedrockモデル名 (デフォルト: `anthropic.claude-sonnet-4-20250514`)
  - `AWS_REGION`: リージョン
- SSMからSlack Bot Tokenを取得し、モジュールレベルでキャッシュ (コールドスタート最適化)

## Slack投稿

- `slack_sdk` は使わず `requests` で直接 `https://slack.com/api/chat.postMessage` を叩く (依存を減らすため)
- Block Kit形式でリッチなフォーマットにする
- ヘッダーに日付、各記事はセクションブロックでタイトル・要約・リンク

## Terraform

### lambda.tf

- `aws_lambda_function` に `lifecycle { ignore_changes = [filename, source_code_hash, layers] }` を付けること
- 初回はダミーzipで関数を作成する想定
- IAM Roleには以下のポリシーをアタッチ:
  - DynamoDB feeds テーブルへの読み取り (dynamodb:Scan, dynamodb:GetItem)
  - SSM Parameter Storeの読み取り (ssm:GetParameter) + KMS復号
  - Bedrock InvokeModel
  - CloudWatch Logs書き込み
- タイムアウトは300秒、メモリは512MB

### eventbridge.tf

- `aws_scheduler_schedule` を使用
- cron式: `cron(0 23 * * ? *)` (UTC 23:00 = JST 8:00)
- ターゲットはLambda関数

### ssm.tf

- `aws_ssm_parameter` でタイプ `SecureString` のパラメータの箱だけ作成
- 値は `"PLACEHOLDER"` で作成し、実際の値はマネコンか `aws ssm put-parameter` で手動投入
- tfstateに秘密情報を残さない設計

### dynamodb.tf

- billing_mode: PAY_PER_REQUEST
- TTLは不要

### .tflint.hcl

- AWS pluginを有効化
- 推奨ルールを有効にする

## lambroll

### function.jsonnet

- Terraformが作成したLambda関数名・ロールARNを参照
- 環境変数にテーブル名・SSMパラメータ名・モデルIDを設定
- ランタイム: python3.12
- ハンドラ: src.handler.lambda_handler

## .mise.toml

```toml
[tools]
python = "3.12"
terraform = "1.9"
tflint = "latest"
"ubi:fujiwara/lambroll" = "v1"
"aqua:aws/aws-cli" = "2"

[env]
AWS_REGION = "ap-northeast-1"
```

## pyproject.toml

```toml
[project]
name = "aws-blog-digest"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "strands-agents",
    "strands-agents-tools",
    "feedparser",
    "beautifulsoup4",
    "requests",
    "boto3",
]

[dependency-groups]
dev = [
    "pytest",
    "moto[dynamodb,ssm]",
    "responses",
    "ruff",
    "mypy",
    "boto3-stubs[dynamodb,ssm,bedrock-runtime]",
    "pre-commit",
]

[tool.pytest.ini_options]
testpaths = ["app/tests"]

[tool.ruff]
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

## .pre-commit-config.yaml

コミット時にローカルで静的検査を実行する。以下のフックを定義:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0  # 適切な最新バージョンを使用
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0  # 適切な最新バージョンを使用
    hooks:
      - id: mypy
        additional_dependencies:
          - boto3-stubs[dynamodb,ssm,bedrock-runtime]
        files: ^app/src/

  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.96.0  # 適切な最新バージョンを使用
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
        args: ['--hook-config=--retry-once-with-cleanup=true']
      - id: terraform_tflint
        args: ['--args=--config=__GIT_WORKING_DIR__/terraform/.tflint.hcl']
```

## GitHub Actions (.github/workflows/ci.yml)

push および pull_request をトリガーに、2つのジョブを並列実行する:

### lint-app ジョブ

```yaml
jobs:
  lint-app:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - name: Ruff check
        run: uv run ruff check app/
      - name: Ruff format check
        run: uv run ruff format --check app/
      - name: Mypy
        run: uv run mypy app/src/
      - name: Pytest
        run: uv run pytest
```

### lint-terraform ジョブ

```yaml
  lint-terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform fmt
        run: terraform -chdir=terraform fmt -check -recursive
      - name: Terraform init
        run: terraform -chdir=terraform init -backend=false
      - name: Terraform validate
        run: terraform -chdir=terraform validate
      - uses: terraform-linters/setup-tflint@v4
      - name: TFLint init
        run: cd terraform && tflint --init --config=.tflint.hcl
      - name: TFLint
        run: cd terraform && tflint --config=.tflint.hcl
      - name: Trivy config scan
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: config
          scan-ref: terraform/
          exit-code: 1
```

## Makefile

```makefile
.PHONY: setup test lint lint-app lint-tf build deploy-infra deploy-app deploy seed

setup:
	mise install
	uv sync
	uv run pre-commit install

test:
	uv run pytest

lint: lint-app lint-tf

lint-app:
	uv run ruff check app/
	uv run ruff format --check app/
	uv run mypy app/src/

lint-tf:
	cd terraform && terraform fmt -check -recursive
	cd terraform && terraform validate
	cd terraform && tflint --config=.tflint.hcl

build:
	uv export --no-dev --no-hashes -o requirements.txt
	rm -rf .build
	pip install -r requirements.txt -t .build/ --quiet
	cp -r app/src/* .build/
	cd .build && zip -r ../function.zip .

deploy-infra:
	cd terraform && terraform init && terraform apply

deploy-app: build
	cd app && lambroll deploy --function function.jsonnet

deploy: deploy-infra deploy-app

seed:
	uv run python scripts/seed_feeds.py
```

## seed_feeds.py

初期データとして以下のフィードを投入。inserted_at, updated_atにはスクリプト実行時のISO 8601タイムスタンプを設定する:

```python
INITIAL_FEEDS = [
    {
        "feed_url": "https://aws.amazon.com/blogs/aws/feed/",
        "name": "AWS News Blog",
        "category": "aws",
        "channel_id": "CXXXXXXXXXX",  # 要設定
    },
]
```

## テスト方針

- **conftest.py**: motoでDynamoDBとSSMのモック環境を構築するfixtureを定義。サンプルRSS XMLのfixture。DynamoDBのfixture はinserted_at, updated_atも含めてレコードを投入する。
- **test_rss_fetch.py**: responsesでHTTPをモックし、feedparserが正しくパースすることを検証。過去24時間フィルタのテスト。
- **test_web_scrape.py**: responsesでHTMLレスポンスをモックし、BeautifulSoupで本文抽出を検証。
- **test_store.py**: motoでDynamoDBをモックし、フィード全件取得、channel_idグルーピングを検証。
- **test_slack_notifier.py**: responsesでSlack APIをモックし、Block Kit形式の投稿を検証。
- **test_agent.py**: Strands Agentのツール呼び出しをモックし、エージェントの動作を検証。
- **test_handler.py**: 全モジュールのモックを組み合わせた結合テスト。

## .gitignore

```
__pycache__/
*.pyc
.build/
function.zip
.terraform/
*.tfstate*
.terraform.lock.hcl
*.egg-info/
dist/
.venv/
.ruff_cache/
.mypy_cache/
requirements.txt
```

## README.md

以下の構成で記述:
- プロジェクト概要 (1段落)
- アーキテクチャ図 (上記のASCII図)
- セットアップ手順 (mise install, uv sync, uv run pre-commit install)
- Slack App作成手順 (Bot Token Scopes: chat:write)
- デプロイ手順 (make deploy-infra → SSMにトークン設定 → make seed → make deploy-app)
- 静的検査 (make lint)
- ローカルテスト (make test)
- フィード追加方法 (DynamoDBに直接レコード追加、inserted_at/updated_atを設定)
- フィード削除方法 (DynamoDBからレコードを物理削除)

## 注意事項

- すべてのファイルを実際に生成すること。説明だけで終わらせない。
- Strands Agents SDKの `@tool` デコレータの使い方は公式ドキュメントを参照して正しい形式で実装すること。
- Lambda内でのBedrock呼び出しはStrands経由で行い、boto3で直接InvokeModelは呼ばない。
- 型ヒントを積極的に使用すること。
- エラーハンドリングを適切に入れること (フィード取得失敗時にbot全体が止まらないように)。
- pre-commit-config.yamlの各revは最新の安定バージョンを確認して設定すること。
- GitHub Actionsのci.ymlではpathsフィルタは付けず、全push/PRで実行すること。
