# econte converters — `compile` / `ingest` / `sheet` specification

Authoritative spec for the three CLI subcommands that connect
`storyboard.json` to the manifest/report format from `docs/profile-spec.md`.
Together they close the loop described in the README's pipeline diagram:

```
storyboard.json --compile--> manifest --run--> report --ingest--> storyboard.json (updated) --sheet--> approval.html
```

## Scope boundary: econte does not measure media duration

`Render.actualSeconds` (`docs/schema-spec.md`) is documented as a
*measured* duration (e.g. via ffprobe), not a guess. The delivery report's
`elapsedSeconds` (`docs/profile-spec.md`) is **generation time**, a
completely different number — conflating them would silently write a wrong
duration into the storyboard. econte deliberately does not depend on
ffmpeg/ffprobe (keeps the dependency footprint minimal, and this exact job
— normalizing/measuring generated assets — is already the stated
responsibility of the Remotion/editor side's own `normalize-assets`
tooling, not the generation side). `econte ingest` therefore never writes
`Render.actualSeconds`; a separate, later tool measures it.

## `econte compile <storyboard.json> --target keyframes|clips`

Reads a storyboard, selects the shots eligible for the given target, groups
them by backend profile, and writes one manifest file per group.

**Flags:**

| flag | required | meaning |
|---|---|---|
| `--target keyframes\|clips` | yes | which kind of manifest to produce |
| `--profile-dir DIR` | no, default `profiles` | where to find `<backend>.yaml` |
| `--width` / `--height` | yes | pixel resolution for this compile pass. **Not stored in storyboard.json on purpose** — `Metadata.aspectRatios` declares which *ratios* (e.g. `16:9`, `9:16`) a piece targets, deliberately not literal pixel dimensions, since the same storyboard can be compiled at different resolutions for different backends/formats (`docs/why.md`'s multi-format note). Must match one of `metadata.aspectRatios` (error if it doesn't reduce to the same ratio) |
| `--output-dir DIR` | no, default alongside `storyboard.json` | where manifest files are written |

**Eligibility filter**, applied to every shot in document order:

- `shot.source` must be present and `source.type == "generate"` (`asset`/
  `remotion` shots are never compiled — they're not econte's to generate).
- `source.backend` must be set. Missing → **skip with a warning** (not
  fatal; a storyboard mid-authoring may have shots not yet assigned a
  backend) naming the shot id.
- `source.prompt` must be non-empty. Missing → skip with a warning.
- For `--target clips` only, additionally: `source.approved` must be
  `true` (the approval gate) — this is the whole point of the stills-first
  workflow: unapproved keyframes never reach clip generation. Not yet
  approved → skip **silently at warning level, not error level** (this is
  the expected, common case while a storyboard is still under review, not
  a mistake).
- The referenced `profiles/<backend>.yaml` must load. A load failure
  (missing file, invalid YAML) is an **error** (naming the shot and
  backend), not a silent skip, since this is almost always a
  storyboard-authoring typo (a nonexistent backend name).
- If the profile loads but its `kind` does not match the target
  (`keyframe` for `--target keyframes`, `video` for `--target clips`), the
  shot is **skipped with a warning** (naming the shot, its backend, and the
  profile's actual kind) — **not** an error. A realistic multi-stage
  production storyboard routinely has some shots already progressed to a
  different backend/phase than the one currently being compiled (e.g. some
  shots advanced to a video backend for a later `--target clips` pass while
  others still need a `--target keyframes` pass); compiling one target must
  not fail on the whole document just because it also contains shots
  legitimately staged for the other target.

**Grouping.** Remaining eligible shots are grouped by `source.backend`; one
manifest is written per group, named
`<output-dir>/<storyboard-title-slug>_<target>_<backend>.json` (slug: the
same charset as `Scene.id`/`Shot.id`, lowercased, spaces to `-`).

**Field mapping**, per shot → manifest job:

| manifest job field | source | notes |
|---|---|---|
| `id` | `shot.id` | unchanged — this is the join key `ingest` uses later |
| `seed` | `shot.source.seed` if set | else **auto-derived** deterministically from `hash(shot.id)` (see below), with a printed notice (not a warning — this is expected, ergonomic behavior, not a problem) so the user knows a seed now exists if they want to pin it by editing `source.seed` |
| `prompt` | `shot.source.prompt` | verbatim |
| `material` | `shot.source.material`, default `"chain_start"` if absent | matches the schema's documented default-treatment convention |
| `chain_from` | `shot.source.chain_from` | passed through verbatim; already validated referentially correct by the schema itself |
| `fast` | not currently a `Shot.source` field | **not set by compile in v1** — a profile's own `defaults.fast` (or manifest-level `defaults.fast` set by hand after compiling) applies. A future schema addition could add a `Shot.source.fast` if this proves to matter enough; not adding it speculatively now |
| `ref_image` | **differs by target, see below** | |
| `width` / `height` | the compile invocation's `--width`/`--height` | placed in the manifest's `defaults`, not per-job (uniform across one compile pass) |
| `latent_folder` (defaults only, `--target clips` only) | derived, `<storyboard-slug>_clips_<backend>_latents` | chain-capable video profiles (e.g. `minimax-h3-motion-context`) reference `${latent_folder}` in their graph templates to scope where per-chain latents save/load; deterministic per (storyboard, backend) so repeated compiles agree. Omitted for `--target keyframes` (no shipped keyframe profile uses it) |

**`ref_image` resolution — the important, target-dependent part:**

- **`--target keyframes`**: if `shot.subject` is set (`"@" + character id`),
  `ref_image = characters[that id].refs[0]` (the character's first/primary
  reference image — typically a front view). If `shot.subject` is absent
  (character-free B-roll), `ref_image` is omitted entirely (the profile's
  `no_ref`-style variant applies).
- **`--target clips`**: `ref_image = shot.source.keyframe` if set (the
  **approved keyframe still** — this is the stills-first point: the video
  backend animates the already-approved image, not the raw character
  sheet). If no keyframe exists yet (a shot going straight to video without
  a keyframe pass), fall back to the same character-reference-sheet logic
  as the keyframes target. If neither exists, omit `ref_image` (standalone
  B-roll clip).

**Deterministic seed derivation** (only used when `source.seed` is unset):
`seed = int(hashlib.sha256(shot.id.encode()).hexdigest()[:8], 16) % (2**31)`
— stable across repeated compiles of the same storyboard (doesn't drift
run to run), fits in a signed 32-bit range (some samplers choke on larger).

## `econte ingest <storyboard.json> <report.json> --target keyframes|clips`

Reads a delivery report (`docs/profile-spec.md`'s `<manifest>_report.json`)
and writes results back into the matching shots, by `id`. A shot id in the
report with no matching shot in the storyboard is a warning (not fatal —
the storyboard may have been edited since compiling), not the reverse (a
storyboard shot absent from the report is simply left untouched, the
common case for a partial/`--only` run).

For each report job with `status == "success"`:

- **`--target keyframes`**: set `shot.source.keyframe = job.file` (path
  made relative to the storyboard.json's own directory, per the paths
  convention in `docs/schema-spec.md`). **If this changes `keyframe` to a
  different value than it already held** (a retake), also reset
  `shot.source.approved = false` — a stale approval must never survive a
  retake silently. If the value is unchanged (re-ingesting the same report
  idempotently), leave `approved` as it was.
- **`--target clips`**: set `shot.render = { file: job.file, renderedAt:
  <the report's own generatedAt> }` — deliberately no `actualSeconds` (see
  Scope boundary above).

For each report job with `status != "success"`: do not touch that shot.
Collect all such ids and print a one-line-per-shot summary at the end
(`status` + id), so a failed/missing generation is visible, not silently
dropped.

`job.file` (`docs/profile-spec.md`) is relative to the **ComfyUI output
directory**, while `source.keyframe`/`render.file` must be relative to the
**storyboard.json's own directory** (`docs/schema-spec.md`'s paths
convention) — two different base directories in general. `--comfyui-output-dir DIR`
supplies the former so `ingest` can rebase `job.file` onto the
storyboard's directory before writing it. If omitted, `job.file` is written
verbatim (unrebased) — only correct when the two directories happen to
coincide.

Writes the updated storyboard back to the same path by default; `--output
PATH` writes elsewhere instead (leaving the input untouched — useful for
review-before-overwrite workflows).

## `econte sheet <storyboard.json> [--output sheet.html] [--thumb-width 420]`

Generates a single self-contained HTML file — no external requests, no
build step, opens directly in a browser — for human approval review. One
card per shot, in document order (scene by scene), showing:

- The keyframe thumbnail if `shot.source.keyframe` is set (base64-embedded
  JPEG, resized to `--thumb-width`, so the file stays reasonably sized and
  works offline/emailed/etc.) — a placeholder (not an error) if not yet
  generated.
- Shot id, `camera.framing` (shot-size abbreviation), `material` as a
  color-coded badge (a visual convention worth keeping consistent with the
  project's own prior art: chain/chain_start material in one color, family,
  standalone/B-roll in another — see the existing hand-built example this
  project grew out of for the palette this should resemble, though exact
  colors are the implementer's call).
- `idea` and `action` text, `audioSync` note.
- Approval state, visually distinct for `approved: true` vs `false` (e.g. a
  border/badge color difference) — this is the whole point of the sheet.
- A summary line at the top: total shot count, how many have a keyframe,
  how many are approved.

This is read-only output — the sheet does not itself write approval state
back into storyboard.json (no capability to click "approve" and have it
persist, in v1); a human edits `source.approved` in the JSON directly (or a
future tool does). Keep this limitation explicit in the sheet's own header
text so it isn't a silent gap.
