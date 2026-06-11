import logging
from datetime import UTC, datetime

from pydantic import BaseModel
from strands import Agent
from strands.models import BedrockModel

from src import config
from src.tools.api_fetch import api_fetch
from src.tools.rss_fetch import rss_fetch
from src.tools.slack_history import slack_last_bot_post
from src.tools.web_scrape import web_scrape

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
あなたは技術情報のダイジェストを作成する編集者です。
与えられたURLから記事を取得し、日本語のダイジェスト本文を作成してください。

# 記事の取得
- URLやレスポンスの内容から、適切な取得方法
  （rss_fetch / web_scrape / api_fetch）を自律的に選ぶ。
- 指定された時間範囲内に公開された記事のみを対象とする。

# ソース種別ごとの方針
- 公式ブログ（例: AWS Blog）: 対象期間内の全記事を取り上げる。
  各記事は日本語に訳したタイトルと、内容を端的に表す1行解説を付ける。
- ニュース・ブックマーク系（例: はてなブックマーク）:
  特に注目すべき主要な記事を最大5件まで選んで取り上げる。
- いずれの場合も、各記事に元記事へのリンクを必ず添える。

# 出力スタイル（読者向け・重要）
- 不特定多数のSlack読者がそのまま読む前提で、自然で分かりやすい日本語にする。
- 取得処理や指示に関するメタな言及は一切含めない。
  例:「指定された期間」「記事を取得できました」「以下にまとめます」
  「RSSフィードから」等の裏側の説明は書かない。読者は記事内容だけを読みたい。
- 時刻を書く場合は必ず日本時間（JST）で表記する。
  受け取る時刻はUTCなので、+9時間して「YYYY-MM-DD HH:MM JST」のように書く。
- 対象期間内に該当記事が無い場合は、新着がない旨を1文で簡潔に伝える。

# Slack mrkdwn 記法（重要）
本文は Slack の mrkdwn で書く。通常の Markdown とは異なるので注意:
- 強調・見出しは `*太字*`（アスタリスク1つ）を使う。
  `#` や `**` は使わない（そのまま文字として表示されてしまう）。
- 箇条書きは行頭に `•` を使う。
- リンクは `<https://example.com|表示名>` の形式にする。
  `[表示名](URL)` や裸のURLは使わない。

# 出力
- 完成したダイジェスト本文を、あなたの最終メッセージとしてそのまま出力する。
- 投稿は呼び出し側が行うので、ツールでSlackへ投稿してはいけない。
- 本文以外（前置き・あいさつ・補足説明）は一切出力しない。
"""

HEADLINE_SYSTEM_PROMPT = """\
あなたは技術情報ダイジェストの編集者です。
これからSlackスレッドの親メッセージとして表示される「ヘッドライン」を作成します。
スレッド内には各フィードのダイジェストが返信として投稿済みで、
その全文があなたへの入力として与えられます。

# ヘッドラインの書き方
- スレッド全体の導入文として、2〜3文・簡潔にまとめる。
- 特に注目すべき記事を1〜2個だけ取り上げ、何が起きたかを一言で伝える。
- リンクは張らない（URLや `<url|text>` 形式を含めない）。
- すべてのフィードで新着が無い場合は、本日は新着がない旨を1文で伝える。

# 出力スタイル（読者向け・重要）
- 不特定多数のSlack読者がそのまま読む前提で、自然で分かりやすい日本語にする。
- 取得処理や指示に関するメタな言及は一切含めない。
- Slack mrkdwn で書く。強調は `*太字*`（アスタリスク1つ）。`#` や `**` は使わない。

# 出力
- 完成したヘッドライン本文のみを、あなたの最終メッセージとしてそのまま出力する。
- 本文以外（前置き・あいさつ・補足説明）は一切出力しない。
"""

PLAN_SYSTEM_PROMPT = """\
あなたは技術情報ダイジェストの投稿スケジューラです。
投稿スケジュール（自由テキスト）と現在日時から、本日ダイジェストを投稿すべきかを
判定し、投稿する場合は対象期間の開始時刻（since）を決定します。

# 投稿可否の判定
- 投稿スケジュールは「毎日」「月曜と木曜」「平日のみ」のような自由な文章で
  書かれている。現在日時（JST）の曜日・日付がスケジュールに該当するかで判定する。
- スケジュールが解釈できない場合や判断に迷う場合は、投稿する（should_post=true）。

# since の決定（should_post=true の場合のみ）
- slack_last_bot_post で対象チャンネルにおけるbotの前回投稿時刻を取得し、
  それをそのまま since とする。
- 前回投稿が見つからない場合やエラーの場合は、現在時刻の24時間前を since とする。

# 出力
- should_post: 本日投稿すべきかどうか。
- since: 対象期間の開始時刻（UTC）。should_post=false の場合は null でよい。
- reason: 判定理由を日本語1文で。
"""


class DigestPlan(BaseModel):
    """Per-source decision: whether to post today and from when to collect."""

    should_post: bool
    since: datetime | None
    reason: str


def run_plan(channel: str, posting_schedule: str, now: datetime) -> DigestPlan:
    """Decide whether to post today and the digest window start (since).

    The agent interprets the free-text posting schedule against the current
    JST date and, when posting, derives ``since`` from the bot's last post in
    the channel (via the slack_last_bot_post tool; falls back to 24h ago).
    """
    model = BedrockModel(
        model_id=config.BEDROCK_MODEL_ID,
        region_name=config.AWS_REGION,
    )
    agent = Agent(
        model=model,
        tools=[slack_last_bot_post],
        system_prompt=PLAN_SYSTEM_PROMPT,
    )
    now_utc = now.astimezone(UTC)
    now_jst = now.astimezone(config.JST)
    prompt = (
        f"チャンネルID: {channel}\n"
        f"投稿スケジュール: {posting_schedule}\n"
        f"現在日時: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}（UTC）"
        f" = {now_jst.strftime('%Y-%m-%d %H:%M')} JST（{now_jst.strftime('%A')}）\n"
        f"本日投稿すべきか判定し、投稿する場合は since を決定してください。"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt, structured_output_model=DigestPlan)
    plan = result.structured_output
    if not isinstance(plan, DigestPlan):
        raise ValueError(f"plan agent returned no structured output: {result}")
    logger.info("Bedrock output: %s", plan)
    return plan


def run_digest(url: str, since: datetime, until: datetime) -> str:
    model = BedrockModel(
        model_id=config.BEDROCK_MODEL_ID,
        region_name=config.AWS_REGION,
    )
    agent = Agent(
        model=model,
        tools=[rss_fetch, web_scrape, api_fetch],
        system_prompt=SYSTEM_PROMPT,
    )
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = (
        f"以下のURLから記事を取得してダイジェスト本文を作成してください:\n"
        f"- {url}\n\n"
        f"対象期間: {since_iso} から {until_iso} まで（UTC）\n"
        f'rss_fetchを呼び出す際は since="{since_iso}" until="{until_iso}"'
        f" を必ず指定してください。"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt)
    output = str(result)
    logger.info("Bedrock output: %s", output)
    return output


def run_headline(digests: list[tuple[str, str]]) -> str:
    """Generate the thread-parent headline from the completed digest bodies.

    Args:
        digests: (name, body) pairs of every digest posted into the thread.
    """
    model = BedrockModel(
        model_id=config.BEDROCK_MODEL_ID,
        region_name=config.AWS_REGION,
    )
    agent = Agent(
        model=model,
        tools=[],
        system_prompt=HEADLINE_SYSTEM_PROMPT,
    )
    sections = "\n\n".join(f"## {name}\n{body}" for name, body in digests)
    prompt = (
        f"以下は本日スレッドに投稿される各フィードのダイジェスト全文です。"
        f"これらを踏まえてヘッドラインを作成してください:\n\n{sections}"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt)
    output = str(result)
    logger.info("Bedrock output: %s", output)
    return output
