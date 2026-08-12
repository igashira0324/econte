"""Shared paths and small helpers for econte.runners tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from econte.runners import Manifest, Profile, load_profile

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = REPO_ROOT / "profiles"
REPLAY_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "comfyui-replay"

QWEN_PROFILE_PATH = PROFILES_DIR / "qwen-image-edit-2511.yaml"
MINIMAX_PROFILE_PATH = PROFILES_DIR / "minimax-h3-motion-context.yaml"


@pytest.fixture(scope="session", autouse=True)
def _sanity_check_paths() -> None:
    assert PROFILES_DIR.is_dir(), f"profiles/ not found at {PROFILES_DIR}"
    assert QWEN_PROFILE_PATH.is_file(), QWEN_PROFILE_PATH
    assert MINIMAX_PROFILE_PATH.is_file(), MINIMAX_PROFILE_PATH


@pytest.fixture
def qwen_profile() -> Profile:
    return load_profile(QWEN_PROFILE_PATH)


@pytest.fixture
def minimax_profile() -> Profile:
    return load_profile(MINIMAX_PROFILE_PATH)


def make_minimal_profile_dict(**overrides: Any) -> dict[str, Any]:
    """A small, synthetic-but-schema-valid profile dict, for tests that
    need to construct edge cases (missing catch-all, unknown variant
    reference, ...) without cluttering the two real reference profiles."""
    base: dict[str, Any] = {
        "id": "synthetic-test-profile",
        "kind": "keyframe",
        "server": {"default_host": "127.0.0.1", "default_port": 8188},
        "cost": {
            "reference_resolution": {"width": 100, "height": 100},
            "base_seconds_per_job": 10,
            "first_job_overhead_seconds": 5,
            "multipliers": {},
        },
        "output": {"glob": "${filename_prefix}_*.png", "pick": "newest"},
        "variant_selector": {
            "fields": ["ref_image"],
            "map": [
                {"when": {"ref_image": None}, "variant": "no_ref"},
                {"when": {}, "variant": "with_ref"},
            ],
        },
        "variants": {
            "with_ref": {"graph": {"1": {"class_type": "X", "inputs": {"seed": "${seed}"}}}},
            "no_ref": {"graph": {"1": {"class_type": "Y", "inputs": {"seed": "${seed}"}}}},
        },
    }
    base.update(overrides)
    return base


def make_manifest(**overrides: Any) -> Manifest:
    base: dict[str, Any] = {
        "profile": "synthetic-test-profile",
        "output_prefix": "out",
        "defaults": {"width": 100, "height": 100},
        "jobs": [{"id": "job-1", "seed": 1, "prompt": "p"}],
    }
    base.update(overrides)
    return Manifest.model_validate(base)
