"""A record/replay ComfyUIClientLike test double driven by
``tests/fixtures/comfyui-replay/``.

Per ``docs/profile-spec.md``'s "Testing: record/replay" section, this is
keyed by which job/variant the *test* expects to be submitted, not by
pattern-matching the built graph JSON byte-for-byte -- the test wires up
one fixture case name per job id ahead of time, and this double simply
serves that job's canned ``prompt_response``/``history_response`` (or
raises like a real HTTP 400 for a validation-failure case) the next time
``post_json("/prompt", ...)`` is called, in job order.

Only implements ``post_json``/``get_json`` -- see
``econte.runners.client.ComfyUIClientLike`` for why that's the entire
surface :func:`econte.runners.runner.run` needs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from econte.runners import ComfyUIError

REPLAY_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "comfyui-replay"


def load_case(name: str) -> dict[str, Any]:
    case_dir = REPLAY_DIR / name
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    case: dict[str, Any] = {"meta": meta}

    prompt_response_path = case_dir / "prompt_response.json"
    if prompt_response_path.is_file():
        case["prompt_response"] = json.loads(prompt_response_path.read_text(encoding="utf-8"))

    history_response_path = case_dir / "history_response.json"
    if history_response_path.is_file():
        case["history_response"] = json.loads(history_response_path.read_text(encoding="utf-8"))

    prompt_error_path = case_dir / "prompt_error_response.json"
    if prompt_error_path.is_file():
        case["prompt_error_response"] = json.loads(prompt_error_path.read_text(encoding="utf-8"))

    return case


class ReplayClient:
    """Serves one recorded case per successive ``POST /prompt`` call, in
    the order given to the constructor -- the runner submits jobs in
    manifest order, so ``case_names[i]`` corresponds to the ``i``-th job
    actually submitted this run (jobs skipped via ``only``/chain-abort
    never call ``post_json`` at all, so they don't consume an entry)."""

    def __init__(self, case_names: list[str]) -> None:
        self._cases = [load_case(name) for name in case_names]
        self._next_index = 0
        self._history_by_prompt_id: dict[str, dict[str, Any]] = {}

    @property
    def submitted_count(self) -> int:
        """How many ``POST /prompt`` calls have actually been served so
        far -- tests use this to catch a job that was silently never
        submitted (e.g. a graph-build failure) even when the final report
        happens to look right for an unrelated reason (a stale file
        already on disk)."""
        return self._next_index

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert path == "/prompt", path
        if self._next_index >= len(self._cases):
            raise AssertionError(
                f"ReplayClient: more POST /prompt calls than configured cases "
                f"({len(self._cases)}); body={body!r}"
            )
        case = self._cases[self._next_index]
        self._next_index += 1

        if "prompt_error_response" in case:
            error_body = case["prompt_error_response"]
            raise ComfyUIError(
                f"POST /prompt failed: HTTP 400: {json.dumps(error_body)}",
                status=400,
                body=json.dumps(error_body),
            )

        response: dict[str, Any] = case["prompt_response"]
        self._history_by_prompt_id[response["prompt_id"]] = case["history_response"]
        return response

    def get_json(self, path: str) -> dict[str, Any]:
        assert path.startswith("/history/") or path == "/system_stats", path
        if path == "/system_stats":
            return {"system": {"comfyui_version": "replay"}}
        prompt_id = path.rsplit("/", 1)[-1]
        return self._history_by_prompt_id[prompt_id]
