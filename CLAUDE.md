# Project conventions for coding assistants

## What this repo is
Stage 1 of the heritage pipeline: harvest raw records with provenance. Downstream repos
(heritage-lake, heritage-atlas) depend on the `RawRecord` JSONL format; do not change its
fields without bumping the minor version and updating heritage-lake's bronze loader.

## Rules
- Never parse or normalise upstream data in a source. Payloads stay as received.
- All HTTP goes through `PoliteClient`. No bare `httpx` calls in sources.
- Tests never touch the network: mock with `respx`, put sample responses in `tests/fixtures/`.
- Inject `sleep` (see `tests/conftest.py::FakeSleep`) so tests never actually wait.
- A new source needs: a fixture captured from the real endpoint, a pagination test,
  a limit test, and an error-path test.
- Official APIs: `check_robots=False` and a comment naming the usage policy.
  Websites: robots always on.

## Commands
- `pytest -q` – full suite, must stay green
- `ruff check . && ruff format --check .` – lint

## Before finishing a task
Run the tests, update README "Project layout" if files were added, and list in the
summary any behaviour you were unsure about rather than guessing silently.
