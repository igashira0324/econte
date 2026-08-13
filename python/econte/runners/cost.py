"""Dry-run cost (time) estimation.

Implements ``docs/profile-spec.md``'s "Cost estimate" section exactly:

```
total_seconds = first_job_overhead_seconds
              + sum over jobs of:
                  base_seconds_per_job
                  * (job.width * job.height)
                    / (reference_resolution.width * reference_resolution.height)
                  * (job.frames / reference_frames)      # only if reference_frames is set
                  * product(multipliers[f] for f in multipliers if job.get(f) is truthy)
```

"``job.width``/``job.height``/``job.frames``" means each job's *resolved*
values (via :func:`econte.runners.manifest.resolve_context`), since most
jobs get these from ``manifest.defaults`` or ``profile.defaults`` rather
than setting them per-job.

The frame term is deliberately *linear* even though a video DiT's attention
cost is superlinear in sequence length. Linearity is a good approximation
only near the measured reference point, which is exactly why
``constraints.max_frames`` is an **error** rather than a warning: past that
budget this estimate is not merely imprecise, it is wrong by orders of
magnitude, so the runner refuses the job instead of quoting a number it
knows it cannot stand behind.
"""

from __future__ import annotations

from pydantic import BaseModel

from .manifest import Manifest, resolve_context
from .profile import Profile

__all__ = ["CostEstimate", "CostError", "JobCost", "estimate"]


class CostError(Exception):
    """Raised when a job's resolved context is missing a value the cost
    estimate needs (width/height always; ``frames`` when the profile sets
    ``cost.reference_frames``) -- e.g. neither the job nor any default
    layer set them."""


class JobCost(BaseModel):
    id: str
    seconds: float


class CostEstimate(BaseModel):
    total_seconds: float
    per_job: list[JobCost]


def estimate(profile: Profile, manifest: Manifest) -> CostEstimate:
    """Compute the dry-run total/per-job time estimate for every job in
    ``manifest`` under ``profile``'s cost model. Purely arithmetic -- no
    network calls, no filesystem access."""
    ref = profile.cost.reference_resolution
    reference_area = ref.width * ref.height

    per_job: list[JobCost] = []
    total = float(profile.cost.first_job_overhead_seconds)

    for job in manifest.jobs:
        context = resolve_context(profile, manifest, job)
        width = context.get("width")
        height = context.get("height")
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            raise CostError(
                f"job {job.id!r}: cost estimate requires a resolved numeric width/height "
                f"(got width={width!r}, height={height!r}); set them in the job, "
                "manifest.defaults, or profile.defaults"
            )

        frame_ratio = 1.0
        reference_frames = profile.cost.reference_frames
        if reference_frames is not None:
            frames = context.get("frames")
            if not isinstance(frames, (int, float)) or isinstance(frames, bool):
                raise CostError(
                    f"job {job.id!r}: this profile's cost model sets reference_frames="
                    f"{reference_frames}, so a resolved numeric 'frames' is required "
                    f"(got frames={frames!r}); set it in the job, manifest.defaults, "
                    "or profile.defaults"
                )
            frame_ratio = frames / reference_frames

        multiplier = 1.0
        for field, factor in profile.cost.multipliers.items():
            if context.get(field):
                multiplier *= factor

        seconds = (
            profile.cost.base_seconds_per_job
            * (width * height / reference_area)
            * frame_ratio
            * multiplier
        )
        per_job.append(JobCost(id=job.id, seconds=seconds))
        total += seconds

    return CostEstimate(total_seconds=total, per_job=per_job)
