"""The single record type every source emits.

Sources stay dumb: they return the payload exactly as the upstream system gave it,
plus provenance. All interpretation (dates, names, deduplication) happens downstream
in heritage-lake, so a parsing bug never forces a re-scrape.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def canonical_hash(payload: dict[str, Any]) -> str:
    """Stable content hash: key order and whitespace do not change it."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RawRecord(BaseModel):
    source: str = Field(description="Short source name, e.g. 'wikidata', 'europeana', 'web'")
    source_id: str = Field(description="Identifier that is stable within the source")
    url: str = Field(description="Where the record can be looked at by a human")
    fetched_at: datetime
    payload: dict[str, Any]
    content_hash: str

    @classmethod
    def create(cls, source: str, source_id: str, url: str, payload: dict[str, Any]) -> RawRecord:
        return cls(
            source=source,
            source_id=source_id,
            url=url,
            fetched_at=datetime.now(UTC),
            payload=payload,
            content_hash=canonical_hash(payload),
        )
