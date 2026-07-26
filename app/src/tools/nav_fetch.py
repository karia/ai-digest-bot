import logging

from strands import tool

from src.nav import fetch_nav_series

logger = logging.getLogger(__name__)


@tool
def nav_fetch(isin_cd: str, assoc_fund_cd: str, days: int = 90) -> str:
    """Fetch a Japanese mutual fund's NAV (基準価額) history.

    Args:
        isin_cd: The fund's ISIN code, e.g. "JP90C000H1T1".
        assoc_fund_cd: 投資信託協会のファンドコード, e.g. "0331418A".
        days: How many trailing business days to return (default: 90).

    Returns:
        CSV text with a "date,nav" header, one row per business day in
        ascending date order, or an error message.
    """
    logger.debug("nav_fetch: isin_cd=%s assoc_fund_cd=%s", isin_cd, assoc_fund_cd)
    try:
        points = fetch_nav_series(isin_cd, assoc_fund_cd, days=days)
    except Exception as e:
        logger.warning("nav_fetch failed for %s: %s", isin_cd, e)
        return f"Error fetching NAV: {e}"

    if not points:
        return "No NAV data found."

    rows = "\n".join(f"{p.date:%Y-%m-%d},{p.nav}" for p in points)
    return f"date,nav\n{rows}"
