"""Europeana Search API with cursor-based deep pagination.

Get a free key at https://pro.europeana.eu/page/get-api and export
EUROPEANA_API_KEY. The public demo key works for small tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from ..http import PoliteClient
from ..models import RawRecord

ENDPOINT = "https://api.europeana.eu/record/v2/search.json"


class EuropeanaSource:
    name = "europeana"

    def __init__(
        self,
        client: PoliteClient,
        query: str = "*",
        filters: list[str] | None = None,
        api_key: str | None = None,
        rows: int = 100,
    ):
        self.client = client
        self.query = query
        self.filters = filters if filters is not None else ["COUNTRY:belgium", "TYPE:IMAGE"]
        self.api_key = api_key or os.environ.get("EUROPEANA_API_KEY", "api2demo")
        self.rows = rows

    async def records(self, limit: int | None = None) -> AsyncIterator[RawRecord]:
        cursor, emitted = "*", 0
        while cursor:
            params: dict = {
                "wskey": self.api_key,
                "query": self.query,
                "rows": self.rows,
                "cursor": cursor,
                "profile": "rich",
                "media": "true",
            }
            if self.filters:
                params["qf"] = self.filters
            data = await self.client.get_json(ENDPOINT, params=params, check_robots=False)
            if not data.get("success", True):
                raise RuntimeError(f"Europeana error: {data.get('error')}")
            for item in data.get("items", []):
                url = item.get("guid") or f"https://www.europeana.eu/item{item['id']}"
                yield RawRecord.create(self.name, item["id"], url, item)
                emitted += 1
                if limit and emitted >= limit:
                    return
            cursor = data.get("nextCursor")
