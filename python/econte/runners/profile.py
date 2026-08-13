"""Pydantic v2 models for ``profiles/*.yaml`` (backend profile) documents.

See ``docs/profile-spec.md`` at the repository root for the authoritative
field-by-field specification this mirrors. A profile's ``variants[*].graph``
is kept as a plain nested ``dict`` -- ComfyUI's own per-node-class input
schemas are out of scope for econte, which only ever treats a graph as
opaque JSON with ``${token}`` placeholders in leaf positions (see
``econte.runners.template``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "Constraints",
    "CostModel",
    "OnJobFailure",
    "OutputSpec",
    "Profile",
    "ProfileError",
    "Resolution",
    "SelectorRule",
    "ServerSpec",
    "Variant",
    "VariantSelector",
    "load_profile",
]


class ProfileError(Exception):
    """Raised for any profile-load-time problem: bad YAML, schema mismatch,
    or a structurally inconsistent ``variant_selector`` (missing catch-all,
    a ``variant`` name with no matching entry in ``variants``, ...).

    Deliberately distinct from :class:`pydantic.ValidationError` so callers
    (the CLI, tests) can catch one thing for "this profile is broken",
    regardless of whether the problem was per-field typing or cross-field
    consistency.
    """


class Resolution(BaseModel):
    """``cost.reference_resolution``: the resolution the profile's measured
    ``base_seconds_per_job`` was measured at."""

    model_config = ConfigDict(extra="ignore")

    width: int
    height: int


class ServerSpec(BaseModel):
    """``server``: default ComfyUI host/port, overridable by ``econte run
    --host/--port``."""

    model_config = ConfigDict(extra="ignore")

    default_host: str
    default_port: int


class Constraints(BaseModel):
    """``constraints``: validated once per resolved job's width/height (and
    ``frames``, for profiles that declare a frame budget), before any
    network call (both ``--dry-run`` and real runs)."""

    model_config = ConfigDict(extra="ignore")

    resolution_multiple: int | None = None
    max_megapixels: float | None = None
    max_frames: int | None = None


class CostModel(BaseModel):
    """``cost``: the dry-run time estimate model. See
    ``docs/profile-spec.md``'s "Cost estimate" section for the exact
    formula this feeds (``econte.runners.cost.estimate``).

    ``reference_frames`` is optional so image profiles, which have no frame
    axis at all, stay unaffected. Setting it opts a profile into
    frame-proportional scaling *and* makes a resolved ``frames`` mandatory
    for every job -- the same treatment width/height already get, because a
    silently-unscaled estimate is worse than a refused one.
    """

    model_config = ConfigDict(extra="ignore")

    reference_resolution: Resolution
    reference_frames: int | None = None
    base_seconds_per_job: float
    first_job_overhead_seconds: float = 0.0
    multipliers: dict[str, float] = Field(default_factory=dict)


class OutputSpec(BaseModel):
    """``output``: where to find a job's produced file after success.

    ``pick`` currently only supports ``"newest"`` (break ties by mtime) --
    modeled as a ``Literal`` so an unsupported value is rejected at
    profile-load time with a normal pydantic error, rather than surfacing
    confusingly deep in a run.
    """

    model_config = ConfigDict(extra="ignore")

    glob: str
    pick: Literal["newest"] = "newest"


class SelectorRule(BaseModel):
    """One entry of ``variant_selector.map``: ``when`` names zero or more
    resolved-context fields to match (each value a bare scalar or a list of
    acceptable scalars), ``variant`` is the variant name to use if it
    matches. An empty ``when: {}`` matches unconditionally (the catch-all)."""

    model_config = ConfigDict(extra="ignore")

    when: dict[str, Any] = Field(default_factory=dict)
    variant: str


class VariantSelector(BaseModel):
    """``variant_selector``: the top-to-bottom, first-match-wins rule table
    that picks a graph variant for a given resolved job context."""

    model_config = ConfigDict(extra="ignore")

    fields: list[str] = Field(default_factory=list)
    map: list[SelectorRule] = Field(default_factory=list)


class Variant(BaseModel):
    """One named, complete ComfyUI API-format graph with ``${token}``
    placeholders in leaf string positions. Kept as an opaque nested dict --
    see the module docstring."""

    model_config = ConfigDict(extra="ignore")

    graph: dict[str, Any]


OnJobFailure = Literal["continue", "abort_remaining_chain"]


class Profile(BaseModel):
    """Top-level shape of a ``profiles/<id>.yaml`` document.

    ``on_job_failure`` is not spelled out in the field list in the top of
    ``docs/profile-spec.md``'s ``Profile`` YAML example, but the "Runner
    algorithm" section and the real ``minimax-h3-motion-context.yaml``
    profile both use it (default ``"continue"`` if a profile omits it), so
    it is modeled here as a real field rather than silently dropped by
    ``extra="ignore"`` -- see the runner algorithm in
    ``econte.runners.runner.run`` for how it's consumed.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    kind: Literal["keyframe", "video"]
    defaults: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    on_job_failure: OnJobFailure = "continue"
    server: ServerSpec
    constraints: Constraints = Field(default_factory=Constraints)
    cost: CostModel
    output: OutputSpec
    variant_selector: VariantSelector
    variants: dict[str, Variant]

    def check_consistency(self) -> None:
        """Profile-load-time structural checks beyond per-field typing.

        Raises :class:`ProfileError` (never a bare pydantic
        ``ValidationError``) so both :func:`load_profile` and direct
        construction from a hand-built :class:`Profile` (as tests do) get
        the same clear failure mode. Checked:

        - ``variant_selector.map`` is non-empty and its LAST entry is a
          catch-all (``when: {}``).
        - No *earlier* entry is itself an (unreachable) catch-all.
        - Every ``variant`` name referenced from the map exists in
          ``variants``.

        All problems found are collected and reported together, not just
        the first one.
        """
        errors: list[str] = []
        rule_map = self.variant_selector.map

        if not rule_map:
            errors.append("variant_selector.map must not be empty (a catch-all entry is required)")
        else:
            last = rule_map[-1]
            if last.when:
                errors.append(
                    "variant_selector.map: the last entry must be a catch-all "
                    f"(empty `when: {{}}`), but its `when` is {last.when!r}"
                )
            for idx, rule in enumerate(rule_map[:-1]):
                if not rule.when:
                    errors.append(
                        f"variant_selector.map[{idx}]: empty `when: {{}}` (catch-all) found "
                        "before the last entry -- every rule after it would be unreachable; "
                        "the catch-all must be LAST"
                    )

        for idx, rule in enumerate(rule_map):
            if rule.variant not in self.variants:
                errors.append(
                    f"variant_selector.map[{idx}]: variant {rule.variant!r} is not defined "
                    f"under `variants:` (known variants: {sorted(self.variants)})"
                )

        if errors:
            joined = "\n".join(f"  - {e}" for e in errors)
            raise ProfileError(f"profile {self.id!r} failed consistency checks:\n{joined}")


def load_profile(path: Path) -> Profile:
    """Load and fully validate a ``profiles/<id>.yaml`` file.

    Raises :class:`ProfileError` for anything that goes wrong: an unreadable
    file, invalid YAML, a schema mismatch, or a structurally inconsistent
    ``variant_selector`` (see :meth:`Profile.check_consistency`).
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"could not read profile file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path}: not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileError(f"{path}: profile YAML must parse to a mapping at the top level")

    try:
        profile = Profile.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(f"{path}: profile does not match the expected schema:\n{exc}") from exc

    profile.check_consistency()
    return profile
