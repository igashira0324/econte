# Backend profiles

A profile connects an econte manifest to *your* ComfyUI workflow: it's a
YAML file describing the API-format graph, how manifest fields map onto
node inputs, generation constraints (resolution multiples, VRAM, etc.), and
a cost model used for `--dry-run` time estimates. Profiles are data, not
code — adding a new backend should never require changing runner Python.

Reference profiles land in Phase P2 of `docs/implementation-plan.md`:

- `qwen-image-edit-2511.yaml` — keyframe generation (Qwen-Image-Edit 2511 +
  Lightning LoRA), verified at ~40s/frame on a 12GB GPU.
- `minimax-h3-motion-context.yaml` — chained video clip generation (MiniMax
  H3 + Motion Context), verified at ~13.5 min/clip on a 12GB GPU.

See `custom-workflow.md` (also landing in P2) for how to write your own.
