"""Shared paths and small builder helpers for econte.converters tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from econte.models import Storyboard
from econte.runners import DeliveryReport

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = REPO_ROOT / "profiles"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "converters"

QWEN_PROFILE_PATH = PROFILES_DIR / "qwen-image-edit-2511.yaml"  # kind: keyframe
MINIMAX_PROFILE_PATH = PROFILES_DIR / "minimax-h3-motion-context.yaml"  # kind: video

SAMPLE_STORYBOARD_PATH = FIXTURES_DIR / "sample-storyboard.json"


@pytest.fixture(scope="session", autouse=True)
def _sanity_check_paths() -> None:
    assert PROFILES_DIR.is_dir(), f"profiles/ not found at {PROFILES_DIR}"
    assert QWEN_PROFILE_PATH.is_file(), QWEN_PROFILE_PATH
    assert MINIMAX_PROFILE_PATH.is_file(), MINIMAX_PROFILE_PATH
    assert SAMPLE_STORYBOARD_PATH.is_file(), SAMPLE_STORYBOARD_PATH


def load_sample_storyboard() -> Storyboard:
    """The shared 3-scene fixture storyboard (see fixtures/converters/
    sample-storyboard.json): a mix of standalone/chain_start/chain shots, a
    character-free B-roll shot, a shot missing a backend, a shot missing a
    prompt, and asset/remotion/no-source shots -- all its ``generate``
    shots use the keyframe-kind ``qwen-image-edit-2511`` backend, so a
    ``--target keyframes`` compile over the whole thing succeeds cleanly
    and produces one manifest group. Being single-kind, this fixture alone
    cannot exercise the case where a storyboard has *some* shots already
    progressed to a different backend/kind than the one being compiled --
    see test_compile.py's ``test_mixed_kind_storyboard_*`` tests (a
    synthetic two-backend storyboard) for that scenario; compiling this
    fixture for ``--target clips`` instead just skips every shot with a
    kind-mismatch warning, since none of them use a video-kind backend.
    """
    with SAMPLE_STORYBOARD_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return Storyboard.model_validate(data)


def sample_storyboard_dict() -> dict[str, Any]:
    with SAMPLE_STORYBOARD_PATH.open(encoding="utf-8") as f:
        result: dict[str, Any] = json.load(f)
        return result


def make_storyboard(
    *,
    title: str = "Test Storyboard",
    aspect_ratios: list[str] | None = None,
    characters: list[dict[str, Any]] | None = None,
    shots: list[dict[str, Any]],
    scene_id: str = "S01",
) -> Storyboard:
    """A small, synthetic-but-schema-valid single-scene storyboard, for
    tests that need to construct a specific edge case without cluttering
    the shared realistic fixture (see :func:`load_sample_storyboard`)."""
    return Storyboard.model_validate(
        {
            "version": "0.1.0",
            "metadata": {
                "title": title,
                "fps": 24,
                "aspectRatios": aspect_ratios or ["9:16"],
            },
            "characters": characters or [],
            "scenes": [{"id": scene_id, "shots": shots}],
        }
    )


def shot_dict(
    shot_id: str,
    *,
    frames: tuple[int, int] = (0, 24),
    subject: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A minimal ``Shot`` dict, for use in :func:`make_storyboard`'s
    ``shots=[...]`` list."""
    result: dict[str, Any] = {"id": shot_id, "frames": list(frames)}
    if subject is not None:
        result["subject"] = subject
    if source is not None:
        result["source"] = source
    return result


def make_report(
    jobs: list[dict[str, Any]],
    *,
    profile: str = "qwen-image-edit-2511",
    manifest: str = "out/manifest.json",
    generated_at: str = "2026-08-13T12:00:00Z",
) -> DeliveryReport:
    return DeliveryReport.model_validate(
        {
            "profile": profile,
            "manifest": manifest,
            "generatedAt": generated_at,
            "jobs": jobs,
        }
    )
