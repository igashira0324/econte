# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) once it reaches 1.0.0.
Before 1.0.0, any 0.x release may contain breaking schema changes — see the
version field in each release's schema for the exact contract in force.

## [Unreleased]

### Added
- Initial project scaffold: repository layout, license (Apache-2.0), CI skeleton.
- `spec/` — canonical storyboard schema (JSON Schema 2020-12), generated from
  the TypeScript/Zod source of truth in `packages/econte`.
- `python/econte` — pydantic mirror of the schema, validation CLI (`econte validate`),
  manifest compiler (`econte compile`), delivery-report ingester (`econte ingest`),
  and approval-sheet generator (`econte sheet`).
- `profiles/` — backend profile format for connecting arbitrary local ComfyUI
  workflows (keyframe and video generation) to the storyboard pipeline.
- `examples/haruka/` — an original, rights-clean sample character and an
  8-shot storyboard demonstrating the full pipeline end to end.
