"""``econte sheet``: render a self-contained HTML approval sheet.

See ``docs/compile-spec.md`` at the repository root, section ``econte
sheet``, for the authoritative specification this module implements.

The output is a single HTML string with everything inlined (``<style>``,
base64-embedded JPEG thumbnails) so it opens directly in a browser with no
external requests, no build step, and no server -- it can be emailed or
shared as one file. It is read-only: nothing on the page writes back into
``storyboard.json``; a human (or a future tool) edits ``source.approved``
there directly.
"""

from __future__ import annotations

import base64
import html
import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..models import Scene, Shot, Storyboard

__all__ = [
    "build_sheet_html",
    "format_summary_line",
    "summarize_storyboard",
]

logger = logging.getLogger(__name__)

# JPEG quality for embedded thumbnails: high enough to judge composition/
# expression/framing for approval, low enough to keep a many-shot sheet a
# reasonable file size.
_THUMB_JPEG_QUALITY = 82

_CSS = """
:root {
  color-scheme: dark;
  --bg: #12141a;
  --bg-header: #171a22;
  --card-bg: #1b1e28;
  --card-border: #2a2e3b;
  --text: #e6e8ee;
  --text-muted: #9aa0b0;
  --text-faint: #6b7280;
  --accent: #8fb4ff;

  --chain-bg: #2c2454;
  --chain-fg: #c9baff;
  --standalone-bg: #10373a;
  --standalone-fg: #7fe3d8;
  --none-bg: #2a2d35;
  --none-fg: #9aa0b0;

  --approved-bg: #123321;
  --approved-fg: #7fe0a3;
  --approved-border: #2fbf6e;
  --review-bg: #3a1620;
  --review-fg: #ff9fae;
  --review-border: #e0435e;
  --nosource-border: #4a4e5c;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.4;
}

.page { max-width: 1400px; margin: 0 auto; padding: 24px 20px 64px; }

.page-header {
  background: var(--bg-header);
  border: 1px solid var(--card-border);
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 28px;
}

.page-header h1 { margin: 0 0 12px; font-size: 1.5rem; }

.readonly-note {
  margin: 0 0 14px;
  padding: 10px 14px;
  background: rgba(143, 180, 255, 0.08);
  border: 1px solid rgba(143, 180, 255, 0.25);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 0.88rem;
}

.readonly-note code {
  background: rgba(255, 255, 255, 0.08);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.85em;
}

.summary { margin: 0; font-size: 1.05rem; font-weight: 600; color: var(--accent); }

h2.scene-heading {
  font-size: 1.15rem;
  color: var(--text);
  border-bottom: 1px solid var(--card-border);
  padding-bottom: 8px;
  margin: 32px 0 16px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(max(220px, var(--thumb-width, 420px)), 1fr));
  gap: 18px;
}

.card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-left-width: 5px;
  border-left-style: solid;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.card.card-approved { border-left-color: var(--approved-border); }
.card.card-needs-review { border-left-color: var(--review-border); }
.card.card-no-source { border-left-color: var(--nosource-border); }

.thumb-wrap {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #05060a;
  display: block;
}

.thumb {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 12px;
  color: var(--text-faint);
  font-size: 0.82rem;
  font-style: italic;
}

.card-body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 8px; }

.card-title-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.shot-id { font-weight: 700; font-size: 1.02rem; }
.framing {
  font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
  font-size: 0.8rem;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
}

.badge-row { display: flex; gap: 6px; flex-wrap: wrap; }

.badge {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 999px;
}

.badge-chain { background: var(--chain-bg); color: var(--chain-fg); }
.badge-standalone { background: var(--standalone-bg); color: var(--standalone-fg); }
.badge-none { background: var(--none-bg); color: var(--none-fg); }
.badge-approved { background: var(--approved-bg); color: var(--approved-fg); }
.badge-needs-review { background: var(--review-bg); color: var(--review-fg); }

.card-body p { margin: 0; font-size: 0.88rem; color: var(--text); }
.card-body p strong { color: var(--text-muted); font-weight: 600; }
"""


def summarize_storyboard(storyboard: Storyboard) -> tuple[int, int, int]:
    """Return ``(total_shots, shots_with_keyframe, shots_approved)``.

    A shot counts as "has a keyframe" if ``shot.source.keyframe`` is set to
    a non-empty value (regardless of whether that file actually resolves on
    disk -- that's a rendering-time concern, not a counting one). A shot
    counts as "approved" if ``shot.source.approved`` is ``True``. A shot
    with no ``source`` at all (no generation plan yet) counts toward
    neither.
    """
    total = 0
    with_keyframe = 0
    approved = 0
    for scene in storyboard.scenes:
        for shot in scene.shots:
            total += 1
            if shot.source is not None:
                if shot.source.keyframe:
                    with_keyframe += 1
                if shot.source.approved:
                    approved += 1
    return total, with_keyframe, approved


def format_summary_line(total: int, with_keyframe: int, approved: int) -> str:
    """Format the top-of-sheet summary line, e.g.
    ``"24 shots · 18 have a keyframe · 11 approved"``."""
    return f"{total} shots · {with_keyframe} have a keyframe · {approved} approved"


def _placeholder_html(message: str) -> str:
    return f'<div class="thumb-placeholder">{html.escape(message)}</div>'


def _encode_thumbnail(image_path: Path, thumb_width: int) -> str | None:
    """Return a ``data:image/jpeg;base64,...`` URI for a thumbnail of
    ``image_path`` resized to ``thumb_width`` (preserving aspect ratio), or
    ``None`` if the file exists but could not be read/decoded as an image.

    Never raises: any I/O or decode failure is logged and treated as "no
    thumbnail available", matching the missing-file case handled by the
    caller.
    """
    try:
        with Image.open(image_path) as source_image:
            source_image.load()

            if source_image.mode in ("RGBA", "LA", "P"):
                rgba = source_image.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, (255, 255, 255))
                flattened.paste(rgba, mask=rgba.split()[-1])
                rgb_image = flattened
            else:
                rgb_image = source_image.convert("RGB")

            orig_width, orig_height = rgb_image.size
            if orig_width <= 0 or orig_height <= 0:
                return None

            new_width = max(1, thumb_width)
            new_height = max(1, round(orig_height * (new_width / orig_width)))
            resized = rgb_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=_THUMB_JPEG_QUALITY)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.warning("sheet: could not read keyframe image %s: %s", image_path, exc)
        return None


def _render_keyframe_cell(shot: Shot, storyboard_dir: Path, thumb_width: int) -> str:
    keyframe = shot.source.keyframe if shot.source is not None else None
    if not keyframe:
        return _placeholder_html("not yet generated")

    # All storyboard paths are forward-slash and relative to the
    # storyboard.json's own directory (docs/schema-spec.md); pathlib
    # resolves "/"-separated relative paths correctly on Windows too, so no
    # separator translation is needed.
    image_path = storyboard_dir / keyframe
    if not image_path.is_file():
        return _placeholder_html(f"keyframe file not found: {keyframe}")

    data_uri = _encode_thumbnail(image_path, thumb_width)
    if data_uri is None:
        return _placeholder_html(f"keyframe file could not be read as an image: {keyframe}")

    alt = html.escape(f"keyframe thumbnail for shot {shot.id}")
    return f'<img class="thumb" src="{data_uri}" alt="{alt}" loading="lazy">'


def _material_badge(shot: Shot) -> str:
    if shot.source is None:
        return '<span class="badge badge-none">no source</span>'

    material = shot.source.material
    if material is None:
        # docs/compile-spec.md's field-mapping table treats an absent
        # `material` as `chain_start` by convention when compiling; the
        # sheet mirrors that default for display (marked "(default)" since
        # it was not explicitly set in storyboard.json) so a shot's
        # effective material is visible at a glance either way.
        label = "chain_start (default)"
        css_class = "badge-chain"
    elif material == "standalone":
        label = "standalone"
        css_class = "badge-standalone"
    else:  # "chain" or "chain_start", explicitly set
        label = material
        css_class = "badge-chain"

    return f'<span class="badge {css_class}">{html.escape(label)}</span>'


def _approval_badge_and_card_class(shot: Shot) -> tuple[str, str]:
    """Return ``(card_css_class, approval_badge_html)``."""
    if shot.source is None:
        return "card-no-source", '<span class="badge badge-none">no source</span>'
    if shot.source.approved:
        return "card-approved", '<span class="badge badge-approved">approved</span>'
    return "card-needs-review", '<span class="badge badge-needs-review">needs review</span>'


def _render_shot_card(shot: Shot, storyboard_dir: Path, thumb_width: int) -> str:
    card_css_class, approval_badge = _approval_badge_and_card_class(shot)

    parts: list[str] = [f'<article class="card {card_css_class}">']
    parts.append('<div class="thumb-wrap">')
    parts.append(_render_keyframe_cell(shot, storyboard_dir, thumb_width))
    parts.append("</div>")

    parts.append('<div class="card-body">')
    parts.append('<div class="card-title-row">')
    parts.append(f'<span class="shot-id">{html.escape(shot.id)}</span>')
    if shot.camera is not None and shot.camera.framing is not None:
        parts.append(f'<span class="framing">{html.escape(shot.camera.framing)}</span>')
    parts.append("</div>")

    parts.append('<div class="badge-row">')
    parts.append(_material_badge(shot))
    parts.append(approval_badge)
    parts.append("</div>")

    if shot.idea:
        parts.append(f'<p class="idea"><strong>Idea:</strong> {html.escape(shot.idea)}</p>')
    if shot.action:
        parts.append(f'<p class="action"><strong>Action:</strong> {html.escape(shot.action)}</p>')
    if shot.audioSync:
        parts.append(
            f'<p class="audio-sync"><strong>Audio sync:</strong> {html.escape(shot.audioSync)}</p>'
        )

    parts.append("</div>")  # .card-body
    parts.append("</article>")
    return "".join(parts)


def _render_scene_section(scene: Scene, storyboard_dir: Path, thumb_width: int) -> str:
    heading = scene.id if not scene.section else f"{scene.id} — {scene.section}"
    cards = "".join(_render_shot_card(shot, storyboard_dir, thumb_width) for shot in scene.shots)
    return (
        '<section class="scene">'
        f'<h2 class="scene-heading">{html.escape(heading)}</h2>'
        f'<div class="cards">{cards}</div>'
        "</section>"
    )


def build_sheet_html(
    storyboard: Storyboard, *, storyboard_dir: Path, thumb_width: int = 420
) -> str:
    """Render ``storyboard`` as a single self-contained HTML approval sheet.

    ``storyboard_dir`` is the directory the storyboard's own JSON file lives
    in -- ``Shot.source.keyframe`` paths (and every other path in the
    schema) are relative to it, per ``docs/schema-spec.md``. Thumbnails are
    resized to ``thumb_width`` pixels wide, preserving aspect ratio, and
    embedded as base64 JPEGs so the returned HTML needs no external
    requests to render. A shot with no keyframe (unset, or pointing at a
    file that doesn't exist or can't be decoded) renders a placeholder box
    instead of a broken image -- this never raises.

    See ``docs/compile-spec.md``'s "econte sheet" section for the full
    specification.
    """
    total, with_keyframe, approved = summarize_storyboard(storyboard)
    summary_line = format_summary_line(total, with_keyframe, approved)

    scene_sections = "".join(
        _render_scene_section(scene, storyboard_dir, thumb_width) for scene in storyboard.scenes
    )

    title = html.escape(storyboard.metadata.title)
    style = f":root {{ --thumb-width: {int(thumb_width)}px; }}\n{_CSS}"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — econte approval sheet</title>
<style>{style}</style>
</head>
<body>
<div class="page">
<header class="page-header">
<h1>{title} — Approval Sheet</h1>
<p class="readonly-note">
This page is <strong>read-only</strong>, generated by <code>econte sheet</code> from
<code>storyboard.json</code>. Clicking anything here does not change
<code>source.approved</code> or any other field in the storyboard &mdash; a human edits
<code>storyboard.json</code> directly (or a future tool does), then re-runs
<code>econte sheet</code> to refresh this page.
</p>
<p class="summary">{html.escape(summary_line)}</p>
</header>
<main>
{scene_sections}
</main>
</div>
</body>
</html>
"""
