# Example: `haruka`

A complete, runnable econte project: an original character, an 8-shot
storyboard, and the keyframes generated from it — everything you need to
see the whole pipeline without inventing your own content first.

## What this is

`haruka.storyboard.json` is a short vertical (9:16) piece about someone
leaving an apartment at dusk. It is deliberately built to exercise the
parts of econte that matter, not just the happy path:

| Shot | What it demonstrates |
|---|---|
| `S01-A` | Character-free B-roll (`subject: null`, `material: standalone`) — the establishing shot |
| `S01-B` | A character shot resolving `ref_image` from the character bible |
| `S02-A` | A closer shot (`MCU`) starting its own chain, with a `lyric` line attached |
| `S02-B` | An insert shot (`INS`) cutting away from the character entirely |
| `S03-A` | A new chain origin — new location, new framing |
| `S03-B` | `material: "chain"` + `chain_from: "S03-A"`, continuing the previous shot's take |
| `S03-C` | Breaking the chain to change framing (a chained clip cannot reframe — see below) |
| `S04-A` | Closing B-roll that mirrors the opening |

That mix is the point. A single generation chain can only ever produce
one continuous take: the character stays on screen and the framing is
fixed at the chain's origin. Cutting away, changing shot size, or showing
the world without the character in it all require *separate* material,
assembled by an editor afterwards. The storyboard is where you plan that
mix; `material`/`chain_from` is how you tell the generator about it.

## The character

`characters/haruka/` holds a three-view reference sheet (front, side,
back). `front.png` was generated from text; `side.png` and `back.png`
were generated *from* `front.png` so all three depict the same person.
`Character.identity` in the storyboard is the one-line description that
gets pasted into every prompt referencing her.

haruka is an original character created for this repository and released
under CC0 (public domain dedication) along with the generated images in
this directory — you may reuse them freely, including commercially, with
no attribution required. See `CONTRIBUTING.md` at the repository root:
examples must never contain third-party IP or real-person likenesses.

## What's already here

**Keyframes.** The images in `keyframes/` were produced by econte itself,
on an RTX 3060 12GB, from exactly the commands below — 7 shots at
864x1536, ~28s each for the character-free B-roll (the profile's
`no_ref` variant) and ~48s each for the character shots (`with_ref`),
5m43s total. The files committed here are downscaled to 768px JPEG to
keep the repository small; the generator produced full-resolution PNGs.

`haruka-sample_keyframes_qwen-image-edit-2511.json` (the compiled
manifest) and `..._report.json` (the delivery report) are committed too,
so you can read what a real manifest and a real report look like without
running anything.

**Video.** `S03-A`'s approved keyframe (above) was also used to seed a
real chained video sequence via `minimax-h3-motion-context`: `S03-B`
(`material: chain_start`, seeded from `S03-A`'s keyframe) then `S03-D`
(`material: chain`, `chain_from: S03-B`) — the mechanism that lets a
generator continue one continuous take across a cut instead of every
clip re-guessing motion from a single still. Measured: 601.8s + 701.9s
= 22.1 minutes total at 576x1024, matching the `--dry-run` estimate
(1296.0s) to within 0.6%. The chain's join is frame-exact — clip 1's
last frame and clip 2's first frame are pixel-identical, which is what
Motion Context's pinned-frame handoff is supposed to guarantee.

`haruka-sample_clips_minimax-h3-motion-context.json` and its
`..._report.json` are committed for the same reason as the keyframes
pair. The generated `.mp4` files themselves are **not** committed
(repository media policy — see the root `.gitignore`); `S03-B`/`S03-D`'s
`render` field is therefore left unset here even though a real,
successful render exists — the report is the record of it.

## Running it yourself

The reference profiles this example names (`qwen-image-edit-2511`,
`minimax-h3-motion-context`) point at specific model files on the
author's ComfyUI install. Adjust `profiles/*.yaml` to match your own
model paths, or point the shots at a profile of your own — see
`profiles/README.md` and `docs/profile-spec.md`.

Everything except step 4 works with no GPU and no ComfyUI server:

```bash
# 1. Check the storyboard is well-formed (offline)
econte validate examples/haruka/haruka.storyboard.json

# 2. Turn it into a keyframe generation manifest (offline)
econte compile examples/haruka/haruka.storyboard.json \
  --target keyframes --width 864 --height 1536 --output-dir examples/haruka

# 3. See what it would cost before running anything (offline, no server)
econte run examples/haruka/haruka-sample_keyframes_qwen-image-edit-2511.json --dry-run

# 4. Actually generate (needs ComfyUI running with the profile's models).
#    Copy characters/haruka/*.jpg into your ComfyUI input directory first,
#    under the same relative path the manifest names.
econte run examples/haruka/haruka-sample_keyframes_qwen-image-edit-2511.json \
  --output-dir /path/to/ComfyUI/output

# 5. Write the results back into the storyboard
econte ingest examples/haruka/haruka.storyboard.json \
  examples/haruka/haruka-sample_keyframes_qwen-image-edit-2511_report.json \
  --target keyframes --comfyui-output-dir /path/to/ComfyUI/output

# 6. Build the approval sheet and look at what you got
econte sheet examples/haruka/haruka.storyboard.json --output examples/haruka/approval.html
```

Note that step 2 prints a warning that `S03-B` was skipped: that shot
names a *video* backend, and this is a keyframes pass. That is correct
behavior, not an error — a storyboard mid-production routinely has shots
staged for different passes, and compiling one target never fails the
whole document because of the others.

Then flip `approved: true` on the shots you want to keep, re-run step 2
with `--target clips` (only approved shots compile), and the video
backend animates the approved stills rather than guessing from the
character sheet again.

## Note on `approved`

Every shot in this example ships with `approved: false`. That is not an
oversight — it is the initial state of any real storyboard. The approval
gate exists so that unreviewed keyframes can never silently become the
basis for the (far more expensive) video generation pass.
