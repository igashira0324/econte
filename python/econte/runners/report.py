"""The delivery report (``<manifest>_report.json``) shape, and output-file
resolution (glob + pick) against disk.

See ``docs/profile-spec.md``'s "Output resolution & delivery report"
section for the exact JSON shape this mirrors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .profile import OutputSpec
from .template import render_template_string

__all__ = ["DeliveryReport", "JobReport", "resolve_output_file"]

JobStatus = Literal["success", "failed", "missing"]


class JobReport(BaseModel):
    """One entry of ``<manifest>_report.json``'s ``jobs`` array.

    ``model_config = ConfigDict(extra="allow")`` because every other job
    field from the manifest (``material``, ``fast``, ``chain_from``,
    ``ref_image``, ...) is carried through verbatim so ``econte ingest``
    doesn't need the original manifest at hand -- the runner passes those
    through as extra fields rather than this model hardcoding a
    profile-specific field list.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    status: JobStatus
    file: str | None = None
    elapsedSeconds: float | None = None
    seed: int
    prompt: str


class DeliveryReport(BaseModel):
    """The full ``<manifest>_report.json`` document."""

    model_config = ConfigDict(extra="ignore")

    profile: str
    manifest: str
    generatedAt: str
    jobs: list[JobReport]


def resolve_output_file(
    output_spec: OutputSpec,
    context: dict[str, Any],
    output_dir: Path,
    *,
    profile_id: str = "<unknown>",
) -> Path | None:
    """Resolve ``output_spec.glob`` (a ``${token}``-templated glob pattern,
    e.g. ``"${filename_prefix}_*.png"``) against ``context``, then glob it
    relative to ``output_dir`` and pick per ``output_spec.pick``.

    Returns ``None`` if nothing matches (the job's status is then
    ``"missing"``). ``output_spec.pick == "newest"`` is currently the only
    supported value (enforced by :class:`econte.runners.profile.OutputSpec`
    at profile-load time via a ``Literal`` type), broken by file mtime.
    """
    pattern = render_template_string(
        output_spec.glob, context, profile_id=profile_id, location="output.glob"
    )
    matches = [p for p in output_dir.glob(pattern) if p.is_file()]
    if not matches:
        return None

    # output_spec.pick is a Literal["newest"], so this is the only branch,
    # but keep the explicit check rather than assuming -- a future second
    # `pick` value should fail loudly here, not silently fall through.
    if output_spec.pick == "newest":
        return max(matches, key=lambda p: p.stat().st_mtime)

    raise ValueError(f"unsupported output.pick value: {output_spec.pick!r}")  # pragma: no cover
