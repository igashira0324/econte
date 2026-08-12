"""Tests for econte.runners.manifest: ManifestJob/Manifest shape, job-id
uniqueness, load_manifest, and resolve_context's exact precedence rule."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from econte.runners import (
    Manifest,
    ManifestError,
    Profile,
    load_manifest,
    load_profile,
    resolve_context,
)
from econte.runners.manifest import ManifestJob

from .conftest import MINIMAX_PROFILE_PATH, make_manifest, make_minimal_profile_dict

# --- ManifestJob: open/extra-fields-allowed ---------------------------------


def test_manifest_job_accepts_arbitrary_extra_fields() -> None:
    job = ManifestJob.model_validate(
        {
            "id": "a",
            "seed": 1,
            "prompt": "p",
            "material": "chain_start",
            "fast": True,
            "custom_field": 42,
        }
    )
    assert job.id == "a"
    assert job.seed == 1
    assert job.prompt == "p"
    dumped = job.model_dump()
    assert dumped["material"] == "chain_start"
    assert dumped["fast"] is True
    assert dumped["custom_field"] == 42


def test_manifest_job_requires_id_seed_prompt() -> None:
    with pytest.raises(ValidationError):
        ManifestJob.model_validate({"seed": 1, "prompt": "p"})
    with pytest.raises(ValidationError):
        ManifestJob.model_validate({"id": "a", "prompt": "p"})
    with pytest.raises(ValidationError):
        ManifestJob.model_validate({"id": "a", "seed": 1})


# --- Manifest: unique job ids ------------------------------------------------


def test_manifest_rejects_duplicate_job_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        Manifest.model_validate(
            {
                "profile": "x",
                "output_prefix": "out",
                "jobs": [
                    {"id": "S01", "seed": 1, "prompt": "p"},
                    {"id": "S01", "seed": 2, "prompt": "q"},
                ],
            }
        )


def test_manifest_accepts_unique_job_ids() -> None:
    manifest = Manifest.model_validate(
        {
            "profile": "x",
            "output_prefix": "out",
            "jobs": [
                {"id": "S01", "seed": 1, "prompt": "p"},
                {"id": "S02", "seed": 2, "prompt": "q"},
            ],
        }
    )
    assert [j.id for j in manifest.jobs] == ["S01", "S02"]


# --- load_manifest -----------------------------------------------------------


def test_load_manifest_success(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "profile": "x",
                "output_prefix": "out",
                "jobs": [{"id": "a", "seed": 1, "prompt": "p"}],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_manifest(path)
    assert manifest.profile == "x"
    assert manifest.jobs[0].id == "a"


def test_load_manifest_missing_file_raises_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "nope.json")


def test_load_manifest_invalid_json_raises_manifest_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_load_manifest_schema_violation_raises_manifest_error(tmp_path: Path) -> None:
    path = tmp_path / "dupes.json"
    path.write_text(
        json.dumps(
            {
                "profile": "x",
                "output_prefix": "out",
                "jobs": [
                    {"id": "a", "seed": 1, "prompt": "p"},
                    {"id": "a", "seed": 2, "prompt": "q"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError):
        load_manifest(path)


# --- resolve_context: precedence -------------------------------------------


def _synthetic_profile(**overrides: object) -> Profile:
    return Profile.model_validate(make_minimal_profile_dict(**overrides))


def test_resolve_context_precedence_profile_lt_manifest_lt_job() -> None:
    profile = _synthetic_profile(defaults={"steps": 20, "width": 111, "height": 111})
    manifest = make_manifest(
        defaults={"width": 720, "height": 1280},
        jobs=[{"id": "job-1", "seed": 1, "prompt": "p", "height": 999}],
    )
    ctx = resolve_context(profile, manifest, manifest.jobs[0])

    assert ctx["steps"] == 20  # only profile.defaults sets this -> inherited
    assert ctx["width"] == 720  # manifest.defaults overrides profile.defaults
    assert ctx["height"] == 999  # job's own field overrides manifest.defaults
    assert ctx["seed"] == 1
    assert ctx["prompt"] == "p"


def test_resolve_context_null_does_not_override_lower_layer() -> None:
    profile = _synthetic_profile()
    manifest = make_manifest(
        defaults={"ref_image": "characters/haruka/front.png", "width": 720, "height": 1280},
        jobs=[{"id": "job-1", "seed": 1, "prompt": "p", "ref_image": None}],
    )
    ctx = resolve_context(profile, manifest, manifest.jobs[0])
    # explicit null on the job must NOT blank out manifest.defaults.ref_image
    assert ctx["ref_image"] == "characters/haruka/front.png"


def test_resolve_context_explicit_empty_string_does_override() -> None:
    profile = _synthetic_profile()
    manifest = make_manifest(
        defaults={"ref_image": "characters/haruka/front.png", "width": 720, "height": 1280},
        jobs=[{"id": "job-1", "seed": 1, "prompt": "p", "ref_image": ""}],
    )
    ctx = resolve_context(profile, manifest, manifest.jobs[0])
    assert ctx["ref_image"] == ""


def test_resolve_context_computed_fields() -> None:
    profile = _synthetic_profile()
    manifest = make_manifest(
        output_prefix="SBdemo",
        jobs=[
            {"id": "S01-A", "seed": 1, "prompt": "p"},
            {"id": "S01-B", "seed": 2, "prompt": "q"},
        ],
    )
    ctx_a = resolve_context(profile, manifest, manifest.jobs[0])
    ctx_b = resolve_context(profile, manifest, manifest.jobs[1])

    assert ctx_a["id"] == "S01-A"
    assert ctx_a["output_prefix"] == "SBdemo"
    assert ctx_a["filename_prefix"] == "SBdemo/S01-A"
    assert ctx_a["job_index"] == 1
    assert "chain_from_index" not in ctx_a  # no chain_from set -> field entirely absent

    assert ctx_b["job_index"] == 2
    assert ctx_b["filename_prefix"] == "SBdemo/S01-B"


def test_resolve_context_computed_field_wins_and_warns_on_collision(
    caplog: pytest.LogCaptureFixture,
) -> None:
    profile = _synthetic_profile()
    manifest = make_manifest(jobs=[{"id": "job-1", "seed": 1, "prompt": "p", "job_index": 999}])

    with caplog.at_level(logging.WARNING, logger="econte.runners.manifest"):
        ctx = resolve_context(profile, manifest, manifest.jobs[0])

    assert ctx["job_index"] == 1  # computed value wins, not the user-supplied 999
    assert len(caplog.records) == 1
    assert "job_index" in caplog.text
    assert "999" in caplog.text


def test_resolve_context_no_warning_when_field_simply_unset(
    caplog: pytest.LogCaptureFixture,
) -> None:
    profile = _synthetic_profile()
    manifest = make_manifest(jobs=[{"id": "job-1", "seed": 1, "prompt": "p"}])

    with caplog.at_level(logging.WARNING, logger="econte.runners.manifest"):
        resolve_context(profile, manifest, manifest.jobs[0])

    assert caplog.records == []


def test_resolve_context_no_warning_when_computed_value_matches_supplied_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # If a user-supplied value happens to already equal what the runner
    # would compute, nothing actually changes -- this must not warn either
    # (only a *different* value being overridden counts as a collision).
    profile = _synthetic_profile()
    manifest = make_manifest(
        output_prefix="out",
        jobs=[{"id": "job-1", "seed": 1, "prompt": "p", "filename_prefix": "out/job-1"}],
    )

    with caplog.at_level(logging.WARNING, logger="econte.runners.manifest"):
        ctx = resolve_context(profile, manifest, manifest.jobs[0])

    assert ctx["filename_prefix"] == "out/job-1"
    assert caplog.records == []


# --- resolve_context: chain_from_index --------------------------------------


def test_resolve_context_chain_from_index_resolves_by_id_lookup() -> None:
    profile = load_profile(MINIMAX_PROFILE_PATH)
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        output_prefix="MVdemo",
        defaults={"width": 640, "height": 1152, "latent_folder": "chain"},
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {"id": "S02-B", "seed": 2, "prompt": "p", "material": "chain", "chain_from": "S02-A"},
            {"id": "S02-C", "seed": 3, "prompt": "p", "material": "chain", "chain_from": "S02-B"},
        ],
    )
    ctx_b = resolve_context(profile, manifest, manifest.jobs[1])
    ctx_c = resolve_context(profile, manifest, manifest.jobs[2])

    assert ctx_b["chain_from_index"] == 1
    assert ctx_c["chain_from_index"] == 2


def test_resolve_context_chain_from_unknown_id_raises_manifest_error() -> None:
    profile = load_profile(MINIMAX_PROFILE_PATH)
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        output_prefix="MVdemo",
        defaults={"width": 640, "height": 1152, "latent_folder": "chain"},
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain_start"},
            {
                "id": "S02-B",
                "seed": 2,
                "prompt": "p",
                "material": "chain",
                "chain_from": "does-not-exist",
            },
        ],
    )
    with pytest.raises(ManifestError, match="does-not-exist"):
        resolve_context(profile, manifest, manifest.jobs[1])


def test_resolve_context_chain_from_must_be_earlier_not_just_present() -> None:
    """chain_from referencing a job that exists in the manifest but comes
    LATER must still be rejected -- "earlier" is positional, not just
    "any id present"."""
    profile = load_profile(MINIMAX_PROFILE_PATH)
    manifest = make_manifest(
        profile="minimax-h3-motion-context",
        output_prefix="MVdemo",
        defaults={"width": 640, "height": 1152, "latent_folder": "chain"},
        jobs=[
            {"id": "S02-A", "seed": 1, "prompt": "p", "material": "chain", "chain_from": "S02-B"},
            {"id": "S02-B", "seed": 2, "prompt": "p", "material": "chain_start"},
        ],
    )
    with pytest.raises(ManifestError, match="S02-B"):
        resolve_context(profile, manifest, manifest.jobs[0])
