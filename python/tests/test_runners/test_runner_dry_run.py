"""Tests for econte.runners.runner.dry_run: fully offline (no network, no
ComfyUI server) constraint validation + cost estimate, including the
required integration check of dry-running both REAL reference profiles.
"""

from __future__ import annotations

import pytest

from econte.runners import Profile, dry_run

from .conftest import make_manifest, make_minimal_profile_dict


def _synthetic_profile(**overrides: object) -> Profile:
    return Profile.model_validate(make_minimal_profile_dict(**overrides))


def test_dry_run_flags_resolution_multiple_violation() -> None:
    profile = _synthetic_profile(constraints={"resolution_multiple": 8})
    manifest = make_manifest(defaults={"width": 723, "height": 1280})  # 723 not a multiple of 8
    report = dry_run(profile, manifest)
    assert report.has_errors
    errors = [i for i in report.issues if i.severity == "error"]
    assert any(i.field == "resolution_multiple" for i in errors)


def test_dry_run_resolution_multiple_pass_when_divisible() -> None:
    profile = _synthetic_profile(constraints={"resolution_multiple": 8})
    manifest = make_manifest(defaults={"width": 720, "height": 1280})
    report = dry_run(profile, manifest)
    assert not report.has_errors


def test_dry_run_max_megapixels_is_warning_not_error() -> None:
    profile = _synthetic_profile(constraints={"resolution_multiple": 8, "max_megapixels": 1.5})
    # 2000*2000 = 4,000,000 = 4.0MP > 1.5MP, but still a multiple of 8
    manifest = make_manifest(defaults={"width": 2000, "height": 2000})
    report = dry_run(profile, manifest)
    assert not report.has_errors  # warning-only, must not flip the exit code
    warnings = [i for i in report.issues if i.severity == "warning"]
    assert any(i.field == "max_megapixels" for i in warnings)
    assert not any(i.field == "max_megapixels" and i.severity == "error" for i in report.issues)


def test_dry_run_max_frames_is_error_not_warning() -> None:
    # Deliberately the opposite severity to max_megapixels above: exceeding a
    # frame budget invalidates the linear cost estimate rather than merely
    # straining it, so the runner refuses instead of quoting a bad number.
    # See docs/profile-spec.md, "Why max_frames is an error".
    profile = _synthetic_profile(constraints={"max_frames": 124})
    manifest = make_manifest(defaults={"width": 100, "height": 100, "frames": 339})
    report = dry_run(profile, manifest)
    assert report.has_errors
    assert any(i.field == "max_frames" and i.severity == "error" for i in report.issues)


def test_dry_run_max_frames_passes_at_exactly_the_budget() -> None:
    profile = _synthetic_profile(constraints={"max_frames": 124})
    manifest = make_manifest(defaults={"width": 100, "height": 100, "frames": 124})
    report = dry_run(profile, manifest)
    assert not report.has_errors


def test_dry_run_errors_when_max_frames_set_but_frames_unresolved() -> None:
    profile = _synthetic_profile(constraints={"max_frames": 124})
    manifest = make_manifest(defaults={"width": 100, "height": 100})  # no frames anywhere
    report = dry_run(profile, manifest)
    assert report.has_errors
    assert any(i.field == "frames" and i.severity == "error" for i in report.issues)


def test_dry_run_ignores_frames_entirely_when_profile_sets_no_frame_budget() -> None:
    # Image profiles have no frame axis; they must be wholly unaffected.
    profile = _synthetic_profile(constraints={"resolution_multiple": 8})
    manifest = make_manifest(defaults={"width": 720, "height": 1280})
    report = dry_run(profile, manifest)
    assert not report.has_errors
    assert not any(i.field in {"frames", "max_frames"} for i in report.issues)


def test_dry_run_collects_all_issues_not_just_the_first() -> None:
    profile = _synthetic_profile(constraints={"resolution_multiple": 8, "max_megapixels": 0.01})
    manifest = make_manifest(
        defaults={"width": 2000, "height": 2000},  # divisible by 8, but well over the tiny mp limit
        jobs=[
            {"id": "bad-res", "seed": 1, "prompt": "p", "width": 723, "height": 1280},  # not /8
            {"id": "big-mp", "seed": 2, "prompt": "p"},  # inherits 2000x2000 -> mp warning only
        ],
    )
    report = dry_run(profile, manifest)
    job_ids_with_issues = {i.job_id for i in report.issues}
    assert "bad-res" in job_ids_with_issues
    assert "big-mp" in job_ids_with_issues
    assert len(report.issues) >= 2


def test_dry_run_missing_width_height_is_an_error() -> None:
    profile = _synthetic_profile()
    manifest = make_manifest(defaults={})  # no width/height anywhere
    report = dry_run(profile, manifest)
    assert report.has_errors
    assert any(i.field == "width/height" for i in report.issues)


# --- Required integration check: dry_run() against BOTH real profiles ------


def test_dry_run_real_qwen_profile_succeeds(qwen_profile: Profile) -> None:
    manifest = make_manifest(
        profile="qwen-image-edit-2511",
        output_prefix="SBdemo",
        defaults={"ref_image": "characters/haruka/front.png", "width": 720, "height": 1280},
        jobs=[
            {"id": "S01-A", "seed": 1001, "prompt": "haruka, full body, standing"},  # -> with_ref
            {
                "id": "S01-B",
                "seed": 1002,
                "prompt": "empty street, no characters",
                "ref_image": "",
            },  # -> no_ref
        ],
    )
    report = dry_run(qwen_profile, manifest)
    assert report.issues == []
    assert not report.has_errors
    # 240 (overhead, once) + 2 * 40.0 (both jobs at exactly the reference resolution) = 320.0
    assert report.cost.total_seconds == pytest.approx(320.0)
    assert {jc.id for jc in report.cost.per_job} == {"S01-A", "S01-B"}


def test_dry_run_real_minimax_profile_succeeds(minimax_profile: Profile) -> None:
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        output_prefix="MVdemo",
        defaults={"width": 640, "height": 1152, "latent_folder": "S02-chain"},
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},  # -> origin_ec
            {
                "id": "S02-B",
                "seed": 2,
                "prompt": "p",
                "material": "chain",
                "chain_from": "S02-A",
                "fast": True,
            },  # -> chained_fast
        ],
    )
    report = dry_run(minimax_profile, manifest)
    assert report.issues == []
    assert not report.has_errors
    # 0 (overhead) + 810.0 (non-fast, reference resolution) + 1458.0 (fast: *1.8) = 2268.0
    assert report.cost.total_seconds == pytest.approx(2268.0)


def test_dry_run_real_minimax_profile_flags_non_multiple_of_32(minimax_profile: Profile) -> None:
    # 640x1152 is a multiple of 32; 640x1150 is not (verified-in-production
    # gotcha this profile's own comments call out: a multiple of 16 is not
    # enough).
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        output_prefix="MVdemo",
        defaults={"width": 640, "height": 1150, "latent_folder": "S02-chain"},
        jobs=[{"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"}],
    )
    report = dry_run(minimax_profile, manifest)
    assert report.has_errors
    assert any(i.field == "resolution_multiple" for i in report.issues)
