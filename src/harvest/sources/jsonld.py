"""Crawl a museum's online collection and extract artwork records.

Most collection websites embed schema.org JSON-LD for SEO; that is the most
stable thing to scrape because it survives redesigns. Where it is missing we
fall back to OpenGraph tags, and finally to per-site CSS selectors.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..http import PoliteClient, RobotsDisallowed
from ..models import RawRecord

ARTWORK_TYPES = {"VisualArtwork", "Painting", "Sculpture", "CreativeWork", "Photograph"}


def _iter_nodes(data: Any):
    if isinstance(data, list):
        for d in data:
            yield from _iter_nodes(d)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])
        yield data


def _types(node: dict) -> set[str]:
    t = node.get("@type", [])
    return set(t if isinstance(t, list) else [t])


def extract_artwork(
    html: str, url: str, selectors: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """Return the artwork described by a detail page, or None if it is not one."""
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue  # broken JSON-LD is common; try the next block
        for node in _iter_nodes(data):
            if _types(node) & ARTWORK_TYPES:
                return {"method": "jsonld", "url": url, **node}

    og = {
        m["property"][3:]: m.get("content")
        for m in soup.find_all("meta", property=re.compile(r"^og:"))
        if m.get("content")
    }
    record: dict[str, Any] = {}
    if selectors:
        for field_name, css in selectors.items():
            el = soup.select_one(css)
            if el:
                record[field_name] = (
                    el.get("content") or el.get("src") or el.get_text(" ", strip=True)
                )
    if record:
        return {"method": "selectors", "url": url, **record, "og": og}
    if og.get("type") in {"article", "website", None} and og.get("title") and og.get("image"):
        return {
            "method": "opengraph",
            "url": url,
            "name": og["title"],
            "image": og["image"],
            "description": og.get("description"),
        }
    return None


class JsonLdCrawler:
    """Breadth-first crawl, bounded to one host and to links matching a pattern."""

    name = "web"

    def __init__(
        self,
        client: PoliteClient,
        start_urls: list[str],
        detail_pattern: str,
        follow_pattern: str | None = None,
        selectors: dict[str, str] | None = None,
        max_pages: int = 200,
        source_name: str | None = None,
    ):
        self.client = client
        self.start_urls = start_urls
        self.detail_re = re.compile(detail_pattern)
        self.follow_re = re.compile(follow_pattern) if follow_pattern else None
        self.selectors = selectors
        self.max_pages = max_pages
        self.hosts = {urlsplit(u).netloc for u in start_urls}
        if source_name:
            self.name = source_name
        self.skipped: list[tuple[str, str]] = []

    def _links(self, html: str, base: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for a in soup.find_all("a", href=True):
            link = urldefrag(urljoin(base, a["href"]))[0]
            if urlsplit(link).netloc in self.hosts:
                out.append(link)
        return out

    async def records(self, limit: int | None = None) -> AsyncIterator[RawRecord]:
        queue: deque[str] = deque(self.start_urls)
        seen: set[str] = set(self.start_urls)
        fetched = emitted = 0
        while queue and fetched < self.max_pages:
            url = queue.popleft()
            try:
                html = await self.client.get_text(url)
            except RobotsDisallowed:
                self.skipped.append((url, "robots"))
                continue
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop a crawl
                self.skipped.append((url, type(exc).__name__))
                continue
            fetched += 1

            if self.detail_re.search(url):
                art = extract_artwork(html, url, self.selectors)
                if art:
                    yield RawRecord.create(self.name, art.get("identifier") or url, url, art)
                    emitted += 1
                    if limit and emitted >= limit:
                        return
                else:
                    self.skipped.append((url, "no-artwork"))

            for link in self._links(html, url):
                if link in seen:
                    continue
                if self.detail_re.search(link) or (self.follow_re and self.follow_re.search(link)):
                    seen.add(link)
                    queue.append(link)
