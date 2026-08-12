"""econte: storyboard schema (pydantic mirror) for AI video pipelines.

See ``docs/schema-spec.md`` at the repository root for the authoritative
field-by-field specification, and ``python/econte/README.md`` for usage.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import (
    Camera,
    Character,
    GlobalStyle,
    Lyric,
    Metadata,
    Render,
    Scene,
    Shot,
    Source,
    Storyboard,
)

__all__ = [
    "Camera",
    "Character",
    "GlobalStyle",
    "Lyric",
    "Metadata",
    "Render",
    "Scene",
    "Shot",
    "Source",
    "Storyboard",
    "validate_storyboard",
]

__version__ = "0.1.0"


def validate_storyboard(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a raw dict against the :class:`Storyboard` schema.

    Returns ``(True, [])`` on success, or ``(False, [error, ...])`` on
    failure. Never raises: ``pydantic.ValidationError`` is caught internally
    and converted into a list of readable ``"path: message"`` strings.
    """
    try:
        Storyboard.model_validate(data)
    except ValidationError as exc:
        errors: list[str] = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error["loc"]) or "<root>"
            errors.append(f"{loc}: {error['msg']}")
        return False, errors
    return True, []
