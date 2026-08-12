# Contributing to econte

Thanks for considering a contribution. econte is a young, single-maintainer
project, so please keep changes focused and discuss larger proposals in an
issue before opening a large PR.

## Ground rules

- **License**: all contributions are accepted under Apache-2.0 (see `LICENSE`).
  By submitting a PR you agree your contribution is licensed under the same
  terms.
- **No GPL code.** Several adjacent projects in this space (ComfyUI storyboard
  UIs, timeline editors) are GPL-3.0 licensed. Do not copy code from them —
  observing their JSON output shape for interoperability is fine, copying
  implementation is not. If you've looked at a GPL project's source while
  writing a PR, say so in the PR description so we can review carefully.
- **No third-party IP in examples.** `examples/` must only ever contain
  original characters and assets we hold the rights to (or CC0). Do not add
  fan art, real-person likenesses, or copyrighted characters, even as a
  "just for testing" sample.
- **Schema changes**: before 1.0.0, breaking changes to `spec/econte.schema.json`
  are allowed but must update the `version` field, `CHANGELOG.md`, and the
  cross-language golden tests in the same PR. The TypeScript Zod schema in
  `packages/econte` is the source of truth; `spec/econte.schema.json` is
  generated from it (`npm run build:schema`) and the Python pydantic models
  in `python/econte/models.py` are a hand-maintained mirror validated against
  the same golden fixtures — don't let them drift.
- **Backend profiles** (`profiles/*.yaml`) are data, not code. Adding support
  for a new local model/workflow should not require touching the runner
  Python code — if it does, that's a sign the profile schema needs a new
  field, not a special case.

## Development setup

```bash
# TypeScript / schema package
cd packages/econte && npm install && npm test

# Python / CLI + runners
cd python && pip install -e ".[dev]" && pytest
```

Runner tests use recorded ComfyUI API responses (`tests/fixtures/comfyui-replay/`)
so CI does not require a GPU or a running ComfyUI server. If you change a
runner's request shape, re-record fixtures against a real server and note
which ComfyUI version you used in the PR.

## Reporting issues

Open a GitHub issue. For schema questions, include the smallest
`storyboard.json` fragment that reproduces the question — that becomes a
candidate golden fixture either way.
