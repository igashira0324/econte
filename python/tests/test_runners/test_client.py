"""Tests for econte.runners.client: ComfyUIClient against a real (local)
HTTP server -- exercises actual socket I/O via urllib, not a mock."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from econte.runners import ComfyUIClient, ComfyUIError, ServerNotReadyError


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        pass  # silence test server logging

    def _write_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        if self.path == "/system_stats":
            self._write_json(200, {"system": {"comfyui_version": "test"}})
        elif self.path == "/history/success-id":
            self._write_json(200, {"success-id": {"status": {"status_str": "success"}}})
        elif self.path == "/never-ready":
            self._write_json(500, {"error": "not ready"})
        else:
            self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib method name
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        body = json.loads(raw) if raw else {}
        if self.path == "/prompt":
            if body.get("prompt") == {"bad": "graph"}:
                self._write_json(
                    400,
                    {
                        "error": {"type": "prompt_outputs_failed_validation", "message": "bad"},
                        "node_errors": {"1": {"errors": [{"type": "value_not_in_list"}]}},
                    },
                )
            else:
                self._write_json(200, {"prompt_id": "success-id", "number": 1, "node_errors": {}})
        else:
            self._write_json(404, {"error": "not found"})


@pytest.fixture
def server() -> Iterator[HTTPServer]:
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def client(server: HTTPServer) -> ComfyUIClient:
    port = server.server_address[1]
    return ComfyUIClient(f"http://127.0.0.1:{port}")


def test_get_json_success(client: ComfyUIClient) -> None:
    result = client.get_json("/system_stats")
    assert result["system"]["comfyui_version"] == "test"


def test_post_json_success(client: ComfyUIClient) -> None:
    result = client.post_json("/prompt", {"prompt": {"1": {}}, "client_id": "abc"})
    assert result["prompt_id"] == "success-id"
    assert result["node_errors"] == {}


def test_post_json_http_error_includes_body(client: ComfyUIClient) -> None:
    with pytest.raises(ComfyUIError) as excinfo:
        client.post_json("/prompt", {"prompt": {"bad": "graph"}})
    exc = excinfo.value
    assert exc.status == 400
    assert exc.body is not None
    assert "prompt_outputs_failed_validation" in exc.body
    assert "value_not_in_list" in str(exc)


def test_get_json_404_raises_comfyui_error(client: ComfyUIClient) -> None:
    with pytest.raises(ComfyUIError) as excinfo:
        client.get_json("/nonexistent")
    assert excinfo.value.status == 404


def test_wait_for_server_succeeds_when_ready(client: ComfyUIClient) -> None:
    client.wait_for_server(timeout_s=5)  # /system_stats answers immediately -> must not raise


def test_wait_for_server_raises_when_never_ready() -> None:
    # No server bound at all -- connection refused every time.
    unreachable = ComfyUIClient("http://127.0.0.1:1")
    with pytest.raises(ServerNotReadyError):
        unreachable.wait_for_server(timeout_s=0)


def test_base_url_trailing_slash_is_stripped() -> None:
    client_with_slash = ComfyUIClient("http://127.0.0.1:8188/")
    assert client_with_slash.base_url == "http://127.0.0.1:8188"
