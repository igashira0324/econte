"""Pydantic v2 models mirroring the econte storyboard schema.

This is a **hand-maintained mirror** of the TypeScript/Zod schema in
``packages/econte`` (the source of truth). Every constraint here must be
independently derived from ``docs/schema-spec.md`` and kept in sync with it
-- see that document and ``CONTRIBUTING.md`` for the cross-language golden
fixture policy (``spec/fixtures/*.json``).

Field names intentionally use the same camelCase spelling as the JSON
documents themselves (e.g. ``globalStyle``, ``aspectRatios``) rather than
being translated to snake_case, so that the model shape maps 1:1 onto the
wire format and onto the Zod schema this mirrors.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# --- Reusable constrained string types -------------------------------------

VersionStr = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
AspectRatioStr = Annotated[str, StringConstraints(pattern=r"^\d+:\d+$")]
HexColorStr = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
CharacterIdStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]
SceneOrShotIdStr = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]

# ISO 8601 datetime with a required offset (`Z`, or `+HH:MM`/`+HHMM`),
# mirroring the regex `packages/econte/src/schema.ts`'s
# `z.string().datetime({ offset: true })` check compiles to (see zod's
# `datetimeRegex`/`dateRegexSource`/`timeRegexSource` helpers) -- including
# leap-year-aware calendar validation -- so that Python rejects exactly what
# TS rejects for `Render.renderedAt`.
_ISO_DATE_SRC = (
    r"((\d\d[2468][048]|\d\d[13579][26]|\d\d0[48]|[02468][048]00|[13579][26]00)-02-29"
    r"|\d{4}-((0[13578]|1[02])-(0[1-9]|[12]\d|3[01])"
    r"|(0[469]|11)-(0[1-9]|[12]\d|30)"
    r"|(02)-(0[1-9]|1\d|2[0-8])))"
)
_ISO_TIME_SRC = r"([01]\d|2[0-3]):[0-5]\d(:[0-5]\d(\.\d+)?)?"
_ISO_OFFSET_SRC = r"(Z|([+-]\d{2}:?\d{2}))"
IsoDatetimeStr = Annotated[
    str,
    StringConstraints(
        pattern=rf"^{_ISO_DATE_SRC}T{_ISO_TIME_SRC}{_ISO_OFFSET_SRC}$"
    ),
]

Framing = Literal[
    "ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS", "OTS", "POV", "2S", "INS", "FS", "BEV",
]
SourceType = Literal["generate", "asset", "remotion"]
SourceMaterial = Literal["chain", "chain_start", "standalone"]


class Metadata(BaseModel):
    """Storyboard-level metadata: title, audio, framerate, output formats."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1)
    artist: str | None = None
    audio: str | None = None
    durationInSeconds: float | None = Field(default=None, gt=0)
    fps: int = Field(gt=0)
    aspectRatios: list[AspectRatioStr] = Field(min_length=1)
    concept: str | None = None


class Character(BaseModel):
    """A recurring character, referenced from ``Shot.subject`` as ``"@" + id``."""

    model_config = ConfigDict(extra="ignore")

    id: CharacterIdStr
    identity: str = Field(min_length=1)
    refs: list[str] = Field(min_length=1)


class GlobalStyle(BaseModel):
    """Document-wide look: color palette, grade description, negative terms."""

    model_config = ConfigDict(extra="ignore")

    palette: list[HexColorStr] | None = None
    grade: str | None = None
    negative: list[str] | None = None


class Camera(BaseModel):
    """Per-shot camera framing (enum) and movement (free text)."""

    model_config = ConfigDict(extra="ignore")

    framing: Framing | None = None
    movement: str | None = None


class Source(BaseModel):
    """Generation / asset provenance for a shot."""

    model_config = ConfigDict(extra="ignore")

    type: SourceType
    backend: str | None = None
    keyframe: str | None = None
    seed: int | None = None
    prompt: str | None = None
    # Machine-readable approval gate. Defaults to False when omitted on
    # input; implementations must always populate it (never leave as None)
    # so downstream consumers can rely on it always being present.
    approved: bool = False
    material: SourceMaterial | None = None


class Render(BaseModel):
    """Populated by ``econte ingest`` after generation; absent until then."""

    model_config = ConfigDict(extra="ignore")

    file: str | None = None
    actualSeconds: float | None = Field(default=None, gt=0)
    renderedAt: IsoDatetimeStr | None = None


class Lyric(BaseModel):
    """A lyric line synced to a shot's frame range."""

    model_config = ConfigDict(extra="ignore")

    text: str
    startMs: int = Field(ge=0)
    endMs: int
    animation: str | None = None


class Shot(BaseModel):
    """A single shot within a scene."""

    model_config = ConfigDict(extra="ignore")

    id: SceneOrShotIdStr
    frames: tuple[int, int]
    idea: str | None = None
    subject: str | None = None
    action: str | None = None
    camera: Camera | None = None
    heroMotion: str | None = None
    audioSync: str | None = None
    source: Source | None = None
    render: Render | None = None
    lyric: Lyric | None = None

    @model_validator(mode="after")
    def _validate_frame_bounds(self) -> Shot:
        # Per-field bound: both frame indices must be non-negative. The
        # comparative "end > start" rule is a document-level rule (spec
        # rule 4) and is enforced on the root Storyboard model, alongside
        # the other cross-field checks.
        start, end = self.frames
        if start < 0 or end < 0:
            raise ValueError("frames: both start and end must be >= 0")
        return self

    @model_validator(mode="after")
    def _validate_subject_prefix(self) -> Shot:
        # A non-null subject must be "@" + <character id>. The referential
        # check (does that character id actually exist) needs the full
        # document and is done in Storyboard's model_validator.
        if self.subject is not None and (
            not self.subject.startswith("@") or len(self.subject) <= 1
        ):
            raise ValueError(
                'subject: must be null/absent or "@" followed by a character id '
                '(e.g. "@haruka"); a bare id, or "@" alone, is not a defined '
                "convention in v1"
            )
        return self


class Scene(BaseModel):
    """A named group of shots, e.g. a song section."""

    model_config = ConfigDict(extra="ignore")

    id: SceneOrShotIdStr
    section: str | None = None
    shots: list[Shot] = Field(min_length=1)


class Storyboard(BaseModel):
    """Top-level econte storyboard document."""

    model_config = ConfigDict(extra="ignore")

    version: VersionStr
    metadata: Metadata
    characters: list[Character]
    globalStyle: GlobalStyle | None = None
    audioAnalysis: str | None = None
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_document_rules(self) -> Storyboard:
        """Cross-field / document-level rules from schema-spec.md.

        1. Character.id unique within characters[].
        2. Scene.id unique within scenes[].
        3. Shot.id unique across the *entire* document (all scenes combined).
        4. Shot.frames: frames[1] > frames[0].
        5. Shot.subject, if "@"-prefixed, must reference an existing Character.id.
        6. Lyric.endMs > Lyric.startMs.
        (Non-empty array constraints -- rule 7 -- are enforced via Field
        constraints on the individual models above.)
        """
        errors: list[str] = []

        # Rule 1: character id uniqueness.
        character_ids = [c.id for c in self.characters]
        seen_character_ids: set[str] = set()
        for cid in character_ids:
            if cid in seen_character_ids:
                errors.append(f"characters: duplicate character id {cid!r}")
            seen_character_ids.add(cid)

        # Rule 2 & 3: scene id uniqueness, and shot id uniqueness across the
        # whole document.
        seen_scene_ids: set[str] = set()
        seen_shot_ids: set[str] = set()
        for scene_index, scene in enumerate(self.scenes):
            if scene.id in seen_scene_ids:
                errors.append(f"scenes[{scene_index}]: duplicate scene id {scene.id!r}")
            seen_scene_ids.add(scene.id)

            for shot_index, shot in enumerate(scene.shots):
                path = f"scenes[{scene_index}].shots[{shot_index}]"

                if shot.id in seen_shot_ids:
                    errors.append(f"{path}: duplicate shot id {shot.id!r} across document")
                seen_shot_ids.add(shot.id)

                # Rule 4: frames end > start.
                start, end = shot.frames
                if end <= start:
                    errors.append(
                        f"{path}.frames: end ({end}) must be greater than start ({start})"
                    )

                # Rule 5: subject referential integrity.
                if shot.subject is not None:
                    referenced_id = shot.subject[1:]  # strip leading "@"
                    if referenced_id not in seen_character_ids:
                        errors.append(
                            f"{path}.subject: references unknown character id "
                            f"{referenced_id!r}"
                        )

                # Rule 6: lyric endMs > startMs.
                if shot.lyric is not None and shot.lyric.endMs <= shot.lyric.startMs:
                    errors.append(
                        f"{path}.lyric: endMs ({shot.lyric.endMs}) must be greater than "
                        f"startMs ({shot.lyric.startMs})"
                    )

        if errors:
            raise ValueError("; ".join(errors))

        return self
