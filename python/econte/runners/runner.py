"""The ``econte run`` orchestration algorithm: offline dry-run validation,
and the real submit/poll/report loop against a ComfyUI server.

See ``docs/profile-spec.md``'s "Runner algorithm" section for the spec this
implements.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .client import ComfyUIClientLike, ComfyUIError, ServerNotReadyError
from .cost import CostError, CostEstimate, estimate
from .manifest import Manifest, resolve_context
from .profile import Profile
from .report import DeliveryReport, JobReport, resolve_output_file
from .selector import SelectorError, select_variant
from .template import TemplateError, build_graph

__all__ = [
    "ConstraintIssue",
    "DryRunReport",
    "JobTimeoutError",
    "dry_run",
    "run",
]


class JobTimeoutError(Exception):
    """Raised when a submitted prompt does not reach a terminal
    ``status.status_str`` within ``job_timeout_s``."""


class ConstraintIssue(BaseModel):
    """One constraint problem found for one job during :func:`dry_run`."""

    job_id: str
    field: str
    severity: Literal["error", "warning"]
    message: str


class DryRunReport(BaseModel):
    """The full offline ``--dry-run`` result: every constraint problem
    found across every job (not just the first), plus the cost estimate.
    Never touches the network or filesystem beyond the already-loaded
    profile/manifest."""

    issues: list[ConstraintIssue]
    cost: CostEstimate

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


def dry_run(profile: Profile, manifest: Manifest) -> DryRunReport:
    """Validate every job's resolved width/height against
    ``profile.constraints`` and confirm every job resolves to exactly one
    variant, collecting ALL problems (not stopping at the first). Also
    computes the cost estimate. Makes no network call and requires no
    ComfyUI server -- safe to run with nothing but the profile/manifest
    files on disk.
    """
    issues: list[ConstraintIssue] = []

    for job in manifest.jobs:
        context = resolve_context(profile, manifest, job)
        width = context.get("width")
        height = context.get("height")

        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            issues.append(
                ConstraintIssue(
                    job_id=job.id,
                    field="width/height",
                    severity="error",
                    message=(
                        f"job has no resolved numeric width/height (got width={width!r}, "
                        f"height={height!r}); set width/height on the job, manifest.defaults, "
                        "or profile.defaults"
                    ),
                )
            )
        else:
            multiple = profile.constraints.resolution_multiple
            if multiple is not None and (int(width) % multiple != 0 or int(height) % multiple != 0):
                issues.append(
                    ConstraintIssue(
                        job_id=job.id,
                        field="resolution_multiple",
                        severity="error",
                        message=f"{width}x{height} is not a multiple of {multiple}",
                    )
                )

            mp_limit = profile.constraints.max_megapixels
            if mp_limit is not None:
                megapixels = (width * height) / 1_000_000
                if megapixels > mp_limit:
                    issues.append(
                        ConstraintIssue(
                            job_id=job.id,
                            field="max_megapixels",
                            severity="warning",
                            message=(
                                f"{width}x{height} = {megapixels:.2f}MP exceeds "
                                f"max_megapixels={mp_limit} (warning only)"
                            ),
                        )
                    )

        try:
            select_variant(profile, context)
        except SelectorError as exc:
            issues.append(
                ConstraintIssue(
                    job_id=job.id, field="variant_selector", severity="error", message=str(exc)
                )
            )

    try:
        cost = estimate(profile, manifest)
    except CostError as exc:
        # Already covered by a per-job "width/height" issue above in the
        # normal case, but estimate() re-derives its own resolved context
        # rather than sharing this loop's, so guard here too rather than
        # letting a missing-width/height job crash dry_run() outright.
        issues.append(
            ConstraintIssue(job_id="<cost>", field="cost", severity="error", message=str(exc))
        )
        cost = CostEstimate(total_seconds=0.0, per_job=[])

    return DryRunReport(issues=issues, cost=cost)


def _execution_error_detail(history_entry: dict[str, Any]) -> str | None:
    """Extract a human-readable error summary from a terminal ``/history``
    entry's ``status.messages``, per the ``execution_error`` message shape
    in ``docs/profile-spec.md``. Returns ``None`` if no such message is
    present (unexpected, but handled rather than assumed)."""
    messages = history_entry.get("status", {}).get("messages", [])
    for message in messages:
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            info = message[1]
            node_id = info.get("node_id")
            node_type = info.get("node_type")
            exception_message = info.get("exception_message")
            return f"node {node_id!r} ({node_type}): {exception_message}"
    return None


def _wait_for_server(client: ComfyUIClientLike, timeout_s: int) -> None:
    """Poll ``/system_stats`` via ``client.get_json`` until it responds, or
    raise :class:`~econte.runners.client.ServerNotReadyError` after
    ``timeout_s`` seconds.

    Deliberately implemented here in terms of ``get_json`` alone -- rather
    than delegating to :meth:`ComfyUIClient.wait_for_server` -- so that
    :func:`run`'s test double never needs to implement anything beyond
    ``post_json``/``get_json`` (see :class:`ComfyUIClientLike`).
    """
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.get_json("/system_stats")
            return
        except ComfyUIError as exc:
            last_error = exc
        time.sleep(2.0)

    raise ServerNotReadyError(
        f"ComfyUI server did not become ready within {timeout_s}s (last error: {last_error})"
    )


def _poll_until_terminal(
    client: ComfyUIClientLike,
    prompt_id: str,
    *,
    poll_interval_s: float,
    job_timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + job_timeout_s
    while True:
        history = client.get_json(f"/history/{prompt_id}")
        entry = history.get(prompt_id)
        if entry is not None:
            status_str = entry.get("status", {}).get("status_str", "")
            if status_str:
                result: dict[str, Any] = entry
                return result

        if time.monotonic() >= deadline:
            raise JobTimeoutError(
                f"prompt {prompt_id!r} did not reach a terminal status within {job_timeout_s}s"
            )
        time.sleep(poll_interval_s)


def _blocked_by_failed_chain(
    job_id: str, resolved_chain_from: dict[str, str | None], failed_ids: set[str]
) -> bool:
    """Walk ``job_id``'s ``chain_from`` ancestry (transitively); True if any
    ancestor is in ``failed_ids``. Used to implement ``on_job_failure:
    abort_remaining_chain``: skip jobs whose chain (however many links
    back) hit a failure, while still running unrelated jobs."""
    current = resolved_chain_from.get(job_id)
    seen: set[str] = set()
    while current is not None and current not in seen:
        seen.add(current)
        if current in failed_ids:
            return True
        current = resolved_chain_from.get(current)
    return False


def _build_delivery_report(
    profile: Profile,
    manifest: Manifest,
    manifest_path: str,
    contexts: dict[str, dict[str, Any]],
    output_dir: Path,
    elapsed_by_id: dict[str, float],
    attempted_status: dict[str, Literal["success", "failed"]],
) -> DeliveryReport:
    """Rebuild the full delivery report from whatever is currently on disk
    for EVERY job in the manifest, not just the ones run this invocation --
    matching both predecessor scripts' "always rebuild from disk state"
    behavior, which is what makes ``--only`` retakes and interrupted-run
    resumes safe."""
    jobs: list[JobReport] = []

    for job in manifest.jobs:
        context = contexts.get(job.id) or resolve_context(profile, manifest, job)
        file_path = resolve_output_file(profile.output, context, output_dir, profile_id=profile.id)

        status: Literal["success", "failed", "missing"]
        file_str: str | None
        if file_path is not None:
            status = "success"
            file_str = str(file_path.relative_to(output_dir)).replace("\\", "/")
        elif attempted_status.get(job.id) == "failed":
            status = "failed"
            file_str = None
        else:
            status = "missing"
            file_str = None

        extra_fields = {
            k: v for k, v in job.model_dump().items() if k not in ("id", "seed", "prompt")
        }

        jobs.append(
            JobReport(
                id=job.id,
                status=status,
                file=file_str,
                elapsedSeconds=elapsed_by_id.get(job.id),
                seed=job.seed,
                prompt=job.prompt,
                **extra_fields,
            )
        )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return DeliveryReport(
        profile=profile.id, manifest=manifest_path, generatedAt=generated_at, jobs=jobs
    )


def run(
    profile: Profile,
    manifest: Manifest,
    client: ComfyUIClientLike,
    *,
    only: list[str] | None = None,
    output_dir: Path,
    poll_interval_s: float = 4.0,
    job_timeout_s: float = 3600,
    manifest_path: str | Path = "",
) -> DeliveryReport:
    """Run (a subset of, if ``only`` is given) ``manifest``'s jobs against a
    live ComfyUI server through ``client``, then always rebuild and return
    the full delivery report from disk state for every job in the
    manifest.

    ``manifest_path`` is only used to populate the report's own
    ``manifest`` field (not part of the algorithm) -- it is not one of the
    fields the runner needs to *do* anything, purely bookkeeping for the
    written report so ``econte ingest`` can find its way back to the
    manifest that produced it.
    """
    _wait_for_server(client, timeout_s=600)

    only_set = set(only) if only is not None else None
    client_id = uuid.uuid4().hex

    contexts: dict[str, dict[str, Any]] = {}
    resolved_chain_from: dict[str, str | None] = {}
    for job in manifest.jobs:
        context = resolve_context(profile, manifest, job)
        contexts[job.id] = context
        resolved_chain_from[job.id] = context.get("chain_from") or None

    failed_ids: set[str] = set()
    elapsed_by_id: dict[str, float] = {}
    attempted_status: dict[str, Literal["success", "failed"]] = {}

    for job in manifest.jobs:
        if only_set is not None and job.id not in only_set:
            continue

        if profile.on_job_failure == "abort_remaining_chain" and _blocked_by_failed_chain(
            job.id, resolved_chain_from, failed_ids
        ):
            print(
                f"[{job.id}] skipped: an earlier job in its chain failed "
                "(on_job_failure: abort_remaining_chain)"
            )
            # Propagate so anything chained off *this* (skipped) job is
            # skipped too -- abort_remaining_chain is transitive.
            failed_ids.add(job.id)
            continue

        context = contexts[job.id]
        try:
            variant_name = select_variant(profile, context)
            graph = build_graph(
                profile.variants[variant_name].graph,
                context,
                profile_id=profile.id,
                variant_name=variant_name,
            )
        except (SelectorError, TemplateError) as exc:
            print(f"[{job.id}] FAILED before submission: {exc}")
            failed_ids.add(job.id)
            attempted_status[job.id] = "failed"
            continue

        print(f"[{job.id}] submitting ({variant_name})...")
        start = time.monotonic()
        try:
            response = client.post_json("/prompt", {"prompt": graph, "client_id": client_id})
            prompt_id = response["prompt_id"]
            entry = _poll_until_terminal(
                client, prompt_id, poll_interval_s=poll_interval_s, job_timeout_s=job_timeout_s
            )
        except (ComfyUIError, JobTimeoutError, KeyError) as exc:
            elapsed = time.monotonic() - start
            elapsed_by_id[job.id] = elapsed
            attempted_status[job.id] = "failed"
            failed_ids.add(job.id)
            print(f"[{job.id}] FAILED after {elapsed:.1f}s: {exc}")
            continue

        elapsed = time.monotonic() - start
        elapsed_by_id[job.id] = elapsed
        status_str = entry.get("status", {}).get("status_str")
        if status_str == "success":
            attempted_status[job.id] = "success"
            print(f"[{job.id}] success in {elapsed:.1f}s")
        else:
            attempted_status[job.id] = "failed"
            failed_ids.add(job.id)
            detail = _execution_error_detail(entry) or f"status_str={status_str!r}"
            print(f"[{job.id}] FAILED after {elapsed:.1f}s: {detail}")

    return _build_delivery_report(
        profile, manifest, str(manifest_path), contexts, output_dir, elapsed_by_id, attempted_status
    )
