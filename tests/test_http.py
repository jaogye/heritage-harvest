import httpx
import pytest
import respx

from harvest.http import HostRateLimiter, PoliteClient, RobotsDisallowed


@respx.mock
async def test_robots_disallow_blocks_crawl(client):
    respx.get("https://museum.test/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /private/"
    )
    respx.get("https://museum.test/public/1").respond(200, text="ok")
    assert (await client.get_text("https://museum.test/public/1")) == "ok"
    with pytest.raises(RobotsDisallowed):
        await client.get("https://museum.test/private/1")


@respx.mock
async def test_missing_robots_means_allowed(client):
    respx.get("https://museum.test/robots.txt").respond(404)
    respx.get("https://museum.test/x").respond(200, text="ok")
    assert (await client.get_text("https://museum.test/x")) == "ok"


@respx.mock
async def test_robots_5xx_is_conservative(client):
    respx.get("https://museum.test/robots.txt").respond(503)
    with pytest.raises(RobotsDisallowed):
        await client.get("https://museum.test/x")


@respx.mock
async def test_retries_on_429_and_honours_retry_after(client, fake_sleep):
    route = respx.get("https://api.test/data").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    data = await client.get_json("https://api.test/data", check_robots=False)
    assert data == {"ok": True}
    assert route.call_count == 3
    assert 7.0 in fake_sleep.calls  # Retry-After respected
    assert 4.0 in fake_sleep.calls  # exponential backoff for attempt 1 (2 * 2**1)
    assert client.stats["retries"] == 2


@respx.mock
async def test_gives_up_after_max_retries(fake_sleep):
    respx.get("https://api.test/data").respond(500)
    async with PoliteClient(max_retries=2, sleep=fake_sleep) as c:
        with pytest.raises(httpx.HTTPStatusError):
            await c.get("https://api.test/data", check_robots=False)
        assert c.stats["requests"] == 3


@respx.mock
async def test_disk_cache_avoids_refetch(tmp_path, fake_sleep):
    route = respx.get("https://api.test/item").respond(200, json={"id": 1})
    async with PoliteClient(cache_dir=tmp_path, sleep=fake_sleep) as c:
        await c.get_json("https://api.test/item", params={"q": "a"}, check_robots=False)
    async with PoliteClient(cache_dir=tmp_path, sleep=fake_sleep) as c:
        assert await c.get_json("https://api.test/item", params={"q": "a"}, check_robots=False) == {
            "id": 1
        }
        assert c.stats["cache_hits"] == 1
    assert route.call_count == 1


def test_rate_limiter_wait_time():
    now = [100.0]
    rl = HostRateLimiter(min_interval=2.0, clock=lambda: now[0])
    assert rl.wait_time("a") == 0.0
    rl.mark("a")
    now[0] = 100.5
    assert rl.wait_time("a") == pytest.approx(1.5)
    assert rl.wait_time("b") == 0.0
    now[0] = 103.0
    assert rl.wait_time("a") == 0.0


@respx.mock
async def test_consecutive_requests_are_spaced(client, fake_sleep):
    respx.get("https://api.test/a").respond(200, text="1")
    respx.get("https://api.test/b").respond(200, text="2")
    await client.get("https://api.test/a", check_robots=False)
    await client.get("https://api.test/b", check_robots=False)
    assert fake_sleep.calls and 0 < fake_sleep.calls[0] <= 1.0
