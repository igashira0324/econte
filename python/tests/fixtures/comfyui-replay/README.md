# ComfyUI record/replay fixtures

Recorded (see **Provenance** below) ComfyUI HTTP responses, used to drive
runner unit tests without a GPU or a running ComfyUI server — see
`docs/profile-spec.md`'s "Testing: record/replay" section for why this
exists and how the runner is expected to consume it.

## Provenance — read this before trusting these bytes

**These fixtures were hand-constructed, not captured live.** They were
built from real ComfyUI response *shapes* observed against a live server
during a previous session (the raw `POST /prompt` success/failure shapes
and the terminal `GET /history/<id>` shape were given verbatim to the
agent that authored this directory); the `prompt-validation-failure` case's
`prompt_error_response.json` is a real captured example reused verbatim.
Everything else — `prompt_id` values, filenames, node IDs referenced in
error payloads, the OOM traceback text, latent/video filenames — was
filled in by hand to be *plausible and internally consistent* with the
reference profiles in `profiles/`, not re-captured from an actual run.

Treat these as shape/contract fixtures (good for exercising runner control
flow: success parsing, error parsing, chain-abort propagation) rather than
as a guarantee that, e.g., the exact OOM message text matches what your
ComfyUI/PyTorch version will emit. If you have a live ComfyUI server, a
higher-fidelity regeneration would be valuable — see **Follow-up work**
below.

## Directory format

```
comfyui-replay/
  <case-name>/
    meta.json               # always present
    prompt_response.json    # present for cases where POST /prompt succeeded
    history_response.json   # present for cases where a prompt_id was minted
    prompt_error_response.json   # present ONLY for a POST /prompt validation
                                  # failure (HTTP 400) — mutually exclusive
                                  # with the two files above, since no
                                  # prompt_id is ever minted in that case
```

Each `<case-name>` directory is one recorded (or hand-built, see above)
scenario a runner test can replay. A test double HTTP layer serves these
files instead of opening real sockets; per `docs/profile-spec.md`, it
should be keyed by which variant/job the runner's *own built graph*
corresponds to (i.e. the test picks the fixture directory that matches the
manifest/profile/job under test — it does not try to pattern-match the
graph JSON byte-for-byte against a recording).

### `meta.json`

```jsonc
{
  "profile": "<profile id>",   // matches profiles/<id>.yaml's `id` field
  "variant": "<variant name>", // matches a key under that profile's `variants:`
  "description": "one line"
}
```
Lets a test enumerate `comfyui-replay/*/meta.json` and select cases by
profile/variant without hardcoding directory names, the same way
`spec/fixtures/*.json` is discovered by prefix in
`python/tests/test_fixtures.py`.

### `prompt_response.json`

Exactly the JSON body `POST /prompt` returns when ComfyUI accepts the
submitted graph (whether or not the job later succeeds — acceptance and
execution outcome are separate events):

```jsonc
{ "prompt_id": "<uuid>", "number": <int>, "node_errors": {} }
```

### `history_response.json`

Exactly the JSON body `GET /history/<prompt_id>` returns once the job has
reached a terminal state (`status.completed == true`, whether it
succeeded or errored). Shape:

```jsonc
{
  "<prompt_id>": {                 // MUST equal prompt_response.json's prompt_id
    "outputs": {
      "<node_id>": { "images": [{"filename": "...", "subfolder": "...", "type": "output"}] }
      // or "videos": [...] for SaveVideo-producing nodes — the runner
      // resolves real output files by filesystem glob (profile's
      // `output.glob`), not by parsing this field, so the exact key name
      // here is illustrative/plausible rather than load-bearing.
    },
    "status": {
      "status_str": "success" | "error",
      "completed": true | false,   // false observed on the one error case
                                    // recorded here: the queue item did not
                                    // run to completion
      "messages": [
        ["execution_start", {"prompt_id": "<prompt_id>"}],
        // ... zero or more informational messages ...
        ["execution_success", {"prompt_id": "<prompt_id>"}]
        // OR, on failure:
        ["execution_error", {
          "prompt_id": "<prompt_id>", "node_id": "<id>", "node_type": "<ClassType>",
          "exception_message": "...", "exception_type": "...",
          "executed": ["<id>", ...], "traceback": ["..."],
          "current_inputs": {}, "current_outputs": {}
        }]
      ]
    }
  }
}
```

A runner's history-poll loop is expected to treat `status.completed` as
the terminal signal and branch on `status.status_str`; on `"error"` it
should surface `node_id` / `node_type` / `exception_message` from the
`execution_error` message per `docs/profile-spec.md` step 5 ("print the
ComfyUI error detail").

### `prompt_error_response.json` (validation-failure cases only)

Exactly the JSON body of an HTTP 400 response from `POST /prompt` itself —
the graph was rejected before any node executed, so no `prompt_id` exists
and there is no corresponding `history_response.json`. Shape matches
ComfyUI's own `prompt_outputs_failed_validation` error:

```jsonc
{
  "error": {"type": "prompt_outputs_failed_validation", "message": "...", "details": "", "extra_info": {}},
  "node_errors": {
    "<node_id>": {
      "errors": [{"type": "...", "message": "...", "details": "...", "extra_info": {...}}],
      "dependent_outputs": ["<node_id>", ...],
      "class_type": "<ClassType>"
    }
  }
}
```

## Cases in this directory

| case | profile | variant | what it exercises |
|---|---|---|---|
| `qwen-with-ref-success/` | `qwen-image-edit-2511` | `with_ref` | happy path, image output |
| `h3-origin-ec-success/` | `minimax-h3-motion-context` | `origin_ec` | happy path, video output, chain-start latent write |
| `h3-chained-ec-success/` | `minimax-h3-motion-context` | `chained_ec` | happy path, video output continuing a chain |
| `generic-failure/` | `minimax-h3-motion-context` | `origin_ec` | `status_str: "error"` handling; a chain-start job failing is also the scenario `on_job_failure: abort_remaining_chain` needs (a later job with `chain_from` pointing at this one's `id`, even transitively, must be skipped rather than submitted) |
| `prompt-validation-failure/` | `qwen-image-edit-2511` | `with_ref` | HTTP 400 from `POST /prompt` before a `prompt_id` exists — no history poll ever starts |

## Follow-up work

A `scripts/record_fixture.py` that drives a real ComfyUI server (submit a
known manifest/job, capture the raw `POST /prompt` and terminal
`GET /history/<id>` bodies to a new `comfyui-replay/<case-name>/`
directory automatically) would let these be regenerated with actual
byte-for-byte server output instead of hand-built approximations, and
would make it cheap to add fixtures for new profiles as third parties
contribute them. Not built as part of this change — noted here, and in
`CONTRIBUTING.md`'s existing "re-record fixtures against a real server"
guidance, as the natural next step.
