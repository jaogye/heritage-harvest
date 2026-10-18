import respx

from harvest.sources.jsonld import JsonLdCrawler, extract_artwork

from .conftest import load


def test_extracts_artwork_from_graph():
    art = extract_artwork(load("artwork_page.html"), "https://museum.test/object/101")
    assert art["method"] == "jsonld"
    assert art["@type"] == "VisualArtwork"
    assert art["name"] == "Portrait of a Lady with a Rosary"
    assert art["creator"]["name"] == "Unknown Flemish master"


def test_broken_jsonld_falls_back_to_opengraph():
    html = """<html><head>
      <script type="application/ld+json">{ not json </script>
      <meta property="og:title" content="Still Life with Oysters">
      <meta property="og:image" content="https://museum.test/img/202.jpg">
    </head></html>"""
    art = extract_artwork(html, "https://museum.test/object/202")
    assert art["method"] == "opengraph"
    assert art["name"] == "Still Life with Oysters"


def test_custom_selectors():
    html = '<h1 class="t">Bust of a Woman</h1><span class="d">c. 1890</span>'
    art = extract_artwork(html, "u", selectors={"name": "h1.t", "date": "span.d"})
    assert art == {
        "method": "selectors",
        "url": "u",
        "name": "Bust of a Woman",
        "date": "c. 1890",
        "og": {},
    }


def test_non_artwork_page_returns_none():
    assert extract_artwork("<html><body>Opening hours</body></html>", "u") is None


@respx.mock
async def test_crawler_follows_pagination_and_respects_robots(client):
    respx.get("https://museum.test/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /object/999"
    )
    # more specific route first: respx matches a bare URL regardless of query string
    respx.get("https://museum.test/collection?page=2").respond(
        200, text='<a href="/object/103">c</a><a href="/object/999">blocked</a>'
    )
    respx.get("https://museum.test/collection").respond(200, text=load("listing_page.html"))
    respx.get("https://museum.test/object/101").respond(200, text=load("artwork_page.html"))
    respx.get("https://museum.test/object/102").respond(200, text="<p>temporarily unavailable</p>")
    respx.get("https://museum.test/object/103").respond(
        200, text=load("artwork_page.html").replace("MUS-0101", "MUS-0103")
    )

    crawler = JsonLdCrawler(
        client,
        ["https://museum.test/collection"],
        detail_pattern=r"/object/\d+",
        follow_pattern=r"[?&]page=",
        source_name="museum_test",
    )
    records = [r async for r in crawler.records()]
    assert sorted(r.source_id for r in records) == ["MUS-0101", "MUS-0103"]
    assert all(r.source == "museum_test" for r in records)
    reasons = dict(crawler.skipped)
    assert reasons["https://museum.test/object/999"] == "robots"
    assert reasons["https://museum.test/object/102"] == "no-artwork"
    # external links are never followed
    assert not any("elsewhere.test" in u for u, _ in crawler.skipped)
