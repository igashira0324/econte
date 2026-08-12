# econte storyboard schema — v1 specification

This is the **authoritative field-by-field spec**. `packages/econte` (Zod) and
`python/econte/models.py` (pydantic) are two independent implementations of
this document and must agree on every fixture in `spec/fixtures/`. If they
ever disagree, this document is the tiebreaker — fix whichever
implementation is wrong, don't change the fixture to match a bug.

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
| `durationInSeconds` | number | no | must be `> 0` if present. Should be a measured value (e.g. via ffprobe), not eyeballed — this is a documentation convention, not a machine-checkable rule |
| `fps` | integer | yes | `> 0` |
| `aspectRatios` | string[] | yes | non-empty; each entry matches `^\d+:\d+$` (e.g. `"16:9"`, `"9:16"`) |
| `concept` | string | no | one-sentence emotional/creative compass for the piece |

## `Character`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^[a-z][a-z0-9_-]*$`; unique across `characters[]`. Referenced from `Shot.subject` as `"@" + id` |
| `identity` | string | yes | non-empty, recommended ≤200 chars — a short enough description to paste into every prompt that needs this character |
| `refs` | string[] | yes | non-empty; paths to reference images (front/side/back turnaround, expression sheet, etc.) |

## `GlobalStyle`

| field | type | required | notes |
|---|---|---|---|
| `palette` | string[] | no | each entry a 6-digit hex color, `^#[0-9a-fA-F]{6}$` |
| `grade` | string | no | free-text color-grade description |
| `negative` | string[] | no | free-text negative-prompt terms applied to every shot by convention (consumers decide how to merge with per-shot negatives; econte does not merge them itself) |

## `Scene`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^[A-Za-z0-9_-]+$`; unique across `scenes[]` |
| `section` | string | no | free text (e.g. `"verse1"`, `"chorus"`) — deliberately not an enum; song structure vocabularies vary too much to fix one |
| `shots` | `Shot[]` | yes | must be non-empty |

## `Shot`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^[A-Za-z0-9_-]+$`; **unique across the entire document**, not just within its scene |
| `frames` | `[integer, integer]` | yes | `[start, end]`, both `>= 0`, `end > start` |
| `idea` | string | no | one sentence: what this shot is *for* (the "why") |
| `subject` | string \| null | no | either `null`/absent (no character — B-roll/insert), or `"@" + <characters[].id>` referencing a declared character. Referential integrity is enforced: if present and prefixed `@`, the referenced id must exist in `characters[]` |
| `action` | string | no | one sentence: what happens (the "what") — convention is one idea, one action per shot |
| `camera` | `Camera` | no | |
| `heroMotion` | string | no | short description of the subject's motion, primarily for storyboard-sheet display |
| `audioSync` | string | no | free text describing the relationship to the music (e.g. `"cut on kick"`, `"chorus downbeat"`) — the *intent*; actual frame-accurate sync is Remotion/editor-side, econte only carries the intent |
| `source` | `Source` | no | generation/asset provenance — absent means the shot has no generation plan yet (pure placeholder) |
| `render` | `Render` | no | populated by `econte ingest` after generation; absent until then |
| `lyric` | `Lyric` \| null | no | |

### `Camera`

| field | type | required | notes |
|---|---|---|---|
| `framing` | enum | no | one of: `ECU`, `CU`, `MCU`, `MS`, `MLS`, `WS`, `EWS`, `OTS`, `POV`, `2S`, `INS`, `FS`, `BEV` (extreme close-up, close-up, medium close-up, medium shot, medium long shot, wide shot, extreme wide shot, over-the-shoulder, point-of-view, two-shot, insert, full shot, bird's-eye view) |
| `movement` | string | no | free text — deliberately not an enum (`"push-in 1.00→1.05"`, `"static"`, `"slow orbit 15°"`, `"handheld"` all valid). Constraining this killed expressiveness in early drafts; JSON-structured *fields* (framing) plus free-text *direction* (movement) is the balance this schema strikes |

### `Source`

| field | type | required | notes |
|---|---|---|---|
| `type` | enum | yes | `generate` \| `asset` \| `remotion` — `generate` = AI-generated from `prompt`; `asset` = pre-existing file dropped in as-is; `remotion` = built by editor-side code (title cards, typography), not an image/video file at all |
| `backend` | string | no | a `profiles/*.yaml` profile id (e.g. `"qwen-image-edit-2511"`); meaningless/absent when `type != "generate"` |
| `keyframe` | string | no | path to the approved (or candidate) keyframe still image |
| `seed` | integer | no | for reproducibility of `type: "generate"` shots |
| `prompt` | string | no | the generation prompt, in whatever language the backend expects (convention: English, regardless of `idea`/`action`'s language) |
| `approved` | boolean | yes | default `false` if omitted on input, but implementations MUST always emit it explicitly on output (never omit) — this is the machine-readable approval gate the whole pipeline hinges on |
| `material` | enum | no | `chain` \| `chain_start` \| `standalone` — only meaningful for chained-video backends (e.g. Motion-Context-style generators): `chain_start` begins a new generation chain (fresh identity lock/framing), `chain` continues from `chain_from`, `standalone` is a one-off (typical for character-less B-roll). Absent shots are treated as `chain_start` by runners that need this field, but econte itself does not assume a default — see `profiles/README.md` |
| `chain_from` | string | no | when `material == "chain"`, the `id` of the shot this one continues from (must reference another `Shot.id` elsewhere in the document — referential integrity is enforced, see rule 8 below). Deliberately explicit rather than "the previous shot in document order": document order is for editorial/display purposes and a chain does not have to be contiguous with other material (a B-roll or a different chain's shots may be interleaved between two shots of the same chain). Meaningless when `material` is `chain_start`/`standalone`/absent |

### `Render`

| field | type | required | notes |
|---|---|---|---|
| `file` | string | no | path to the rendered output (image or video) |
| `actualSeconds` | number | no | `> 0` if present — the *measured* duration (e.g. via ffprobe for video), written by `econte ingest`, not hand-entered |
| `renderedAt` | string | no | ISO 8601 datetime |

### `Lyric`

| field | type | required | notes |
|---|---|---|---|
| `text` | string | yes | |
| `startMs` | integer | yes | `>= 0` |
| `endMs` | integer | yes | `> startMs` |
| `animation` | string | no | free text, editor-side animation preset name |

## Document-level (cross-field) validation rules

Both implementations must enforce all of these, not just per-field types:

1. Every `Character.id` is unique within `characters[]`.
2. Every `Scene.id` is unique within `scenes[]`.
3. Every `Shot.id` is unique **across the whole document** (all scenes combined) — shot ids are the join key used by `compile`/`ingest`/`sheet`, so cross-scene collisions must be rejected, not just same-scene ones.
4. `Shot.frames`: `frames[1] > frames[0]`.
5. `Shot.subject`, if it starts with `"@"`, must reference an existing `Character.id` (i.e. `subject == "@" + c.id` for some `c` in `characters[]`). A `subject` that does not start with `"@"` is not currently a defined convention in v1 — implementations should reject it (reserved for future non-character subjects).
6. `Lyric.endMs > Lyric.startMs`.
7. `scenes` non-empty; every `scene.shots` non-empty; `characters` may be empty; `metadata.aspectRatios` non-empty.
8. `Shot.source.chain_from`, if present, must reference an existing `Shot.id` elsewhere in the document (same global id space as rule 3 — any scene, not just the same one). Self-reference (`chain_from == id` of the shot it's set on) is rejected as a special case of "must reference an existing shot" that can never be meaningful.

## Fixtures (`spec/fixtures/`)

Both implementations' test suites must load every file in this directory and
assert the expected verdict encoded in its filename:

- `valid-*.json` — must pass validation.
- `invalid-<rule>.json` — must fail validation, and the rule violated should
  be identifiable from the filename (e.g. `invalid-duplicate-shot-id.json`,
  `invalid-frames-end-before-start.json`, `invalid-subject-unknown-character.json`).

This is also what `scripts/cross_check_goldens.py` (CI's cross-language
consistency job) runs against: it must get the *same* accept/reject verdict
from both the TypeScript and Python implementations for every fixture.
