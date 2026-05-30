import logging

import requests
from bs4 import BeautifulSoup
from strands import tool

logger = logging.getLogger(__name__)


@tool
def web_scrape(url: str) -> str:
    """Fetch a web page and extract its main text content.

    Args:
        url: The URL of the web page to scrape.

    Returns:
        The extracted main text content of the page, truncated to 5000 characters.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DigestBot/1.0)"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        return f"Error fetching page: {e}"

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.find("body")
    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)[:5000]
