import csv
import io
import logging
import re
from datetime import date
from typing import NamedTuple

import requests

logger = logging.getLogger(__name__)

# 投資信託協会「投信総合検索ライブラリー」の CSV ダウンロード。
# Not a documented API; if it changes, this module is the only thing to fix.
NAV_CSV_URL = "https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download"

# Rows look like "2026年07月24日,38243,13205500,,"; the header row does not match.
_DATE_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


class NavPoint(NamedTuple):
    """One day's NAV (基準価額) in whole yen."""

    date: date
    nav: int


def parse_nav_csv(raw: bytes) -> list[NavPoint]:
    """Parse the association's NAV CSV into ascending NavPoints.

    The response advertises charset=utf-8 but the bytes are actually cp932,
    so the declared charset must be ignored. Rows that are not dated data
    rows (header, blank, totals) are dropped.
    """
    text = raw.decode("cp932", errors="replace")
    points: list[NavPoint] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        matched = _DATE_PATTERN.fullmatch(row[0].strip())
        if not matched:
            continue
        try:
            nav = int(row[1].strip())
        except ValueError:
            continue
        points.append(
            NavPoint(
                date=date(
                    int(matched.group(1)), int(matched.group(2)), int(matched.group(3))
                ),
                nav=nav,
            )
        )
    return points


def fetch_nav_series(isin: str, assoc_fund_cd: str, days: int = 180) -> list[NavPoint]:
    """Download a fund's NAV history and return the most recent ``days`` points.

    Args:
        isin: ISIN code, e.g. "JP90C000H1T1".
        assoc_fund_cd: 協会ファンドコード, e.g. "0331418A".
        days: How many trailing rows to keep (rows are business days).

    Raises:
        requests.RequestException: if the download fails.
    """
    logger.debug("fetch_nav_series: isin=%s assoc_fund_cd=%s", isin, assoc_fund_cd)
    response = requests.get(
        NAV_CSV_URL,
        params={"isinCd": isin, "associFundCd": assoc_fund_cd},
        timeout=30,
    )
    response.raise_for_status()
    points = parse_nav_csv(response.content)
    # days is exposed to the agent as a tool parameter with no minimum, so it
    # can arrive as 0 (points[-0:] would return the *entire* series) or
    # negative (which would silently return the oldest rows instead of the
    # newest). Clamp to at least 1 trailing row.
    return points[-max(days, 1) :]
