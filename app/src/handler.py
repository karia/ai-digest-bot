import logging
from datetime import UTC, datetime
from typing import Any

from src.advisor import run_advisor_job
from src.digest import run_digest_job
from src.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _parse_scheduled_time(event: dict[str, Any]) -> datetime:
    raw = event.get("scheduled_time")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Invalid scheduled_time %r; falling back to now()", raw)
    return datetime.now(UTC)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    configure_logging()
    now = _parse_scheduled_time(event)
    # EventBridge picks the job; anything unrecognized falls back to digest so
    # a malformed schedule input never silently does nothing.
    job = event.get("job", "digest")
    logger.info("Dispatching job=%s at %s", job, now.isoformat())
    if job == "advisor":
        return run_advisor_job(now)
    return run_digest_job(now)
