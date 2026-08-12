"""Tests for econte.runners.cost: the dry-run time estimate formula.

The minimax numbers are hand-verified against the profile's own documented
cost fields (see profiles/minimax-h3-motion-context.yaml's `cost:` block):
  reference_resolution: 640x1152, base_seconds_per_job: 810,
  first_job_overhead_seconds: 0, multipliers: { fast: 1.8 }

For a single job at exactly the reference resolution:
  area_ratio = (640*1152) / (640*1152) = 1.0
  non-fast: total = 0 + 810 * 1.0 * 1.0            = 810.0
  fast:     total = 0 + 810 * 1.0 * 1.0 * 1.8       = 1458.0
"""

from __future__ import annotations

import pytest

from econte.runners import CostError, Profile, estimate

from .conftest import make_manifest


def test_minimax_single_non_fast_job_at_reference_resolution(minimax_profile: Profile) -> None:
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        defaults={"width": 640, "height": 1152},
        jobs=[{"id": "a", "seed": 1, "prompt": "p", "fast": False}],
    )
    result = estimate(minimax_profile, manifest)
    # 0 (overhead) + 810 * (640*1152)/(640*1152) * 1.0 (fast is falsy, no multiplier) = 810.0
    assert result.total_seconds == pytest.approx(810.0)
    assert len(result.per_job) == 1
    assert result.per_job[0].id == "a"
    assert result.per_job[0].seconds == pytest.approx(810.0)


def test_minimax_single_fast_job_at_reference_resolution(minimax_profile: Profile) -> None:
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        defaults={"width": 640, "height": 1152},
        jobs=[{"id": "a", "seed": 1, "prompt": "p", "fast": True}],
    )
    result = estimate(minimax_profile, manifest)
    # 0 (overhead) + 810 * 1.0 * 1.8 (fast multiplier applies) = 1458.0
    assert result.total_seconds == pytest.approx(1458.0)
    assert result.per_job[0].seconds == pytest.approx(1458.0)


def test_minimax_multiple_jobs_sum_and_first_job_overhead_added_once(
    minimax_profile: Profile,
) -> None:
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        defaults={"width": 640, "height": 1152},
        jobs=[
            {"id": "a", "seed": 1, "prompt": "p", "fast": False},  # 810.0
            {"id": "b", "seed": 2, "prompt": "p", "fast": True},  # 1458.0
        ],
    )
    result = estimate(minimax_profile, manifest)
    # first_job_overhead_seconds is 0 for this profile, so this mostly
    # exercises "sum, not just last job", but is asserted explicitly below
    # against the qwen profile which has a non-zero overhead.
    assert result.total_seconds == pytest.approx(810.0 + 1458.0)


def test_qwen_single_job_includes_first_job_overhead_once(qwen_profile: Profile) -> None:
    # qwen's cost block: reference_resolution 720x1280, base_seconds_per_job
    # 40, first_job_overhead_seconds 240, multipliers {}.
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        defaults={"width": 720, "height": 1280},
        jobs=[{"id": "a", "seed": 1, "prompt": "p"}],
    )
    result = estimate(qwen_profile, manifest)
    # 240 (overhead, once) + 40 * (720*1280)/(720*1280) * 1.0 (no multipliers) = 280.0
    assert result.total_seconds == pytest.approx(280.0)


def test_qwen_overhead_added_once_not_per_job(qwen_profile: Profile) -> None:
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        defaults={"width": 720, "height": 1280},
        jobs=[
            {"id": "a", "seed": 1, "prompt": "p"},
            {"id": "b", "seed": 2, "prompt": "p"},
            {"id": "c", "seed": 3, "prompt": "p"},
        ],
    )
    result = estimate(qwen_profile, manifest)
    # 240 (once) + 3 * 40.0 = 360.0, NOT 3 * (240 + 40) = 840.0
    assert result.total_seconds == pytest.approx(240.0 + 3 * 40.0)


def test_cost_scales_with_resolution_area_ratio(qwen_profile: Profile) -> None:
    # Half the reference area (720*1280/2 = 460800) at, say, 720x640 -> half the per-job seconds.
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        defaults={"width": 720, "height": 640},
        jobs=[{"id": "a", "seed": 1, "prompt": "p"}],
    )
    result = estimate(qwen_profile, manifest)
    expected = 240.0 + 40.0 * (720 * 640) / (720 * 1280)
    assert result.total_seconds == pytest.approx(expected)


def test_cost_error_when_width_or_height_unresolved(minimax_profile: Profile) -> None:
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        defaults={},  # no width/height anywhere
        jobs=[{"id": "a", "seed": 1, "prompt": "p"}],
    )
    with pytest.raises(CostError, match="a"):
        estimate(minimax_profile, manifest)
