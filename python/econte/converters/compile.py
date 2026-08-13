"""``econte compile``: turn a storyboard into per-backend manifest files.

See ``docs/compile-spec.md`` at the repository root, section
``econte compile``, for the authoritative specification this module
implements exactly: the eligibility filter (which shots are compiled for a
given ``--target``), the backend grouping + manifest filename convention,
the shot -> :class:`~econte.runners.manifest.ManifestJob` field mapping
(including the target-dependent ``ref_image`` resolution logic), and the
deterministic seed-derivation formula.

This module does not write any files itself -- :func:`compile_storyboard`
is a pure function from a validated :class:`~econte.models.Storyboard` to a
:class:`CompileResult`. Writing each group's manifest to disk (using the
``<storyboard-title-slug>_<target>_<backend>.json`` naming convention, via
:func:`slugify`) is the CLI's job (``econte.cli._cmd_compile``), so the
naming convention lives here as a reusable, independently-testable
function rather than being duplicated in the CLI.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..models import Character, Shot, Storyboard
from ..runners import Manifest, ManifestJob, Profile, ProfileError, load_profile

__all__ = [
    "CompileError",
    "CompileGroup",
    "CompileResult",
    "compile_storyboard",
    "slugify",
]

CompileTarget = Literal["keyframes", "clips"]

# Maps a compile --target to the profiles/*.yaml `kind` it requires.
# See docs/compile-spec.md's Eligibility filter, last bullet.
_EXPECTED_PROFILE_KIND: dict[CompileTarget, Literal["keyframe", "video"]] = {
    "keyframes": "keyframe",
    "clips": "video",
}

# Same charset as Shot.id/Scene.id (see docs/schema-spec.md): only these
# characters survive slugify(); everything else is stripped, not replaced,
# per docs/compile-spec.md's "strip/replace anything else" wording -- see
# slugify()'s docstring for why stripping was chosen over replacing.
_SLUG_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9_-]+")


class CompileError(Exception):
    """Raised for a *hard* compile error: an invalid ``--width``/``--height``
    (doesn't reduce to any of ``metadata.aspectRatios``), or one or more
    shots whose ``source.backend`` profile fails to load entirely (missing
    file, invalid YAML -- almost always a typo'd/nonexistent backend name).

    A profile that loads fine but has the *wrong kind* for ``--target`` is
    **not** a hard error -- see ``compile_storyboard``'s docstring for why:
    it is treated as an ordinary eligibility skip (a warning), since it is
    the normal shape of a shot already staged for a different compile pass.

    Per-shot hard errors are collected across the *entire* storyboard
    (mirroring ``Storyboard._validate_document_rules``'s "collect everything,
    then raise once" style) rather than raising on the first one found, so a
    single ``compile`` invocation reports every problem at once.
    """


@dataclass
class CompileGroup:
    """One compiled manifest, for a single ``source.backend`` value.

    ``warnings`` holds per-group notices -- currently only seed
    auto-derivation notices (see :func:`compile_storyboard`'s docstring) --
    as opposed to :class:`CompileResult`'s top-level ``warnings``, which
    holds whole-storyboard eligibility-skip notices that aren't tied to any
    particular backend (a shot skipped for having no backend at all has no
    group to attach a warning to).
    """

    backend: str
    manifest: Manifest
    warnings: list[str] = field(default_factory=list)


@dataclass
class CompileResult:
    """The result of :func:`compile_storyboard`: one :class:`CompileGroup`
    per backend encountered among eligible shots (in the order each backend
    was first encountered, i.e. document order), plus top-level
    ``warnings`` for storyboard-wide eligibility-skip notices."""

    groups: list[CompileGroup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def slugify(title: str) -> str:
    """Slugify a storyboard title for use in a manifest filename.

    Per ``docs/compile-spec.md``'s "Grouping" section: lowercased, spaces
    replaced with ``-``, then restricted to the same charset as
    ``Shot.id``/``Scene.id`` (``^[A-Za-z0-9_-]+$``) by *stripping* (not
    replacing) any other character. Stripping was chosen over substituting
    a placeholder character because the spec's own "strip/replace anything
    else" wording explicitly allows either, and stripping keeps slugs
    shorter and avoids runs of placeholder characters for titles with
    several kinds of punctuation (e.g. ``"Haruka: A Memory!"``).
    """
    lowered = title.lower().replace(" ", "-")
    return _SLUG_DISALLOWED_RE.sub("", lowered)


def _reduce_ratio(width: int, height: int) -> tuple[int, int]:
    divisor = math.gcd(width, height)
    return width // divisor, height // divisor


def _parse_aspect_ratio(ratio: str) -> tuple[int, int]:
    width_str, height_str = ratio.split(":")
    return int(width_str), int(height_str)


def _validate_resolution_matches_aspect_ratio(
    storyboard: Storyboard, width: int, height: int
) -> None:
    """``--width``/``--height`` must reduce to the same ratio as one of
    ``metadata.aspectRatios``. Both sides are reduced via ``math.gcd``
    before comparing (not just the ``--width``/``--height`` side) so an
    unreduced ``aspectRatios`` entry -- the schema only requires the
    ``\\d+:\\d+`` pattern, not that it already be in lowest terms -- still
    matches correctly.
    """
    if width <= 0 or height <= 0:
        raise CompileError(f"--width/--height must both be positive (got {width}x{height})")

    target_ratio = _reduce_ratio(width, height)
    for declared in storyboard.metadata.aspectRatios:
        declared_w, declared_h = _parse_aspect_ratio(declared)
        if _reduce_ratio(declared_w, declared_h) == target_ratio:
            return

    raise CompileError(
        f"--width {width} --height {height} (reduces to "
        f"{target_ratio[0]}:{target_ratio[1]}) does not match any of "
        f"metadata.aspectRatios {list(storyboard.metadata.aspectRatios)!r}"
    )


def _derive_seed(shot_id: str) -> int:
    """Deterministic seed derivation, used only when ``source.seed`` is
    unset. Verbatim from ``docs/compile-spec.md``'s "Deterministic seed
    derivation" section -- do not approximate this formula, it must be
    reproducible byte-for-byte against the spec's own worked description::

        seed = int(hashlib.sha256(shot.id.encode()).hexdigest()[:8], 16) % (2**31)
    """
    return int(hashlib.sha256(shot_id.encode()).hexdigest()[:8], 16) % (2**31)


def _character_ref_image(shot: Shot, characters_by_id: dict[str, Character]) -> str | None:
    """``characters[subject_id].refs[0]`` if ``shot.subject`` is set, else
    ``None``. Shared by both targets' ``ref_image`` resolution (see
    :func:`_resolve_ref_image`)."""
    if shot.subject is None:
        return None
    character_id = shot.subject[1:]  # strip the leading "@"
    character = characters_by_id.get(character_id)
    if character is None:
        # Storyboard-level validation (schema-spec.md rule 5) already
        # guarantees shot.subject references an existing character, so this
        # is unreachable for a Storyboard that passed model validation --
        # kept as a defensive fallback rather than an assert.
        return None
    return character.refs[0]


def _resolve_ref_image(
    shot: Shot, target: CompileTarget, characters_by_id: dict[str, Character]
) -> str | None:
    """``ref_image`` resolution -- the target-dependent part of
    ``docs/compile-spec.md``'s "Field mapping" section. ``None`` means
    "omit ``ref_image`` from the job entirely" (the caller must not set the
    key at all, not set it to an explicit ``null``/``None`` -- see that
    section's "omitted entirely" wording, and ``docs/profile-spec.md``'s
    manifest field precedence, where an *absent* ``ref_image`` and an
    *explicit* ``null`` mean the same thing to the runner in practice, but
    "omitted entirely" is what the spec asks for)."""
    if target == "keyframes":
        return _character_ref_image(shot, characters_by_id)

    # target == "clips": the approved keyframe still, if set; otherwise the
    # same character-reference-sheet fallback as keyframes; otherwise omit.
    source = shot.source
    assert source is not None  # guaranteed by the eligibility filter, see compile_storyboard
    if source.keyframe:
        return source.keyframe
    return _character_ref_image(shot, characters_by_id)


def compile_storyboard(
    storyboard: Storyboard,
    *,
    target: CompileTarget,
    profile_dir: Path,
    width: int,
    height: int,
) -> CompileResult:
    """Compile ``storyboard`` into one manifest per ``source.backend`` group
    among the shots eligible for ``target``.

    Implements ``docs/compile-spec.md``'s "Eligibility filter" and "Field
    mapping" sections exactly:

    - ``shot.source`` must be present with ``type == "generate"`` (``asset``/
      ``remotion`` shots, and shots with no ``source`` at all, are silently
      not eligible -- not a warning, they're simply not econte's to
      generate).
    - Missing ``source.backend`` or empty ``source.prompt`` -> skip with a
      warning (collected into :class:`CompileResult`'s top-level
      ``warnings``).
    - For ``target == "clips"`` only: ``source.approved`` must be ``true``,
      else skip (also collected as a warning, at "this is normal" severity
      -- see the spec's own wording -- rather than being escalated).
    - The shot's ``profiles/<backend>.yaml`` must load. A load failure (the
      file is missing or fails to parse) is a hard error, collected across
      the whole storyboard and raised together as a single
      :class:`CompileError` once every shot has been examined (see that
      exception's docstring) -- this is almost always a storyboard-authoring
      typo (a nonexistent backend name), so it must not be silently skipped.
    - If the profile loads but its ``kind`` does not match ``target``
      (``keyframe`` for ``keyframes``, ``video`` for ``clips``), the shot is
      **skipped with a warning**, not a hard error. This is deliberately
      *not* escalated to :class:`CompileError`: a realistic multi-stage
      production storyboard routinely contains shots already progressed to
      a different backend/phase than the one currently being compiled (e.g.
      some shots advanced to a video backend while others still need a
      keyframes pass) -- that is completely normal and must not block
      compiling the shots that *are* eligible for this pass. The warning
      still names the shot, its backend, and the profile's actual kind, so a
      genuine wrong-backend-assignment mistake remains visible.

    Raises :class:`CompileError` if ``--width``/``--height`` don't reduce to
    any of ``metadata.aspectRatios``, or if any shot's backend profile
    failed to load.
    """
    _validate_resolution_matches_aspect_ratio(storyboard, width, height)

    characters_by_id = {c.id: c for c in storyboard.characters}
    expected_kind = _EXPECTED_PROFILE_KIND[target]

    top_level_warnings: list[str] = []
    hard_errors: list[str] = []
    profile_cache: dict[str, Profile] = {}
    jobs_by_backend: dict[str, list[ManifestJob]] = {}
    notices_by_backend: dict[str, list[str]] = {}

    for scene in storyboard.scenes:
        for shot in scene.shots:
            source = shot.source
            if source is None or source.type != "generate":
                continue

            if not source.backend:
                top_level_warnings.append(f"shot {shot.id!r} skipped: no backend set")
                continue

            if not source.prompt:
                top_level_warnings.append(f"shot {shot.id!r} skipped: no prompt set")
                continue

            if target == "clips" and not source.approved:
                top_level_warnings.append(
                    f"shot {shot.id!r} skipped: not approved yet "
                    "(--target clips requires source.approved=true)"
                )
                continue

            backend = source.backend
            profile = profile_cache.get(backend)
            if profile is None:
                try:
                    profile = load_profile(profile_dir / f"{backend}.yaml")
                except ProfileError as exc:
                    hard_errors.append(
                        f"shot {shot.id!r}: backend profile {backend!r} failed to load: {exc}"
                    )
                    continue
                profile_cache[backend] = profile

            if profile.kind != expected_kind:
                # Not a hard error: a shot whose backend has already
                # progressed to a different kind/phase is the normal shape
                # of an incremental, multi-stage storyboard (see
                # compile_storyboard's docstring and docs/compile-spec.md's
                # eligibility filter) -- skip it for *this* compile pass
                # rather than failing the whole storyboard.
                top_level_warnings.append(
                    f"shot {shot.id!r} skipped: backend {backend!r} is a {profile.kind!r} "
                    f"profile, but --target {target} requires a {expected_kind!r} profile "
                    "(likely a shot already staged for a different compile pass)"
                )
                continue

            seed = source.seed
            if seed is None:
                seed = _derive_seed(shot.id)
                notices_by_backend.setdefault(backend, []).append(
                    f"shot {shot.id!r}: no source.seed set, auto-derived seed {seed} from the "
                    "shot id (set source.seed to pin it)"
                )

            job_fields: dict[str, Any] = {
                "id": shot.id,
                "seed": seed,
                "prompt": source.prompt,
                "material": source.material or "chain_start",
                "chain_from": source.chain_from,
            }
            ref_image = _resolve_ref_image(shot, target, characters_by_id)
            if ref_image is not None:
                job_fields["ref_image"] = ref_image

            jobs_by_backend.setdefault(backend, []).append(ManifestJob.model_validate(job_fields))

    if hard_errors:
        raise CompileError("; ".join(hard_errors))

    slug = slugify(storyboard.metadata.title)
    groups = [
        CompileGroup(
            backend=backend,
            manifest=Manifest(
                profile=backend,
                output_prefix=f"{slug}_{target}_{backend}",
                defaults={"width": width, "height": height},
                jobs=jobs,
            ),
            warnings=notices_by_backend.get(backend, []),
        )
        for backend, jobs in jobs_by_backend.items()
    ]

    return CompileResult(groups=groups, warnings=top_level_warnings)
