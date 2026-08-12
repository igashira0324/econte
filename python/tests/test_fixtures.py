"""Golden fixture tests.

Loads every file in ``spec/fixtures/*.json`` (resolved relative to this
test file, so it works regardless of the current working directory) and
asserts the accept/reject verdict encoded in the filename:

- ``valid-*.json``   must validate successfully.
- ``invalid-*.json`` must fail validation.

This suite must not hand-pick a subset -- every fixture file is discovered
and parametrized over, so a new fixture added to ``spec/fixtures/`` is
automatically covered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from econte import validate_storyboard

FIXTURES_DIR = Path(__file__).parent.parent.parent / "spec" / "fixtures"

FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        result: dict[str, Any] = json.load(f)
        return result


@pytest.fixture(scope="session", autouse=True)
def _fixtures_dir_sanity_check() -> None:
    assert FIXTURES_DIR.is_dir(), f"fixtures directory not found: {FIXTURES_DIR}"
    assert FIXTURE_FILES, f"no fixture files discovered in {FIXTURES_DIR}"


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixture_verdict(fixture_path: Path) -> None:
    name = fixture_path.name
    data = _load(fixture_path)
    ok, errors = validate_storyboard(data)

    if name.startswith("valid-"):
        assert ok, f"{name}: expected VALID but validation failed with: {errors}"
    elif name.startswith("invalid-"):
        assert not ok, f"{name}: expected INVALID but validation succeeded"
    else:
        pytest.fail(
            f"{name}: fixture filename must start with 'valid-' or 'invalid-' "
            "so the expected verdict can be determined"
        )
