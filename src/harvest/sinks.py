"""Append-only JSONL sink with content-hash deduplication.

Layout: <root>/<source>/<YYYY-MM-DD>.jsonl. Re-running a harvest only writes
records whose content changed since any earlier run, so the raw zone doubles as
a change log that heritage-lake can replay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .models import RawRecord


@dataclass
class SinkStats:
    written: int = 0
    unchanged: int = 0
    by_source: dict[str, int] = field(default_factory=dict)


class JsonlSink:
    def __init__(self, root: Path, source: str, run_date: str | None = None):
        self.dir = root / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{run_date or datetime.now(UTC).date().isoformat()}.jsonl"
        self.stats = SinkStats()
        self._seen = self._load_seen()

    def _load_seen(self) -> set[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        for f in sorted(self.dir.glob("*.jsonl")):
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rec = json.loads(line)
                        seen.add((rec["source_id"], rec["content_hash"]))
        return seen

    def write(self, record: RawRecord) -> bool:
        key = (record.source_id, record.content_hash)
        if key in self._seen:
            self.stats.unchanged += 1
            return False
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")
        self._seen.add(key)
        self.stats.written += 1
        return True
