"""Command-line interface for econte.

Only the ``validate`` subcommand is implemented in this phase: it loads a
JSON file and runs it through :func:`econte.validate_storyboard`, printing
``OK`` and exiting 0 on success, or printing the validation errors and
exiting non-zero on failure.

``compile``, ``run``, ``ingest``, and ``sheet`` are a later phase of this
project (see ``docs/implementation-plan.md``) and are intentionally not
stubbed out here with placeholder logic -- they will be added when their
underlying manifest/runner machinery exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import validate_storyboard


def _cmd_validate(path: str) -> int:
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    ok, errors = validate_storyboard(data)
    if ok:
        print("OK")
        return 0

    for error in errors:
        print(error, file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="econte", description="econte storyboard toolchain")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="validate a storyboard JSON file against the econte schema"
    )
    validate_parser.add_argument("path", help="path to a storyboard JSON file")

    # NOTE: `compile`, `run`, `ingest`, and `sheet` subcommands land in a
    # later phase of this project (see docs/implementation-plan.md) once
    # the manifest/runner machinery they depend on exists. They are
    # deliberately not registered here yet.

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return _cmd_validate(args.path)

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse.error() exits the process


if __name__ == "__main__":
    raise SystemExit(main())
