# econte backend profiles & runner — specification

This is the authoritative spec for `profiles/*.yaml` and the generic runner
that executes them (`python/econte/runners/`). It plays the same role for
P2 that `docs/schema-spec.md` plays for the storyboard schema: implement
against this document, and validate against the fixtures it defines.

## Why complete graph variants, not a patching DSL

ComfyUI API-format graphs are just JSON: `{node_id: {class_type, inputs}}`.
The tempting design is a single graph template plus small conditional
patches ("add this node if X, rewire that input if Y"). Real profiles don't
support that cleanly — verified against the two hand-written harnesses this
project grew out of (`keyframe_runner.py`, `h3_chain_runner.py`):

- Toggling EasyCache on/off doesn't just add a node, it changes which node
  ID feeds `BasicGuider.model` and `BasicScheduler.model`.
- Toggling "chained vs. origin" clip generation doesn't just add a
  `MotionContextLoadLatent` node, it changes which node feeds
  `BasicGuider.conditioning`, `SamplerCustomAdvanced.latent_image`'s
  upstream chain, and `MotionContextTrim`'s `trim_frames` input.

A patch/rewire DSL general enough to express that is harder to write
correctly and harder for a profile author to reason about than just... the
thing a ComfyUI user already does by hand: build variant A in the UI, "Save
(API format)", flip a node, "Save (API format)" again as variant B. So a
profile declares one or more **complete** named graph variants, each a full
API-format graph with `${token}` placeholders in leaf positions, and a
small selector table that picks which variant applies to a given job.

## Manifest

The input to `econte run`. `econte compile` (a later phase) produces this
from a `storyboard.json`; it can also be written by hand.

```jsonc
{
  "profile": "qwen-image-edit-2511",       // profiles/<id>.yaml to use
  "output_prefix": "SBdemo",               // passed to the profile as ${output_prefix}
  "defaults": {                            // manifest-wide fallback values for job fields
    "ref_image": "characters/haruka/front.png",
    "width": 720, "height": 1280
  },
  "jobs": [
    {
      "id": "S01-A",                       // required, unique within the manifest; becomes the
                                            // delivery report's join key back to storyboard shot ids
      "seed": 1001,                        // required
      "prompt": "...",                     // required
      "ref_image": null,                   // optional; overrides defaults.ref_image; null/absent means
                                            // "use defaults.ref_image", explicit "" means "no reference"
      "width": 720, "height": 1280,        // optional per-job override of defaults
      "material": "standalone",            // profile-defined field: consumed by variant_selector, see below
      "chain_from": null,                  // profile-defined field: for chained-video profiles, the id of
                                            // the job this one continues from (must appear earlier in jobs[])
      "fast": false                        // profile-defined field: consumed by variant_selector and/or cost multipliers
    }
  ]
}
```

Only `id`, `seed`, and `prompt` are fixed/required by the runner itself.
Every other field (`material`, `chain_from`, `fast`, ...) is *profile-defined*
— the runner passes the whole resolved job dict through as template
context (see Placeholder resolution) and to `variant_selector`; it doesn't
hardcode what fields a video vs. keyframe profile needs. A profile's own
doc comment (`description`, and `docs/profile-spec.md`-style prose in its
YAML) should say which extra fields it expects.

**Resolution.** For each job, the runner builds a resolved context by
merging, lowest to highest precedence: `profile.defaults` (a profile may
supply its own fallback for fields it expects but a manifest may omit,
e.g. a `steps: 20` default) → `manifest.defaults` → the job's own fields →
runner-computed fields (below, always last). Anything not overridden by a
higher layer is inherited as-is (e.g. `width`/`height` are typically only
set once in `manifest.defaults`). If a runner-computed field name collides
with a user-supplied one, the computed value wins and the runner logs a
warning naming the collision — computed fields are derived, not meant to
be hand-set, but a silent, unexplained override would be worse than a
noisy one.

**Runner-computed context fields**, always available regardless of profile:

| name | value |
|---|---|
| `id` | the job's `id` |
| `output_prefix` | `manifest.output_prefix` |
| `filename_prefix` | `f"{output_prefix}/{id}"` |
| `chain_from_index` | if `chain_from` is set: the 1-based position of the referenced job within `jobs[]` (runner resolves this by id lookup so profiles never do positional arithmetic); error if `chain_from` doesn't match an earlier job's `id` |
| `job_index` | the job's 1-based position within `jobs[]` |

## Profile

```yaml
id: qwen-image-edit-2511          # matches the filename (profiles/<id>.yaml); referenced by manifest.profile
kind: keyframe                    # keyframe | video — informational + used by `econte compile` in a later
                                   # phase to decide which storyboard shots feed which kind of manifest
defaults: {}                      # profile-level fallback context fields, lowest precedence (e.g. a video
                                   # profile might set `steps: 20` here so manifests don't have to)
description: >
  Qwen-Image-Edit 2511 (FP8) + Lightning 4-step LoRA. Verified ~40s/frame
  at 720x1280 on a 12GB GPU (2026-08-13). Character identity holds across
  full-body/chest-up/face-ECU/back-view/top-down/different-location shots
  from a single reference image.

server:
  default_host: "127.0.0.1"
  default_port: 8188

constraints:                      # validated by the runner before submitting ANY job (dry-run and real run)
  resolution_multiple: 8          # width and height must both be divisible by this
  max_megapixels: 1.5             # warning (not error) above this — matches Qwen-Image's ~1MP sweet spot

cost:                             # dry-run time estimate; all figures are measured, not guessed —
                                   # see the profile's own description/comments for the source measurement
  reference_resolution: { width: 720, height: 1280 }
  base_seconds_per_job: 40
  first_job_overhead_seconds: 240 # one-time model load, added once regardless of job count
  multipliers: {}                 # e.g. `fast: 1.8` — see minimax-h3-motion-context.yaml for a profile that uses this

output:
  # Where to find the produced file after a successful job. ${...} tokens resolve against the same
  # per-job context as graph templates. `pick: newest` breaks ties by mtime (ComfyUI's own numbering
  # is not always contiguous e.g. after a --only retake).
  glob: "${filename_prefix}_*.png"
  pick: newest

variant_selector:
  fields: [ref_image]             # which resolved context fields this selector inspects
  map:
    # Evaluated top to bottom; first match wins. A field value of null in `when` matches missing/None/"".
    - when: { ref_image: null }
      variant: no_ref
    - when: {}                     # empty `when` = catch-all fallback; must be the last entry
      variant: with_ref

variants:
  with_ref:
    graph: { ... }                 # full ComfyUI API-format graph, ${token} placeholders in leaf strings
  no_ref:
    graph: { ... }
```

### Placeholder resolution

Within a variant's `graph`, every string leaf is scanned:

1. If the **entire** string matches `^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$`
   (nothing but a single token), it is replaced with the **raw, typed**
   value from the resolved context (so `"${seed}"` becomes the actual
   integer `1001`, not the string `"1001"` — ComfyUI node inputs are
   type-sensitive).
2. Otherwise, every `${name}` occurrence within the string is replaced with
   `str(value)` (e.g. a hypothetical `"prefix_${id}"` becomes
   `"prefix_S01-A"`). This form is rarely needed since `filename_prefix` is
   already provided pre-composed, but is supported for profile authors who
   want it.
3. A token name not present in the resolved context is a **hard error**
   (fail the job before submitting anything to ComfyUI), naming the
   profile id, variant, node id, and the missing token — never silently
   left as a literal `${...}` string in a submitted graph.

Non-string leaves (numbers, booleans, node-reference arrays like
`["6", 0]`) are left untouched — node-reference arrays are graph
structure, not data, and are never templated.

### Variant selection

`variant_selector.map` is evaluated top to bottom against the resolved
job context; the first entry whose `when` clause matches wins. A `when`
clause matches if, for every field it names, the context's value equals
one of the listed value(s) (a bare scalar means "equals this value"; the
spec's own examples show both a single-value and an implicit list — an
implementer should accept `when: {field: value}` and `when: {field: [v1, v2]}`
uniformly, treating the scalar form as a one-element list). An empty
`when: {}` matches everything and must be the last (default) entry — the
runner should error at profile-load time if a profile's map has no such
catch-all and no branch matches a given job later, rather than fail deep
into a run.

### Constraints

Checked once per resolved job's `width`/`height` at manifest-validation
time (both `--dry-run` and real runs), before any network call:

- `resolution_multiple`: error if `width % n != 0 or height % n != 0`.
- `max_megapixels`: warning (not error) if `width * height` exceeds it.

### Cost estimate (`--dry-run`)

```
total_seconds = first_job_overhead_seconds
              + sum over jobs of:
                  base_seconds_per_job
                  * (job.width * job.height) / (reference_resolution.width * reference_resolution.height)
                  * product(multipliers[f] for f in multipliers if job.get(f) is truthy)
```

The dry-run report prints this total (and a per-job breakdown) without
making any network call — this must work with no ComfyUI server running,
exactly like both predecessor scripts' `--dry-run`.

### Output resolution & delivery report

After a job's ComfyUI `/history` poll reports `status_str == "success"`,
the runner globs `output.glob` (resolved against that job's context,
relative to the ComfyUI output directory configured on the runner/CLI —
econte does not hardcode a ComfyUI installation path) and picks per
`output.pick` (currently only `"newest"`, by mtime — matches both
predecessor scripts' behavior).

At the end of a run (whether it completed, was interrupted, or is being
re-run after `--only` retakes), the runner regenerates the full delivery
report from whatever is currently on disk for every job in the manifest
(not just the jobs from this invocation) — matching both predecessor
scripts' "always rebuild the full report" behavior, which makes retakes
and resumes safe.

```jsonc
// <manifest>_report.json
{
  "profile": "qwen-image-edit-2511",
  "manifest": "path/to/manifest.json",
  "generatedAt": "2026-08-13T12:00:00Z",
  "jobs": [
    {
      "id": "S01-A",
      "status": "success",          // success | failed | missing (no output file found on disk)
      "file": "SBdemo/S01-A_00001_.png",   // relative to the ComfyUI output dir; forward slashes
      "elapsedSeconds": 41.2,       // omitted for "missing"
      "seed": 1001,
      "prompt": "...",
      // every other job field from the manifest is carried through verbatim (material, fast,
      // chain_from, ref_image, ...) so `econte ingest` doesn't need the original manifest at hand
      "material": "standalone"
    }
  ]
}
```

## Runner algorithm (`econte run`)

1. Load the manifest; load `profiles/<manifest.profile>.yaml`.
2. Validate every job's resolved `width`/`height` against `constraints`
   (collect ALL errors/warnings before exiting, like both predecessor
   scripts — don't stop at the first one).
3. Validate every job resolves to exactly one variant (see Variant
   selection) — a profile-load-time error if the map has no catch-all, a
   job-resolution-time error if somehow nothing matches despite one.
4. If `--dry-run`: print the constraint report and the cost estimate,
   exit 0 if no errors, exit 1 otherwise. No network calls.
5. Otherwise: wait for the ComfyUI server (`server.default_host:port`, or
   `--host`/`--port` overrides) to answer `/system_stats`, then for each
   job (optionally filtered by `--only <id>...`, matching `keyframe_runner.py`'s
   retake flag): resolve its variant, build its graph (placeholder
   substitution), `POST /prompt`, poll `/history/<id>` until terminal,
   record status + elapsed time. On failure, print the ComfyUI error
   detail and continue to the next job by default (both predecessor
   scripts' behavior differs slightly here — `h3_chain_runner.py` aborts
   the whole chain on a failed chained job since a broken chain can't
   continue; `keyframe_runner.py` continues past independent failures.
   The generic runner should default to **continue**, and a profile may
   set `on_job_failure: abort_remaining_chain` — meaning: skip any
   remaining job whose `chain_from` (transitively) points at the failed
   job, but continue with unrelated jobs — which subsumes both
   predecessors' behaviors correctly rather than picking one).
6. Write `<manifest>_report.json` (always regenerated from disk state, per
   above).

## Testing: record/replay

CI has no GPU and no running ComfyUI server. `python/tests/fixtures/comfyui-replay/`
holds hand-constructed shape/contract fixtures — built from real ComfyUI
response *shapes* observed against a live server, but not captured live
byte-for-byte (see that directory's `README.md` "Provenance" section for
the full disclosure, and its "Follow-up work" section for the planned
`scripts/record_fixture.py` that would let these be re-recorded against a
real server) — as `<case-name>/prompt_response.json` (the `POST /prompt`
response) and `<case-name>/history_response.json` (the terminal
`/history/<id>` response), plus a per-case `meta.json` identifying the
profile/variant it exercises.

A test double HTTP layer (`ReplayClient`, in
`python/tests/test_runners/replay_client.py`) serves these instead of real
sockets. It is keyed purely by **call order**: a test constructs it with
an ordered `list[str]` of fixture case names, and each successive
`POST /prompt` call consumes the next name in that list — it never
inspects the built graph or request body. This relies on the runner
submitting jobs in manifest order, and means a job skipped via `--only` or
chain-abort simply never consumes an entry.

Fixture directories use flat, descriptive names rather than a
profile-nested layout — see `python/tests/fixtures/comfyui-replay/README.md`
for the authoritative directory format and the full case table. At
minimum this includes one success case per reference profile
(`qwen-with-ref-success/`, `h3-origin-ec-success/`, `h3-chained-ec-success/`),
one generic failure case (a `status_str: "error"` history response,
`generic-failure/`) to verify error handling and
`on_job_failure: abort_remaining_chain` propagation, and one `POST /prompt`
validation-failure case (`prompt-validation-failure/`).
