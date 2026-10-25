---
name: security-audit
description: Audit this repository for exploitable vulnerabilities in the OSS Scanner style: scan profile and threat model first, then entry points, then findings with reproducers, a second independent pass, and a ledger with stable IDs. Use for a full audit before a release or monthly, or a diff audit after changes to the scan scope.
---

# Security audit (OSS Scanner style)

Inputs, in this order: `.oss-scanner/scan.yaml` (scope, untrusted inputs, severity rule),
`.oss-scanner/threat_model.md` (trust boundaries and the severity rubric), and
`.oss-scanner/findings.json` (the ledger). Do not rate anything without them.

## Modes
- **full**: the whole `scope` in scan.yaml. Before each release, and at least monthly.
  Full scans are the only way to catch issues that an earlier audit missed.
- **diff**: only files changed since `scanned_commit` in `baseline.json`
  (`git diff --name-only <commit>..HEAD -- <scope>`). Without a baseline, run full.

## Procedure
1. **Build and test offline**: `cd python && pytest -q`,
   `cd packages/econte && npm ci --ignore-scripts && npm test`,
   `python scripts/cross_check_goldens.py`. These are the same steps as `.oss-scanner/Dockerfile`.
2. **Enumerate entry points** from scan.yaml's `untrusted_inputs`. Check that nothing new reaches
   a file system call, a subprocess, a URL, HTML or a deserializer. Trace where each value really
   comes from before you describe it. (The 2026-10-25 audit said a report's `job.file` came from the
   ComfyUI response; `runner.py` actually builds it from a local glob of the profile's `output.glob`.)
3. **Hunt by class** at each entry point: path traversal, command injection, unsafe
   deserialization, SSRF and trusting server responses, XSS in generated HTML, ReDoS,
   unbounded input, CI misuse, vulnerable dependencies (`pip-audit`, `npm audit`, https://api.osv.dev).
   For unbounded input, measure: a size limit only helps if it is enforced before element-wise
   validation. zod 3 keeps validating every element after `.max()` fails; pydantic stops early.
4. **Give every candidate a stable ID.** fingerprint = first 12 hex digits of
   sha256(`rule|file|symbol`). If the fingerprint is already in findings.json, update that entry;
   never add a second one. Otherwise take the next `ECO-NNNN`. IDs are never renumbered or reused.
5. **Reproduce** each candidate with inputs you construct, in a scratch directory, never with
   real data. Put the exact command in `reproducer`. Windows notes:
   - `..` is normalised lexically, even when the directory does not exist, but only when it is
     its own path segment. Test a write traversal with `x/../../y`, not with `x_../y`.
   - A path check must reject a drive (`C:x`), a root (`\x` resolves against the current drive)
     and `..` segments. `PureWindowsPath` splits on both separators.
6. **Second pass (required).** Start a fresh agent that receives ONLY the claim, the file and symbol,
   the reproducer command and the severity rule. It must not receive the first agent's reasoning
   or severity. It reproduces or refutes the claim, checks the fix, and rates with the threat
   model's rubric. Record its result in `second_pass`, its rating as `severity`, and the first-pass
   rating as `first_pass_severity` when they differ. Disagreements go to the owner; they are not
   settled by vote.
7. **Report** only confirmed findings, or findings the owner has confirmed. Unconfirmed candidates
   stay in the ledger as `model-found`.
8. **Fix** in this order: a schema check with a `spec/fixtures/invalid-*.json` and a `valid-*.json`
   pair (so both implementations are pinned), then the sink (confinement where the value is used),
   then the docs (`docs/*.md`, `SECURITY.md`, `CHANGELOG.md`). Add a regression test to
   `python/tests/test_security.py` (or `packages/econte/test/`) for every fix.
9. **Update the ledger.** Status flow: `model-found` → `second-pass-confirmed` →
   `fixed-pending-review` (tests green) → `fixed-confirmed` (the owner reviewed the diff, and
   `human_confirmed` is set to true). `wontfix`, `accepted` and `mitigated` need a `reason`.
10. **Write the baseline** after each full scan: `baseline.json` = `{scanned_commit, scanned_at, mode,
    finding_ids}`. An ID that is not in the previous baseline is a new finding. A finding in a file that
    has not changed since the last baseline, and that the ledger did not contain, is a *previously
    missed* issue. Send it through the second pass as well.

## Rules
- Read-only with respect to the repository until the owner has reviewed the report.
- Never run project code on untrusted input with side effects.
- Every new validation rule needs a golden fixture that `scripts/cross_check_goldens.py` passes in
  both implementations, or a unit test in both languages when the input is too large for a fixture.
