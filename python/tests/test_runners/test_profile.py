"""Tests for econte.runners.profile: the Profile pydantic model, load_profile,
and Profile.check_consistency's structural checks on variant_selector."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from econte.runners import OutputSpec, Profile, ProfileError, load_profile

from .conftest import MINIMAX_PROFILE_PATH, QWEN_PROFILE_PATH, make_minimal_profile_dict

# --- Loading the two real, hand-verified reference profiles ----------------
# This is the most important integration check for this module: both files
# must load and pass every structural check load_profile performs.


def test_load_qwen_profile_shape() -> None:
    profile = load_profile(QWEN_PROFILE_PATH)
    assert profile.id == "qwen-image-edit-2511"
    assert profile.kind == "keyframe"
    assert profile.on_job_failure == "continue"  # not set in this profile -> default
    assert profile.server.default_host == "127.0.0.1"
    assert profile.server.default_port == 8188
    assert profile.constraints.resolution_multiple == 8
    assert profile.constraints.max_megapixels == 1.5
    # An image profile has no frame axis: both frame fields stay unset, which
    # is what keeps the frame term out of its cost estimate entirely.
    assert profile.constraints.max_frames is None
    assert profile.cost.reference_frames is None
    assert profile.cost.reference_resolution.width == 720
    assert profile.cost.reference_resolution.height == 1280
    assert profile.cost.base_seconds_per_job == 40
    assert profile.cost.first_job_overhead_seconds == 240
    assert profile.cost.multipliers == {}
    assert profile.output.glob == "${filename_prefix}_*.png"
    assert profile.output.pick == "newest"
    assert set(profile.variants) == {"with_ref", "no_ref"}
    assert [rule.variant for rule in profile.variant_selector.map] == ["no_ref", "with_ref"]
    assert profile.variant_selector.map[-1].when == {}


def test_load_minimax_profile_shape() -> None:
    profile = load_profile(MINIMAX_PROFILE_PATH)
    assert profile.id == "minimax-h3-motion-context"
    assert profile.kind == "video"
    assert profile.on_job_failure == "abort_remaining_chain"  # explicitly set in this profile
    assert profile.server.default_port == 8189
    assert profile.constraints.resolution_multiple == 32
    assert profile.constraints.max_megapixels is None
    assert profile.constraints.max_frames == 124
    assert profile.cost.reference_resolution.width == 640
    assert profile.cost.reference_resolution.height == 1152
    assert profile.cost.reference_frames == 124
    assert profile.cost.base_seconds_per_job == 810
    assert profile.cost.first_job_overhead_seconds == 0
    assert profile.cost.multipliers == {"fast": 1.8}
    assert profile.defaults == {
        "steps": 20,
        "fast": False,
        "material": "chain_start",
        "frames": 124,
    }
    assert set(profile.variants) == {"origin_ec", "origin_fast", "chained_ec", "chained_fast"}
    assert profile.variant_selector.map[-1].when == {}
    assert profile.variant_selector.map[-1].variant == "origin_ec"


def test_load_profile_missing_file_raises_profile_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(ProfileError):
        load_profile(missing)


def test_load_profile_invalid_yaml_raises_profile_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: [unterminated\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(bad)


def test_load_profile_non_mapping_yaml_raises_profile_error(tmp_path: Path) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(bad)


def test_load_profile_schema_mismatch_raises_profile_error(tmp_path: Path) -> None:
    bad = tmp_path / "incomplete.yaml"
    bad.write_text("id: x\nkind: keyframe\n", encoding="utf-8")  # missing server/cost/output/...
    with pytest.raises(ProfileError):
        load_profile(bad)


# --- Profile.check_consistency: catch-all + variant-existence checks ------


def test_check_consistency_passes_for_valid_map() -> None:
    Profile.model_validate(make_minimal_profile_dict()).check_consistency()  # must not raise


def test_check_consistency_rejects_missing_catch_all() -> None:
    data = make_minimal_profile_dict()
    data["variant_selector"] = {
        "fields": ["ref_image"],
        "map": [{"when": {"ref_image": None}, "variant": "no_ref"}],  # no catch-all
    }
    profile = Profile.model_validate(data)
    with pytest.raises(ProfileError, match="catch-all"):
        profile.check_consistency()


def test_check_consistency_rejects_empty_map() -> None:
    data = make_minimal_profile_dict()
    data["variant_selector"] = {"fields": [], "map": []}
    profile = Profile.model_validate(data)
    with pytest.raises(ProfileError, match="must not be empty"):
        profile.check_consistency()


def test_check_consistency_rejects_catch_all_not_last() -> None:
    data = make_minimal_profile_dict()
    data["variant_selector"] = {
        "fields": ["ref_image"],
        "map": [
            {"when": {}, "variant": "with_ref"},  # catch-all, but not last
            {"when": {"ref_image": None}, "variant": "no_ref"},
        ],
    }
    profile = Profile.model_validate(data)
    with pytest.raises(ProfileError, match="must be LAST"):
        profile.check_consistency()


def test_check_consistency_rejects_unknown_variant_reference() -> None:
    data = make_minimal_profile_dict()
    data["variant_selector"] = {
        "fields": ["ref_image"],
        "map": [
            {"when": {"ref_image": None}, "variant": "does_not_exist"},
            {"when": {}, "variant": "with_ref"},
        ],
    }
    profile = Profile.model_validate(data)
    with pytest.raises(ProfileError, match="does_not_exist"):
        profile.check_consistency()


def test_check_consistency_collects_multiple_errors_at_once() -> None:
    data = make_minimal_profile_dict()
    data["variant_selector"] = {
        "fields": [],
        "map": [{"when": {"x": 1}, "variant": "nope"}],  # no catch-all AND unknown variant
    }
    profile = Profile.model_validate(data)
    with pytest.raises(ProfileError) as excinfo:
        profile.check_consistency()
    message = str(excinfo.value)
    assert "catch-all" in message
    assert "nope" in message


def test_output_spec_rejects_unsupported_pick_value() -> None:
    with pytest.raises(ValidationError):
        OutputSpec.model_validate({"glob": "x", "pick": "oldest"})


def test_load_profile_runs_consistency_check(tmp_path: Path) -> None:
    """A profile that parses fine field-by-field but has no catch-all must
    still fail at load_profile() time, not just when check_consistency() is
    called manually."""
    data = make_minimal_profile_dict()
    data["variant_selector"] = {
        "fields": ["ref_image"],
        "map": [{"when": {"ref_image": None}, "variant": "no_ref"}],
    }
    path = tmp_path / "no-catch-all.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ProfileError, match="catch-all"):
        load_profile(path)
