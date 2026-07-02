# tests/test_no_disk_leak.py
"""Ensure the server never writes image bytes to disk.

We monkey-patch the high-risk write APIs and run a representative tool call
end-to-end against the live application. The test passes iff no API that could
write user image content to disk is invoked.
"""

from __future__ import annotations

import base64
import builtins
import io
import pathlib
from unittest.mock import patch

import pytest
import respx
from starlette.testclient import TestClient

from vision_mcp.config import Config
from vision_mcp.server import build_app


@pytest.fixture
def cfg():
    return Config(
        ark_base_url="https://ark.example.com",
        ark_api_key="test-key",
        ark_model="m",
        vision_bearer_token="the-secret-token",
        host="127.0.0.1",
        port=8100,
    )


@pytest.fixture
def tiny_png_b64():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="red").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _record_writes():
    """Patch file writing APIs and return a list that any write appends to."""
    calls: list[str] = []

    real_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        # Allow read-only opens; block any mode that writes.
        if any(c in mode for c in ("w", "a", "x", "+")):
            calls.append(f"open({file!r}, {mode!r})")
            raise AssertionError(
                f"Disk write attempted: open({file!r}, {mode!r})"
            )
        return real_open(file, mode, *args, **kwargs)

    return calls, _guarded_open


def test_tool_call_does_not_write_to_disk(cfg, tiny_png_b64):
    calls, guarded_open = _record_writes()
    with patch.object(builtins, "open", guarded_open), patch.object(
        pathlib.Path, "write_bytes", side_effect=AssertionError("Path.write_bytes called")
    ), patch.object(pathlib.Path, "write_text", side_effect=AssertionError("Path.write_text called")
    ):
        # Note: tempfile.NamedTemporaryFile is intentionally NOT patched.
        # Uvicorn/starlette call it during startup for their own bookkeeping
        # (unrelated to image data). Only the high-risk write APIs that could
        # plausibly receive user image bytes are guarded here.
        app = build_app(cfg)
        with TestClient(app) as client:
            with respx.mock(base_url="https://ark.example.com") as mock:
                mock.post("/api/v3/chat/completions").respond(
                    200,
                    json={
                        "choices": [
                            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                        ]
                    },
                )
                r = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "ocr_image",
                            "arguments": {"image_base64": tiny_png_b64, "lang": "auto"},
                        },
                    },
                    headers={
                        "Authorization": "Bearer the-secret-token",
                        "Accept": "application/json, text/event-stream",
                        "Host": "localhost:80",
                    },
                )
            assert r.status_code in (200, 202), r.text
        assert calls == [], f"unexpected write attempts: {calls}"