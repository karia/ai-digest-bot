import pytest

CHANNEL = "CTEST12345"


def test_a_source_cannot_take_a_header_an_advisor_already_posts(integrated_aws_mock):
    from src.store import add_source

    # SAMPLE_ADVISOR posts "iDeCo 投資判断" to CADVISOR01.
    with pytest.raises(ValueError, match="unique per channel"):
        add_source(
            "iDeCo 投資判断",
            "CADVISOR01",
            [{"url": "https://example.com/a", "name": "A"}],
        )


def test_an_advisor_cannot_take_a_header_a_source_already_posts(integrated_aws_mock):
    from src.advisor_store import add_advisor

    # SAMPLE_SOURCE posts "Tech Digest" to CTEST12345.
    with pytest.raises(ValueError, match="unique per channel"):
        add_advisor(
            advisor_id="new-advisor",
            channel_id=CHANNEL,
            title="Tech Digest",
            products=[],
            news_feeds=[],
            trading_notes="",
        )


def test_the_same_header_is_free_in_another_channel(integrated_aws_mock):
    from src.store import add_source, get_all_sources

    add_source(
        "iDeCo 投資判断",
        "COTHER0001",
        [{"url": "https://example.com/a", "name": "A"}],
    )

    titles = {s["title"] for s in get_all_sources()}
    assert "iDeCo 投資判断" in titles


def test_re_registering_a_source_does_not_clash_with_itself(integrated_aws_mock):
    from src.store import add_source, get_all_sources

    add_source(
        "Tech Digest",
        CHANNEL,
        [{"url": "https://example.com/b", "name": "B"}],
    )

    source = next(s for s in get_all_sources() if s["title"] == "Tech Digest")
    assert source["items"][0]["name"] == "B"


def test_the_cost_job_header_is_never_checked(integrated_aws_mock):
    from src import headers

    # cost posts a dated header and reads no history, so nothing it posts can
    # collide with a digest or advisor definition.
    headers.assert_header_available(CHANNEL, "AWS コスト 2026-09-13")
