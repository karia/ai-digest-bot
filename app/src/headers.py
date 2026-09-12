"""The rule that lets every job post into one Slack channel.

digest and advisor both find their previous post by matching the header on the
bot's own messages (``slack_reader.find_last_post_time``). Two definitions
posting the same header to the same channel each match the other's post: the
digest derives its window from the advisor's thread, and the advisor reads the
digest's post as proof it has already run and skips forever. Neither failure
surfaces at runtime, so the collision is refused at registration time.

cost posts a dated header and never reads history, so it cannot take part in a
collision and is not checked here.
"""

import logging

from src import advisor_store, store
from src.slack_notifier import HEADER_LIMIT

logger = logging.getLogger(__name__)


def _marker(header: str) -> str:
    # post_message truncates the header, so only this prefix reaches Slack and
    # only this prefix is ever compared against it.
    return header[:HEADER_LIMIT]


def assert_header_available(
    channel_id: str,
    header: str,
    *,
    source_title: str | None = None,
    advisor_id: str | None = None,
) -> None:
    """Refuse a header another definition already posts to ``channel_id``.

    Args:
        channel_id: Channel the definition posts to.
        header: Headline header it would post.
        source_title: Title of the source being registered, so re-registering
            one does not clash with itself.
        advisor_id: Id of the advisor being registered, likewise.

    Raises:
        ValueError: if another source or advisor already claims that header in
            that channel.
    """
    marker = _marker(header)

    for source in store.get_all_sources():
        if (
            source["title"] != source_title
            and source["channel_id"] == channel_id
            and _marker(source["title"]) == marker
        ):
            raise ValueError(
                f"source {source['title']!r} already posts {header!r}"
                f" to {channel_id}; headers must be unique per channel"
            )

    for advisor in advisor_store.get_all_advisors():
        if (
            advisor["advisor_id"] != advisor_id
            and advisor["channel_id"] == channel_id
            and _marker(advisor["title"]) == marker
        ):
            raise ValueError(
                f"advisor {advisor['advisor_id']!r} already posts {header!r}"
                f" to {channel_id}; headers must be unique per channel"
            )
