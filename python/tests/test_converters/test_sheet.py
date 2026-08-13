"""Tests for econte.converters.sheet: the ``econte sheet`` HTML approval
sheet generator.

Covers: real-keyframe thumbnails round-trip through base64 JPEG encoding,
missing/unset keyframes render a placeholder instead of crashing or
producing a broken <img>, HTML-injection-shaped free text is escaped,
summary counts match a hand-built mix of shots, and the overall document is
well-formed enough to matter (balanced tag nesting).
"""

from __future__ import annotations

import base64
import html
import io
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image

from econte.converters.sheet import build_sheet_html, format_summary_line, summarize_storyboard
from econte.models import Camera, Metadata, Scene, Shot, Source, Storyboard

# --- fixtures -----------------------------------------------------------


@pytest.fixture
def tiny_png(tmp_path: Path) -> Path:
    """Write a tiny (64x36, 16:9), solid-color, real PNG file and return its
    path -- a real decodable image rather than an empty/fake stand-in, so
    thumbnail-generation tests exercise actual Pillow decode/resize/encode.
    Defined locally (rather than in conftest.py) so this test module stays
    self-contained and doesn't compete over shared fixture file content
    with the other econte.converters test modules.
    """
    path = tmp_path / "keyframe.png"
    image = Image.new("RGB", (64, 36), color=(80, 120, 200))
    image.save(path, format="PNG")
    return path


# --- helpers ----------------------------------------------------------------


def _storyboard(scenes: list[Scene], *, title: str = "Test Storyboard") -> Storyboard:
    return Storyboard(
        version="0.1.0",
        metadata=Metadata(title=title, fps=24, aspectRatios=["16:9"]),
        characters=[],
        scenes=scenes,
    )


_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _TagBalanceChecker(HTMLParser):
    """A permissive well-formedness check: every non-void opening tag must
    be closed, in order, by a matching closing tag. Not a full HTML
    validator (that's overkill for a generated, self-contained sheet), but
    enough to catch an unclosed <div>/<article>/<section> left behind by a
    templating bug."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        assert self.stack, f"unexpected closing tag </{tag}> with an empty open-tag stack"
        top = self.stack.pop()
        assert top == tag, f"mismatched tag nesting: expected </{top}>, got </{tag}>"


def _assert_balanced_html(html_text: str) -> None:
    checker = _TagBalanceChecker()
    checker.feed(html_text)
    checker.close()
    assert checker.stack == [], f"unclosed tag(s) at end of document: {checker.stack}"


def _extract_first_data_uri(html_text: str) -> bytes:
    match = re.search(r'data:image/jpeg;base64,([A-Za-z0-9+/=]+)"', html_text)
    assert match is not None, "expected an embedded base64 JPEG data URI in the output"
    return base64.b64decode(match.group(1))


# --- tests --------------------------------------------------------------


def test_real_keyframe_renders_a_valid_embedded_jpeg_thumbnail(tiny_png: Path) -> None:
    storyboard_dir = tiny_png.parent
    shot = Shot(
        id="S01-A",
        frames=(0, 10),
        source=Source(
            type="generate", backend="qwen-image-edit-2511", prompt="p",
            keyframe=tiny_png.name, approved=True,
        ),
    )
    storyboard = _storyboard([Scene(id="SC1", shots=[shot])])

    html_out = build_sheet_html(storyboard, storyboard_dir=storyboard_dir, thumb_width=200)

    decoded = _extract_first_data_uri(html_out)
    with Image.open(io.BytesIO(decoded)) as img:
        img.load()
        assert img.format == "JPEG"
        width, height = img.size

    assert width == 200
    orig_width, orig_height = 64, 36  # matches the tiny_png fixture
    assert abs((height / width) - (orig_height / orig_width)) < 0.02


def test_shot_with_no_keyframe_set_renders_placeholder_without_crashing(tmp_path: Path) -> None:
    shot = Shot(
        id="S02-A",
        frames=(0, 10),
        source=Source(type="generate", backend="qwen-image-edit-2511", prompt="p"),
    )
    storyboard = _storyboard([Scene(id="SC1", shots=[shot])])

    html_out = build_sheet_html(storyboard, storyboard_dir=tmp_path)

    assert "not yet generated" in html_out
    assert "data:image/jpeg;base64" not in html_out


def test_shot_with_dangling_keyframe_reference_renders_placeholder_without_crashing(
    tmp_path: Path,
) -> None:
    shot = Shot(
        id="S03-A",
        frames=(0, 10),
        source=Source(
            type="generate", backend="qwen-image-edit-2511", prompt="p",
            keyframe="does/not/exist.png",
        ),
    )
    storyboard = _storyboard([Scene(id="SC1", shots=[shot])])

    # Must not raise despite the file not existing on disk.
    html_out = build_sheet_html(storyboard, storyboard_dir=tmp_path)

    assert "keyframe file not found" in html_out
    assert "data:image/jpeg;base64" not in html_out


def test_html_injection_shaped_text_is_escaped(tmp_path: Path) -> None:
    injected = "<script>alert(1)</script>"
    shot = Shot(
        id="S04-A",
        frames=(0, 10),
        idea=injected,
        action=injected,
        audioSync=injected,
        source=Source(type="generate", backend="qwen-image-edit-2511", prompt="p"),
    )
    scene = Scene(id="SC1", section=injected, shots=[shot])
    storyboard = _storyboard([scene], title=injected)

    html_out = build_sheet_html(storyboard, storyboard_dir=tmp_path)

    assert injected not in html_out
    assert html.escape(injected) in html_out


def test_summary_counts_are_correct_for_a_known_mix(tmp_path: Path) -> None:
    shots = [
        Shot(  # has keyframe, approved
            id="A1", frames=(0, 10),
            source=Source(
                type="generate", backend="b", prompt="p", keyframe="a.png", approved=True
            ),
        ),
        Shot(  # has keyframe, not approved
            id="A2", frames=(0, 10),
            source=Source(
                type="generate", backend="b", prompt="p", keyframe="b.png", approved=False
            ),
        ),
        Shot(  # source present, no keyframe yet, not approved
            id="A3", frames=(0, 10),
            source=Source(type="generate", backend="b", prompt="p", approved=False),
        ),
        Shot(  # has keyframe, approved
            id="A4", frames=(0, 10),
            source=Source(
                type="generate", backend="b", prompt="p", keyframe="d.png", approved=True
            ),
        ),
        Shot(id="A5", frames=(0, 10), source=None),  # no source at all
    ]
    storyboard = _storyboard([Scene(id="SC1", shots=shots)])

    total, with_keyframe, approved = summarize_storyboard(storyboard)
    assert (total, with_keyframe, approved) == (5, 3, 2)
    assert format_summary_line(total, with_keyframe, approved) == (
        "5 shots · 3 have a keyframe · 2 approved"
    )

    html_out = build_sheet_html(storyboard, storyboard_dir=tmp_path)
    assert "5 shots · 3 have a keyframe · 2 approved" in html_out


def test_output_is_well_formed_html(tiny_png: Path) -> None:
    storyboard_dir = tiny_png.parent
    shots = [
        Shot(
            id="S01",
            frames=(0, 10),
            idea="a && b < c",
            action="<b>bold</b>? no.",
            audioSync="cut on kick",
            camera=Camera(framing="CU"),
            source=Source(
                type="generate", backend="b", prompt="p",
                keyframe=tiny_png.name, approved=True,
            ),
        ),
        Shot(id="S02", frames=(10, 20), source=None),
        Shot(
            id="S03",
            frames=(20, 30),
            source=Source(
                type="generate", backend="b", prompt="p",
                keyframe="missing.png", material="standalone",
            ),
        ),
    ]
    scene = Scene(id="SC1", section="verse1", shots=shots)
    storyboard = _storyboard([scene])

    html_out = build_sheet_html(storyboard, storyboard_dir=storyboard_dir, thumb_width=150)

    _assert_balanced_html(html_out)
    # sanity: all three shots and the scene heading actually made it in
    assert "S01" in html_out and "S02" in html_out and "S03" in html_out
    assert "SC1" in html_out
