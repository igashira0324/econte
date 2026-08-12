"""Dry-run cost (time) estimation.

Implements ``docs/profile-spec.md``'s "Cost estimate" section exactly:

```
total_seconds = first_job_overhead_seconds
              + sum over jobs of:
                  base_seconds_per_job
                  * (job.width * job.height)
                    / (reference_resolution.width * reference_resolution.height)
                  * product(multipliers[f] for f in multipliers if job.get(f) is truthy)
```

"``job.width``/``job.height``" means each job's *resolved* width/height
(via :func:`econte.runners.manifest.resolve_context`), since most jobs get
these from ``manifest.defaults`` rather than setting them per-job.
"""

from __future__ import annotations

from pydantic import BaseModel

from .manifest import Manifest, resolve_context
from .profile import Profile

__all__ = ["CostEstimate", "CostError", "JobCost", "estimate"]


class CostError(Exception):
    """Raised when a job's resolved context is missing the width/height a
    cost estimate needs (e.g. neither the job nor any default layer set
    them)."""


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

        multiplier = 1.0
        for field, factor in profile.cost.multipliers.items():
            if context.get(field):
                multiplier *= factor

        seconds = profile.cost.base_seconds_per_job * (width * height / reference_area) * multiplier
        per_job.append(JobCost(id=job.id, seconds=seconds))
        total += seconds

    return CostEstimate(total_seconds=total, per_job=per_job)
