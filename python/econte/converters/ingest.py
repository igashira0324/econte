"""``econte ingest``: write a delivery report's results back into a
storyboard, by shot id.

See ``docs/compile-spec.md`` at the repository root, section
``econte ingest``, for the authoritative specification this module
implements exactly, including the "Scope boundary: econte does not measure
media duration" section at the top of that document -- this is why
:func:`ingest_report` never writes ``Render.actualSeconds``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..models import Render, Shot, Storyboard
from ..runners import DeliveryReport

__all__ = ["IngestResult", "SkippedJob", "ingest_report"]

IngestTarget = Literal["keyframes", "clips"]


@dataclass
class SkippedJob:
    """One report job that was *not* written into the storyboard because
    its ``status`` was not ``"success"``."""

    id: str
    status: str


@dataclass
class IngestResult:
    """The result of :func:`ingest_report`.

    ``storyboard`` is the *same* :class:`~econte.models.Storyboard` object
    passed in, mutated in place (its ``Shot``/``Source``/``Render``
    sub-models are ordinary mutable pydantic models) -- returned here
    anyway so callers have a single result value to work with, matching the
    task's requested shape.
    """

    storyboard: Storyboard
    updated: list[str] = field(default_factory=list)
    skipped: list[SkippedJob] = field(default_factory=list)
    unmatched_report_ids: list[str] = field(default_factory=list)


def _rebase_job_file(
    file: str | None,
    *,
    comfyui_output_dir: Path | None,
    storyboard_dir: Path | None,
) -> str | None:
    """Re-express a report job's ``file`` -- documented in
    ``docs/profile-spec.md`` as relative to the *ComfyUI output directory*
    -- as a path relative to the storyboard.json's own directory instead,
    per ``docs/schema-spec.md``'s paths convention (``source.keyframe`` /
    ``render.file`` must be relative to storyboard.json's directory,
    forward-slash separated, regardless of host OS). These are two
    different base directories in general.

    When ``comfyui_output_dir`` is ``None`` (``econte ingest`` was not given
    ``--comfyui-output-dir``), ``file`` is returned unchanged -- the
    pre-existing, still-supported behavior for the common case where the
    report's paths already happen to be storyboard-relative (e.g. the
    ComfyUI output directory *is* the storyboard's own directory). ``file``
    itself is also passed through unchanged if ``None`` (nothing to rebase).

    When ``comfyui_output_dir`` is given, ``file`` is resolved against it
    and re-expressed relative to ``storyboard_dir`` (defaulting to the
    current directory if that is somehow not given alongside it).

    On Windows, ``comfyui_output_dir`` and ``storyboard_dir`` are commonly
    on *different drives* (e.g. models on a dedicated data drive, projects
    on the system drive -- a completely ordinary setup, not an edge case).
    ``os.path.relpath``/``PurePath.relative_to`` cannot express a relative
    path across drives at all and raise ``ValueError``. In that situation
    we fall back to the absolute, forward-slash-normalized path instead of
    crashing the whole ingest run over one job -- an absolute path is a
    valid (if non-portable) value for ``source.keyframe``/``render.file``,
    and is strictly better than aborting every other job in the report.
    """
    if file is None or comfyui_output_dir is None:
        return file
    base_dir = storyboard_dir if storyboard_dir is not None else Path(".")
    absolute = (comfyui_output_dir / file).resolve()
    try:
        relative = os.path.relpath(absolute, base_dir.resolve())
    except ValueError:
        # Different drives on Windows -- no relative path is expressible.
        return absolute.as_posix()
    return Path(relative).as_posix()


def _ingest_keyframe_job(shot: Shot, file: str | None) -> bool:
    """``--target keyframes``: set ``shot.source.keyframe = file`` (``file``
    is ``job.file``, already rebased onto the storyboard's directory by the
    caller -- see :func:`_rebase_job_file`).

    Retake-resets-approval rule, verbatim from ``docs/compile-spec.md``: if
    this *changes* ``keyframe`` to a different value than it already held,
    also reset ``shot.source.approved = False`` -- a stale approval must
    never survive a retake silently. Re-ingesting the same report
    idempotently (the value is unchanged) leaves ``approved`` as it was.
    Returns whether anything actually changed.
    """
    assert shot.source is not None  # checked by the caller before dispatching here
    if shot.source.keyframe == file:
        return False
    shot.source.keyframe = file
    shot.source.approved = False
    return True


def _ingest_clip_job(shot: Shot, file: str | None, generated_at: str) -> bool:
    """``--target clips``: set ``shot.render = { file, renderedAt }`` (``file``
    is ``job.file``, already rebased onto the storyboard's directory by the
    caller -- see :func:`_rebase_job_file`).

    Deliberately never sets ``actualSeconds`` -- see this module's and
    ``docs/compile-spec.md``'s "Scope boundary" section: ``elapsedSeconds``
    on the report job is *generation* time, a different, unrelated number
    from the *measured* media duration ``Render.actualSeconds`` is
    documented to hold, and conflating them would silently write a wrong
    duration into the storyboard. Returns whether anything actually
    changed (comparing the new ``file``/``renderedAt`` against the shot's
    existing ``render``, if any).
    """
    new_render = Render(file=file, renderedAt=generated_at)
    old_render = shot.render
    if (
        old_render is not None
        and old_render.file == new_render.file
        and old_render.renderedAt == new_render.renderedAt
    ):
        return False
    shot.render = new_render
    return True


def ingest_report(
    storyboard: Storyboard,
    report: DeliveryReport,
    *,
    target: IngestTarget,
    comfyui_output_dir: Path | None = None,
    storyboard_dir: Path | None = None,
) -> IngestResult:
    """Write ``report``'s successful jobs back into ``storyboard``'s
    matching shots (joined by ``Shot.id`` == ``JobReport.id``), mutating
    ``storyboard`` in place.

    - A report job with ``status == "success"`` and a matching shot writes
      that shot's ``source.keyframe`` (``target == "keyframes"``, with the
      retake-resets-approval rule -- see :func:`_ingest_keyframe_job`) or
      ``render`` (``target == "clips"``, see :func:`_ingest_clip_job`).
    - A report job with any other ``status`` is left untouched and recorded
      in :attr:`IngestResult.skipped`.
    - A report job whose ``id`` has no matching shot in the storyboard is
      recorded in :attr:`IngestResult.unmatched_report_ids` (a warning-level
      situation per the spec, not fatal -- the storyboard may have been
      edited since compiling).
    - A storyboard shot absent from the report is simply left untouched (not
      reported anywhere) -- the expected, common case for a partial/
      ``--only`` run.

    ``job.file`` is documented (``docs/profile-spec.md``) as relative to the
    *ComfyUI output directory*, while ``source.keyframe``/``render.file``
    must be relative to *the storyboard.json's own directory*
    (``docs/schema-spec.md``) -- two different base directories in general.
    When both ``comfyui_output_dir`` and ``storyboard_dir`` are given,
    ``job.file`` is rebased from the former onto the latter before being
    written (see :func:`_rebase_job_file`). When ``comfyui_output_dir`` is
    omitted (the default), ``job.file`` is written verbatim, unrebased --
    the pre-existing behavior, correct only when the two directories
    happen to coincide.
    """
    shots_by_id: dict[str, Shot] = {
        shot.id: shot for scene in storyboard.scenes for shot in scene.shots
    }

    updated: list[str] = []
    skipped: list[SkippedJob] = []
    unmatched_report_ids: list[str] = []

    for job in report.jobs:
        shot = shots_by_id.get(job.id)
        if shot is None:
            unmatched_report_ids.append(job.id)
            continue

        if job.status != "success":
            skipped.append(SkippedJob(id=job.id, status=job.status))
            continue

        if shot.source is None:
            # Defensive only: compile_storyboard never produces a manifest
            # job for a shot with no source, so a "success" report job
            # should never join to a sourceless shot in the normal
            # compile -> run -> ingest pipeline. If the storyboard was
            # edited between compiling and ingesting, there is nothing
            # sensible to write -- treat like "do not touch that shot"
            # rather than crashing or inventing a Source from scratch.
            continue

        file = _rebase_job_file(
            job.file,
            comfyui_output_dir=comfyui_output_dir,
            storyboard_dir=storyboard_dir,
        )

        if target == "keyframes":
            changed = _ingest_keyframe_job(shot, file)
        else:
            changed = _ingest_clip_job(shot, file, report.generatedAt)

        if changed:
            updated.append(job.id)

    return IngestResult(
        storyboard=storyboard,
        updated=updated,
        skipped=skipped,
        unmatched_report_ids=unmatched_report_ids,
    )
