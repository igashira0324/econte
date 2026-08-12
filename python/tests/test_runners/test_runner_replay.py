"""Integration tests for econte.runners.runner.run against the recorded
ComfyUI record/replay fixtures (tests/fixtures/comfyui-replay/) -- exercises
the full submit -> poll -> report control flow, including
`on_job_failure: abort_remaining_chain` propagation, with no GPU and no
real ComfyUI server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from econte.runners import ComfyUIError, JobTimeoutError, Profile, run

from .conftest import make_manifest
from .replay_client import ReplayClient


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake output")


# --- qwen-image-edit-2511 -----------------------------------------------


def test_run_qwen_success(tmp_path: Path, qwen_profile: Profile) -> None:
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        output_prefix="SBdemo",
        defaults={"ref_image": "characters/haruka/front.png", "width": 720, "height": 1280},
        jobs=[{"id": "S01-A", "seed": 1001, "prompt": "a test prompt"}],
    )
    # Per docs/profile-spec.md, output resolution is filesystem-glob-based,
    # not parsed from the /history response -- so the test must place the
    # file itself, matching the fixture's recorded filename.
    _touch(tmp_path / "SBdemo" / "S01-A_00001_.png")

    client = ReplayClient(["qwen-with-ref-success"])
    report = run(
        qwen_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    assert client.submitted_count == 1  # the job was actually submitted, not just found on disk
    assert report.profile == "qwen-image-edit-2511"
    assert len(report.jobs) == 1
    job = report.jobs[0]
    assert job.id == "S01-A"
    assert job.status == "success"
    assert job.file == "SBdemo/S01-A_00001_.png"
    assert job.elapsedSeconds is not None and job.elapsedSeconds >= 0
    assert job.seed == 1001
    assert job.prompt == "a test prompt"


def test_run_qwen_prompt_validation_failure(tmp_path: Path, qwen_profile: Profile) -> None:
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        output_prefix="SBdemo",
        defaults={"ref_image": "characters/haruka/front.png", "width": 720, "height": 1280},
        jobs=[{"id": "S01-X", "seed": 1, "prompt": "p"}],
    )
    client = ReplayClient(["prompt-validation-failure"])
    report = run(
        qwen_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    job = report.jobs[0]
    assert job.status == "failed"
    assert job.file is None


# --- minimax-h3-motion-context: success + chaining ---------------------


def _minimax_manifest(**overrides: Any) -> Any:
    base: dict[str, Any] = dict(
        profile="minimax-h3-motion-context",
        output_prefix="MVdemo",
        defaults={
            "width": 640,
            "height": 1152,
            "latent_folder": "S02-chain",
            "ref_image": "characters/haruka/front.png",
        },
    )
    base.update(overrides)
    return make_manifest(**base)


def test_run_minimax_origin_then_chained_success(tmp_path: Path, minimax_profile: Profile) -> None:
    manifest = _minimax_manifest(
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {"id": "S02-B", "seed": 2, "prompt": "p", "material": "chain", "chain_from": "S02-A"},
        ]
    )
    _touch(tmp_path / "MVdemo" / "S02-A_00001_.mp4")
    _touch(tmp_path / "MVdemo" / "S02-B_00001_.mp4")

    client = ReplayClient(["h3-origin-ec-success", "h3-chained-ec-success"])
    report = run(
        minimax_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    assert client.submitted_count == 2  # both jobs were actually submitted, not just found on disk
    assert [j.status for j in report.jobs] == ["success", "success"]
    assert report.jobs[0].file == "MVdemo/S02-A_00001_.mp4"
    assert report.jobs[1].file == "MVdemo/S02-B_00001_.mp4"
    # every other manifest field is carried through verbatim
    assert report.jobs[1].model_dump()["chain_from"] == "S02-A"
    assert report.jobs[1].model_dump()["material"] == "chain"


def test_run_minimax_generic_failure_reports_failed_not_missing(
    tmp_path: Path, minimax_profile: Profile, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _minimax_manifest(
        jobs=[{"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"}]
    )
    client = ReplayClient(["generic-failure"])
    report = run(
        minimax_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    job = report.jobs[0]
    assert job.status == "failed"
    assert job.file is None
    assert job.elapsedSeconds is not None

    # The task requires the ComfyUI error detail to actually surface
    # somewhere (not just be swallowed into a generic "failed" status) --
    # the fixture's execution_error carries a real CUDA-OOM message with
    # node_id "11" / node_type "SamplerCustomAdvanced"; runner.py prints
    # this via _execution_error_detail(). Verify it made it to stdout.
    out = capsys.readouterr().out
    assert "S02-A" in out
    assert "11" in out
    assert "SamplerCustomAdvanced" in out
    assert "out of memory" in out


def test_run_abort_remaining_chain_skips_downstream_job(
    tmp_path: Path, minimax_profile: Profile
) -> None:
    """S02-A fails (generic-failure); S02-B chains from it and must be
    skipped entirely -- never even submitted -- because
    minimax-h3-motion-context.yaml sets on_job_failure: abort_remaining_chain.
    """
    assert minimax_profile.on_job_failure == "abort_remaining_chain"
    manifest = _minimax_manifest(
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {"id": "S02-B", "seed": 2, "prompt": "p", "material": "chain", "chain_from": "S02-A"},
        ]
    )
    # Only ONE case configured: if the runner incorrectly tried to submit
    # S02-B too, ReplayClient.post_json raises AssertionError and this test
    # fails loudly rather than silently passing.
    client = ReplayClient(["generic-failure"])
    report = run(
        minimax_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    by_id = {j.id: j for j in report.jobs}
    assert by_id["S02-A"].status == "failed"
    # never submitted, no output file on disk -> "missing", not "failed"
    assert by_id["S02-B"].status == "missing"
    assert by_id["S02-B"].elapsedSeconds is None


def test_run_abort_remaining_chain_does_not_block_unrelated_jobs(
    tmp_path: Path, minimax_profile: Profile
) -> None:
    """A standalone job (no chain_from at all) must still run even after an
    unrelated chain-start job fails."""
    manifest = _minimax_manifest(
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {"id": "S03-A", "seed": 3, "prompt": "p", "material": "standalone"},
        ]
    )
    _touch(tmp_path / "MVdemo" / "S03-A_00001_.mp4")
    # S02-A fails (generic-failure); S03-A is unrelated and must still be
    # submitted -- reuse h3-origin-ec-success's shape as a stand-in success
    # response for the unrelated job.
    client = ReplayClient(["generic-failure", "h3-origin-ec-success"])
    report = run(
        minimax_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    assert client.submitted_count == 2
    by_id = {j.id: j for j in report.jobs}
    assert by_id["S02-A"].status == "failed"
    assert by_id["S03-A"].status == "success"


# --- --only filtering -----------------------------------------------------


def test_run_only_filters_jobs(tmp_path: Path, minimax_profile: Profile) -> None:
    manifest = _minimax_manifest(
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {"id": "S03-A", "seed": 2, "prompt": "p", "material": "standalone"},
        ]
    )
    _touch(tmp_path / "MVdemo" / "S02-A_00001_.mp4")
    # Only one case configured: S03-A must never be submitted when --only
    # excludes it.
    client = ReplayClient(["h3-origin-ec-success"])
    report = run(
        minimax_profile,
        manifest,
        client,
        only=["S02-A"],
        output_dir=tmp_path,
        poll_interval_s=0,
        job_timeout_s=5,
    )

    assert client.submitted_count == 1
    by_id = {j.id: j for j in report.jobs}
    assert by_id["S02-A"].status == "success"
    assert by_id["S03-A"].status == "missing"  # not run this invocation, nothing on disk


# --- Report always rebuilt from disk, even for jobs not run this time -----


def test_run_rebuilds_report_for_every_manifest_job_even_if_not_run(
    tmp_path: Path, minimax_profile: Profile
) -> None:
    manifest = _minimax_manifest(
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {"id": "S03-A", "seed": 2, "prompt": "p", "material": "standalone"},
        ]
    )
    # S03-A's output already exists on disk from a PRIOR invocation -- this
    # run only touches S02-A, but the final report must still show S03-A as
    # success because it re-globs disk state for every job.
    _touch(tmp_path / "MVdemo" / "S03-A_00001_.mp4")
    _touch(tmp_path / "MVdemo" / "S02-A_00001_.mp4")
    client = ReplayClient(["h3-origin-ec-success"])
    report = run(
        minimax_profile,
        manifest,
        client,
        only=["S02-A"],
        output_dir=tmp_path,
        poll_interval_s=0,
        job_timeout_s=5,
    )
    assert client.submitted_count == 1
    by_id = {j.id: j for j in report.jobs}
    assert by_id["S02-A"].status == "success"
    assert by_id["S03-A"].status == "success"
    assert by_id["S03-A"].elapsedSeconds is None  # not timed this invocation


# --- Timeout handling (synthetic double, not from fixtures) ---------------


class _NeverTerminalClient:
    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"prompt_id": "stuck", "number": 1, "node_errors": {}}

    def get_json(self, path: str) -> dict[str, Any]:
        if path == "/system_stats":
            return {}
        return {"stuck": {"status": {"status_str": "", "messages": []}}}


def test_run_job_timeout_is_reported_as_failed(tmp_path: Path, minimax_profile: Profile) -> None:
    manifest = _minimax_manifest(
        jobs=[{"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"}]
    )
    client = _NeverTerminalClient()
    report = run(
        minimax_profile,
        manifest,
        client,
        output_dir=tmp_path,
        poll_interval_s=0.01,
        job_timeout_s=0.05,
    )

    job = report.jobs[0]
    assert job.status == "failed"
    assert job.file is None


class _AlwaysConnectionErrorClient:
    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        raise ComfyUIError("connection refused")

    def get_json(self, path: str) -> dict[str, Any]:
        if path == "/system_stats":
            return {}
        raise AssertionError("should never poll history if post_json failed")


def test_run_post_json_error_is_reported_as_failed_and_does_not_crash(
    tmp_path: Path, minimax_profile: Profile
) -> None:
    manifest = _minimax_manifest(
        jobs=[{"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"}]
    )
    client = _AlwaysConnectionErrorClient()
    report = run(
        minimax_profile, manifest, client, output_dir=tmp_path, poll_interval_s=0, job_timeout_s=5
    )

    assert report.jobs[0].status == "failed"


# sanity: JobTimeoutError is importable/public, used above indirectly via run()
def test_job_timeout_error_is_a_real_exception_type() -> None:
    assert issubclass(JobTimeoutError, Exception)
