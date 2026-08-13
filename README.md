# econte

**A storyboard schema and local-generation toolchain for AI video pipelines.**

*[日本語版 README はこちら](README.ja.md)*

econte lets you treat a storyboard (絵コンテ) as the source of truth for an
AI video project: one JSON file holding characters, global style, shots,
camera direction, lyric/beat sync, and a machine-readable approval gate —
plus a set of tools to generate keyframes and video clips from it against
your own local ComfyUI models, and to write the results back into the
storyboard.

It exists because, as of 2026, this space has no standard storyboard
interchange format, and no approval-gated, offline/local generation
toolchain: hosted AI storyboard tools (LTX Studio, Google Flow, ...) lock
the data in their own product, and the "script → storyboard → video" open
source agents that do exist (ViMax, VideoClaw, ...) are cloud-API only —
none target a local ComfyUI backend on consumer GPU hardware. See
[`docs/why.md`](docs/why.md) for the fuller landscape review this project
is a response to.

## What's in the box

| Package | What it does |
|---|---|
| [`spec/`](spec/) | Canonical `econte.schema.json` (JSON Schema 2020-12), generated from the TypeScript source of truth |
| [`packages/econte`](packages/econte/) | TypeScript/Zod schema + validator — the source of truth |
| [`python/econte`](python/econte/) | pydantic mirror + CLI: `validate`, `compile`, `run`, `ingest`, `sheet` |
| [`profiles/`](profiles/) | Backend profiles — data files that connect an econte manifest to *your* ComfyUI workflow (any model, not just the ones we've tested) |
| `examples/haruka/` | **Planned, not yet in the repo** — an original, rights-clean sample character and 8-shot storyboard, generated end to end. See `CHANGELOG.md` |

## The pipeline

```
storyboard.json  (characters, shots, camera, lyric/beat sync, approved: false)
       │
       │  econte compile --target keyframes
       ▼
keyframes manifest  →  econte run  →  keyframe PNGs (your local model)
       │
       │  econte sheet            (self-contained HTML contact sheet)
       ▼
   human approval  (flip approved: true, or --only <id> to retake rejects)
       │
       │  econte compile --target clips   (approved keyframes only)
       ▼
clips manifest  →  econte run  →  video clips (your local model)
       │
       │  econte ingest
       ▼
storyboard.json, updated with real file paths (not durations — see below)
```

`econte ingest` deliberately never writes a measured clip duration: the
delivery report's timing is *generation* time, not media duration, and
conflating the two would silently write a wrong number. Measuring the
real duration of a generated file (e.g. via ffprobe) is left to a
separate, later tool — see `docs/compile-spec.md`'s "Scope boundary"
section for the reasoning.

Nothing here assumes a specific model. `profiles/` describes the ComfyUI
graph and how manifest fields map onto its node inputs; two reference
profiles are included (a Qwen-Image-Edit keyframe profile and a
MiniMax-H3-Motion-Context video profile) as *examples* of the shape, not as
the only supported backends.

## Status

Early and under active development (targeting v0.1.0). The schema may
still change before 1.0.0 — see `CHANGELOG.md` for what moved and when.
Issues and small, focused PRs are welcome; see `CONTRIBUTING.md`.

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
