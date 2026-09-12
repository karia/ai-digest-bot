# AWS Blog Digest Bot

AWS Blog などの技術ブログフィードを日次で取得し、Bedrock 上の LLM エージェントが自律的に取得・要約を行い、Slack チャンネルへ日本語ダイジェストを投稿する Lambda Bot です。投稿は **ソース単位で 1 スレッド**にまとまり、ヘッドラインを親メッセージ、URL ごとの要約をスレッド返信として届けます。

同じ Lambda には、iDeCo 等の保有商品について投資判断情報（BUY/SELL/HOLD）を配信する **advisor** ジョブと、AWS アカウントの利用料金を配信する **cost** ジョブも同居しています（詳細は後述の[投資判断アドバイザー（advisor）](#投資判断アドバイザーadvisor)と[コストレポート（cost）](#コストレポートcost)を参照）。

## アーキテクチャ

```
EventBridge Schedule (cron: 毎日 JST 9:00)
  │
  ▼
Lambda (Python 3.14 / uv)
  ├─ DynamoDB: sources テーブル → 購読ソース一覧を取得
  │   （1 ソース = title + channel_id + items[{url, name}] + posting_schedule）
  └─ ソースごとに以下を実行（1 ソース = 1 スレッド）:
      ├─ プランエージェントが投稿可否と対象期間を決定:
      │   ├─ posting_schedule（「毎日」「月曜と木曜」などの自由テキスト）を
      │   │   解釈し、本日が投稿対象日でなければスキップ
      │   └─ slack_last_bot_post ツールでチャンネル内の bot 前回投稿時刻
      │       （最大2週間遡る）を取得して期間の起点に。見つからなければ過去24時間
      ├─ items の URL ごとにダイジェストを生成（投稿はまだしない）:
      │   ├─ Strands Agents SDK でエージェントを起動
      │   │   エージェントは以下のツールを自律的に選択して記事を取得:
      │   │   ├─ rss_fetch: RSSフィードの取得・パース
      │   │   ├─ web_scrape: RSS非対応ソースのWebページ取得
      │   │   └─ api_fetch: API経由の取得
      │   └─ 対象期間内の記事を日本語ダイジェストに要約
      ├─ 全ダイジェスト本文からヘッドライン文を生成（冒頭に対象期間を明記、
      │   注目記事1〜2件に言及、リンクなし）
      ├─ ヘッドライン（title + ヘッドライン文）を投稿し ts を取得
      └─ ダイジェストごとに Slack API (chat.postMessage, thread_ts) でスレッド返信
          （見出しは item の name。新着が無い URL も「新着なし」を返信）
```

## セットアップ

```bash
mise install
uv sync
prek install
```

## Slack App の作成

1. https://api.slack.com/apps → **Create New App** → **From scratch**
2. **OAuth & Permissions** → **Bot Token Scopes** に以下を追加:
   - `chat:write`: メッセージ投稿（スレッド返信もこのスコープで可能）
   - `chat:write.public`: チャンネル未参加でも投稿する場合（任意）
   - `channels:history`: bot の前回投稿時刻の取得（パブリックチャンネルの履歴読み取り）
   - `groups:history`: プライベートチャンネルへ投稿する場合の履歴読み取り（任意）
3. **Install App to Workspace** でワークスペースにインストール

> 履歴の読み取りには bot が対象チャンネルに**参加している**必要があります（`/invite @bot名`）。
> 未参加の場合、前回投稿時刻の取得に失敗し、対象期間は過去24時間にフォールバックします。
> スコープを後から追加した場合はアプリの再インストールが必要で、トークンが変わった場合は SSM パラメータも更新してください。
4. **Bot User OAuth Token**（`xoxb-...`）をコピーし、SSM Parameter Store に登録:

```bash
aws ssm put-parameter \
  --name "/karia-ai-digest-bot/slack-bot-token" \
  --value "xoxb-..." \
  --type SecureString \
  --overwrite
```

## デプロイ

Terraform state は S3 backend（S3 ネイティブロック）で管理します。state 保存先のバケットは事前に用意し（バージョニング有効推奨）、バケット名は git 管理外の `terraform/backend.tfbackend` から注入します。

```bash
# 1. Terraform backend の設定（初回のみ。git 管理外の terraform/backend.tfbackend を生成）
make config TFSTATE_BUCKET=<your-tfstate-bucket>

# 2. インフラ構築
make deploy-infra

# 3. Slack Bot Token を SSM に登録（上記手順参照）

# 4. 配信するソースを DynamoDB に登録（ITEMS は "url|name" を ";" 区切りで複数指定可）
make sources-add TITLE="技術ブログダイジェスト" CHANNEL_ID="CXXXXXXXXXX" \
  ITEMS="https://aws.amazon.com/blogs/aws/feed/|AWS News Blog"

# 5. Lambda にソースコードをデプロイ
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

`sources` テーブルの一覧・追加・削除は Make ターゲットで行います（内部で `scripts/manage_sources.py` を実行）。1 ソースは `title`（スレッドのヘッドライン＝パーティションキー）、`channel_id`、`items`（`{url, name}` の配列）、`posting_schedule`（投稿スケジュール）から成り、1 スレッドに対応します。

### 一覧表示

```bash
make sources-list
```

### 追加・更新

```bash
make sources-add TITLE="技術ブログダイジェスト" CHANNEL_ID="CXXXXXXXXXX" \
  ITEMS="https://example.com/feed/|Example Blog; https://aws.amazon.com/blogs/aws/feed/|AWS News Blog" \
  POSTING_SCHEDULE="月曜と木曜"
```

`ITEMS` は `url|name` を `;` 区切りで複数指定します（`name` に空白を含められます）。同じ `TITLE` で再実行すると `items` ごと上書き更新されます（`inserted_at` は保持、`updated_at` のみ更新）。

`url|name|daily` のように `|daily` を付けたitemは、1返信にまとめる代わりに **JST日付ごとに1スレッド返信**へ分割されます（記事が無かった日は投稿されず、期間内に1件も無ければ返信自体を行いません）。AWS What's New のような発表件数の多いフィード向けです。

> AWS What's New のフィードは直近50件（通常期で約2週間分）しか保持しないため、発表が多い時期（re:Invent 期など）は期間内でも古い発表が欠落することがあります。

`POSTING_SCHEDULE` は「毎日」「月曜と木曜」「平日のみ」のような自由テキストで、投稿可否の判定はエージェントが解釈して行います。省略時は「毎日」です。**上書き更新時に省略すると「毎日」にリセットされる**点に注意してください。

### 削除

```bash
make sources-delete TITLE="技術ブログダイジェスト"
```

## 旧 feeds テーブルからの移行

旧スキーマ（`feeds` テーブル、1 行 = 1 フィード）で運用していた環境は、以下の手順で `sources` テーブルへ移行します。

```bash
# 1. インフラ更新（terraform の removed ブロックにより、旧 feeds テーブルは
#    state から外れるだけで、テーブルとデータはそのまま残る）
make deploy-infra

# 2. データ移行（冪等: sources にデータがあれば何もしない。
#    TITLE でスレッドのヘッドライン名を指定可能。既定は「技術ブログダイジェスト」）
make migrate

# 3. アプリをデプロイして動作確認
make deploy-app
make invoke

# 4. Slack への投稿を確認できたら、旧テーブルを手動で削除
aws dynamodb delete-table --table-name karia-ai-digest-bot-feeds
```

移行ルール: 旧 feeds を `channel_id` ごとに 1 ソースへ集約します（items は登録順）。チャンネルが複数ある場合、タイトルは `<TITLE> (<channel_id>)` になります。

## コストレポート（cost）

AWS アカウントの利用料金を Cost Explorer から取得し、当月累計・当月の着地見込み・前日のサービス別内訳を Slack へ投稿するジョブです。EventBridge（毎日 JST 8:00、`job: "cost"`）→ Lambda が起点。digest（9:00）より前に動かすのは、前日分のコストが Cost Explorer へ反映される時間を夜間に確保するためです。投稿は 1 メッセージで、スレッドは作りません。

サービス別の行には、前日比と前月同日比の増減を並べます。日額が $0.01 未満のサービスは末尾の 1 行にまとめますが、判定は絶対値で行うため、返金やクレジットのようなマイナス計上は畳まれずに単独行として残ります。

```
AWS コスト 2026-09-12

当月累計 $18.84  →  着地見込み $52.00
前日 09/11 $1.33 (前々日比 -$0.24 / 前月同日比 +$0.35)

Amazon Simple Storage Service     $0.82  前日  +$0.03  前月同日  +$0.07
Claude Sonnet 5 (Amazon Bedro…    $0.31  前日  -$0.28  前月同日  +$0.31
AWS Lambda                        $0.12  前日      ±0  前月同日  +$0.02
Amazon DynamoDB                   $0.07  前日  +$0.01  前月同日  -$0.05
他 6 サービス $0.01
```

### 投稿先チャンネル

チャンネル ID は SSM Parameter Store（`/<project_name>/cost-channel-id`）から読みます。terraform が作るのはプレースホルダだけなので、値は手動で入れてください。public リポジトリにチャンネル ID を残さないため、コードや terraform の変数には書きません。

```bash
aws ssm put-parameter --name /karia-ai-digest-bot/cost-channel-id \
  --value CXXXXXXXXXX --type String --overwrite
```

### Cost Explorer の課金と精度

Cost Explorer の API は 1 リクエスト $0.01 課金されます。1 回の実行で `GetCostAndUsage` と `GetCostForecast` を 1 回ずつ呼ぶため、日次実行で月 $0.6 程度です。サービス数が増えてレスポンスがページングされる日は、全ページを読むぶんだけ加算されます。

着地見込みは `GetCostForecast` を `MONTHLY` で呼んだ結果です。月の途中を起点に指定しても API 側が期間を月全体へ正規化するため、返る値は**その月の着地額**であり、当月累計へ加算するものではありません。

Cost Explorer は未反映の日を「グループ 0 件」で返し、これは利用が実際にゼロだった日と区別できません。そのため前日分が未反映のときは、当月累計だけを投稿し、前日のサービス別内訳は省いて未反映である旨を添えます。

### 手動実行

```bash
make invoke-cost
```


## 投資判断アドバイザー（advisor）

保有商品・乗り換え候補（iDeCo 想定）について、基準価額の推移（定量）と市況ニュース・USD/JPY 為替（定性）を Bedrock 上の Agent が調査し、商品ごとに BUY/SELL/HOLD の投資判断情報を Slack へ投稿する、digest とは独立したジョブ系統です。EventBridge（毎日 JST 17:00、`job: "advisor"`）→ Lambda が起点。投稿は **アドバイザー単位で 1 スレッド**にまとまり、市況サマリ・判断変更点・過去推奨の成績サマリ・免責を親メッセージ、商品ごとの判断（前回 → 今回の変化を含む）をスレッド返信として届けます。判断履歴は DynamoDB `advisor-judgments` テーブルに保存され、次回実行時の成績検証（騰落率）に使われます。投稿日は `POST_WEEKDAY`（`FRI` など JST の曜日）で指定します。起動自体は毎日なので、目標曜日の実行が失敗しても翌日以降の実行が取りこぼしを拾います。`POST_WEEKDAY` を指定しない場合は `interval_days`（既定7日）による間隔判定になり、投稿日は最初の投稿日に引きずられます。いずれも同一日の再実行では重複投稿しません。

### 登録

`advisors` テーブルの一覧・追加・削除は Make ターゲットで行います（内部で `scripts/manage_advisors.py` を実行）。

```bash
make advisors-add ADVISOR_ID=ideco-sbi CHANNEL_ID=CXXXXXXXXXX TITLE="iDeCo 投資判断" \
  PRODUCTS='[{"isin":"JP90C000H1T1","name":"eMAXIS Slim 全世界株式(オール・カントリー)","category":"全世界株","holding":true,"assoc_fund_cd":"0331418A"}]' \
  NEWS_FEEDS='[{"url":"https://example.com/rss","name":"市況ニュース"}]' \
  TRADING_NOTES="スイッチングは指示から完了まで概ね1週間から10日。掛金の配分変更は翌月拠出分から反映。" \
  POST_WEEKDAY=FRI
```

`POST_WEEKDAY` は `MON`〜`SUN` で指定します（省略時は `INTERVAL_DAYS` による間隔判定）。両方指定した場合は `POST_WEEKDAY` が優先されます。

商品は `isin` / `name` / `category` / `holding` / `assoc_fund_cd`（投資信託協会のファンドコード。基準価額取得に使用）の5フィールドを持つため、`sources` の `url|name` 形式では表現しきれず `PRODUCTS` / `NEWS_FEEDS` は JSON 配列で指定します。`make advisors-add` は full upsert のため、既存の `ADVISOR_ID` に再実行すると省略したフィールドもクリアされる点に注意してください。

```bash
make advisors-list
make advisors-delete ADVISOR_ID=ideco-sbi
```

手動実行:

```bash
make invoke-advisor
```

### 必要な Slack スコープと運用上の注意

advisor は `channels:history`（または `groups:history`）で bot 自身の前回投稿を検索して冪等性を判定します。digest と同じく、bot がこのスコープを持ち、投稿先チャンネルに**参加している**必要があります（未参加の場合は誤って重複投稿するより安全側に倒し、投稿せずエラー終了します）。

**3 ジョブは同一チャンネルに同居できます。** 前回投稿を読むのは digest と advisor の 2 つで、どちらも `slack_reader.find_last_post_time` でヘッダーが一致する投稿だけを対象にするため、他ジョブのスレッドを自分のものと取り違えません（cost は履歴を読みません）。同居の条件は、同一チャンネル内でヘッダーが重複しないことです。なお [ADR 0001 の Consequences](docs/adr/0001-ideco-investment-advisor.md) には digest と advisor を別チャンネルに分ける旨の記述がありますが、これは digest がヘッダーで絞り込む前の制約です。

**`TITLE` は表示用ヘッダーであると同時に冪等性の目印です。** advisor は「自分の `title` をヘッダーに持つ過去の投稿」を探して投稿済みかを判定するため、`TITLE` を変更すると過去の投稿が見つからなくなり、`interval_days` を待たずにその場で投稿します。誤字修正などで変更するときは、次回投稿が前倒しで発火することを織り込んでください。

同じ理由から、**同一チャンネルに同じ `TITLE` のアドバイザーを2つ登録することはできません**（`make advisors-add` が拒否します）。登録できてしまうと、片方がもう片方の投稿を自分のものと誤認し、永久に skip し続けます。チャンネルが違えば同じ `TITLE` を使えます。

## How to Contribute

### ローカル開発環境のセットアップ

1. **mise のインストール**（未インストールの場合）:

```bash
# macOS
brew install mise

# Linux / その他
curl https://mise.run | sh
```

2. **ツール一式のインストール**（Python 3.14, Terraform, tflint, lambroll, aws-cli, pinact, prek）:

```bash
mise install
```

3. **Python 依存パッケージのインストール**:

```bash
uv sync
```

4. **Git hooks の登録**（prek + pinact による GitHub Actions ハッシュ固定）:

```bash
prek install
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
