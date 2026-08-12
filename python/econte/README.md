# econte (Python)

A pydantic v2 mirror of the econte storyboard schema, plus the beginnings
of the `econte` CLI. See the [repository root README](../../README.md) for
the project overview and [`docs/schema-spec.md`](../../docs/schema-spec.md)
for the authoritative field-by-field specification this package implements.

This package is a **hand-maintained mirror** of the TypeScript/Zod schema in
[`packages/econte`](../../packages/econte/), which is the source of truth.
Both implementations are validated against the same golden fixtures in
[`spec/fixtures/`](../../spec/fixtures/); if they ever disagree,
`docs/schema-spec.md` is the tiebreaker.

## Install

```bash
cd python
pip install -e ".[dev]"
```

## Usage as a library

```python
import json
from econte import validate_storyboard

with open("storyboard.json", encoding="utf-8") as f:
    data = json.load(f)

ok, errors = validate_storyboard(data)
if not ok:
    for error in errors:
        print(error)
```

`validate_storyboard` never raises: it returns `(True, [])` on success, or
`(False, [error, ...])` on failure, with each error formatted as a
`"path: message"` string.

The individual pydantic models (`Storyboard`, `Metadata`, `Character`,
`GlobalStyle`, `Scene`, `Shot`, `Camera`, `Source`, `Render`, `Lyric`) are
also exported from `econte` if you need direct access, e.g.
`Storyboard.model_validate(data)`.

## Usage as a CLI

```bash
econte validate path/to/storyboard.json
```

Prints `OK` and exits `0` on success; otherwise prints each validation
error to stderr and exits non-zero.

`compile`, `run`, `ingest`, and `sheet` are planned for a later phase of
this project (see [`docs/implementation-plan.md`](../../docs/implementation-plan.md))
and are not yet implemented.

## Development

```bash
cd python
pip install -e ".[dev]"
pytest
ruff check .
mypy econte
```

`tests/test_fixtures.py` loads every file in `spec/fixtures/*.json` and
asserts the accept/reject verdict encoded in its filename (`valid-*.json`
must pass, `invalid-*.json` must fail) -- it is not a hand-picked subset,
so any fixture added to that directory is automatically covered.
