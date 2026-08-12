"""Tests for econte.runners.selector: variant_selector.map evaluation.

Drives context combinations that reach every documented variant of both
real reference profiles, plus the null/missing/"" equivalence and the
defensive SelectorError path.
"""

from __future__ import annotations

import pytest

from econte.runners import Profile, SelectorError, select_variant

# --- qwen-image-edit-2511: both variants reachable --------------------------


def test_qwen_with_ref_selected_when_ref_image_present(qwen_profile: Profile) -> None:
    assert select_variant(qwen_profile, {"ref_image": "front.png"}) == "with_ref"


def test_qwen_no_ref_selected_when_ref_image_missing(qwen_profile: Profile) -> None:
    assert select_variant(qwen_profile, {}) == "no_ref"


def test_qwen_no_ref_selected_when_ref_image_none(qwen_profile: Profile) -> None:
    assert select_variant(qwen_profile, {"ref_image": None}) == "no_ref"


def test_qwen_no_ref_selected_when_ref_image_empty_string(qwen_profile: Profile) -> None:
    # Per the manifest spec, explicit "" means "no reference" -- and per
    # the profile's own `when: { ref_image: null }` convention, that must
    # also land on no_ref, not fall through to the with_ref catch-all.
    assert select_variant(qwen_profile, {"ref_image": ""}) == "no_ref"


# --- minimax-h3-motion-context: all four variants reachable -----------------


@pytest.mark.parametrize(
    ("material", "fast", "expected_variant"),
    [
        ("chain", False, "chained_ec"),
        ("chain", True, "chained_fast"),
        ("chain_start", False, "origin_ec"),
        ("chain_start", True, "origin_fast"),
        ("standalone", False, "origin_ec"),
        ("standalone", True, "origin_fast"),
    ],
)
def test_minimax_all_documented_variants_reachable(
    minimax_profile: Profile, material: str, fast: bool, expected_variant: str
) -> None:
    context = {"material": material, "fast": fast}
    assert select_variant(minimax_profile, context) == expected_variant


def test_minimax_catch_all_fallback(minimax_profile: Profile) -> None:
    # A context that names neither `material` nor `fast` at all still
    # resolves, via the catch-all -> origin_ec.
    assert select_variant(minimax_profile, {}) == "origin_ec"


# --- Generic mechanics -------------------------------------------------------


def test_first_match_wins_top_to_bottom(minimax_profile: Profile) -> None:
    # material=chain, fast=false matches the FIRST rule (chained_ec), even
    # though {} (the catch-all) would also technically match every field
    # the map inspects if it were reached -- first match wins.
    assert select_variant(minimax_profile, {"material": "chain", "fast": False}) == "chained_ec"


def test_selector_error_when_no_rule_matches() -> None:
    # Hand-construct a Profile bypassing load_profile()'s consistency
    # check, so its map has no catch-all -- select_variant must still fail
    # safely (defensively) rather than silently pick something.
    data = {
        "id": "no-catch-all",
        "kind": "keyframe",
        "server": {"default_host": "127.0.0.1", "default_port": 8188},
        "cost": {
            "reference_resolution": {"width": 1, "height": 1},
            "base_seconds_per_job": 1,
        },
        "output": {"glob": "x", "pick": "newest"},
        "variant_selector": {
            "fields": ["material"],
            "map": [{"when": {"material": "chain"}, "variant": "v"}],
        },
        "variants": {"v": {"graph": {}}},
    }
    profile = Profile.model_validate(data)  # skips check_consistency() deliberately
    with pytest.raises(SelectorError):
        select_variant(profile, {"material": "does-not-match-anything"})


def _profile_with_single_rule(when: dict[str, object]) -> Profile:
    data = {
        "id": "scalar-vs-list",
        "kind": "keyframe",
        "server": {"default_host": "127.0.0.1", "default_port": 8188},
        "cost": {"reference_resolution": {"width": 1, "height": 1}, "base_seconds_per_job": 1},
        "output": {"glob": "x", "pick": "newest"},
        "variant_selector": {
            "fields": ["material"],
            "map": [{"when": when, "variant": "matched"}, {"when": {}, "variant": "fallback"}],
        },
        "variants": {"matched": {"graph": {}}, "fallback": {"graph": {}}},
    }
    return Profile.model_validate(data)


def test_scalar_when_value_normalized_same_as_single_element_list() -> None:
    scalar_profile = _profile_with_single_rule({"material": "chain"})
    list_profile = _profile_with_single_rule({"material": ["chain"]})

    for context in ({"material": "chain"}, {"material": "standalone"}, {}):
        assert select_variant(scalar_profile, context) == select_variant(list_profile, context)


def test_list_when_value_matches_any_listed_value(minimax_profile: Profile) -> None:
    # material: [chain_start, standalone] in the real profile's map -- both
    # listed values must independently match that rule.
    context_start = {"material": "chain_start", "fast": False}
    context_standalone = {"material": "standalone", "fast": False}
    assert select_variant(minimax_profile, context_start) == "origin_ec"
    assert select_variant(minimax_profile, context_standalone) == "origin_ec"
