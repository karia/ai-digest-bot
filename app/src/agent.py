import logging
from datetime import datetime

from strands import Agent
from strands.models import BedrockModel

from src import config
from src.tools.api_fetch import api_fetch
from src.tools.rss_fetch import rss_fetch
from src.tools.web_scrape import web_scrape

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
あなたは技術情報のダイジェストを作成し、Slackチャンネルの読者へ投稿する編集者です。
与えられたURLから記事を取得し、日本語のダイジェストを作成してください。

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
"""


def run_digest(feed_urls: list[str], since: datetime, until: datetime) -> str:
    model = BedrockModel(
        model_id=config.BEDROCK_MODEL_ID,
        region_name=config.AWS_REGION,
    )
    agent = Agent(
        model=model,
        tools=[rss_fetch, web_scrape, api_fetch],
        system_prompt=SYSTEM_PROMPT,
    )
    url_list = "\n".join(f"- {u}" for u in feed_urls)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = (
        f"以下のURLから記事を取得してダイジェストを作成してください:\n{url_list}\n\n"
        f"対象期間: {since_iso} から {until_iso} まで（UTC）\n"
        f"rss_fetchを呼び出す際は"
        f' since="{since_iso}" until="{until_iso}" を必ず指定してください。'
    )
    # Bedrock input/output is logged at INFO so the digest generation can be
    # traced in normal operation, not only when DEBUG is enabled.
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt)
    output = str(result)
    logger.info("Bedrock output: %s", output)
    return output
