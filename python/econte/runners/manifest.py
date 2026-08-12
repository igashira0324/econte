"""Pydantic v2 models for the ``econte run`` manifest JSON shape, plus
``resolve_context`` -- the per-job context resolution algorithm described in
``docs/profile-spec.md``'s "Manifest" section.

See that section for the exact precedence rule; this module's docstrings
only summarize it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .profile import Profile

__all__ = [
    "Manifest",
    "ManifestError",
    "ManifestJob",
    "load_manifest",
    "resolve_context",
]

logger = logging.getLogger(__name__)

# Runner-computed context field names -- see the table in
# docs/profile-spec.md's "Manifest" section. Always win on name collision
# with a profile/manifest/job-supplied value of the same name.
_COMPUTED_FIELD_NAMES = frozenset(
    {"id", "output_prefix", "filename_prefix", "job_index", "chain_from_index"}
)


class ManifestError(Exception):
    """Raised for manifest-shape problems the pydantic schema alone can't
    express: duplicate job ids, or a ``chain_from`` that doesn't resolve to
    an earlier job in the same manifest."""


class ManifestJob(BaseModel):
    """One entry of ``manifest.jobs``.

    Only ``id``, ``seed``, and ``prompt`` are fixed/required by the runner
    itself. Every other field (``ref_image``, ``width``, ``height``,
    ``material``, ``chain_from``, ``fast``, or any other profile-defined
    field) is accepted as open/extra data -- the runner never hardcodes
    what fields a given profile needs, it just passes the whole resolved
    job dict through as template context (see
    :func:`resolve_context` and ``econte.runners.template``).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    seed: int
    prompt: str


class Manifest(BaseModel):
    """Top-level shape of an ``econte run`` manifest JSON document."""

    model_config = ConfigDict(extra="ignore")

    profile: str
    output_prefix: str
    defaults: dict[str, Any] = Field(default_factory=dict)
    jobs: list[ManifestJob] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_job_ids(self) -> Manifest:
        seen: set[str] = set()
        dupes: list[str] = []
        for job in self.jobs:
            if job.id in seen and job.id not in dupes:
                dupes.append(job.id)
            seen.add(job.id)
        if dupes:
            raise ValueError(f"jobs: duplicate job id(s) within this manifest: {dupes}")
        return self


def load_manifest(path: Path) -> Manifest:
    """Load and validate an ``econte run`` manifest JSON file.

    Raises :class:`ManifestError` for an unreadable file, invalid JSON, or a
    schema/uniqueness violation (wrapping the underlying
    :class:`pydantic.ValidationError` so callers have one exception type to
    catch, mirroring :func:`econte.runners.profile.load_profile`).
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"could not read manifest file {path}: {exc}") from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path}: not valid JSON: {exc}") from exc

    try:
        return Manifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(f"{path}: manifest does not match the expected schema:\n{exc}") from exc


def _merge_non_none(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Merge ``src`` into ``dst`` in place, skipping any key whose value is
    ``None``.

    This is the mechanism behind the manifest spec's per-field convention
    that ``null``/absent means "inherit from a lower-precedence layer" (e.g.
    a job's explicit ``"ref_image": null`` must NOT blank out a
    ``manifest.defaults.ref_image`` value -- only an explicit non-null
    value, including ``""``, overrides).
    """
    for key, value in src.items():
        if value is not None:
            dst[key] = value


def resolve_context(profile: Profile, manifest: Manifest, job: ManifestJob) -> dict[str, Any]:
    """Build the resolved per-job template/selector context.

    Merges, lowest to highest precedence: ``profile.defaults`` ->
    ``manifest.defaults`` -> the job's own fields -> runner-computed fields
    (``id``, ``output_prefix``, ``filename_prefix``, ``job_index``, and
    ``chain_from_index`` when applicable). A ``None`` value at any layer
    does not override a lower layer's value (see :func:`_merge_non_none`).
    Runner-computed fields always win on a name collision; a collision
    (i.e. the field was already present in the context *with a different
    value*) is logged via ``logging``, not raised -- the run continues.

    Raises :class:`ManifestError` if the job's resolved ``chain_from``
    doesn't match the ``id`` of any job appearing *earlier* in
    ``manifest.jobs``.
    """
    context: dict[str, Any] = {}
    _merge_non_none(context, profile.defaults)
    _merge_non_none(context, manifest.defaults)
    _merge_non_none(context, job.model_dump())

    try:
        job_index = next(i for i, j in enumerate(manifest.jobs, start=1) if j.id == job.id)
    except StopIteration as exc:
        raise ManifestError(
            f"job {job.id!r} is not present in manifest.jobs -- resolve_context() must be "
            "called with a job object that belongs to the given manifest"
        ) from exc

    chain_from = context.get("chain_from")
    chain_from_index: int | None = None
    if chain_from:
        earlier_ids = [j.id for j in manifest.jobs[: job_index - 1]]
        if chain_from not in earlier_ids:
            raise ManifestError(
                f"job {job.id!r}: chain_from={chain_from!r} does not match the id of any "
                f"job appearing earlier in manifest.jobs (earlier ids: {earlier_ids})"
            )
        chain_from_index = earlier_ids.index(chain_from) + 1

    computed: dict[str, Any] = {
        "id": job.id,
        "output_prefix": manifest.output_prefix,
        "filename_prefix": f"{manifest.output_prefix}/{job.id}",
        "job_index": job_index,
    }
    if chain_from_index is not None:
        computed["chain_from_index"] = chain_from_index

    for key, value in computed.items():
        if key in context and context[key] != value:
            logger.warning(
                "job %r: runner-computed context field %r (=%r) overrides a manifest/profile "
                "-supplied value of %r for the same name",
                job.id,
                key,
                value,
                context[key],
            )
        context[key] = value

    return context
