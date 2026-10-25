"""Regression tests for the hardening described in SECURITY.md.

Each test pins one guarantee: a shared storyboard, profile, manifest or
delivery report must not be able to read or write outside the directories
econte is told about, and oversized input is refused before it is parsed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

import econte.cli as cli
from econte import Storyboard, validate_storyboard
from econte.cli import MAX_STORYBOARD_BYTES, _ensure_size_limit, _is_loopback_host
from econte.converters import CompileError, compile_storyboard, ingest_report
from econte.converters.ingest import _job_file_escapes
from econte.converters.sheet import build_sheet_html
from econte.models import MAX_SHOTS_PER_SCENE, MAX_TOTAL_SHOTS, Metadata, Scene, Shot, Source
from econte.runners import ManifestError, load_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples" / "haruka"
PROFILES_DIR = REPO_ROOT / "profiles"


def _document(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "version": "0.1.0",
        "metadata": {"title": "t", "fps": 24, "aspectRatios": ["16:9"]},
        "characters": [],
        "scenes": [{"id": "S01", "shots": [{"id": "S01-A", "frames": [0, 120]}]}],
    }
    data.update(overrides)
    return data


def _one_shot(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": "S01", "shots": [{"id": "S01-A", "frames": [0, 120], "source": source}]}]


def _storyboard_with_keyframe(keyframe: str) -> Storyboard:
    data = _document(
        scenes=_one_shot({"type": "generate", "keyframe": keyframe, "approved": False})
    )
    ok, errors = validate_storyboard(data)
    assert ok, errors
    return Storyboard.model_validate(data)


def _write_image(path: Path, image_format: str = "PNG") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (200, 30, 30)).save(path, format=image_format)


# --- source.backend ---------------------------------------------------------


@pytest.mark.parametrize("backend", ["../evil", "C:/evil", "/evil", "a/b", "a\\b", "a..b"])
def test_backend_must_be_a_profile_id(backend: str) -> None:
    data = _document(scenes=_one_shot({"type": "generate", "backend": backend, "prompt": "p"}))
    ok, errors = validate_storyboard(data)
    assert not ok
    assert any("backend" in e for e in errors)


def test_compile_rechecks_backend_even_without_validation(tmp_path: Path) -> None:
    # model_construct() bypasses validation; compile must still refuse to
    # turn a traversal string into a path.
    source = Source.model_construct(type="generate", backend="../evil", prompt="p", approved=False)
    shot = Shot.model_construct(id="S01-A", frames=(0, 120), source=source)
    scene = Scene.model_construct(id="S01", shots=[shot])
    storyboard = Storyboard.model_construct(
        version="0.1.0",
        metadata=Metadata(title="t", fps=24, aspectRatios=["16:9"]),
        characters=[],
        scenes=[scene],
    )
    # 1280x720 matches the storyboard's "16:9", so the aspect-ratio check
    # (which runs first) passes and the backend re-check is what trips.
    with pytest.raises(CompileError, match="not a valid profile id"):
        compile_storyboard(
            storyboard, target="keyframes", profile_dir=tmp_path, width=1280, height=720
        )


# --- econte sheet -----------------------------------------------------------


def test_sheet_embeds_keyframe_inside_storyboard_dir(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_image(project / "kf" / "a.png")
    html = build_sheet_html(_storyboard_with_keyframe("kf/a.png"), storyboard_dir=project)
    assert "data:image/jpeg;base64," in html


def test_sheet_refuses_keyframe_outside_storyboard_dir(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "outside" / "secret.png"
    _write_image(secret)

    for keyframe in ("../outside/secret.png", secret.as_posix()):
        html = build_sheet_html(_storyboard_with_keyframe(keyframe), storyboard_dir=project)
        assert "data:image/jpeg;base64," not in html
        assert "outside the storyboard directory" in html

    # The operator can opt in for storyboards they trust.
    html = build_sheet_html(
        _storyboard_with_keyframe("../outside/secret.png"),
        storyboard_dir=project,
        allow_external_keyframes=True,
    )
    assert "data:image/jpeg;base64," in html


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_sheet_decodes_png_jpeg_webp(tmp_path: Path, image_format: str) -> None:
    _write_image(tmp_path / "kf.img", image_format)
    html = build_sheet_html(_storyboard_with_keyframe("kf.img"), storyboard_dir=tmp_path)
    assert "data:image/jpeg;base64," in html


@pytest.mark.parametrize("image_format", ["TIFF", "GIF", "BMP"])
def test_sheet_does_not_decode_other_formats(tmp_path: Path, image_format: str) -> None:
    _write_image(tmp_path / "kf.img", image_format)
    html = build_sheet_html(_storyboard_with_keyframe("kf.img"), storyboard_dir=tmp_path)
    assert "data:image/jpeg;base64," not in html
    assert "PNG, JPEG or WebP" in html


# --- econte ingest ----------------------------------------------------------


@pytest.mark.parametrize(
    "file",
    [
        "../../secret.png",
        "sub/../../secret.png",
        "..\\secret.png",
        "C:/secret.png",
        "C:\\secret.png",
        "C:secret.png",
        "\\secret.png",
        "/etc/x",
    ],
)
def test_ingest_verbatim_mode_refuses_escaping_paths(file: str) -> None:
    assert _job_file_escapes(file, None)


def test_ingest_verbatim_mode_keeps_plain_relative_paths() -> None:
    assert not _job_file_escapes("kf/a.png", None)
    assert not _job_file_escapes("a.png", None)
    assert not _job_file_escapes("a..b.png", None)
    assert not _job_file_escapes(None, None)


def test_ingest_rebase_mode_confines_to_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    assert not _job_file_escapes("sub/a.png", out)
    assert _job_file_escapes("../secret.png", out)


def test_ingest_report_skips_unsafe_job_as_unsafe_path() -> None:
    storyboard = _storyboard_with_keyframe("kf/old.png")
    report = SimpleNamespace(
        generatedAt="2026-10-25T00:00:00Z",
        jobs=[SimpleNamespace(id="S01-A", status="success", file="../../secret.png")],
    )
    result = ingest_report(storyboard, report, target="keyframes")  # type: ignore[arg-type]
    assert [(s.id, s.status) for s in result.skipped] == [("S01-A", "unsafe_path")]
    assert result.updated == []
    assert storyboard.scenes[0].shots[0].source is not None
    assert storyboard.scenes[0].shots[0].source.keyframe == "kf/old.png"


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES_DIR.glob("*_report.json")))
def test_example_report_paths_are_not_flagged_unsafe(name: str) -> None:
    # Reports written by `econte run` must keep ingesting: no false positives.
    report = json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))
    files = [job["file"] for job in report["jobs"] if job.get("file")]
    assert files
    assert [f for f in files if _job_file_escapes(f, None)] == []


# --- manifests ----------------------------------------------------------------


def _write_manifest(tmp_path: Path, **overrides: Any) -> Path:
    manifest: dict[str, Any] = {
        "profile": "qwen-image-edit-2511",
        "output_prefix": "demo",
        "jobs": [{"id": "S01-A", "seed": 1, "prompt": "p"}],
    }
    manifest.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "overrides",
    [
        {"profile": "../evil"},
        {"output_prefix": "../evil"},
        {"output_prefix": "a/b"},
        {"jobs": [{"id": "a/../b", "seed": 1, "prompt": "p"}]},
    ],
    ids=["profile", "output_prefix-dotdot", "output_prefix-slash", "job-id"],
)
def test_manifest_identifiers_must_be_slugs(tmp_path: Path, overrides: dict[str, Any]) -> None:
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, **overrides))


@pytest.mark.parametrize(
    "name",
    sorted(
        p.name for p in EXAMPLES_DIR.glob("*_*_*.json") if not p.name.endswith("_report.json")
    ),
)
def test_example_manifests_still_load(name: str) -> None:
    load_manifest(EXAMPLES_DIR / name)


# --- econte run: host taken from the profile ---------------------------------


class _StopBeforeNetwork(Exception):
    pass


def _run_until_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    profile_host: str,
    extra_args: list[str],
) -> str:
    """Run ``econte run`` on the example keyframes manifest against a copy of
    its profile whose default_host is ``profile_host``, stopping just before
    any network call. Returns what was printed to stderr."""
    profile = (PROFILES_DIR / "qwen-image-edit-2511.yaml").read_text(encoding="utf-8")
    assert 'default_host: "127.0.0.1"' in profile
    (tmp_path / "qwen-image-edit-2511.yaml").write_text(
        profile.replace('default_host: "127.0.0.1"', f'default_host: "{profile_host}"'),
        encoding="utf-8",
    )

    def stop(*args: object, **kwargs: object) -> None:
        raise _StopBeforeNetwork

    monkeypatch.setattr(cli, "ComfyUIClient", lambda base_url: object())
    monkeypatch.setattr(cli, "run_manifest", stop)
    manifest = EXAMPLES_DIR / "haruka-sample_keyframes_qwen-image-edit-2511.json"
    capsys.readouterr()
    with pytest.raises(_StopBeforeNetwork):
        cli.main(["run", str(manifest), "--profile-dir", str(tmp_path), *extra_args])
    return capsys.readouterr().err


def test_run_warns_when_the_profile_picks_a_non_loopback_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    err = _run_until_connect(tmp_path, monkeypatch, capsys, "192.168.0.5", [])
    assert "warning: connecting to 192.168.0.5:8188" in err


def test_run_does_not_warn_for_loopback_or_an_explicit_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "warning: connecting" not in _run_until_connect(
        tmp_path, monkeypatch, capsys, "127.0.0.1", []
    )
    assert "warning: connecting" not in _run_until_connect(
        tmp_path, monkeypatch, capsys, "192.168.0.5", ["--host", "127.0.0.1"]
    )


# --- input size limits ------------------------------------------------------


def test_size_limit_refuses_oversized_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "MAX_STORYBOARD_BYTES", 10)
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * 11)
    with pytest.raises(OSError, match="above the 10-byte limit"):
        cli._ensure_size_limit(big)
    small = tmp_path / "small.json"
    small.write_bytes(b"x" * 10)
    cli._ensure_size_limit(small)  # no error


def test_size_limit_default_is_generous_but_bounded(tmp_path: Path) -> None:
    assert MAX_STORYBOARD_BYTES == 32 * 1024 * 1024
    f = tmp_path / "s.json"
    f.write_text("{}", encoding="utf-8")
    _ensure_size_limit(f)


def test_oversized_array_fails_fast() -> None:
    data = _document()
    data["metadata"]["aspectRatios"] = ["x"] * 1_000_000
    ok, errors = validate_storyboard(data)
    assert not ok
    assert len(errors) == 1  # one error for the array, not one per element


def test_total_shot_count_is_bounded() -> None:
    def full_scenes(count: int) -> list[dict[str, Any]]:
        return [
            {
                "id": f"S{i}",
                "shots": [
                    {"id": f"S{i}-{j}", "frames": [0, 1]} for j in range(MAX_SHOTS_PER_SCENE)
                ],
            }
            for i in range(count)
        ]

    at_limit = MAX_TOTAL_SHOTS // MAX_SHOTS_PER_SCENE
    ok, errors = validate_storyboard(_document(scenes=full_scenes(at_limit)))
    assert ok, errors[:3]

    ok, errors = validate_storyboard(_document(scenes=full_scenes(at_limit + 1)))
    assert not ok
    assert len(errors) == 1
    assert "shots in total" in errors[0]


# --- loopback detection -----------------------------------------------------


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST", "127.0.0.1", "::1", "[::1]"])
def test_loopback_hosts(host: str) -> None:
    assert _is_loopback_host(host)


@pytest.mark.parametrize("host", ["192.168.0.5", "example.com", "0.0.0.0", "10.0.0.1"])
def test_non_loopback_hosts(host: str) -> None:
    assert not _is_loopback_host(host)
