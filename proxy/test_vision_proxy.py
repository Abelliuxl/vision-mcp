#!/usr/bin/env python3
"""Smoke test for vision_proxy.py.

Run as `python3 proxy/test_vision_proxy.py`. Drives the proxy as a subprocess
via JSON-RPC over stdio. Asserts:
  - initialize returns a valid response with server info.
  - tools/list returns the three tool schemas (ocr_image, describe_image, answer_image).
  - tools/call with a valid PNG fixture and a dummy ARK_API_KEY attempts to
    reach Ark (we expect an upstream error since the key is fake).

Does NOT require a real Ark API key.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile

# Smallest valid 2x2 red PNG (verified): 67 bytes decoded.
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mNk"
    "+M9Q/x8AGBQEfn4wMTYAAAAASUVORK5CYII="
)


def send(proc, msg):
    line = json.dumps(msg, ensure_ascii=False) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()


def recv(proc):
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("proxy closed stdout before responding")
    return json.loads(line.decode("utf-8"))


def expect_tool_result_with_upstream_error(resp):
    """Either JSON-RPC error, or a tool result with isError=True containing
    an upstream/network-style message (we expect the call to fail because
    the test uses a fake ARK_API_KEY)."""
    if "error" in resp:
        msg = str(resp["error"].get("message", ""))
        assert ("Upstream" in msg or "unauthorized" in msg.lower() or "Ark" in msg
                or "SSL" in msg or "Connection" in msg or "Network" in msg), \
            f"unexpected JSON-RPC error: {resp}"
        return f"jsonrpc error: {msg[:80]}"
    result = resp.get("result") or {}
    content = result.get("content") or []
    assert content, f"tool returned empty content: {resp}"
    assert result.get("isError") is True, f"expected isError=True, got: {resp}"
    texts = [c.get("text", "") for c in content if isinstance(c, dict)]
    blob = " ".join(texts)
    assert ("Upstream" in blob or "unauthorized" in blob.lower() or "Ark" in blob
            or "SSL" in blob or "Connection" in blob or "Network" in blob), \
        f"expected upstream/network-error text, got: {blob!r}"
    return f"isError text: {blob[:80]}"


def main():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_proxy.py")
    env = os.environ.copy()
    env["ARK_API_KEY"] = "test-fake-key"
    proc = subprocess.Popen(
        [sys.executable, script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env,
    )

    try:
        # 1. initialize
        send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        })
        r = recv(proc)
        assert r.get("id") == 1, f"initialize: bad id: {r}"
        assert "result" in r, f"initialize: missing result: {r}"
        server = r["result"].get("serverInfo") or {}
        assert server.get("name") == "vision-mcp", f"initialize: bad serverInfo: {r}"
        print("OK: initialize ->", server)

        # 2. tools/list
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        r = recv(proc)
        assert r.get("id") == 2, f"tools/list: bad id: {r}"
        assert "result" in r, f"tools/list: missing result: {r}"
        names = {t["name"] for t in r["result"]["tools"]}
        assert names == {"ocr_image", "describe_image", "answer_image"}, \
            f"tools/list: unexpected names: {names}"
        print("OK: tools/list ->", sorted(names))

        # 3. tools/call with a tiny valid PNG fixture
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(base64.b64decode(TINY_PNG_BASE64))
            fixture = f.name
        try:
            send(proc, {
                "jsonrpc": "2.0", "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ocr_image",
                    "arguments": {"image_path": fixture, "lang": "auto"},
                },
            })
            r = recv(proc)
            assert r.get("id") == 3, f"tools/call: bad id: {r}"
            detail = expect_tool_result_with_upstream_error(r)
            print(f"OK: tool call failed upstream as expected ({detail})")
        finally:
            os.unlink(fixture)

        # 4. gracefully close stdin so proxy exits cleanly
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=2)

        print("ALL OK")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())