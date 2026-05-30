import json
import logging

import requests
from strands import tool

logger = logging.getLogger(__name__)


@tool
def api_fetch(url: str, headers_json: str = "{}") -> str:
    """Fetch data from a REST API endpoint and return the JSON response.

    Args:
        url: The API endpoint URL to fetch from.
        headers_json: Optional HTTP headers as a JSON string (default: "{}").

    Returns:
        The API response as a formatted JSON string, truncated to 5000 characters.
    """
    try:
        headers: dict[str, str] = json.loads(headers_json)
    except json.JSONDecodeError as e:
        return f"Invalid headers_json: {e}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        return f"Error fetching API: {e}"

    try:
        data = response.json()
        return json.dumps(data, ensure_ascii=False, indent=2)[:5000]
    except ValueError:
        return response.text[:5000]
