"""Tests for econte.converters.compile: the eligibility filter, field
mapping (including ref_image resolution and seed derivation), aspect-ratio
validation, and manifest grouping/naming described in
docs/compile-spec.md's "econte compile" section."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from econte.cli import main
from econte.converters import CompileError, compile_storyboard, slugify
from econte.runners import Manifest, load_profile

from .conftest import (
    MINIMAX_PROFILE_PATH,
    PROFILES_DIR,
    QWEN_PROFILE_PATH,
    SAMPLE_STORYBOARD_PATH,
    load_sample_storyboard,
    make_storyboard,
    shot_dict,
)

# --- slugify -----------------------------------------------------------------


def test_slugify_lowercases_and_replaces_spaces_with_hyphens() -> None:
    assert slugify("Fixture Storyboard") == "fixture-storyboard"


def test_slugify_strips_characters_outside_the_shot_id_charset() -> None:
    # Colons, apostrophes, and other punctuation are stripped, not replaced
    # with a placeholder -- see slugify()'s docstring for why.
    assert slugify("Haruka: A Memory!") == "haruka-a-memory"


# --- Eligibility filter: skip-with-warning cases ------------------------------


def test_missing_backend_skips_with_warning_naming_the_shot() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert any("S01-C" in w and "no backend" in w for w in result.warnings), result.warnings
    all_job_ids = {job.id for group in result.groups for job in group.manifest.jobs}
    assert "S01-C" not in all_job_ids


def test_missing_prompt_skips_with_warning_naming_the_shot() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert any("S02-A" in w and "no prompt" in w for w in result.warnings), result.warnings
    all_job_ids = {job.id for group in result.groups for job in group.manifest.jobs}
    assert "S02-A" not in all_job_ids


def test_unapproved_shot_skips_silently_at_warning_level_for_clips_target() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",
                    "prompt": "a clip",
                    "approved": False,
                },
            )
        ]
    )
    result = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert result.groups == []  # nothing eligible -- not an error, just empty
    assert any("S01-A" in w and "approved" in w for w in result.warnings), result.warnings


def test_approved_true_is_not_required_for_keyframes_target() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "a keyframe",
                    "approved": False,
                },
            )
        ]
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert result.groups[0].manifest.jobs[0].id == "S01-A"


# --- Eligibility filter: never-compiled types (no warning) -------------------


def test_asset_type_is_never_compiled_and_produces_no_warning() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert not any("S03-A" in w for w in result.warnings)
    all_job_ids = {job.id for group in result.groups for job in group.manifest.jobs}
    assert "S03-A" not in all_job_ids


def test_remotion_type_is_never_compiled_and_produces_no_warning() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert not any("S03-B" in w for w in result.warnings)
    all_job_ids = {job.id for group in result.groups for job in group.manifest.jobs}
    assert "S03-B" not in all_job_ids


def test_shot_with_no_source_at_all_is_never_compiled_and_produces_no_warning() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert not any("S03-C" in w for w in result.warnings)
    all_job_ids = {job.id for group in result.groups for job in group.manifest.jobs}
    assert "S03-C" not in all_job_ids


# --- Eligibility filter: kind mismatch is a skip-with-warning, not a hard error ---


def test_profile_kind_mismatch_is_skipped_with_warning_naming_shot_and_actual_kind() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",  # kind: video
                    "prompt": "a keyframe",
                    "approved": True,
                },
            )
        ]
    )
    # Must NOT raise: a kind mismatch means this shot is not eligible for
    # *this* compile pass, not that the whole storyboard is broken.
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert result.groups == []
    assert len(result.warnings) == 1
    assert "S01-A" in result.warnings[0]
    assert "video" in result.warnings[0]  # names the profile's *actual* kind


def test_profile_kind_mismatch_on_sample_fixture_for_clips_target_skips_not_errors() -> None:
    # Every eligible (approved, prompted, backend-set) generate shot in the
    # shared fixture uses the keyframe-kind qwen backend, so compiling it
    # for --target clips must skip every such shot with a warning, not
    # hard-error the whole storyboard (see docs/compile-spec.md's
    # eligibility filter and the "mixed-kind storyboard" tests below for
    # the realistic multi-stage scenario this behavior exists for).
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert result.groups == []  # no video-kind backend anywhere in this fixture
    warnings_text = "; ".join(result.warnings)
    assert "S01-A" in warnings_text
    assert "S02-B" in warnings_text


def test_mixed_kind_storyboard_compiles_keyframes_pass_skipping_advanced_shots() -> None:
    """Regression test for the audit's critical finding: a storyboard with
    some shots already progressed to a video backend (approved, ready for
    --target clips) alongside others still needing a keyframes pass must
    compile --target keyframes successfully, producing a manifest for the
    still-eligible shots and only warning (not erroring) about the
    already-advanced ones."""
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",  # kind: keyframe -- eligible
                    "prompt": "a keyframe still to generate",
                    "approved": False,
                },
            ),
            shot_dict(
                "S02-A",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",  # kind: video -- advanced
                    "prompt": "a clip already staged for a video pass",
                    "approved": True,
                    "keyframe": "keyframes/S02-A.png",
                },
            ),
        ]
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.backend == "qwen-image-edit-2511"
    assert {job.id for job in group.manifest.jobs} == {"S01-A"}
    assert any("S02-A" in w for w in result.warnings)


def test_unknown_backend_profile_fails_to_load_is_a_hard_error(tmp_path: Path) -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "does-not-exist",
                    "prompt": "a keyframe",
                    "approved": True,
                },
            )
        ]
    )
    with pytest.raises(CompileError) as excinfo:
        compile_storyboard(
            storyboard, target="keyframes", profile_dir=tmp_path, width=720, height=1280
        )
    assert "S01-A" in str(excinfo.value)
    assert "does-not-exist" in str(excinfo.value)


# --- ref_image resolution: --target keyframes ---------------------------------


def test_ref_image_keyframes_has_subject_uses_first_character_ref() -> None:
    storyboard = make_storyboard(
        characters=[
            {
                "id": "haruka",
                "identity": "test character",
                "refs": ["characters/haruka/front.png", "characters/haruka/side.png"],
            }
        ],
        shots=[
            shot_dict(
                "S01-A",
                subject="@haruka",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "haruka on a rooftop",
                    "approved": True,
                },
            )
        ],
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    job = result.groups[0].manifest.jobs[0]
    assert job.model_dump()["ref_image"] == "characters/haruka/front.png"


def test_ref_image_keyframes_no_subject_is_omitted_entirely() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "empty rooftop, no people",
                    "approved": True,
                },
            )
        ]
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    job = result.groups[0].manifest.jobs[0]
    assert "ref_image" not in job.model_dump()


# --- ref_image resolution: --target clips -------------------------------------


def test_ref_image_clips_has_keyframe_uses_the_approved_still() -> None:
    storyboard = make_storyboard(
        characters=[
            {"id": "haruka", "identity": "test character", "refs": ["characters/haruka/front.png"]}
        ],
        shots=[
            shot_dict(
                "S01-A",
                subject="@haruka",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",
                    "prompt": "haruka on a rooftop",
                    "approved": True,
                    "keyframe": "keyframes/S01-A.png",
                },
            )
        ],
    )
    result = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    job = result.groups[0].manifest.jobs[0]
    # The keyframe wins even though a character ref also exists.
    assert job.model_dump()["ref_image"] == "keyframes/S01-A.png"


def test_ref_image_clips_falls_back_to_character_ref_when_no_keyframe_yet() -> None:
    storyboard = make_storyboard(
        characters=[
            {"id": "haruka", "identity": "test character", "refs": ["characters/haruka/front.png"]}
        ],
        shots=[
            shot_dict(
                "S01-A",
                subject="@haruka",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",
                    "prompt": "haruka on a rooftop",
                    "approved": True,
                    # no keyframe set -- going straight to video with no still pass
                },
            )
        ],
    )
    result = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    job = result.groups[0].manifest.jobs[0]
    assert job.model_dump()["ref_image"] == "characters/haruka/front.png"


def test_ref_image_clips_neither_keyframe_nor_subject_is_omitted() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",
                    "prompt": "a standalone B-roll clip",
                    "approved": True,
                },
            )
        ]
    )
    result = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    job = result.groups[0].manifest.jobs[0]
    assert "ref_image" not in job.model_dump()


# --- Seed derivation -----------------------------------------------------------


def test_seed_auto_derivation_matches_hand_computed_spec_formula() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    jobs_by_id = {job.id: job for group in result.groups for job in group.manifest.jobs}
    job = jobs_by_id["S02-B"]  # source.seed is not set on this fixture shot

    # Hand-computed here, independently of econte.converters.compile's own
    # _derive_seed, using exactly the formula given in docs/compile-spec.md's
    # "Deterministic seed derivation" section -- not imported from the
    # implementation, so a regression there would actually be caught.
    expected_seed = int(hashlib.sha256(b"S02-B").hexdigest()[:8], 16) % (2**31)

    assert job.seed == expected_seed
    assert job.seed == 273270252  # pinned: this must never silently drift

    qwen_group = next(g for g in result.groups if g.backend == "qwen-image-edit-2511")
    assert any("S02-B" in w and str(expected_seed) in w for w in qwen_group.warnings)


def test_explicit_seed_is_used_verbatim_with_no_auto_derivation_notice() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "a keyframe",
                    "approved": True,
                    "seed": 424242,
                },
            )
        ]
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    group = result.groups[0]
    assert group.manifest.jobs[0].seed == 424242
    assert group.warnings == []


# --- Width/height vs. metadata.aspectRatios -----------------------------------


def test_width_height_matching_a_declared_aspect_ratio_passes() -> None:
    storyboard = load_sample_storyboard()  # aspectRatios: ["9:16", "16:9"]
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert result.groups  # did not raise, produced at least one group


def test_width_height_not_matching_any_declared_aspect_ratio_raises() -> None:
    storyboard = load_sample_storyboard()  # aspectRatios: ["9:16", "16:9"]
    with pytest.raises(CompileError) as excinfo:
        compile_storyboard(
            storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=800, height=600
        )
    message = str(excinfo.value)
    assert "4:3" in message  # 800x600 reduces to 4:3


def test_width_height_matches_an_unreduced_aspect_ratio_entry() -> None:
    # metadata.aspectRatios is only required to match ^\d+:\d+$, not already
    # be in lowest terms -- "1280:720" must still match a 1920x1080 request
    # (both reduce to 16:9).
    storyboard = make_storyboard(
        aspect_ratios=["1280:720"],
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "a keyframe",
                    "approved": True,
                },
            )
        ],
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=1920, height=1080
    )
    assert result.groups


# --- Field mapping: material / chain_from -------------------------------------


def test_material_defaults_to_chain_start_when_absent() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "a keyframe",
                    "approved": True,
                    # material omitted
                },
            )
        ]
    )
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert result.groups[0].manifest.jobs[0].model_dump()["material"] == "chain_start"


def test_material_and_chain_from_pass_through_verbatim() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    jobs_by_id = {job.id: job.model_dump() for g in result.groups for job in g.manifest.jobs}
    assert jobs_by_id["S01-B"]["material"] == "chain_start"
    assert jobs_by_id["S01-B"]["chain_from"] is None
    assert jobs_by_id["S02-B"]["material"] == "chain"
    assert jobs_by_id["S02-B"]["chain_from"] == "S01-B"
    assert jobs_by_id["S01-A"]["material"] == "standalone"


# --- Grouping / manifest shape --------------------------------------------------


def test_compile_groups_eligible_shots_by_backend_with_width_height_in_defaults() -> None:
    storyboard = load_sample_storyboard()
    result = compile_storyboard(
        storyboard, target="keyframes", profile_dir=PROFILES_DIR, width=720, height=1280
    )
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.backend == "qwen-image-edit-2511"
    assert isinstance(group.manifest, Manifest)
    assert group.manifest.profile == "qwen-image-edit-2511"
    # keyframes-target: no latent_folder -- no shipped keyframe profile uses it.
    assert group.manifest.defaults == {"width": 720, "height": 1280}
    assert {j.id for j in group.manifest.jobs} == {"S01-A", "S01-B", "S02-B"}
    # width/height must NOT be set per-job -- only in manifest.defaults.
    for job in group.manifest.jobs:
        dumped = job.model_dump()
        assert "width" not in dumped
        assert "height" not in dumped


def test_compile_clips_manifest_defaults_include_a_latent_folder() -> None:
    # Regression test: a clips-target manifest against a chain-capable video
    # profile (minimax-h3-motion-context) with NO latent_folder in
    # manifest.defaults fails outright at `econte run` time -- the profile's
    # chained_ec/chained_fast variants reference `${latent_folder}` in their
    # graph templates (MiniMaxH3MotionContextSaveLatent/LoadLatent) and
    # compile_storyboard never populated it before this test existed, so
    # EVERY clips-target compile against that profile was broken. Caught by
    # manually running the full pipeline end to end against a live server,
    # not by any prior unit test.
    storyboard = make_storyboard(
        characters=[
            {"id": "haruka", "identity": "test character", "refs": ["characters/haruka/front.png"]}
        ],
        shots=[
            shot_dict(
                "S01-A",
                subject="@haruka",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",
                    "prompt": "haruka walking",
                    "approved": True,
                    "material": "chain_start",
                },
            )
        ],
    )
    # 576x1024, not 640x1152: gcd(640, 1152) = 128 -> 5:9, not 9:16 (the
    # exact "non-issue" a prior audit pass flagged) -- 576x1024 is the actual
    # exact-9:16-and-multiple-of-32 resolution, matching make_storyboard's
    # default aspectRatios ["9:16"] and the H3 profile's resolution_multiple.
    result = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=576, height=1024
    )
    defaults = result.groups[0].manifest.defaults
    assert defaults["width"] == 576
    assert defaults["height"] == 1024
    assert "latent_folder" in defaults
    assert isinstance(defaults["latent_folder"], str) and defaults["latent_folder"]
    # Stable/deterministic per (storyboard, backend) -- not random per compile.
    result2 = compile_storyboard(
        storyboard, target="clips", profile_dir=PROFILES_DIR, width=576, height=1024
    )
    assert result2.groups[0].manifest.defaults["latent_folder"] == defaults["latent_folder"]


# --- CLI integration -----------------------------------------------------------


def test_cli_compile_writes_one_manifest_file_per_backend(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "compile",
            str(SAMPLE_STORYBOARD_PATH),
            "--target",
            "keyframes",
            "--width",
            "720",
            "--height",
            "1280",
            "--profile-dir",
            str(PROFILES_DIR),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    manifest_path = output_dir / "fixture-storyboard_keyframes_qwen-image-edit-2511.json"
    assert manifest_path.is_file()

    with manifest_path.open(encoding="utf-8") as f:
        data = json.load(f)
    assert data["profile"] == "qwen-image-edit-2511"
    assert data["defaults"] == {"width": 720, "height": 1280}
    assert {job["id"] for job in data["jobs"]} == {"S01-A", "S01-B", "S02-B"}


def test_cli_compile_exits_1_when_nothing_is_eligible(tmp_path: Path) -> None:
    storyboard_path = tmp_path / "empty.json"
    storyboard_path.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "metadata": {"title": "Empty", "fps": 24, "aspectRatios": ["16:9"]},
                "characters": [],
                "scenes": [{"id": "S01", "shots": [{"id": "S01-A", "frames": [0, 24]}]}],
            }
        ),
        encoding="utf-8",
    )
    exit_code = main(
        [
            "compile",
            str(storyboard_path),
            "--target",
            "keyframes",
            "--width",
            "1280",
            "--height",
            "720",
            "--profile-dir",
            str(PROFILES_DIR),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 1


def test_cli_compile_exits_1_when_all_shots_are_kind_mismatched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every generate shot in the shared fixture uses a keyframe-kind
    # backend, so compiling --target clips over it leaves 0 eligible shots
    # (each kind-mismatched shot is skipped with a warning, not an error --
    # see the mixed-kind unit tests above) -- exit code is still 1 because
    # there is nothing to compile, but via the ordinary "nothing eligible"
    # path, and the per-shot notices land on stdout as warnings, not stderr.
    exit_code = main(
        [
            "compile",
            str(SAMPLE_STORYBOARD_PATH),
            "--target",
            "clips",
            "--width",
            "720",
            "--height",
            "1280",
            "--profile-dir",
            str(PROFILES_DIR),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "S01-A" in captured.out  # kind-mismatch warning, not a hard error
    assert "nothing to compile" in captured.err


def test_cli_compile_exits_1_on_hard_error_unknown_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "metadata": {"title": "T", "fps": 24, "aspectRatios": ["9:16"]},
                "characters": [],
                "scenes": [
                    {
                        "id": "S01",
                        "shots": [
                            {
                                "id": "S01-A",
                                "frames": [0, 24],
                                "source": {
                                    "type": "generate",
                                    "backend": "does-not-exist",
                                    "prompt": "p",
                                    "approved": True,
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    exit_code = main(
        [
            "compile",
            str(storyboard_path),
            "--target",
            "keyframes",
            "--width",
            "720",
            "--height",
            "1280",
            "--profile-dir",
            str(PROFILES_DIR),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "S01-A" in captured.err
    assert "does-not-exist" in captured.err


def test_cli_compile_requires_target_flag() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["compile", str(SAMPLE_STORYBOARD_PATH), "--width", "720", "--height", "1280"])
    assert excinfo.value.code == 2  # argparse's own exit code for missing required args


def test_reference_profile_kinds_are_what_this_test_module_assumes() -> None:
    # Guards the two real reference profiles this whole test module leans
    # on: if their `kind` ever changes, most tests above would silently
    # start testing the wrong thing.
    assert load_profile(QWEN_PROFILE_PATH).kind == "keyframe"
    assert load_profile(MINIMAX_PROFILE_PATH).kind == "video"
