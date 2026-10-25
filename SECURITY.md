# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's
private vulnerability reporting on this repository ("Security" tab →
"Report a vulnerability"). You will get an acknowledgement within a week,
and a fix or a documented decision within 90 days.

## Threat model

The full threat model lives in [`.oss-scanner/threat_model.md`](.oss-scanner/threat_model.md).
In short, econte treats these as **untrusted**:

- storyboard, profile, manifest and delivery-report files you did not write
  yourself (they are made to be shared and sent around);
- every response from the ComfyUI server (`/prompt`, `/history`);
- the image files a storyboard points at.

Command-line arguments and the machine's own configuration are trusted.

## What the implementation guarantees

- Fields that become file names (`source.backend`, manifest `profile`,
  `output_prefix`, `jobs[].id`) are restricted to `^[A-Za-z0-9_-]+$`, in
  both the TypeScript and the Python implementation.
- `econte sheet` embeds only keyframes inside the storyboard's own
  directory, decodes only PNG, JPEG and WebP, and refuses images above 64
  megapixels before decoding them.
- `econte ingest` never writes a report path that is absolute,
  root-relative, has a drive letter or a `..` segment, or (with
  `--comfyui-output-dir`) resolves outside that directory.
- Array sizes and the total shot count are bounded (`docs/schema-spec.md`,
  rule 7) and checked before any element is validated; both CLIs refuse
  storyboard files larger than 32 MiB.
- No `pickle`, `eval`, `exec`, `shell=True` or unsafe YAML loading anywhere.

## Continuous checks

- `.github/workflows/security.yml`: CodeQL (Python, TypeScript and the
  workflows), `pip-audit`, and an `npm audit` gate whose only exceptions are
  listed, each with its mitigation, in `packages/econte/scripts/audit-gate.mjs`.
  It runs on every change and weekly.
- `.github/dependabot.yml`: dependency update PRs.
- `.oss-scanner/`: the scan profile (`scan.yaml`), the threat model, the
  findings ledger with stable IDs (`findings.json`), the last full-scan
  baseline (`baseline.json`) and an offline-auditable `Dockerfile`, in the
  layout of Anthropic's [OSS Scanner](https://github.com/anthropics/oss-scanner).
  `.claude/skills/security-audit/SKILL.md` describes the audit procedure,
  including the independent second pass every finding goes through.
