import logging
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel
from strands import Agent
from strands.models import BedrockModel

from src import config
from src.advisor_store import NewsFeed
from src.tools.api_fetch import api_fetch
from src.tools.nav_fetch import nav_fetch
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
- 対象期間そのもの（「6/10 15:57 〜 6/11 15:57」のような期間表記）は本文に
  含めない。期間はスレッド親のヘッドライン側に表示される。
- 対象期間内に該当記事が無い場合は、新着がない旨を1文で簡潔に伝える。

# Slack mrkdwn 記法（重要）
本文は Slack の mrkdwn で書く。通常の Markdown とは異なるので注意:
- 強調・見出しは `*太字*`（アスタリスク1つ）を使う。
  `#` や `**` は使わない（そのまま文字として表示されてしまう）。
  強調は行末で閉じるか、閉じる `*` の直後に半角スペースを置く。
  `。` `、` `（` などの全角文字が直後に来る位置では強調を使わない。
  Slack が太字と認識せず、アスタリスクがそのまま表示されてしまうため。
- 箇条書きは行頭に `•` を使う。
- リンクは `<https://example.com|表示名>` の形式にする。
  `[表示名](URL)` や裸のURLは使わない。

# 出力
- 完成したダイジェスト本文を、あなたの最終メッセージとしてそのまま出力する。
- 投稿は呼び出し側が行うので、ツールでSlackへ投稿してはいけない。
- 本文以外（前置き・あいさつ・補足説明）は一切出力しない。
"""

DAILY_SYSTEM_PROMPT = """\
あなたは技術情報のダイジェストを作成する編集者です。
与えられたURLから記事を取得し、日本時間（JST）の日付ごとに分類した
日本語のダイジェストを作成してください。

# 記事の取得
- URLやレスポンスの内容から、適切な取得方法
  （rss_fetch / web_scrape / api_fetch）を自律的に選ぶ。
- 指定された時間範囲内に公開された記事のみを対象とする。

# 日付ごとの分類（重要）
- 各記事の公開時刻はUTCなので、+9時間した日本時間（JST）の日付で分類する。
- 記事があった日だけを days に含める（日付昇順）。記事がゼロの日は含めない。
- 対象期間内に記事が1件も無い場合は、days を空配列にする。

# 各日の本文の方針
- その日に公開された全記事を取り上げる。
  各記事は日本語に訳したタイトルと、内容を端的に表す1行解説を付ける。
- 各記事に元記事へのリンクを必ず添える。

# 出力スタイル（読者向け・重要）
- 不特定多数のSlack読者がそのまま読む前提で、自然で分かりやすい日本語にする。
- 取得処理や指示に関するメタな言及は一切含めない。
- 対象期間や日付そのものの見出しは本文に含めない（日付は呼び出し側が表示する）。

# Slack mrkdwn 記法（重要）
本文は Slack の mrkdwn で書く。通常の Markdown とは異なるので注意:
- 強調・見出しは `*太字*`（アスタリスク1つ）を使う。
  `#` や `**` は使わない（そのまま文字として表示されてしまう）。
  強調は行末で閉じるか、閉じる `*` の直後に半角スペースを置く。
  `。` `、` `（` などの全角文字が直後に来る位置では強調を使わない。
  Slack が太字と認識せず、アスタリスクがそのまま表示されてしまうため。
- 箇条書きは行頭に `•` を使う。
- リンクは `<https://example.com|表示名>` の形式にする。
  `[表示名](URL)` や裸のURLは使わない。

# 出力
- date: その日のJST日付。
- body: その日のダイジェスト本文（mrkdwn）。本文以外（前置き・補足）は含めない。
"""

HEADLINE_SYSTEM_PROMPT = """\
あなたは技術情報ダイジェストの編集者です。
これからSlackスレッドの親メッセージとして表示される「ヘッドライン」を作成します。
スレッド内には各フィードのダイジェストが返信として投稿済みで、
その全文があなたへの入力として与えられます。

# ヘッドラインの書き方
- 冒頭1行目に対象期間を必ず明記する。受け取る期間はUTCなので+9時間して
  「対象期間: MM/DD HH:MM 〜 MM/DD HH:MM JST」のように書く。
- 続く本文は1段落（2〜3文）だけ。段落を分けない。
  その1段落の中で、特に注目すべき記事1〜2個に触れ、何が起きたかを一言で伝える。
- リンクは張らない（URLや `<url|text>` 形式を含めない）。
- すべてのフィードで新着が無い場合は、新着がない旨を1文で伝える。
  その場合も対象期間の行は必ず表示する。

# 出力スタイル（読者向け・重要）
- 不特定多数のSlack読者がそのまま読む前提で、自然で分かりやすい日本語にする。
- 取得処理や指示に関するメタな言及は一切含めない。
- Slack mrkdwn で書く。強調は `*太字*`（アスタリスク1つ）。`#` や `**` は使わない。
  強調は行末で閉じるか、閉じる `*` の直後に半角スペースを置く。
  `。` `、` `（` などの全角文字が直後に来る位置では強調を使わない。
  Slack が太字と認識せず、アスタリスクがそのまま表示されてしまうため。

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
- slack_last_bot_post に対象チャンネルとヘッダーの両方を渡し、同じヘッダーを持つ
  botの前回投稿時刻を取得して、それをそのまま since とする。
- header には、入力で与えられたヘッダーを変更せずそのまま渡す。
- 前回投稿が見つからない場合やエラーの場合は、現在時刻の24時間前を since とする。

# 出力
- should_post: 本日投稿すべきかどうか。
- since: 対象期間の開始時刻（UTC）。should_post=false の場合は null でよい。
- reason: 判定理由を日本語1文で。
"""

ADVICE_SYSTEM_PROMPT = """\
あなたは個人投資家向けの投資判断アドバイザーです。
与えられた商品ごとに「買い」「売り」「ホールド」のいずれかを判定し、
その理由と全体の市況サマリを日本語で作成してください。
実際の売買は利用者本人が行います。あなたの役割は判断材料の提供です。

# 判定の規則（重要）
- 判定は BUY / SELL / HOLD の3値のいずれか。あいまいな表現で逃げない。
  「やや強気」「中立寄り」のような中間表現は禁止。必ず3値のどれかに決める。
- 与えられた商品すべてについて、漏れなく1つずつ判定を出す。
  advices の isin は入力で与えられた ISIN をそのまま使う。

# 売買特性の前提（重要）
{trading_notes}

上記の売買特性により、指示から約定までに時間がかかる。
その期間内の値動きで無効になるような判断をしてはならない。
日中や数日の値動きではなく、数週間以上のトレンドと構造的な材料に基づいて判断する。

# 為替（重要）
- api_fetch で USD/JPY の現在値と直近の推移を必ず取得する。
  例: https://api.frankfurter.dev/v1/latest?base=USD&symbols=JPY
  推移: https://api.frankfurter.dev/v1/<YYYY-MM-DD>..?base=USD&symbols=JPY
- 為替ヘッジのない海外資産ファンド（全世界株式・先進国株式など）の判断では、
  為替要因と現地資産要因を切り分けて理由を述べる。
  円安による基準価額の上昇を、現地資産の上昇と混同しない。

# 先の予定の織り込み（重要）
- 判断は「今日の状況」だけでなく、今後1か月の予定を織り込んで行う。
  結果次第で相場が大きく動くと事前に分かっている予定を、
  後から「想定外」として扱ってはならない。
- 入力の「主要な経済指標」の一覧は、経済指標カレンダーから
  現在時刻より後の予定を抜き出したもの。
- 指標カレンダーに載らない予定は、ニュースと既知の日程から自分で洗い出す。
  選挙（米大統領選・中間選挙・日本の国政選挙など）、関税の発動・猶予の期限、
  政府閉鎖の期限、FOMC・日銀会合、大型企業の決算などが該当する。
- 「〇〇の結果を見てから判断する」「〇〇を待つ」という判断や助言は原則として出さない。
  約定まで時間がかかるため、予定が到来してから動いたのでは遅い。
  予定の結果を予想し、その予想を今回の判定に反映する。
- 判断に効く予定ごとに、対象商品が値上がりするか値下がりするかを予想し、
  根拠とともに理由に書く。予定の日付と名前を明記する。
- 中間選挙クラスの重要イベントに限り、
  今のうちに売却してリスクを回避するか否かを判断する。
  結果次第で相場の方向が大きく変わる政治イベントや、それに匹敵する予定が該当する。
  回避する場合は SELL とし、イベント後に買い戻す想定かどうかも理由に書く。
  通常の経済指標では、この事前売却の判断をしない。
- summary に、今後1か月で特に重要な予定を1〜2件、日付と値動きの予想つきで含める。

# トランプ大統領関連の急落と回復（重要）
トランプ大統領の発言・政策（関税など）による急落は、政権側の延期・譲歩をきっかけに
数週間〜数か月で回復してきた。以下は S&P 500 の過去事例。
- 2019年5月: 対中関税の引き上げ表明。約1か月で約7%下落し、6月下旬に高値を回復した。
- 2019年8月: 対中追加関税の表明（8/1）。約6%下落し、
  10月下旬に高値を回復した（約3か月）。
- 2025年4月: 相互関税の発表（4/2）。2/19の高値から4/8まで約19%下落した。
  4/9の90日間の一時停止で急反発し、6/27に高値を回復した。
  15%以上の下落からの回復としては史上最速だった。
- 2025年10月10日: 対中100%関税の表明で1日に2.7%下落した。約2週間で高値を更新した。
- 2026年2月: 最高裁が相互関税の法的根拠を否定した後、15%の暫定関税を表明した。
  下落は1%程度にとどまった。
  関税の脅しに対する市場の反応は、回を追うごとに小さくなっている。

この傾向から、トランプ大統領関連の材料による急落の直後は、狼狽売り（SELL）を避け、
HOLD または回復を見込んだ BUY を優先して検討する。
ただし、回復を前提にしすぎない。下落の主因がトランプ大統領関連以外にもある場合は、
回復が遅れる。金融引き締め・景気後退・企業業績の悪化などが重なる場合がこれにあたる。
2018年10〜12月は関税と FRB の利上げが重なり約20%下落し、
12/24の底から高値の回復まで約4か月かかった。
急落の主因がどれかを切り分け、理由に書く。

# 前回判断との比較
- 入力には前回までの判断履歴が含まれる。
- 前回から判定を変更する場合は、何が変わったのかを理由に必ず含める。
- 変更しない場合も、なぜ維持するのかを一言添える。

# 調査
- nav_fetch: 商品の基準価額の推移。入力のサマリで足りなければ呼ぶ。
- rss_fetch / web_scrape: 与えられた市況ニュースのフィードから相場材料を集める。
- api_fetch: 為替やその他の数値データ。

# 出力
- summary: 今回の市況サマリ（Slack mrkdwn）。USD/JPY の現在値と変動見通しを必ず含め、
  主要な相場材料と、判断を変更した商品があればその要点に触れる。3〜5文程度。
- advices: 商品ごとの {{isin, judgment, reason}}。reason は2〜4文の日本語。
- 本文は Slack の mrkdwn で書く。強調は `*太字*`（アスタリスク1つ）。
  `#` や `**` は使わない。箇条書きは行頭に `•`。
  リンクは `<https://example.com|表示名>` の形式にする。
  強調は行末で閉じるか、閉じる `*` の直後に半角スペースを置く。
  `。` `、` `（` などの全角文字が直後に来る位置では強調を使わない。
  Slack が太字と認識せず、アスタリスクがそのまま表示されてしまうため。
- 免責文は呼び出し側が付けるので、あなたは書かない。
- ツールで Slack へ投稿してはいけない。
"""


class DigestPlan(BaseModel):
    """Per-source decision: whether to post today and from when to collect."""

    should_post: bool
    since: datetime | None
    reason: str


class DailyDigest(BaseModel):
    """Digest body for a single JST day."""

    date: date
    body: str


class DailyDigests(BaseModel):
    """Per-day digests for one feed; days without articles are omitted."""

    days: list[DailyDigest]


def run_plan(
    channel: str, title: str, posting_schedule: str, now: datetime
) -> DigestPlan:
    """Decide whether to post today and the digest window start (since).

    The agent interprets the free-text posting schedule against the current
    JST date and, when posting, derives ``since`` from the bot's last post in
    the channel with the same header (via the slack_last_bot_post tool; falls
    back to 24h ago).
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
        f"ヘッダー: {title}\n"
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


def run_daily_digests(url: str, since: datetime, until: datetime) -> list[DailyDigest]:
    """Generate one digest per JST day for the given feed URL.

    Days without articles are omitted; an empty list means no articles in
    the whole window.
    """
    model = BedrockModel(
        model_id=config.BEDROCK_MODEL_ID,
        region_name=config.AWS_REGION,
    )
    agent = Agent(
        model=model,
        tools=[rss_fetch, web_scrape, api_fetch],
        system_prompt=DAILY_SYSTEM_PROMPT,
    )
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = (
        f"以下のURLから記事を取得して、JST日付ごとのダイジェストを作成してください:\n"
        f"- {url}\n\n"
        f"対象期間: {since_iso} から {until_iso} まで（UTC）\n"
        f'rss_fetchを呼び出す際は since="{since_iso}" until="{until_iso}"'
        f" を必ず指定してください。"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt, structured_output_model=DailyDigests)
    digests = result.structured_output
    if not isinstance(digests, DailyDigests):
        raise ValueError(f"daily digest agent returned no structured output: {result}")
    logger.info("Bedrock output: %s", digests)
    return digests.days


def run_headline(
    digests: list[tuple[str, str]], since: datetime, until: datetime
) -> str:
    """Generate the thread-parent headline from the completed digest bodies.

    Args:
        digests: (name, body) pairs of every digest posted into the thread.
        since: Digest window start (shown as JST in the headline).
        until: Digest window end (shown as JST in the headline).
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
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    sections = "\n\n".join(f"## {name}\n{body}" for name, body in digests)
    prompt = (
        f"対象期間: {since_iso} から {until_iso} まで（UTC）\n\n"
        f"以下は本日スレッドに投稿される各フィードのダイジェスト全文です。"
        f"これらを踏まえてヘッドラインを作成してください:\n\n{sections}"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt)
    output = str(result)
    logger.info("Bedrock output: %s", output)
    return output


class ProductAdvice(BaseModel):
    """The judgment for one product."""

    isin: str
    judgment: Literal["BUY", "SELL", "HOLD"]
    reason: str


class AdviceResult(BaseModel):
    """One advisor run: the market summary plus a judgment per product."""

    summary: str
    advices: list[ProductAdvice]


def run_advice(
    context: str,
    trading_notes: str,
    news_feeds: list[NewsFeed],
    now: datetime,
) -> AdviceResult:
    """Produce BUY/SELL/HOLD judgments for every product in ``context``.

    Args:
        context: Products, NAV summaries, past judgments and their scored
            performance, prepared by the caller.
        trading_notes: The scheme's trading characteristics (settlement lag
            etc.), injected into the system prompt.
        news_feeds: Market news sources the agent may crawl.
        now: The run time; shown to the agent in both UTC and JST.

    Raises:
        ValueError: if the agent returns no structured output.
    """
    model = BedrockModel(
        model_id=config.BEDROCK_ADVICE_MODEL_ID,
        region_name=config.AWS_REGION,
        max_tokens=config.BEDROCK_ADVICE_MAX_TOKENS,
    )
    agent = Agent(
        model=model,
        tools=[nav_fetch, rss_fetch, web_scrape, api_fetch],
        system_prompt=ADVICE_SYSTEM_PROMPT.format(
            trading_notes=trading_notes or "（特記なし）"
        ),
    )
    now_utc = now.astimezone(UTC)
    now_jst = now.astimezone(config.JST)
    feeds = "\n".join(f"- {f['name']}: {f['url']}" for f in news_feeds) or "- （なし）"
    prompt = (
        f"現在日時: {now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}（UTC）"
        f" = {now_jst.strftime('%Y-%m-%d %H:%M')} JST\n\n"
        f"# 判断対象と直近の状況\n{context}\n\n"
        f"# 市況ニュースの取得元\n{feeds}\n\n"
        f"上記すべての商品について判定と理由、および市況サマリを作成してください。"
    )
    logger.info("Bedrock input: %s", prompt)
    result = agent(prompt, structured_output_model=AdviceResult)
    invocation = result.metrics.latest_agent_invocation
    cycles = invocation.cycles if invocation else []
    logger.info(
        "Advice output tokens: peak %d per call (limit %d) over %d call(s)",
        max((c.usage["outputTokens"] for c in cycles), default=0),
        config.BEDROCK_ADVICE_MAX_TOKENS,
        len(cycles),
    )
    advice = result.structured_output
    if not isinstance(advice, AdviceResult):
        raise ValueError(f"advice agent returned no structured output: {result}")
    logger.info("Bedrock output: %s", advice)
    return advice
