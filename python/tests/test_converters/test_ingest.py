"""Tests for econte.converters.ingest: joining a DeliveryReport back into a
storyboard by shot id, the retake-resets-approval rule, and the
actualSeconds scope boundary described in docs/compile-spec.md's
"econte ingest" section (and its "Scope boundary" section at the top of
that document)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from econte.cli import main
from econte.converters import SkippedJob, ingest_report
from econte.models import Storyboard

from .conftest import make_report, make_storyboard, shot_dict

# --- --target keyframes: basic write + retake-resets-approval ----------------


def _keyframe_storyboard(*, approved: bool, keyframe: str | None) -> Storyboard:
    source: dict[str, object] = {
        "type": "generate",
        "backend": "qwen-image-edit-2511",
        "prompt": "a keyframe",
        "approved": approved,
    }
    if keyframe is not None:
        source["keyframe"] = keyframe
    return make_storyboard(shots=[shot_dict("S01-A", source=source)])


def test_ingest_keyframes_first_time_sets_keyframe_and_marks_updated() -> None:
    storyboard = _keyframe_storyboard(approved=False, keyframe=None)
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "keyframes/S01-A_v1.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report, target="keyframes")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    assert shot.source.keyframe == "keyframes/S01-A_v1.png"
    assert result.updated == ["S01-A"]
    assert result.skipped == []
    assert result.unmatched_report_ids == []


def test_ingest_keyframes_idempotent_reingest_does_not_reset_approved() -> None:
    # The shot already carries v1's keyframe and has been manually approved
    # (approved=True) -- re-ingesting a report with the SAME file must not
    # touch approved, and must not be reported as an actual change.
    storyboard = _keyframe_storyboard(approved=True, keyframe="keyframes/S01-A_v1.png")
    report_v1_again = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "keyframes/S01-A_v1.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report_v1_again, target="keyframes")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    assert shot.source.keyframe == "keyframes/S01-A_v1.png"
    assert shot.source.approved is True  # NOT reset -- value is unchanged
    assert result.updated == []  # nothing actually changed


def test_ingest_keyframes_retake_resets_approval_on_actual_change() -> None:
    storyboard = _keyframe_storyboard(approved=True, keyframe="keyframes/S01-A_v1.png")
    report_v2 = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "keyframes/S01-A_v2.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report_v2, target="keyframes")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    assert shot.source.keyframe == "keyframes/S01-A_v2.png"
    assert shot.source.approved is False  # a stale approval must not survive a retake
    assert result.updated == ["S01-A"]


def test_ingest_keyframes_retake_when_already_unapproved_stays_unapproved() -> None:
    storyboard = _keyframe_storyboard(approved=False, keyframe="keyframes/S01-A_v1.png")
    report_v2 = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "keyframes/S01-A_v2.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report_v2, target="keyframes")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    assert shot.source.approved is False
    assert result.updated == ["S01-A"]  # keyframe itself still changed


# --- --target clips: render write + actualSeconds scope boundary -------------


def _clip_storyboard() -> Storyboard:
    return make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "minimax-h3-motion-context",
                    "prompt": "a clip",
                    "approved": True,
                    "keyframe": "keyframes/S01-A.png",
                },
            )
        ]
    )


def test_ingest_clips_sets_render_file_and_renderedAt_from_report() -> None:
    storyboard = _clip_storyboard()
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "clips/S01-A_00001_.mp4",
                "elapsedSeconds": 41.2,
                "seed": 1,
                "prompt": "p",
            }
        ],
        generated_at="2026-08-13T12:00:00Z",
    )
    result = ingest_report(storyboard, report, target="clips")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.render is not None
    assert shot.render.file == "clips/S01-A_00001_.mp4"
    assert shot.render.renderedAt == "2026-08-13T12:00:00Z"
    assert result.updated == ["S01-A"]


def test_ingest_never_writes_actual_seconds_regression_guard() -> None:
    """Regression guard: docs/compile-spec.md's "Scope boundary" section is
    explicit that `elapsedSeconds` (generation time) must never be conflated
    with `Render.actualSeconds` (a measured media duration, written by a
    separate, later tool). This must keep failing loudly if that mistake is
    ever reintroduced."""
    storyboard = _clip_storyboard()
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "clips/S01-A_00001_.mp4",
                "elapsedSeconds": 41.2,  # present on the report job...
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report, target="clips")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.render is not None
    assert shot.render.actualSeconds is None  # ...but must NEVER be copied/derived into this field


def test_ingest_clips_idempotent_reingest_does_not_mark_updated() -> None:
    storyboard = _clip_storyboard()
    report = make_report(
        [{"id": "S01-A", "status": "success", "file": "clips/S01-A.mp4", "seed": 1, "prompt": "p"}],
        generated_at="2026-08-13T12:00:00Z",
    )
    ingest_report(storyboard, report, target="clips")  # first ingest
    result = ingest_report(storyboard, report, target="clips")  # re-ingest, same report
    assert result.updated == []


# --- Non-"success" statuses are never written ---------------------------------


@pytest.mark.parametrize("status", ["failed", "missing"])
def test_non_success_status_job_never_written_and_is_recorded_as_skipped(status: str) -> None:
    storyboard = _keyframe_storyboard(approved=True, keyframe="keyframes/S01-A_v1.png")
    report = make_report([{"id": "S01-A", "status": status, "seed": 1, "prompt": "p"}])
    result = ingest_report(storyboard, report, target="keyframes")

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    assert shot.source.keyframe == "keyframes/S01-A_v1.png"  # untouched
    assert shot.source.approved is True  # untouched
    assert result.updated == []
    assert result.skipped == [SkippedJob(id="S01-A", status=status)]


# --- unmatched report ids / untouched storyboard-only shots -------------------


def test_report_job_id_with_no_matching_shot_is_recorded_as_unmatched() -> None:
    storyboard = _keyframe_storyboard(approved=False, keyframe=None)
    report = make_report(
        [{"id": "DOES-NOT-EXIST", "status": "success", "file": "x.png", "seed": 1, "prompt": "p"}]
    )
    result = ingest_report(storyboard, report, target="keyframes")

    assert result.unmatched_report_ids == ["DOES-NOT-EXIST"]
    assert result.updated == []
    assert result.skipped == []


def test_storyboard_shot_absent_from_report_is_left_untouched() -> None:
    storyboard = make_storyboard(
        shots=[
            shot_dict(
                "S01-A",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "p",
                    "approved": False,
                },
            ),
            shot_dict(
                "S01-B",
                source={
                    "type": "generate",
                    "backend": "qwen-image-edit-2511",
                    "prompt": "p",
                    "approved": False,
                },
            ),
        ]
    )
    # Report only covers S01-A (a partial/--only run) -- S01-B must be
    # completely unaffected and unmentioned in any result list.
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "keyframes/S01-A.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report, target="keyframes")

    shot_b = result.storyboard.scenes[0].shots[1]
    assert shot_b.source is not None
    assert shot_b.source.keyframe is None
    assert result.updated == ["S01-A"]
    assert "S01-B" not in result.updated
    assert result.skipped == []
    assert result.unmatched_report_ids == []


# --- job.file rebasing: ComfyUI output dir -> storyboard.json's own dir ------


def test_ingest_without_comfyui_output_dir_writes_job_file_verbatim() -> None:
    # Default/pre-existing behavior: with no --comfyui-output-dir given,
    # job.file is trusted as already being storyboard-relative and written
    # unchanged -- correct only when the two directories happen to coincide.
    storyboard = _keyframe_storyboard(approved=False, keyframe=None)
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "keyframes/S01-A.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(storyboard, report, target="keyframes")
    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    assert shot.source.keyframe == "keyframes/S01-A.png"


def test_ingest_rebases_job_file_when_comfyui_output_dir_differs_from_storyboard_dir(
    tmp_path: Path,
) -> None:
    # The realistic case the audit flagged: ComfyUI's configured output
    # directory is a completely different directory from the one
    # storyboard.json lives in. job.file ("SBdemo/S01-A_00001_.png") is
    # relative to the ComfyUI output dir (docs/profile-spec.md); the value
    # written into source.keyframe must instead be relative to
    # storyboard.json's own directory (docs/schema-spec.md).
    comfyui_output_dir = tmp_path / "ComfyUI" / "output"
    storyboard_dir = tmp_path / "projects" / "haruka"
    comfyui_output_dir.mkdir(parents=True)
    storyboard_dir.mkdir(parents=True)

    storyboard = _keyframe_storyboard(approved=True, keyframe=None)
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "SBdemo/S01-A_00001_.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(
        storyboard,
        report,
        target="keyframes",
        comfyui_output_dir=comfyui_output_dir,
        storyboard_dir=storyboard_dir,
    )

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    # Re-expressed relative to storyboard_dir, forward-slash separated.
    expected = os.path.relpath(
        comfyui_output_dir / "SBdemo" / "S01-A_00001_.png", storyboard_dir
    ).replace(os.sep, "/")
    assert shot.source.keyframe == expected
    assert shot.source.approved is False  # retake rule still applies to the rebased value


def test_ingest_falls_back_to_absolute_path_when_no_relative_path_is_expressible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real-world case found by manual spot-check: on Windows,
    # comfyui_output_dir and storyboard_dir are commonly on *different
    # drives* (e.g. E:\...\ComfyUI\output vs C:\Users\...\project), for
    # which os.path.relpath raises ValueError ("path is on mount 'E:',
    # start on mount 'C:'") -- it cannot express a cross-drive relative
    # path at all. This must degrade to an absolute path, not crash the
    # whole ingest run. Simulated via monkeypatch (portable across CI
    # platforms/drive layouts) rather than depending on two real drive
    # letters existing.
    comfyui_output_dir = tmp_path / "ComfyUI" / "output"
    storyboard_dir = tmp_path / "projects" / "haruka"
    comfyui_output_dir.mkdir(parents=True)
    storyboard_dir.mkdir(parents=True)

    def _raise_cross_drive(*_args: object, **_kwargs: object) -> str:
        raise ValueError("path is on mount 'E:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", _raise_cross_drive)

    storyboard = _keyframe_storyboard(approved=True, keyframe=None)
    report = make_report(
        [
            {
                "id": "S01-A",
                "status": "success",
                "file": "SBdemo/S01-A_00001_.png",
                "seed": 1,
                "prompt": "p",
            }
        ]
    )
    result = ingest_report(
        storyboard,
        report,
        target="keyframes",
        comfyui_output_dir=comfyui_output_dir,
        storyboard_dir=storyboard_dir,
    )

    shot = result.storyboard.scenes[0].shots[0]
    assert shot.source is not None
    expected_absolute = (comfyui_output_dir / "SBdemo" / "S01-A_00001_.png").resolve().as_posix()
    assert shot.source.keyframe == expected_absolute


def test_cli_ingest_comfyui_output_dir_flag_rebases_into_the_written_storyboard(
    tmp_path: Path,
) -> None:
    comfyui_output_dir = tmp_path / "ComfyUI" / "output"
    project_dir = tmp_path / "projects" / "haruka"
    comfyui_output_dir.mkdir(parents=True)
    project_dir.mkdir(parents=True)

    storyboard_path = project_dir / "storyboard.json"
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
                                    "backend": "qwen-image-edit-2511",
                                    "prompt": "p",
                                    "approved": False,
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = project_dir / "storyboard_report.json"
    report_path.write_text(
        json.dumps(
            {
                "profile": "qwen-image-edit-2511",
                "manifest": "out/manifest.json",
                "generatedAt": "2026-08-13T12:00:00Z",
                "jobs": [
                    {
                        "id": "S01-A",
                        "status": "success",
                        "file": "SBdemo/S01-A_00001_.png",
                        "seed": 1,
                        "prompt": "p",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "ingest",
            str(storyboard_path),
            str(report_path),
            "--target",
            "keyframes",
            "--comfyui-output-dir",
            str(comfyui_output_dir),
        ]
    )
    assert exit_code == 0

    with storyboard_path.open(encoding="utf-8") as f:
        data = json.load(f)
    expected = os.path.relpath(
        comfyui_output_dir / "SBdemo" / "S01-A_00001_.png", project_dir
    ).replace(os.sep, "/")
    assert data["scenes"][0]["shots"][0]["source"]["keyframe"] == expected


# --- CLI integration -----------------------------------------------------------


def test_cli_ingest_writes_updated_storyboard_and_prints_summary(
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
                                    "backend": "qwen-image-edit-2511",
                                    "prompt": "p",
                                    "approved": False,
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "storyboard_report.json"
    report_path.write_text(
        json.dumps(
            {
                "profile": "qwen-image-edit-2511",
                "manifest": "out/manifest.json",
                "generatedAt": "2026-08-13T12:00:00Z",
                "jobs": [
                    {
                        "id": "S01-A",
                        "status": "success",
                        "file": "keyframes/S01-A.png",
                        "seed": 1,
                        "prompt": "p",
                    },
                    {"id": "NOPE", "status": "success", "file": "x.png", "seed": 1, "prompt": "p"},
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "storyboard.updated.json"

    exit_code = main(
        [
            "ingest",
            str(storyboard_path),
            str(report_path),
            "--target",
            "keyframes",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "S01-A" in captured.out
    assert "NOPE" in captured.out

    with output_path.open(encoding="utf-8") as f:
        data = json.load(f)
    assert data["scenes"][0]["shots"][0]["source"]["keyframe"] == "keyframes/S01-A.png"

    # --output was given, so the original input file must be untouched.
    with storyboard_path.open(encoding="utf-8") as f:
        original = json.load(f)
    assert "keyframe" not in original["scenes"][0]["shots"][0]["source"]


def test_cli_ingest_without_output_overwrites_the_input_path(tmp_path: Path) -> None:
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
                                    "backend": "qwen-image-edit-2511",
                                    "prompt": "p",
                                    "approved": False,
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "storyboard_report.json"
    report_path.write_text(
        json.dumps(
            {
                "profile": "qwen-image-edit-2511",
                "manifest": "out/manifest.json",
                "generatedAt": "2026-08-13T12:00:00Z",
                "jobs": [
                    {
                        "id": "S01-A",
                        "status": "success",
                        "file": "keyframes/S01-A.png",
                        "seed": 1,
                        "prompt": "p",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["ingest", str(storyboard_path), str(report_path), "--target", "keyframes"])
    assert exit_code == 0

    with storyboard_path.open(encoding="utf-8") as f:
        data = json.load(f)
    assert data["scenes"][0]["shots"][0]["source"]["keyframe"] == "keyframes/S01-A.png"


def test_cli_ingest_invalid_report_json_exits_2(tmp_path: Path) -> None:
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "metadata": {"title": "T", "fps": 24, "aspectRatios": ["9:16"]},
                "characters": [],
                "scenes": [{"id": "S01", "shots": [{"id": "S01-A", "frames": [0, 24]}]}],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "bad_report.json"
    report_path.write_text("{not json", encoding="utf-8")

    exit_code = main(["ingest", str(storyboard_path), str(report_path), "--target", "keyframes"])
    assert exit_code == 2
