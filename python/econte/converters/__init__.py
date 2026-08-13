"""Storyboard <-> manifest/report converters: ``econte compile`` and
``econte ingest``.

See ``docs/compile-spec.md`` at the repository root for the specification
this package implements: :mod:`.compile` (storyboard -> per-backend
manifest files, grouped and field-mapped per the "Eligibility filter" and
"Field mapping" sections) and :mod:`.ingest` (a delivery report's results
written back into a storyboard, by shot id, per the ``econte ingest``
section).
"""

from __future__ import annotations

from .compile import (
    CompileError,
    CompileGroup,
    CompileResult,
    compile_storyboard,
    slugify,
)
from .ingest import IngestResult, SkippedJob, ingest_report

__all__ = [
    "CompileError",
    "CompileGroup",
    "CompileResult",
    "IngestResult",
    "SkippedJob",
    "compile_storyboard",
    "ingest_report",
    "slugify",
]
