"""An HTTP client that behaves like a good citizen.

* one request at a time per host, with a minimum interval between them
* robots.txt honoured for crawling (official APIs opt out per call)
* retries with exponential backoff on 429/5xx, honouring Retry-After
* optional on-disk cache so a crashed run resumes without re-hitting servers
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

RETRYABLE = {429, 500, 502, 503, 504}
DEFAULT_UA = "heritage-harvest/0.3 (+https://github.com/jaogye/heritage-harvest; research use)"


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching a URL."""


class HostRateLimiter:
    """Serialises requests per host and keeps a minimum gap between them."""

    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic):
        self.min_interval = min_interval
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    def lock(self, host: str) -> asyncio.Lock:
        return self._locks.setdefault(host, asyncio.Lock())

    def wait_time(self, host: str) -> float:
        last = self._last.get(host)
        if last is None:
            return 0.0
        return max(0.0, self.min_interval - (self._clock() - last))

    def mark(self, host: str) -> None:
        self._last[host] = self._clock()


class PoliteClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        min_interval: float = 1.0,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        backoff_cap: float = 60.0,
        cache_dir: Path | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.cache_dir = cache_dir
        self.limiter = HostRateLimiter(min_interval)
        self._sleep = sleep
        self._robots: dict[str, RobotFileParser] = {}
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0}
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- robots
    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                resp = await self._client.get(f"{origin}/robots.txt")
                if resp.status_code >= 500:
                    parser.disallow_all = True  # server trouble: be conservative
                elif resp.status_code >= 400:
                    parser.allow_all = True  # no robots.txt: everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except httpx.HTTPError:
                parser.disallow_all = True
            self._robots[origin] = parser
        return parser.can_fetch(self.user_agent, url)

    # ----------------------------------------------------------------- cache
    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path | None:
        if not self.cache_dir:
            return None
        key = url + ("?" + urlencode(sorted(params.items())) if params else "")
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    # ------------------------------------------------------------------- get
    async def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        check_robots: bool = True,
    ) -> httpx.Response:
        cache_path = self._cache_path(url, params)
        if cache_path and cache_path.exists():
            self.stats["cache_hits"] += 1
            cached = json.loads(cache_path.read_text("utf-8"))
            return httpx.Response(
                200,
                content=cached["body"].encode("utf-8"),
                headers={"content-type": cached.get("content_type", "text/plain")},
                request=httpx.Request("GET", url, params=params),
            )

        if check_robots and not await self.allowed(url):
            raise RobotsDisallowed(url)

        host = urlsplit(url).netloc
        async with self.limiter.lock(host):
            for attempt in range(self.max_retries + 1):
                wait = self.limiter.wait_time(host)
                if wait:
                    await self._sleep(wait)
                self.stats["requests"] += 1
                resp = await self._client.get(url, params=params, headers=headers)
                self.limiter.mark(host)
                if resp.status_code not in RETRYABLE or attempt == self.max_retries:
                    break
                delay = self._retry_delay(resp, attempt)
                self.stats["retries"] += 1
                log.warning("%s -> %s, retrying in %.1fs", url, resp.status_code, delay)
                await self._sleep(delay)

        resp.raise_for_status()
        if cache_path:
            cache_path.write_text(
                json.dumps(
                    {"body": resp.text, "content_type": resp.headers.get("content-type", "")}
                ),
                "utf-8",
            )
        return resp

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), self.backoff_cap)
        return min(self.backoff_base * (2**attempt), self.backoff_cap)

    async def get_json(self, url: str, **kw: Any) -> Any:
        return (await self.get(url, **kw)).json()

    async def get_text(self, url: str, **kw: Any) -> str:
        return (await self.get(url, **kw)).text
