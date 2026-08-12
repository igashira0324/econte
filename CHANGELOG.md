# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) once it reaches 1.0.0.
Before 1.0.0, any 0.x release may contain breaking schema changes — see the
version field in each release's schema for the exact contract in force.

## [Unreleased]

### Added
- Initial project scaffold: repository layout, license (Apache-2.0), CI skeleton
  (TypeScript + Python, matrix across windows-latest/ubuntu-latest).
- `docs/schema-spec.md` — the authoritative field-by-field storyboard schema
  specification, and `spec/fixtures/` — 15 golden fixtures (valid/invalid)
  both reference implementations below are validated against.
- `packages/econte` (`@econte/schema`) — TypeScript/Zod schema and validator;
  source of truth for the schema. Generates `spec/econte.schema.json`
  (JSON Schema 2020-12) via `npm run build:schema`.
- `python/econte` — pydantic v2 mirror of the schema, plus the beginnings of
  the `econte` CLI (`econte validate <path>` only so far — `compile`, `run`,
  `ingest`, and `sheet` are planned, not yet implemented).
- `scripts/cross_check_goldens.py` — validates every golden fixture against
  both implementations and asserts they agree with each other and with the
  filename-implied expectation.

### Planned (not yet implemented)
- `python/econte/runners/` — manifest-driven ComfyUI runners for keyframe and
  video-clip generation.
- `profiles/` — backend profile format for connecting arbitrary local ComfyUI
  workflows to the storyboard pipeline.
- `econte compile` / `econte ingest` / `econte sheet` CLI subcommands.
- `examples/haruka/` — an original, rights-clean sample character and an
  8-shot storyboard demonstrating the full pipeline end to end.
