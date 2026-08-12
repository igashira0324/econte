"""Variant selection: pick which of a profile's named graph variants a
resolved job context maps to.

Implements ``docs/profile-spec.md``'s "Variant selection" section exactly:
``variant_selector.map`` is evaluated top to bottom against the resolved
job context, first match wins. A ``when`` clause matches if, for every
field it names, the context's value equals one of the listed value(s) (a
bare scalar is normalized to a one-element list). Per the profile spec's
own annotated example (the ``qwen-image-edit-2511`` profile's
``{ ref_image: null }`` rule), a listed value of ``null`` matches a
context value that is missing, ``None``, or ``""`` -- not just a literal
Python ``None`` -- since a manifest job's ``null``/absent/``""`` all carry
distinct-but-related "no reference image" meanings for that field (see
``docs/profile-spec.md``'s "Manifest" section on ``ref_image``).
"""

from __future__ import annotations

from typing import Any

from .profile import Profile

__all__ = ["SelectorError", "select_variant"]


class SelectorError(Exception):
    """Raised if no entry of ``variant_selector.map`` matches a given
    context. Should be unreachable in practice: ``Profile.check_consistency``
    (run at profile-load time by ``load_profile``) already requires a
    catch-all (``when: {}``) as the map's last entry. Kept as a real,
    defensive check rather than an assertion because a caller could in
    principle hand-construct a ``Profile`` that skips that check."""


def _normalize(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else [raw]


def _value_matches(actual: Any, allowed: list[Any]) -> bool:
    for candidate in allowed:
        if candidate is None:
            # null in `when` matches missing/None/"" -- see module docstring.
            if actual is None or actual == "":
                return True
        elif actual == candidate:
            return True
    return False


def _when_matches(when: dict[str, Any], context: dict[str, Any]) -> bool:
    for field, raw_allowed in when.items():
        if not _value_matches(context.get(field), _normalize(raw_allowed)):
            return False
    return True


def select_variant(profile: Profile, context: dict[str, Any]) -> str:
    """Return the name of the graph variant that ``context`` resolves to
    under ``profile.variant_selector``.

    Raises :class:`SelectorError` if (defensively; see the class docstring)
    no rule matches.
    """
    for rule in profile.variant_selector.map:
        if _when_matches(rule.when, context):
            return rule.variant

    raise SelectorError(
        f"profile {profile.id!r}: no variant_selector.map rule matched context "
        f"(inspected fields: {profile.variant_selector.fields}); this should be unreachable "
        "because profile-load-time validation requires a catch-all `when: {}` entry -- if you "
        "see this, the Profile was constructed without going through load_profile()'s "
        "consistency check"
    )
