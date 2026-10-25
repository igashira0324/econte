# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) once it reaches 1.0.0.
Before 1.0.0, any 0.x release may contain breaking schema changes — see the
version field in each release's schema for the exact contract in force.

## [Unreleased]

### Security
- `Source.backend` is validated as a profile id (`^[A-Za-z0-9_-]+$`) in both
  implementations. `econte compile` used it verbatim as a path component, so
  a shared storyboard could make it load any `.yaml` file as the profile and
  overwrite any `.json` file with a manifest (path traversal).
  `compile_storyboard` re-checks it.
- `econte sheet` embeds only keyframes that live inside the storyboard's own
  directory; anything else gets a placeholder unless
  `--allow-external-keyframes` is passed. It decodes only PNG, JPEG and
  WebP, and refuses images above 64 megapixels before decoding.
- `econte ingest` skips report jobs whose `file` is absolute, root-relative,
  has a drive letter, contains a `..` segment, or (with
  `--comfyui-output-dir`) resolves outside that directory, and lists them as
  `unsafe_path`.
- `econte run` warns when the ComfyUI host comes from the profile rather
  than `--host` and is not loopback.
- Manifest `profile`, `output_prefix` and `jobs[].id` are restricted to the
  slug alphabet (they become file names and ComfyUI's `filename_prefix`).
- Array sizes and the total number of shots are bounded
  (`docs/schema-spec.md`, rule 7), and both CLIs refuse storyboard files
  above 32 MiB. `validateStoryboard()` checks the bounds before zod parses
  anything, because zod 3 keeps validating every element of an array whose
  `.max()` check failed (GHSA-mrhx-c7xc-m3w5): one million entries produced
  one million issues and 317 MB of heap before this check.
- Pillow `>= 13.0.0`, which fixes decoder vulnerabilities reachable from
  `econte sheet` (for example CVE-2026-112403 and CVE-2026-112900).
- CI runs with a read-only token, `npm ci --ignore-scripts` and Node 22
  (Node 20 reached end of life in April 2026). New `security.yml` workflow:
  CodeQL for Python, TypeScript and the workflows, `pip-audit`, and an
  `npm audit` gate with an explicit allowlist, on every change and weekly.
  Also new: Dependabot config, `SECURITY.md`, and `.oss-scanner/` (scan
  profile, threat model, findings ledger, baseline, offline-auditable
  Dockerfile).
- Development dependencies: vitest 2 → 5 plus a non-breaking
  `npm audit fix`, which clears two critical advisories (the vitest UI
  server; tinypool) and the high and moderate ones in vite, esbuild,
  brace-expansion, js-yaml and source-map-js. `npm audit` now reports only
  the runtime zod advisory above.

### Changed
- **Breaking:** Python 3.11 or newer is required. Python 3.10 reached end
  of life in October 2026, and Pillow 13 (above) does not support it.
- `econte sheet` no longer decodes keyframes in formats other than PNG, JPEG
  and WebP; they get a placeholder.

### Added
- `constraints.max_frames` — a per-profile frame budget, checked against each
  job's resolved `frames` before any network call. Unlike `max_megapixels`
  (a warning), exceeding it is an **error**: a video DiT's attention cost is
  superlinear in sequence length, and a large DiT that fit in VRAM at the
  reference frame count can stop fitting past it and re-stream its weights
  every step. Measured on the reference RTX 3060 12GB with
  `minimax-h3-motion-context`: ~70 s/step at 124 frames, **>5400 s/step at
  339 frames** — roughly 77x slower for 2.7x the frames. Past that point the
  cost estimate is not merely imprecise but wrong by orders of magnitude, so
  the runner refuses the job rather than quote a number it cannot stand
  behind. `docs/profile-spec.md` explains the reasoning next to the field.
- `cost.reference_frames` — optional; opts a profile into frame-proportional
  cost scaling. Unset (the default) leaves the estimate formula exactly as it
  was, so image profiles are unaffected. Setting it also makes a resolved
  numeric `frames` mandatory for every job — the same treatment
  `width`/`height` already get.

### Changed
- `profiles/minimax-h3-motion-context.yaml`: clip length is now the `frames`
  context field (`profile.defaults.frames: 124`, consumed as `${frames}`)
  instead of a `length: 124` literal repeated across all four graph variants.
  It was previously a magic number invisible to both the constraint checker
  and the cost model, so editing it bypassed every guard econte has. The
  profile now also declares `max_frames: 124` and `reference_frames: 124`.
  Existing manifests are unaffected: `frames` resolves from
  `profile.defaults`, and at 124 frames the new cost term is exactly 1.0, so
  every previously-reported estimate is unchanged.

## [0.1.0] - 2026-08-13

The first release: a working schema, a generic ComfyUI runner driven by
two hand-verified reference profiles, the CLI subcommands connecting a
storyboard to generated media and back, and a runnable example proving
the whole loop end to end on real hardware — keyframes *and* a chained
video sequence, both generated by econte's own commands, not the
hand-written harness scripts this project grew out of.

### Added
- Initial project scaffold: repository layout, license (Apache-2.0), CI skeleton
  (TypeScript + Python, matrix across windows-latest/ubuntu-latest).
- `docs/schema-spec.md` — the authoritative field-by-field storyboard schema
  specification, and `spec/fixtures/` — 15 golden fixtures (valid/invalid)
  both reference implementations below are validated against.
- `packages/econte` (`@econte/schema`) — TypeScript/Zod schema and validator;
  source of truth for the schema. Generates `spec/econte.schema.json`
  (JSON Schema 2020-12) via `npm run build:schema`.
- `python/econte` — pydantic v2 mirror of the schema, plus the `econte` CLI.
- `docs/profile-spec.md` — the authoritative specification for backend
  profiles (`profiles/*.yaml`) and the generic runner that executes them.
- `profiles/qwen-image-edit-2511.yaml` and
  `profiles/minimax-h3-motion-context.yaml` — two hand-verified reference
  backend profiles (keyframe generation, and chained video clip generation
  with 4 graph variants), ported from real hardware-verified harness scripts.
- `python/econte/runners/` — the generic engine that loads and executes any
  profile shaped like the two references above: profile/manifest schemas,
  `${token}` placeholder substitution, variant selection, dry-run cost
  estimation, a minimal ComfyUI HTTP client, and the submit/poll/report
  orchestration loop (including `on_job_failure: abort_remaining_chain`
  propagation for chained-video profiles). Wired up as `econte run
  <manifest.json> [--dry-run] [--only ID ...] [--host/--port] [--output-dir]
  [--timeout]`.
- `python/tests/fixtures/comfyui-replay/` — recorded ComfyUI HTTP
  request/response fixtures used to test the runner's submit/poll/report
  control flow without a GPU or a live ComfyUI server.
- `scripts/cross_check_goldens.py` — validates every golden fixture against
  both implementations and asserts they agree with each other and with the
  filename-implied expectation.
- `docs/compile-spec.md` — the authoritative specification for the
  `econte compile` / `econte ingest` / `econte sheet` CLI subcommands that
  close the loop between `storyboard.json`, manifests, and delivery reports.
- `python/econte/converters/` (`compile.py`, `ingest.py`, `sheet.py`) and
  their CLI wiring in `python/econte/cli.py` — `econte compile
  <storyboard.json> --target keyframes|clips [--width/--height]
  [--profile-dir] [--output-dir]`, `econte ingest <storyboard.json>
  <report.json> --target keyframes|clips [--output] [--comfyui-output-dir]`,
  and `econte sheet <storyboard.json> [--output] [--thumb-width]` — plus
  `python/tests/test_converters/` covering all three.
- `pillow` — new runtime dependency of `python/econte`, used by
  `econte sheet` to decode and resize keyframe thumbnails for the
  self-contained HTML approval sheet.

- `examples/haruka/` — a complete runnable example: an original CC0 character
  with a three-view reference sheet, an 8-shot vertical storyboard exercising
  B-roll / chain / chain_from / lyric / multi-backend staging, the keyframes
  generated from it by econte's own CLI, and a real chained video sequence
  (stills-first: an approved keyframe seeds a `minimax-h3-motion-context`
  chain, `chain_from` continues it into a second clip with a frame-exact
  join) — 22.1 minutes measured against a 21.6-minute dry-run estimate.

### Fixed
- `econte compile --target clips` never populated a `latent_folder` manifest
  default, so every compile against a chain-capable video profile (e.g.
  `minimax-h3-motion-context`) failed outright the moment `econte run` tried
  to resolve `${latent_folder}` in that profile's chained graph templates.
  Found by running the full pipeline end to end against a live server
  while producing the `examples/haruka` video sequence below — not caught
  by any prior unit test.
