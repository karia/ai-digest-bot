import responses

SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
  <nav>Navigation</nav>
  <main>
    <h1>Article Title</h1>
    <p>This is the main content of the article.</p>
  </main>
  <footer>Footer</footer>
</body>
</html>
"""


@responses.activate
def test_web_scrape_extracts_main_content():
    from src.tools.web_scrape import web_scrape

    responses.add(
        responses.GET, "https://example.com/article", body=SAMPLE_HTML, status=200
    )

    result = web_scrape("https://example.com/article")

    assert "Article Title" in result
    assert "main content" in result
    assert "Navigation" not in result
    assert "Footer" not in result


@responses.activate
def test_web_scrape_handles_http_error():
    from src.tools.web_scrape import web_scrape

    responses.add(responses.GET, "https://example.com/404", status=404)

    result = web_scrape("https://example.com/404")

    assert "Error" in result


@responses.activate
def test_web_scrape_truncates_long_content():
    from src.tools.web_scrape import web_scrape

    long_content = "<html><body><main>" + "a" * 10000 + "</main></body></html>"
    responses.add(
        responses.GET, "https://example.com/long", body=long_content, status=200
    )

    result = web_scrape("https://example.com/long")

    assert len(result) <= 5000
