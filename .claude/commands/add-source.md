Add a new harvest source for: $ARGUMENTS

1. Read `src/harvest/sources/europeana.py` as the reference implementation.
2. Ask me for one real sample response if you cannot fetch it; save it to
   `tests/fixtures/<source>_page.json` (trim to ~5 records, keep the real structure).
3. Write the tests first in `tests/test_<source>.py`: pagination, `limit`, upstream error.
4. Implement `src/harvest/sources/<source>.py`: a class with `name` and an async
   `records(limit)` that yields `RawRecord.create(...)`. Keep the payload untouched.
5. Export it from `sources/__init__.py` and add a `harvest <source>` CLI command.
6. Run `pytest -q` and `ruff check .`. Report anything about the API you had to assume.
