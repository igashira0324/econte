<!--
  GENERATED-STYLE DOCUMENTATION — mirrors packages/econte/src/schema.ts.
  Source of truth: packages/econte/src/schema.ts (Zod). The machine-readable
  counterpart is econte.schema.json (JSON Schema 2020-12) in this same
  directory, built via `npm run build:schema` in packages/econte.

  Do not hand-edit the field tables below without also updating
  packages/econte/src/schema.ts (and, if the change is user-facing,
  docs/schema-spec.md) in the same PR — see CONTRIBUTING.md's "Schema
  changes" section. Prose sections may be edited freely.
-->

# econte storyboard schema

Reference documentation for the econte storyboard format (`storyboard.json`).
This mirrors [`docs/schema-spec.md`](../docs/schema-spec.md), the
authoritative spec that both reference implementations (`packages/econte`
TypeScript/Zod, `python/econte` Python/pydantic) must satisfy — see that
file if this document and the schema ever appear to disagree.

All paths (`refs`, `audio`, `keyframe`, `file`, `audioAnalysis`) are relative
to the storyboard.json file's own directory, forward-slash separated,
regardless of host OS.

## Top level: `Storyboard`

| field | type | required | notes |
|---|---|---|---|
| `version` | string | yes | semver, e.g. `"0.1.0"`. Pattern: `^\d+\.\d+\.\d+$` |
| `metadata` | `Metadata` | yes | |
| `characters` | `Character[]` | yes | may be `[]`. All `id`s unique within this array |
| `globalStyle` | `GlobalStyle` | no | |
| `audioAnalysis` | string | no | path to a beat/section analysis JSON produced elsewhere (e.g. librosa) — econte does not read or validate its contents, only carries the reference |
| `scenes` | `Scene[]` | yes | must be non-empty |

## `Metadata`

| field | type | required | notes |
|---|---|---|---|
| `title` | string | yes | non-empty |
| `artist` | string | no | |
| `audio` | string | no | path to the mixed/master audio file |
| `durationInSeconds` | number | no | must be `> 0` if present |
| `fps` | integer | yes | `> 0` |
| `aspectRatios` | string[] | yes | non-empty; each entry matches `^\d+:\d+$` (e.g. `"16:9"`, `"9:16"`) |
| `concept` | string | no | one-sentence emotional/creative compass for the piece |

## `Character`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^[a-z][a-z0-9_-]*$`; unique across `characters[]`. Referenced from `Shot.subject` as `"@" + id` |
| `identity` | string | yes | non-empty |
| `refs` | string[] | yes | non-empty; paths to reference images |

## `GlobalStyle`

| field | type | required | notes |
|---|---|---|---|
| `palette` | string[] | no | each entry a 6-digit hex color, `^#[0-9a-fA-F]{6}$` |
| `grade` | string | no | free-text color-grade description |
| `negative` | string[] | no | free-text negative-prompt terms applied to every shot by convention |

## `Scene`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^[A-Za-z0-9_-]+$`; unique across `scenes[]` |
| `section` | string | no | free text (e.g. `"verse1"`, `"chorus"`) — not an enum |
| `shots` | `Shot[]` | yes | must be non-empty |

## `Shot`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^[A-Za-z0-9_-]+$`; **unique across the entire document**, not just within its scene |
| `frames` | `[integer, integer]` | yes | `[start, end]`, both `>= 0`, `end > start` |
| `idea` | string | no | one sentence: what this shot is *for* |
| `subject` | string \| null | no | either `null`/absent, or `"@" + <characters[].id>`. Referential integrity is enforced |
| `action` | string | no | one sentence: what happens |
| `camera` | `Camera` | no | |
| `heroMotion` | string | no | short description of the subject's motion |
| `audioSync` | string | no | free text describing the relationship to the music (intent only) |
| `source` | `Source` | no | generation/asset provenance |
| `render` | `Render` | no | populated by `econte ingest` |
| `lyric` | `Lyric` \| null | no | |

### `Camera`

| field | type | required | notes |
|---|---|---|---|
| `framing` | enum | no | one of: `ECU`, `CU`, `MCU`, `MS`, `MLS`, `WS`, `EWS`, `OTS`, `POV`, `2S`, `INS`, `FS`, `BEV` |
| `movement` | string | no | free text (`"push-in 1.00→1.05"`, `"static"`, `"handheld"`, …) |

### `Source`

| field | type | required | notes |
|---|---|---|---|
| `type` | enum | yes | `generate` \| `asset` \| `remotion` |
| `backend` | string | no | a `profiles/*.yaml` profile id |
| `keyframe` | string | no | path to the approved (or candidate) keyframe still image |
| `seed` | integer | no | for reproducibility of `type: "generate"` shots |
| `prompt` | string | no | the generation prompt |
| `approved` | boolean | yes | defaults to `false` when omitted on input; implementations always emit it explicitly on output |
| `material` | enum | no | `chain` \| `chain_start` \| `standalone` |

### `Render`

| field | type | required | notes |
|---|---|---|---|
| `file` | string | no | path to the rendered output (image or video) |
| `actualSeconds` | number | no | `> 0` if present — measured duration, written by `econte ingest` |
| `renderedAt` | string | no | ISO 8601 datetime |

### `Lyric`

| field | type | required | notes |
|---|---|---|---|
| `text` | string | yes | |
| `startMs` | integer | yes | `>= 0` |
| `endMs` | integer | yes | `> startMs` |
| `animation` | string | no | free text, editor-side animation preset name |

## Document-level (cross-field) validation rules

These rules are enforced by the reference implementations
(`packages/econte`'s `.refine()` / `.superRefine()`, `python/econte`'s
`model_validator`) — **not** by `econte.schema.json` alone, since plain JSON
Schema cannot express cross-field constraints:

1. Every `Character.id` is unique within `characters[]`.
2. Every `Scene.id` is unique within `scenes[]`.
3. Every `Shot.id` is unique **across the whole document** (all scenes combined).
4. `Shot.frames`: `frames[1] > frames[0]`.
5. `Shot.subject`, if it starts with `"@"`, must reference an existing `Character.id`. A `subject` that does not start with `"@"` is rejected (reserved for future non-character subjects).
6. `Lyric.endMs > Lyric.startMs`.
7. `scenes` non-empty; every `scene.shots` non-empty; `characters` may be empty; `metadata.aspectRatios` non-empty.

## Files in this directory

| file | what it is |
|---|---|
| [`econte.schema.json`](econte.schema.json) | Machine-readable JSON Schema (draft 2020-12), generated by `npm run build:schema` in `packages/econte`. Structural constraints only — see the cross-field rules note above |
| [`SCHEMA.md`](SCHEMA.md) | This file — human-readable mirror of `econte.schema.json` plus the cross-field rules |
| [`fixtures/`](fixtures/) | Golden fixtures (`valid-*.json` / `invalid-*.json`) exercised by both reference implementations' test suites and by `scripts/cross_check_goldens.py` |
