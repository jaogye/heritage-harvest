import httpx
import respx

from harvest.sources.europeana import ENDPOINT, EuropeanaSource


def page(ids, next_cursor=None):
    body = {
        "success": True,
        "items": [
            {
                "id": f"/2048128/{i}",
                "title": [f"Item {i}"],
                "guid": f"https://www.europeana.eu/item/2048128/{i}",
            }
            for i in ids
        ],
    }
    if next_cursor:
        body["nextCursor"] = next_cursor
    return httpx.Response(200, json=body)


@respx.mock
async def test_cursor_pagination(client):
    route = respx.get(ENDPOINT).mock(side_effect=[page([1, 2], "abc"), page([3])])
    src = EuropeanaSource(client, api_key="test")
    records = [r async for r in src.records()]
    assert [r.source_id for r in records] == ["/2048128/1", "/2048128/2", "/2048128/3"]
    second = route.calls[1].request.url.params
    assert second["cursor"] == "abc"
    assert second.get_list("qf") == ["COUNTRY:belgium", "TYPE:IMAGE"]


@respx.mock
async def test_api_error_is_raised(client):
    respx.get(ENDPOINT).respond(200, json={"success": False, "error": "Invalid API key"})
    src = EuropeanaSource(client, api_key="bad")
    try:
        [r async for r in src.records()]
    except RuntimeError as e:
        assert "Invalid API key" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
