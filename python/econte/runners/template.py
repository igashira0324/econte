"""``${token}`` placeholder substitution for profile graph variants.

Implements ``docs/profile-spec.md``'s "Placeholder resolution" section
exactly:

1. A leaf string that is *entirely* ``${name}`` is replaced with the raw,
   typed value from the resolved context (an int stays an int, a bool
   stays a bool -- ComfyUI's node inputs are type-sensitive).
2. A leaf string *containing* one or more ``${name}`` occurrences (but not
   matching rule 1) has every occurrence replaced with ``str(value)``.
3. A token name absent from the resolved context is a hard error.

Non-string leaves (numbers, booleans, ``None``, and node-reference arrays
like ``["6", 0]``) are left untouched -- this falls out naturally here: a
recursive walk only ever attempts substitution on ``str`` leaves, so a list
like ``["6", 0]`` is walked element-by-element (the literal string ``"6"``
contains no ``${...}`` occurrence and is re-emitted unchanged, the int
``0`` is a non-string leaf) rather than being treated as a single
substitution candidate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = ["TemplateError", "build_graph", "render_template_string"]

# Whole-string form: nothing but a single token. Typed, raw substitution.
_FULL_TOKEN_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
# Substring form: every occurrence gets stringified substitution.
_TOKEN_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class TemplateError(Exception):
    """Raised when a graph (or other profile-defined template string, e.g.
    ``output.glob``) references a ``${token}`` not present in the resolved
    job context. Always names enough to find the offending leaf: the
    profile id, the variant name (for graph leaves), the node id + input
    key path, and the missing token name."""


class _MissingToken(Exception):
    """Internal signal carrying just the missing token name, caught and
    re-raised as a fully-contextualized :class:`TemplateError` by whichever
    public function is walking the structure (so the regex/lookup logic
    itself doesn't need to know whether it's inside a graph node or a bare
    string like ``output.glob``)."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


def _substitute(value: str, context: Mapping[str, Any]) -> Any:
    full = _FULL_TOKEN_RE.fullmatch(value)
    if full is not None:
        token = full.group(1)
        if token not in context:
            raise _MissingToken(token)
        return context[token]

    def _sub_one(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in context:
            raise _MissingToken(token)
        return str(context[token])

    return _TOKEN_RE.sub(_sub_one, value)


def render_template_string(
    value: str,
    context: Mapping[str, Any],
    *,
    profile_id: str,
    location: str,
) -> Any:
    """Render a single template string outside of a graph (e.g.
    ``output.glob``). ``location`` is a free-form description used only in
    the :class:`TemplateError` message on failure (e.g. ``"output.glob"``).
    """
    try:
        return _substitute(value, context)
    except _MissingToken as exc:
        raise TemplateError(
            f"profile {profile_id!r}: {location}: references unknown token "
            f"'${{{exc.token}}}' which is not present in the resolved job context"
        ) from exc


def build_graph(
    variant_graph: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    profile_id: str,
    variant_name: str,
) -> dict[str, Any]:
    """Resolve every ``${token}`` placeholder in ``variant_graph`` against
    ``context``, returning a brand-new (never aliasing the input) graph
    dict ready to submit as a ComfyUI ``/prompt`` body's ``"prompt"``
    value.

    Raises :class:`TemplateError` naming ``profile_id``, ``variant_name``,
    the offending node id, the input key path within that node, and the
    missing token name, on the first unresolved token encountered.
    """

    def _walk(node: Any, path: list[str]) -> Any:
        if isinstance(node, dict):
            return {key: _walk(val, [*path, str(key)]) for key, val in node.items()}
        if isinstance(node, list):
            return [_walk(val, [*path, str(i)]) for i, val in enumerate(node)]
        if isinstance(node, str):
            try:
                return _substitute(node, context)
            except _MissingToken as exc:
                node_id = path[0] if path else "<root>"
                input_path = ".".join(path[1:]) if len(path) > 1 else "<root>"
                raise TemplateError(
                    f"profile {profile_id!r} variant {variant_name!r}: node {node_id!r} "
                    f"input {input_path!r} references unknown token '${{{exc.token}}}' "
                    "which is not present in the resolved job context"
                ) from exc
        # Non-string leaf (int, float, bool, None): structural data, left untouched.
        return node

    result = _walk(dict(variant_graph), [])
    assert isinstance(result, dict)  # the top level of a graph is always a dict of nodes
    return result
