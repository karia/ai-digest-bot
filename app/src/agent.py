import logging
from datetime import datetime

from strands import Agent
from strands.models import BedrockModel

from src import config
from src.tools.api_fetch import api_fetch
from src.tools.rss_fetch import rss_fetch
from src.tools.web_scrape import web_scrape

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたは技術ブログのダイジェスト作成エージェントです。
与えられたURLリストから記事を取得し、日本語でダイジェストを1本にまとめてください。

ルール:
- URLの形式やレスポンスの内容から適切な取得方法を自律的に選択すること
  （rss_fetch / web_scrape / api_fetch）
- 指定された時間範囲内に公開された記事のみを対象とすること
- 各記事はタイトル・要約(2-3文)・リンクの形式でまとめること
- 日本語でまとめること
- 記事が0件の場合は「本日の更新はありません」と返すこと
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
