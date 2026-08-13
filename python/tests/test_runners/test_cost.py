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

from .conftest import make_manifest, make_minimal_profile_dict


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


def test_cost_scales_linearly_with_frames(minimax_profile: Profile) -> None:
    # The profile's reference_frames is 124 (and profile.defaults supplies
    # frames: 124), so halving the frames halves the estimate.
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        defaults={"width": 640, "height": 1152},
        jobs=[{"id": "a", "seed": 1, "prompt": "p", "fast": False, "frames": 62}],
    )
    result = estimate(minimax_profile, manifest)
    assert result.total_seconds == pytest.approx(810.0 * (62 / 124))


def test_cost_frame_term_is_neutral_at_the_reference_frame_count(
    minimax_profile: Profile,
) -> None:
    # profile.defaults sets frames: 124 == reference_frames, so a manifest
    # that never mentions frames must produce exactly the pre-existing
    # 810s figure — i.e. adding frame scaling changed no established number.
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        defaults={"width": 640, "height": 1152},
        jobs=[{"id": "a", "seed": 1, "prompt": "p", "fast": False}],
    )
    result = estimate(minimax_profile, manifest)
    assert result.total_seconds == pytest.approx(810.0)


def test_cost_ignores_frames_when_profile_sets_no_reference_frames(
    qwen_profile: Profile,
) -> None:
    # The keyframe profile has no frame axis; a stray frames value in the
    # manifest must not silently start scaling an image profile's estimate.
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        defaults={"width": 720, "height": 1280, "frames": 999},
        jobs=[{"id": "a", "seed": 1, "prompt": "p"}],
    )
    result = estimate(qwen_profile, manifest)
    assert result.total_seconds == pytest.approx(280.0)


def test_cost_error_when_reference_frames_set_but_frames_unresolved() -> None:
    # Uses a synthetic profile rather than the minimax one: that profile now
    # carries `frames: 124` in its own defaults, and a None at a higher layer
    # deliberately does not override a lower one (see resolve_context), so
    # there is no way to un-resolve frames for it -- which is the point.
    profile = Profile.model_validate(
        make_minimal_profile_dict(
            cost={
                "reference_resolution": {"width": 100, "height": 100},
                "reference_frames": 124,
                "base_seconds_per_job": 10,
                "first_job_overhead_seconds": 5,
                "multipliers": {},
            }
        )
    )
    manifest = make_manifest(defaults={"width": 100, "height": 100})
    with pytest.raises(CostError, match="frames"):
        estimate(profile, manifest)
