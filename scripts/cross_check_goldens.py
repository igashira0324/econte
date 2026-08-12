#!/usr/bin/env python3
"""Cross-language consistency check for econte's golden fixtures.

For every file in ``spec/fixtures/*.json`` this script:

1. Determines the filename-implied expectation (``valid-*`` -> accept,
   ``invalid-*`` -> reject).
2. Validates the fixture in-process with the Python/pydantic implementation
   (``import econte``).
3. Validates the fixture out-of-process with the TypeScript/Zod
   implementation, by shelling out to
   ``packages/econte/scripts/validate-cli.mjs`` via Node and checking its
   exit code (0 = valid, 1 = invalid).
4. Compares all three verdicts (filename, Python, TypeScript) and prints a
   PASS/FAIL table.

Exits non-zero if either implementation disagrees with the filename-implied
expectation, or if the two implementations disagree with each other.

This is the script referenced by ``.github/workflows/ci.yml``'s
"cross-language-consistency" job.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "spec" / "fixtures"
TS_PACKAGE_DIR = REPO_ROOT / "packages" / "econte"
TS_CLI = TS_PACKAGE_DIR / "scripts" / "validate-cli.mjs"


def expected_verdict(filename: str) -> bool | None:
    """True = expected valid, False = expected invalid, None = unrecognized."""
    if filename.startswith("valid-"):
        return True
    if filename.startswith("invalid-"):
        return False
    return None


def python_verdict(fixture_path: Path) -> tuple[bool, str]:
    """Return (is_valid, detail) using the in-process Python implementation."""
    # Imported lazily so that a missing/broken `econte` install produces a
    # clear error message rather than an import-time crash before argv
    # parsing even happens.
    from econte import validate_storyboard

    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"

    ok, errors = validate_storyboard(data)
    detail = "" if ok else "; ".join(errors)
    return ok, detail


def typescript_verdict(fixture_path: Path) -> tuple[bool, str]:
    """Return (is_valid, detail) by shelling out to validate-cli.mjs."""
    proc = subprocess.run(
        ["node", str(TS_CLI), str(fixture_path)],
        cwd=str(TS_PACKAGE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ok = proc.returncode == 0
    detail = "" if ok else (proc.stderr.strip() or proc.stdout.strip())
    return ok, detail


def main() -> int:
    if not FIXTURES_DIR.is_dir():
        print(f"error: fixtures directory not found: {FIXTURES_DIR}", file=sys.stderr)
        return 1

    if not TS_CLI.is_file():
        print(f"error: TypeScript validator CLI not found: {TS_CLI}", file=sys.stderr)
        return 1

    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        print(f"error: no fixtures found in {FIXTURES_DIR}", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str, str, bool]] = []
    any_failure = False

    for fixture_path in fixtures:
        name = fixture_path.name
        expected = expected_verdict(name)

        if expected is None:
            rows.append((name, "???", "???", "???", False))
            any_failure = True
            print(f"UNRECOGNIZED FILENAME (no valid-/invalid- prefix): {name}", file=sys.stderr)
            continue

        py_ok, py_detail = python_verdict(fixture_path)
        ts_ok, ts_detail = typescript_verdict(fixture_path)

        py_matches = py_ok == expected
        ts_matches = ts_ok == expected
        agree = py_ok == ts_ok
        row_pass = py_matches and ts_matches and agree

        if not row_pass:
            any_failure = True

        rows.append(
            (
                name,
                "valid" if expected else "invalid",
                "valid" if py_ok else "invalid",
                "valid" if ts_ok else "invalid",
                row_pass,
            )
        )

        if not py_matches:
            print(f"  [{name}] Python verdict disagrees with filename: {py_detail}", file=sys.stderr)
        if not ts_matches:
            print(f"  [{name}] TypeScript verdict disagrees with filename: {ts_detail}", file=sys.stderr)
        if py_matches and ts_matches and not agree:
            print(
                f"  [{name}] Python and TypeScript disagree with each other "
                f"(py={'valid' if py_ok else 'invalid'}, ts={'valid' if ts_ok else 'invalid'})",
                file=sys.stderr,
            )

    # --- print table -------------------------------------------------------
    name_width = max(len(r[0]) for r in rows)
    header = f"{'fixture':<{name_width}}  {'expected':<8}  {'python':<8}  {'typescript':<10}  result"
    print(header)
    print("-" * len(header))
    for name, expected_s, py_s, ts_s, row_pass in rows:
        status = "PASS" if row_pass else "FAIL"
        print(f"{name:<{name_width}}  {expected_s:<8}  {py_s:<8}  {ts_s:<10}  {status}")

    total = len(rows)
    passed = sum(1 for r in rows if r[4])
    print()
    print(f"{passed}/{total} fixtures consistent across filename, Python, and TypeScript")

    if any_failure:
        print("\nRESULT: FAIL", file=sys.stderr)
        return 1

    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
