import httpx
import respx

from harvest.sources.wikidata import ENDPOINT, WikidataSource, fold_bindings

from .conftest import load


def test_fold_collapses_cartesian_rows():
    data = load("wikidata_page.json")
    items = fold_bindings(data["results"]["bindings"])
    assert set(items) == {"Q9000001", "Q9000002", "Q9000003"}
    triptych = items["Q9000001"]
    # 2 creators x 2 materials = 4 rows upstream, folded into 2 + 2 values
    assert [c["label"] for c in triptych["creator"]] == ["Hubert van Eyck", "Jan van Eyck"]
    assert len(triptych["material"]) == 2
    assert triptych["itemLabel"] == "Adoration of the Mystic Lamb (fixture)"
    assert items["Q9000003"]["creator"] == []  # anonymous work keeps an empty list


@respx.mock
async def test_items_split_across_pages_are_merged(client):
    rows = load("wikidata_page.json")["results"]["bindings"]
    # page_size=3: rows 0-2 on page 1, rows 3-5 on page 2 -> Q9000001 straddles both
    page1 = {"results": {"bindings": rows[:3]}}
    page2 = {"results": {"bindings": rows[3:6]}}
    page3 = {"results": {"bindings": rows[6:]}}
    respx.get(ENDPOINT).mock(
        side_effect=[httpx.Response(200, json=p) for p in (page1, page2, page3)]
    )
    src = WikidataSource(client, page_size=3)
    records = [r async for r in src.records()]
    ids = [r.source_id for r in records]
    assert ids == ["Q9000001", "Q9000002", "Q9000003"]  # each exactly once
    assert len(records[0].payload["creator"]) == 2
    assert len(records[0].payload["material"]) == 2


@respx.mock
async def test_limit_stops_early(client):
    respx.get(ENDPOINT).respond(200, json=load("wikidata_page.json"))
    src = WikidataSource(client, page_size=500)
    records = [r async for r in src.records(limit=2)]
    assert len(records) == 2


def test_query_contains_belgium_and_types(client):
    q = WikidataSource(client, types=["Q3305213"]).build_query(offset=1000)
    assert "wd:Q31" in q and "wd:Q3305213" in q and "OFFSET 1000" in q
