# econte threat model

This file follows the layout of Anthropic's OSS Scanner
(`projects/<name>/threat_model.md`): what is trusted, where untrusted input
enters, what an attacker gains, and how to rate findings. It is also the
input for the repository's own audits (`.oss-scanner/scan.yaml`,
`.claude/skills/security-audit/`).

## What econte is

A storyboard schema (TypeScript/Zod and Python/pydantic) plus a Python CLI
that turns a storyboard into ComfyUI jobs (`compile`), runs them against a
ComfyUI server (`run`), writes the results back (`ingest`) and renders an
HTML approval sheet (`sheet`). It runs on the user's own machine; there is
no service component and no authentication of its own.

## Trust boundaries

| Input | Trust | Why |
|---|---|---|
| `storyboard.json` | **untrusted** | made to be shared between collaborators, downloaded from the web, produced by other tools |
| `profiles/*.yaml` | **untrusted** | shared alongside storyboards; a profile is a ComfyUI workflow template, server defaults and an output glob |
| manifest JSON (`econte run`) | **untrusted** | usually produced by `compile`, but hand-edited and shared in practice |
| delivery report JSON (`econte ingest`) | **untrusted** | written by `econte run`, whose `job.file` comes from the profile's `output.glob`; also hand-edited and shared |
| ComfyUI HTTP responses (`/prompt`, `/history`) | **untrusted** | the server is often on another machine on the LAN; a compromised server must not get code execution or file access on the operator's machine |
| image files referenced by a storyboard | **untrusted** | they come from wherever the storyboard came from |
| command-line arguments, environment, current directory | trusted | the local operator |
| the Python/Node runtimes and installed dependencies | trusted (but audited) | `pip-audit`, `npm audit`, CodeQL, Dependabot |

## Untrusted entry points (file:function)

- `python/econte/cli.py:_cmd_validate`, `_load_storyboard`: JSON parse and
  schema validation of a storyboard file.
- `packages/econte/scripts/validate-cli.mjs`, `src/index.ts:validateStoryboard`:
  the same for the TypeScript implementation.
- `python/econte/converters/compile.py:compile_storyboard`: reads
  `source.backend`, `source.prompt`, `source.keyframe`, `source.seed` and
  loads `profiles/<backend>.yaml`.
- `python/econte/runners/profile.py:load_profile`: `yaml.safe_load` of a
  profile. The profile's `server.default_host/port` decides where `run`
  connects, its workflow template is filled with manifest fields, and its
  `output.glob` decides which file becomes a job's output.
- `python/econte/runners/manifest.py:load_manifest`: manifest JSON.
- `python/econte/runners/client.py` and `runner.py`: HTTP to ComfyUI.
  Outputs are found by globbing the profile's `output.glob` under the output
  directory (`runners/report.py:resolve_output_file`), and the match becomes
  the report's `job.file`.
- `python/econte/converters/ingest.py:ingest_report`: writes `job.file` from
  a report into `source.keyframe` / `render.file`.
- `python/econte/converters/sheet.py:build_sheet_html`: opens and decodes the
  keyframe image files with Pillow and embeds them in HTML.

## What an attacker wants

1. Code execution on the operator's machine from a shared storyboard,
   profile, manifest, report, image file, or a ComfyUI response.
2. Reading files outside the project (for example by getting them embedded
   into a sheet that is then shared), or writing files outside the project
   (manifests, reports, the storyboard itself).
3. Making `econte run` talk to a host of the attacker's choosing (SSRF
   into the operator's LAN).
4. Hanging or exhausting the CLI on a crafted document.

## Severity guidance

Rate on the **default path**: what happens when the operator does what the
tool asks of them with the untrusted file. Then weigh how much of the
outcome the attacker controls.

- **Critical**: code execution from any untrusted input above.
- **High**: reading arbitrary files, or writing attacker-controlled content
  to an attacker-chosen path, by default; secrets exposure.
- **Medium**: overwriting files at an attacker-chosen path with content the
  attacker does not control; leaking a narrow class of files (for example
  images, as thumbnails) once the operator takes one more step, such as
  sharing the generated sheet; SSRF or connection to an attacker-chosen host
  by default; XSS in the generated sheet (it is opened in a browser); denial
  of service from a small input.
- **Low**: needs an opt-in flag, a command the operator wrote themselves, a
  trusted input, or a very large input; reading a file whose content reaches
  only the operator's own console; hardening gaps with no demonstrated path.

**Opt-in rule.** If reaching a path needs an extra deliberate step by the
operator (an opt-in flag such as `--allow-external-keyframes`, or running a
command they wrote themselves), rate it one level lower than the same path
reached by default.

**Who decides.** The second pass re-derives every finding and rates it with
this rubric, and its rating is recorded as the finding's severity. When it
differs from the first pass, both are kept in `findings.json` and the owner
makes the final call.

Examples for econte (ratings from the 2026-10-25 second pass):

| Path | Reached by default? | Rating |
|---|---|---|
| shared storyboard: `source.backend` makes `compile` overwrite any `.json` file with a manifest | yes; the content is a fixed-shape manifest | Medium |
| shared storyboard: `source.backend` makes `compile` load any `.yaml` file as the profile | yes; parsed with `safe_load`, errors reach only the console | Low |
| shared storyboard: `sheet` embeds a local image outside its directory | yes; the image leaks only if the sheet is shared | Medium |
| the same, with `--allow-external-keyframes` | no (opt-in) | Low |
| 40 MB storyboard | yes | Low (the 32 MiB limit refuses it) |

## Out of scope

- The security of ComfyUI itself and of model files; econte assumes the
  server is hostile, not that it is safe.
- Prompt content: econte forwards prompts verbatim and makes no promise
  about what a model generates from them.
- Media duration or codec handling: econte never decodes video.

## Things that look like bugs but are not

- `econte ingest` may write an **absolute** `render.file` / `source.keyframe`
  when the ComfyUI output directory and the storyboard are on different
  Windows drives (no relative path exists). That value is computed by econte
  from `--comfyui-output-dir`, not taken from the report.
- The HTML sheet contains `data:` URIs with base64 JPEG data; those are
  re-encoded thumbnails, not the original files.
