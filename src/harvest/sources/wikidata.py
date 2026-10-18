"""Artworks held in Belgian collections, from the Wikidata Query Service.

SPARQL returns one row per combination of multi-valued properties (an artwork
with two creators and three materials gives six rows). We fold rows back into
one payload per item here, because it is a property of the transport, not of
the data, and doing it downstream would make every consumer re-learn it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..http import PoliteClient
from ..models import RawRecord

ENDPOINT = "https://query.wikidata.org/sparql"

# painting, sculpture, drawing, print, photograph, altarpiece, tapestry
DEFAULT_TYPES = ["Q3305213", "Q860861", "Q93184", "Q11060274", "Q125191", "Q144960", "Q184296"]

QUERY = """
SELECT ?item ?itemLabel ?itemDescription ?type ?typeLabel ?creator ?creatorLabel
       ?inception ?image ?collection ?collectionLabel ?location ?locationLabel
       ?material ?materialLabel ?depicts ?depictsLabel ?inventory
WHERE {{
  VALUES ?type {{ {types} }}
  ?item wdt:P31 ?type ;
        wdt:P195 ?collection .
  ?collection wdt:P17 wd:Q31 .
  OPTIONAL {{ ?item wdt:P170 ?creator . }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }}
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{ ?item wdt:P276 ?location . }}
  OPTIONAL {{ ?item wdt:P186 ?material . }}
  OPTIONAL {{ ?item wdt:P180 ?depicts . }}
  OPTIONAL {{ ?item wdt:P217 ?inventory . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,nl,fr,de". }}
}}
ORDER BY ?item
LIMIT {limit} OFFSET {offset}
"""

SCALAR = {"itemLabel", "itemDescription", "inception", "image", "inventory"}
MULTI = {
    "type": "typeLabel",
    "creator": "creatorLabel",
    "collection": "collectionLabel",
    "location": "locationLabel",
    "material": "materialLabel",
    "depicts": "depictsLabel",
}


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def fold_bindings(bindings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse SPARQL result rows into one dict per item, de-duplicating multi-values."""
    items: dict[str, dict[str, Any]] = {}
    for row in bindings:
        item_id = qid(row["item"]["value"])
        rec = items.setdefault(item_id, {"qid": item_id, **{k: [] for k in MULTI}})
        for key in SCALAR:
            if key in row and key not in rec:
                rec[key] = row[key]["value"]
        for key, label_key in MULTI.items():
            if key in row:
                entry = {
                    "qid": qid(row[key]["value"]),
                    "label": row.get(label_key, {}).get("value"),
                }
                if entry not in rec[key]:
                    rec[key].append(entry)
    return items


def merge_items(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two partial folds of the same item (rows split across pages)."""
    out = {**b, **{k: v for k, v in a.items() if k in SCALAR}}
    for key in MULTI:
        out[key] = a[key] + [v for v in b[key] if v not in a[key]]
    return out


class WikidataSource:
    name = "wikidata"

    def __init__(self, client: PoliteClient, types: list[str] | None = None, page_size: int = 500):
        self.client = client
        self.types = types or DEFAULT_TYPES
        self.page_size = page_size

    def build_query(self, offset: int) -> str:
        types = " ".join(f"wd:{t}" for t in self.types)
        return QUERY.format(types=types, limit=self.page_size, offset=offset)

    async def records(self, limit: int | None = None) -> AsyncIterator[RawRecord]:
        offset, emitted = 0, 0
        carry: tuple[str, dict[str, Any]] | None = None
        while True:
            data = await self.client.get_json(
                ENDPOINT,
                params={"query": self.build_query(offset), "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
                check_robots=False,  # official API, governed by its own usage policy
            )
            bindings = data["results"]["bindings"]
            folded = fold_bindings(bindings)
            # An item's rows can straddle a page boundary: hold back the last item
            # and merge it with the next page so it is never emitted half-complete.
            last_page = len(bindings) < self.page_size
            if carry:
                prev_id, prev = carry
                if prev_id in folded:
                    folded[prev_id] = merge_items(prev, folded[prev_id])
                else:
                    folded = {prev_id: prev, **folded}
            carry = None
            if not last_page and folded:
                last_id = list(folded)[-1]
                carry = (last_id, folded.pop(last_id))
            for item_id, payload in folded.items():
                yield RawRecord.create(
                    self.name, item_id, f"https://www.wikidata.org/wiki/{item_id}", payload
                )
                emitted += 1
                if limit and emitted >= limit:
                    return
            if last_page:
                return
            offset += self.page_size
