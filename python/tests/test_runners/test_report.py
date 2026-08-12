"""Tests for econte.runners.report: resolve_output_file (glob + pick newest)
and the DeliveryReport/JobReport shapes."""

from __future__ import annotations

import os
import time
from pathlib import Path

from econte.runners import DeliveryReport, JobReport, OutputSpec, resolve_output_file


def _touch(path: Path, *, mtime_offset_s: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    if mtime_offset_s:
        now = time.time()
        os.utime(path, (now + mtime_offset_s, now + mtime_offset_s))


def test_resolve_output_file_none_when_no_match(tmp_path: Path) -> None:
    spec = OutputSpec(glob="${filename_prefix}_*.png", pick="newest")
    result = resolve_output_file(spec, {"filename_prefix": "SBdemo/S01-A"}, tmp_path)
    assert result is None


def test_resolve_output_file_finds_single_match(tmp_path: Path) -> None:
    spec = OutputSpec(glob="${filename_prefix}_*.png", pick="newest")
    _touch(tmp_path / "SBdemo" / "S01-A_00001_.png")
    result = resolve_output_file(spec, {"filename_prefix": "SBdemo/S01-A"}, tmp_path)
    assert result == tmp_path / "SBdemo" / "S01-A_00001_.png"


def test_resolve_output_file_picks_newest_by_mtime(tmp_path: Path) -> None:
    spec = OutputSpec(glob="${filename_prefix}_*.png", pick="newest")
    older = tmp_path / "SBdemo" / "S01-A_00001_.png"
    newer = tmp_path / "SBdemo" / "S01-A_00002_.png"
    _touch(older, mtime_offset_s=-100.0)
    _touch(newer, mtime_offset_s=0.0)
    result = resolve_output_file(spec, {"filename_prefix": "SBdemo/S01-A"}, tmp_path)
    assert result == newer


def test_resolve_output_file_does_not_match_a_different_prefix(tmp_path: Path) -> None:
    spec = OutputSpec(glob="${filename_prefix}_*.png", pick="newest")
    _touch(tmp_path / "SBdemo" / "S01-B_00001_.png")  # different job id
    result = resolve_output_file(spec, {"filename_prefix": "SBdemo/S01-A"}, tmp_path)
    assert result is None


def test_delivery_report_round_trips_extra_job_fields() -> None:
    # JobReport allows extra (profile-defined) fields, so construct via
    # model_validate(dict) rather than keyword args -- the latter's static
    # signature only knows the explicitly declared fields.
    job_report = JobReport.model_validate(
        {
            "id": "S01-A",
            "status": "success",
            "file": "SBdemo/S01-A_00001_.png",
            "elapsedSeconds": 41.2,
            "seed": 1001,
            "prompt": "a test prompt",
            "material": "standalone",  # extra, profile-defined field carried verbatim
        }
    )
    report = DeliveryReport(
        profile="qwen-image-edit-2511",
        manifest="path/to/manifest.json",
        generatedAt="2026-08-13T12:00:00Z",
        jobs=[job_report],
    )
    dumped = report.model_dump(mode="json", exclude_none=True)
    assert dumped["jobs"][0]["material"] == "standalone"
    assert dumped["jobs"][0]["id"] == "S01-A"
    assert "elapsedSeconds" in dumped["jobs"][0]


def test_delivery_report_missing_status_omits_elapsed_and_file_when_none() -> None:
    job_report = JobReport(id="S01-C", status="missing", seed=1, prompt="p")
    dumped = job_report.model_dump(mode="json", exclude_none=True)
    assert "elapsedSeconds" not in dumped
    assert "file" not in dumped
    assert dumped["status"] == "missing"
