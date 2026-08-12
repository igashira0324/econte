"""A minimal HTTP client for a ComfyUI server, using only the standard
library (matching the style of the predecessor harness scripts this
project grew out of -- no ``requests`` dependency).

``ComfyUIClient.post_json``/``get_json`` are the only seam
``econte.runners.runner`` needs, by design: a test can substitute a small
double exposing just those two methods (see
``tests/test_runners/test_runner.py``'s record/replay double) to exercise
the full runner control flow without a real socket or a GPU.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

__all__ = ["ComfyUIClient", "ComfyUIClientLike", "ComfyUIError", "ServerNotReadyError"]


class ComfyUIClientLike(Protocol):
    """The structural interface ``econte.runners.runner.run`` actually
    calls: just ``post_json``/``get_json``. :class:`ComfyUIClient` satisfies
    this automatically (Python ``Protocol``s are structural), and so does
    any minimal test double that implements only these two methods -- see
    the module docstring and ``docs/profile-spec.md``'s "Testing:
    record/replay" section."""

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...

    def get_json(self, path: str) -> dict[str, Any]: ...


class ComfyUIError(Exception):
    """Raised when a ComfyUI HTTP call fails, either at the transport level
    or with a non-2xx response. On an HTTPError the response body is read
    and included in the message -- a ``POST /prompt`` validation failure
    (HTTP 400) carries a JSON body worth surfacing (``node_errors``, the
    exact ``value_not_in_list`` detail, ...), not just a status code."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ServerNotReadyError(Exception):
    """Raised by :meth:`ComfyUIClient.wait_for_server` if the server never
    answers ``/system_stats`` within the timeout."""


class ComfyUIClient:
    """Thin wrapper around ``urllib.request`` for talking to one ComfyUI
    server instance at ``base_url`` (e.g. ``"http://127.0.0.1:8188"``)."""

    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """``POST`` a JSON body to ``self.base_url + path`` and return the
        parsed JSON response."""
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._do_request(request)

    def get_json(self, path: str) -> dict[str, Any]:
        """``GET`` ``self.base_url + path`` and return the parsed JSON
        response."""
        request = urllib.request.Request(self.base_url + path, method="GET")
        return self._do_request(request)

    def _do_request(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(
                f"{request.get_method()} {request.full_url} failed: HTTP {exc.code}: {body}",
                status=exc.code,
                body=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise ComfyUIError(
                f"{request.get_method()} {request.full_url} failed: {exc.reason}"
            ) from exc

        if not raw:
            return {}
        result: dict[str, Any] = json.loads(raw)
        return result

    def wait_for_server(self, timeout_s: int = 600) -> None:
        """Poll ``/system_stats`` until it responds, or raise
        :class:`ServerNotReadyError` after ``timeout_s`` seconds."""
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.get_json("/system_stats")
                return
            except ComfyUIError as exc:
                last_error = exc
            time.sleep(2.0)

        raise ServerNotReadyError(
            f"ComfyUI server at {self.base_url} did not become ready within {timeout_s}s "
            f"(last error: {last_error})"
        )
