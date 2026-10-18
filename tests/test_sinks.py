import json

from harvest.models import RawRecord, canonical_hash
from harvest.sinks import JsonlSink


def test_hash_ignores_key_order():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})


def test_sink_skips_unchanged_and_keeps_changes(tmp_path):
    sink = JsonlSink(tmp_path, "wikidata", run_date="2026-10-01")
    assert sink.write(RawRecord.create("wikidata", "Q1", "u", {"label": "A"}))
    assert not sink.write(RawRecord.create("wikidata", "Q1", "u", {"label": "A"}))

    # a later run: unchanged record skipped, edited record kept as a new version
    sink2 = JsonlSink(tmp_path, "wikidata", run_date="2026-10-08")
    assert not sink2.write(RawRecord.create("wikidata", "Q1", "u", {"label": "A"}))
    assert sink2.write(RawRecord.create("wikidata", "Q1", "u", {"label": "A (restored)"}))
    assert sink2.stats.written == 1 and sink2.stats.unchanged == 1

    lines = (tmp_path / "wikidata" / "2026-10-08.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["payload"]["label"] == "A (restored)"
