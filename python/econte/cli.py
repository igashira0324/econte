"""Command-line interface for econte.

``validate`` loads a JSON file and runs it through
:func:`econte.validate_storyboard`, printing ``OK`` and exiting 0 on
success, or printing the validation errors and exiting non-zero on
failure.

``run`` loads a manifest + its profile and either prints a dry-run
constraint/cost report (``--dry-run``, no network call) or drives a real
ComfyUI server through the jobs, writing ``<manifest>_report.json`` next to
the manifest file. See ``docs/profile-spec.md`` for the full algorithm.

``compile``, ``ingest``, and ``sheet`` are a later phase of this project
(see ``docs/implementation-plan.md``) and are intentionally not stubbed out
here with placeholder logic -- they will be added when their underlying
machinery exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import validate_storyboard
from .runners import (
    ComfyUIClient,
    DryRunReport,
    ManifestError,
    ProfileError,
    dry_run,
    load_manifest,
    load_profile,
)
from .runners import (
    run as run_manifest,
)


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


def _print_dry_run_report(report: DryRunReport) -> None:
    errors = [i for i in report.issues if i.severity == "error"]
    warnings = [i for i in report.issues if i.severity == "warning"]

    if errors:
        print(f"{len(errors)} error(s):")
        for issue in errors:
            print(f"  [{issue.job_id}] {issue.field}: {issue.message}")
    if warnings:
        print(f"{len(warnings)} warning(s):")
        for issue in warnings:
            print(f"  [{issue.job_id}] {issue.field}: {issue.message}")
    if not errors and not warnings:
        print("no constraint problems found")

    print()
    print(f"cost estimate: {report.cost.total_seconds:.1f}s total")
    for job_cost in report.cost.per_job:
        print(f"  [{job_cost.id}] {job_cost.seconds:.1f}s")


def _cmd_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    profile_path = Path(args.profile_dir) / f"{manifest.profile}.yaml"
    try:
        profile = load_profile(profile_path)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = dry_run(profile, manifest)
    _print_dry_run_report(report)

    if args.dry_run:
        return 1 if report.has_errors else 0

    if report.has_errors:
        print(
            "error: constraint violations found above; fix the manifest before running",
            file=sys.stderr,
        )
        return 1

    host = args.host or profile.server.default_host
    port = args.port or profile.server.default_port
    client = ComfyUIClient(f"http://{host}:{port}")
    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()

    print()
    print(f"waiting for ComfyUI server at {host}:{port} ...")
    delivery = run_manifest(
        profile,
        manifest,
        client,
        only=args.only,
        output_dir=output_dir,
        job_timeout_s=args.timeout,
        manifest_path=str(manifest_path),
    )

    report_path = manifest_path.with_name(f"{manifest_path.stem}_report.json")
    report_path.write_text(
        json.dumps(delivery.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )

    n_success = sum(1 for j in delivery.jobs if j.status == "success")
    n_failed = sum(1 for j in delivery.jobs if j.status == "failed")
    n_missing = sum(1 for j in delivery.jobs if j.status == "missing")
    print()
    print(
        f"done: {n_success} success, {n_failed} failed, {n_missing} missing "
        f"({len(delivery.jobs)} job(s) total)"
    )
    print(f"wrote {report_path}")

    return 1 if (n_failed or n_missing) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="econte", description="econte storyboard toolchain")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="validate a storyboard JSON file against the econte schema"
    )
    validate_parser.add_argument("path", help="path to a storyboard JSON file")

    run_parser = subparsers.add_parser(
        "run", help="run a manifest against a ComfyUI server (or --dry-run to only estimate)"
    )
    run_parser.add_argument("manifest", help="path to a manifest JSON file")
    run_parser.add_argument(
        "--profile-dir",
        default="profiles",
        help="directory containing <profile>.yaml files (default: profiles)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the constraint report and cost estimate; make no network call",
    )
    run_parser.add_argument(
        "--only",
        nargs="+",
        metavar="ID",
        default=None,
        help="only (re)run these job ids from the manifest",
    )
    run_parser.add_argument("--host", default=None, help="override profile.server.default_host")
    run_parser.add_argument(
        "--port", type=int, default=None, help="override profile.server.default_port"
    )
    run_parser.add_argument(
        "--output-dir",
        default=None,
        help="ComfyUI output directory to resolve output.glob against (default: current directory)",
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=3600,
        help="per-job timeout in seconds while polling /history (default: 3600)",
    )

    # NOTE: `compile`, `ingest`, and `sheet` subcommands land in a later
    # phase of this project (see docs/implementation-plan.md) once the
    # compile/ingest/sheet machinery they depend on exists. They are
    # deliberately not registered here yet.

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return _cmd_validate(args.path)
    if args.command == "run":
        return _cmd_run(args)

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse.error() exits the process


if __name__ == "__main__":
    raise SystemExit(main())
