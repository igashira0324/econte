"""Command-line interface for econte.

``validate`` loads a JSON file and runs it through
:func:`econte.validate_storyboard`, printing ``OK`` and exiting 0 on
success, or printing the validation errors and exiting non-zero on
failure.

``run`` loads a manifest + its profile and either prints a dry-run
constraint/cost report (``--dry-run``, no network call) or drives a real
ComfyUI server through the jobs, writing ``<manifest>_report.json`` next to
the manifest file. See ``docs/profile-spec.md`` for the full algorithm.

``compile`` and ``ingest`` close the loop described in
``docs/compile-spec.md``: ``compile`` turns a storyboard into per-backend
manifest files, ``ingest`` writes a delivery report's results back into a
storyboard by shot id. ``sheet`` renders a self-contained HTML approval
sheet for human review (read-only -- it never writes back into
``storyboard.json``); see ``docs/compile-spec.md``'s "econte sheet" section
and :mod:`econte.converters.sheet`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from . import Storyboard, validate_storyboard
from .converters import CompileError, compile_storyboard, ingest_report, slugify
from .converters.sheet import build_sheet_html, format_summary_line, summarize_storyboard
from .runners import (
    ComfyUIClient,
    DeliveryReport,
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


def _load_storyboard(path: Path) -> tuple[Storyboard | None, int]:
    """Read + parse + schema-validate a storyboard JSON file, reusing the
    exact read/parse/validate handling ``_cmd_validate`` uses (same error
    messages, same read-failure/parse-failure exit code) so ``compile`` and
    ``ingest`` don't each duplicate it.

    Returns ``(storyboard, 0)`` on success, or ``(None, exit_code)`` with an
    error already printed to stderr: ``2`` for a read/JSON-parse failure
    (mirroring ``_cmd_validate``'s own I/O error handling), ``1`` for a
    schema validation failure (mirroring ``_cmd_validate``'s own exit code
    for "the document itself is invalid").
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return None, 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        return None, 2

    ok, errors = validate_storyboard(data)
    if not ok:
        for error in errors:
            print(error, file=sys.stderr)
        return None, 1

    return Storyboard.model_validate(data), 0


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


def _cmd_compile(args: argparse.Namespace) -> int:
    storyboard_path = Path(args.storyboard)
    storyboard, exit_code = _load_storyboard(storyboard_path)
    if storyboard is None:
        return exit_code

    try:
        result = compile_storyboard(
            storyboard,
            target=args.target,
            profile_dir=Path(args.profile_dir),
            width=args.width,
            height=args.height,
        )
    except CompileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"warning: {warning}")

    if not result.groups:
        print(
            f"error: nothing to compile for --target {args.target}: 0 eligible shot(s)",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else storyboard_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(storyboard.metadata.title)

    for group in result.groups:
        for notice in group.warnings:
            print(f"notice: {notice}")
        manifest_path = output_dir / f"{slug}_{args.target}_{group.backend}.json"
        manifest_path.write_text(
            json.dumps(group.manifest.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[{group.backend}] {len(group.manifest.jobs)} job(s) -> wrote {manifest_path}")

    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    storyboard_path = Path(args.storyboard)
    storyboard, exit_code = _load_storyboard(storyboard_path)
    if storyboard is None:
        return exit_code

    report_path = Path(args.report)
    try:
        report_raw = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {report_path}: {exc}", file=sys.stderr)
        return 2

    try:
        report_data = json.loads(report_raw)
    except json.JSONDecodeError as exc:
        print(f"error: {report_path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    try:
        report = DeliveryReport.model_validate(report_data)
    except ValidationError as exc:
        print(
            f"error: {report_path} does not match the expected delivery report schema:\n{exc}",
            file=sys.stderr,
        )
        return 2

    comfyui_output_dir = Path(args.comfyui_output_dir) if args.comfyui_output_dir else None
    result = ingest_report(
        storyboard,
        report,
        target=args.target,
        comfyui_output_dir=comfyui_output_dir,
        storyboard_dir=storyboard_path.parent,
    )

    output_path = Path(args.output) if args.output else storyboard_path
    output_path.write_text(
        json.dumps(result.storyboard.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )

    updated_desc = ", ".join(result.updated) if result.updated else "(none)"
    print(f"updated {len(result.updated)} shot(s): {updated_desc}")

    if result.skipped:
        print(f"{len(result.skipped)} job(s) skipped (non-success status):")
        for skipped_job in result.skipped:
            print(f"  [{skipped_job.status}] {skipped_job.id}")

    if result.unmatched_report_ids:
        print(f"{len(result.unmatched_report_ids)} report job id(s) had no matching shot:")
        for unmatched_id in result.unmatched_report_ids:
            print(f"  {unmatched_id}")

    print(f"wrote {output_path}")

    return 0


def _print_console_safe(text: str) -> None:
    """``print(text)``, but falling back to a lossy re-encode if the
    terminal's codepage can't represent every character.

    The sheet summary line uses "·" (U+00B7), which is not representable
    in cp932 -- the default console codepage on Japanese Windows, a known
    Windows-first trap this project explicitly guards against
    (``docs/implementation-plan.md``'s cp932-console note). Rather than let
    that crash ``econte sheet`` outright, degrade gracefully to `?`-style
    replacement characters on an incapable console; the exact text is still
    written correctly to the (UTF-8) HTML file either way.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding))


def _cmd_sheet(args: argparse.Namespace) -> int:
    storyboard_path = Path(args.storyboard)
    storyboard, exit_code = _load_storyboard(storyboard_path)
    if storyboard is None:
        return exit_code

    total, with_keyframe, approved = summarize_storyboard(storyboard)
    _print_console_safe(format_summary_line(total, with_keyframe, approved))

    html_text = build_sheet_html(
        storyboard,
        storyboard_dir=storyboard_path.parent,
        thumb_width=args.thumb_width,
    )

    output_path = (
        Path(args.output)
        if args.output
        else storyboard_path.with_name(f"{storyboard_path.stem}_sheet.html")
    )
    output_path.write_text(html_text, encoding="utf-8")
    print(f"wrote {output_path}")

    return 0


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

    compile_parser = subparsers.add_parser(
        "compile", help="compile a storyboard into per-backend manifest files"
    )
    compile_parser.add_argument("storyboard", help="path to a storyboard JSON file")
    compile_parser.add_argument(
        "--target",
        required=True,
        choices=["keyframes", "clips"],
        help="which kind of manifest to produce",
    )
    compile_parser.add_argument(
        "--width", required=True, type=int, help="pixel width for this compile pass"
    )
    compile_parser.add_argument(
        "--height", required=True, type=int, help="pixel height for this compile pass"
    )
    compile_parser.add_argument(
        "--profile-dir",
        default="profiles",
        help="directory containing <backend>.yaml profiles (default: profiles)",
    )
    compile_parser.add_argument(
        "--output-dir",
        default=None,
        help="where manifest files are written (default: alongside storyboard.json)",
    )

    ingest_parser = subparsers.add_parser(
        "ingest", help="ingest a delivery report's results back into a storyboard"
    )
    ingest_parser.add_argument("storyboard", help="path to a storyboard JSON file")
    ingest_parser.add_argument("report", help="path to a <manifest>_report.json delivery report")
    ingest_parser.add_argument(
        "--target",
        required=True,
        choices=["keyframes", "clips"],
        help="which kind of report is being ingested",
    )
    ingest_parser.add_argument(
        "--output",
        default=None,
        help="write the updated storyboard here instead of overwriting the input",
    )
    ingest_parser.add_argument(
        "--comfyui-output-dir",
        default=None,
        help=(
            "ComfyUI output directory that the report's job.file paths are relative to "
            "(docs/profile-spec.md); when given, job.file is rebased onto the storyboard's own "
            "directory before being written (docs/schema-spec.md's paths convention). "
            "Default: assume the report's paths are already storyboard-relative (no rebasing) "
            "-- correct only when the two directories coincide."
        ),
    )

    sheet_parser = subparsers.add_parser(
        "sheet", help="generate a self-contained HTML approval sheet for a storyboard"
    )
    sheet_parser.add_argument("storyboard", help="path to a storyboard JSON file")
    sheet_parser.add_argument(
        "--output",
        default=None,
        help="output HTML path (default: <storyboard-stem>_sheet.html next to the storyboard)",
    )
    sheet_parser.add_argument(
        "--thumb-width",
        type=int,
        default=420,
        help="keyframe thumbnail width in pixels, aspect ratio preserved (default: 420)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return _cmd_validate(args.path)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "compile":
        return _cmd_compile(args)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "sheet":
        return _cmd_sheet(args)

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse.error() exits the process


if __name__ == "__main__":
    raise SystemExit(main())
