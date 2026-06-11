import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src import slack_notifier
from src.agent import run_daily_digests, run_digest, run_headline, run_plan
from src.logging_config import configure_logging
from src.store import get_all_sources

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

    sources = get_all_sources()
    logger.info("Fetched %d source(s) from DynamoDB", len(sources))

    if not sources:
        logger.info("No sources found in DynamoDB")
        return {"status": "ok", "sources": 0}

    until = _parse_scheduled_time(event)

    results: dict[str, str] = {}

    for source in sources:
        title = source["title"]
        channel = source["channel_id"]
        items = source["items"]
        # No date in the header: the headline body always carries the digest
        # window, which would make a date here redundant.
        header = title

        # The plan agent interprets the free-text schedule and derives `since`
        # from the bot's last post in the channel (24h ago when unavailable).
        try:
            plan = run_plan(channel, source.get("posting_schedule", "毎日"), until)
        except Exception as e:
            logger.error("Plan failed for %s: %s", title, e, exc_info=True)
            plan = None
        if plan and not plan.should_post:
            logger.info("Skipping %s: %s", title, plan.reason)
            results[title] = f"skipped: {plan.reason}"
            continue
        since = (plan and plan.since) or (until - timedelta(hours=24))

        # Generate every digest first: the headline must summarize the whole
        # thread, so nothing is posted until all bodies are ready.
        digests: list[tuple[str, str, str]] = []  # (url, reply header, body)
        for item in items:
            url = item["url"]
            name = item["name"]
            logger.info(
                "Processing %s (%s) for %s..%s",
                name,
                url,
                since.isoformat(),
                until.isoformat(),
            )
            try:
                if item.get("split_by_day"):
                    days = run_daily_digests(url, since=since, until=until)
                    if not days:
                        # Days without articles get no reply, so an empty
                        # window posts nothing for this item.
                        results[url] = "no articles"
                        continue
                    for day in days:
                        digests.append((url, f"{name} ({day.date:%m/%d})", day.body))
                else:
                    body = run_digest(url, since=since, until=until)
                    digests.append((url, name, body))
            except Exception as e:
                logger.error("Failed for %s: %s", url, e, exc_info=True)
                results[url] = f"error: {e}"

        try:
            headline_body = run_headline(
                [(h, body) for _, h, body in digests], since=since, until=until
            )
        except Exception as e:
            logger.error(
                "Headline generation failed for %s: %s", title, e, exc_info=True
            )
            headline_body = ""

        logger.info("Posting headline for source %s to %s", title, channel)
        try:
            thread_ts = slack_notifier.post_message(
                channel, text=headline_body, header=header
            )
        except Exception as e:
            logger.error("Failed to post headline for %s: %s", title, e, exc_info=True)
            results[title] = f"error: {e}"
            continue

        for url, reply_header, body in digests:
            try:
                slack_notifier.post_message(
                    channel, text=body, header=reply_header, thread_ts=thread_ts
                )
                results[url] = "success"
                logger.info("Reply for %s done", reply_header)
            except Exception as e:
                logger.error("Failed to post reply for %s: %s", url, e, exc_info=True)
                results[url] = f"error: {e}"

    logger.info("Digest run complete: %s", results)
    return {"status": "ok", "sources": len(sources), "results": results}
