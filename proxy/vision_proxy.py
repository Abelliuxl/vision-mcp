#!/usr/bin/env python3
"""vision-mcp local MCP proxy.

Exposes three vision tools (ocr_image, describe_image, answer_image) backed
by Doubao Seed 2.0 Mini on Volcano Ark. Reads local image files, base64-encodes
them, forwards to Ark — no remote server required.

Recommended launch: use `uv run python proxy/vision_proxy.py` from the project
root, which uses the project's `.venv` (Python and CA certificates managed by
uv, sidestepping macOS system-Python SSL issues).

Default transport is stdio for compatibility. Use `--transport http` to run a
single long-lived streamable-http-compatible endpoint instead of letting each
MCP client session spawn another stdio process.

Config: `.env` in the project root (ARK_API_KEY required).
Stdio stdout: line-delimited JSON-RPC 2.0. Stderr: human-readable logs.
"""

from __future__ import annotations

import base64
import argparse
import http.client
import json
import logging
import os
import ssl
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

# --- logging: stderr only ---
logging.basicConfig(
    level=os.environ.get("VISION_PROXY_LOG", "INFO"),
    format="%(asctime)s %(levelname)s vision_proxy: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("vision_proxy")

# --- constants ---
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com"
DEFAULT_MODEL = "doubao-seed-2-0-mini-260215"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # applied before base64
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF89a", "image/gif"),
    (b"GIF87a", "image/gif"),
)
_WEBP_RIFF, _WEBP_TAG = b"RIFF", b"WEBP"
ARK_PATH = "/api/v3/chat/completions"
ARK_TIMEOUT = 60.0  # seconds
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
DEFAULT_HTTP_PATH = "/mcp"
DEFAULT_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = {
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
    "2024-10-07",
}

# --- tool schemas ---
TOOLS: List[Dict[str, Any]] = [
    {"name": "ocr_image",
     "description": "Extract text from an image verbatim. Pass an image_path (local file path).",
     "inputSchema": {"type": "object", "properties": {
         "image_path": {"type": "string",
                        "description": "Absolute or relative path to a local image file."},
         "lang": {"type": "string", "enum": ["zh", "en", "auto"], "default": "auto"}},
         "required": ["image_path"]}},
    {"name": "describe_image",
     "description": "Describe an image objectively. Pass an image_path (local file path).",
     "inputSchema": {"type": "object", "properties": {
         "image_path": {"type": "string"},
         "detail": {"type": "string", "enum": ["short", "medium", "long"], "default": "medium"}},
         "required": ["image_path"]}},
    {"name": "answer_image",
     "description": "Answer a question grounded in the image. Pass an image_path (local file path).",
     "inputSchema": {"type": "object", "properties": {
         "image_path": {"type": "string"},
         "question": {"type": "string"},
         "context": {"type": "string"}},
         "required": ["image_path", "question"]}},
]

# --- system prompts ---
SYSTEM_OCR = "Your only task is to extract every character of text in the image, verbatim. Output the extracted text only, in reading order. Do not translate, summarize, or comment. Preserve line breaks."
SYSTEM_DESCRIBE = "Describe the image objectively. Begin directly with the subject, in present tense, third person. Do not infer intent. Length limits: short <= 60 CJK or <= 120 Latin; medium <= 180 CJK or <= 360 Latin; long <= 600 CJK or <= 1200 Latin. Respect the requested detail level."
SYSTEM_ANSWER = "You are a visual QA assistant. Answer based solely on what is in the image. If the image does not contain enough information, respond with 'The image does not provide enough information.' Do not guess."

def _load_env() -> Dict[str, str]:
    """Parse `<project-root>/.env` as KEY=value lines (optional # comments)."""
    if not os.path.isfile(ENV_FILE):
        return {}
    out: Dict[str, str] = {}
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip()
    except OSError as exc:
        log.warning("could not read %s: %s", ENV_FILE, exc)
    return out

def _config() -> Tuple[str, str, str]:
    """Return (api_key, base_url, model). Env vars override .env file."""
    file_cfg = _load_env()
    api_key = os.environ.get("ARK_API_KEY") or file_cfg.get("ARK_API_KEY", "")
    base_url = (os.environ.get("ARK_BASE_URL") or file_cfg.get("ARK_BASE_URL")
                or DEFAULT_BASE_URL)
    model = os.environ.get("ARK_MODEL") or file_cfg.get("ARK_MODEL") or DEFAULT_MODEL
    return api_key, base_url, model

def _detect_mime(data: bytes) -> Optional[str]:
    """Return image MIME by magic bytes; WebP needs the secondary tag check."""
    if data.startswith(_WEBP_RIFF) and len(data) >= 12 and data[8:12] == _WEBP_TAG:
        return "image/webp"
    for prefix, mime in _MAGIC:
        if data.startswith(prefix):
            return mime
    return None

def _read_image(path: str) -> Tuple[bytes, str]:
    """Read a local image file, validate, cap at MAX_IMAGE_BYTES."""
    if not path:
        raise ValueError("image_path is empty")
    if not os.path.isfile(path):
        raise ValueError(f"image_path not found: {path}")
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError(f"cannot stat image_path: {exc}") from exc
    if size > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit")
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit")
    mime = _detect_mime(data)
    if mime is None:
        raise ValueError("Unrecognized image format (magic-byte check failed). Supported: PNG, JPEG, GIF, WebP.")
    return data, mime

def _parse_host_port(base_url: str) -> Tuple[str, int]:
    """Return (host, port) for an https:// base URL."""
    url = base_url.strip()
    if url.startswith("https://"):
        url = url[len("https://"):]
    elif url.startswith("http://"):
        raise ValueError("ARK_BASE_URL must use https://")
    else:
        raise ValueError("ARK_BASE_URL must start with https://")
    if "/" in url:
        url = url.split("/", 1)[0]
    if ":" in url:
        host, _, port_s = url.partition(":")
        return host, int(port_s)
    return url, 443

def _ark_chat(system: str, user_text: str, image_b64: str,
              mime: str, max_tokens: int) -> str:
    """POST a chat-completion request to Ark. Returns the assistant text."""
    api_key, base_url, model = _config()
    if not api_key:
        raise ValueError(
            "ARK_API_KEY is not set. "
            f"Edit {ENV_FILE} or set the ARK_API_KEY environment variable."
        )
    host, port = _parse_host_port(base_url)
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": user_text},
            ]},
        ],
        "max_tokens": max_tokens,
    }, ensure_ascii=False).encode("utf-8")
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(host, port, timeout=ARK_TIMEOUT, context=ctx)
    try:
        conn.request("POST", ARK_PATH, body=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()
    if resp.status >= 400:
        snippet = raw[:400].decode("utf-8", errors="replace")
        raise RuntimeError(f"Upstream Ark HTTP {resp.status}: {snippet}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Upstream Ark returned invalid JSON: {exc}") from exc
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Upstream Ark response missing choices[0].message.content: {exc}"
        ) from exc

def _tool_error(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}

def _tool_text(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}

def _handle_ocr(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("image_path", "")
    lang = args.get("lang", "auto")
    data, mime = _read_image(path)
    img_b64 = base64.b64encode(data).decode("ascii")
    user_text = f"Extract all text from the image. Language hint: {lang}."
    text = _ark_chat(SYSTEM_OCR, user_text, img_b64, mime, max_tokens=2048)
    return _tool_text(text)

def _handle_describe(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("image_path", "")
    detail = args.get("detail", "medium")
    if detail not in ("short", "medium", "long"):
        return _tool_error(f"detail must be one of short|medium|long (got {detail!r})")
    data, mime = _read_image(path)
    img_b64 = base64.b64encode(data).decode("ascii")
    user_text = f"Describe the image at detail level: {detail}."
    max_tokens = {"short": 256, "medium": 768, "long": 2048}[detail]
    text = _ark_chat(SYSTEM_DESCRIBE, user_text, img_b64, mime, max_tokens)
    return _tool_text(text)

def _handle_answer(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("image_path", "")
    question = (args.get("question") or "").strip()
    context = (args.get("context") or "").strip()
    if not question:
        return _tool_error("question is required for answer_image")
    data, mime = _read_image(path)
    img_b64 = base64.b64encode(data).decode("ascii")
    user_text = f"Question: {question}"
    if context:
        user_text += f"\nAdditional context: {context}"
    text = _ark_chat(SYSTEM_ANSWER, user_text, img_b64, mime, max_tokens=1024)
    return _tool_text(text)

def _route_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "ocr_image":
            return _handle_ocr(args)
        if name == "describe_image":
            return _handle_describe(args)
        if name == "answer_image":
            return _handle_answer(args)
        return _tool_error(f"Unknown tool: {name}")
    except ValueError as exc:
        log.warning("tool %s validation error: %s", name, exc)
        return _tool_error(str(exc))
    except RuntimeError as exc:
        log.warning("tool %s upstream error: %s", name, exc)
        return _tool_error(str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        log.error("tool %s unexpected error: %s", name, exc)
        return _tool_error(f"Unexpected error: {exc}")

def _make_response(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}

def _make_error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}

def _handle_initialize(req: Dict[str, Any]) -> Dict[str, Any]:
    requested = ((req.get("params") or {}).get("protocolVersion")
                 if isinstance(req.get("params"), dict) else None)
    protocol = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": protocol,
        "serverInfo": {"name": "vision-mcp", "version": "0.3.0"},
        "capabilities": {"tools": {}},
    }

def _handle_tools_list(_req: Dict[str, Any]) -> Dict[str, Any]:
    return {"tools": TOOLS}

def _handle_ping(_req: Dict[str, Any]) -> Dict[str, Any]:
    return {}

def _handle_tools_call(req: Dict[str, Any]) -> Dict[str, Any]:
    params = req.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if not isinstance(name, str):
        return _make_error(req.get("id"), -32602, "params.name must be a string")
    if not isinstance(args, dict):
        return _make_error(req.get("id"), -32602, "params.arguments must be an object")
    return _route_tool(name, args)

def _dispatch(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a response for `req`, or None for a notification."""
    req_id = req.get("id")
    method = req.get("method")
    if not isinstance(method, str):
        return (_make_error(req_id, -32600, "method must be a string")
                if req_id is not None else None)
    is_notification = req_id is None
    handler = {
        "initialize": _handle_initialize,
        "ping": _handle_ping,
        "tools/list": _handle_tools_list,
        "tools/call": _handle_tools_call,
    }.get(method)
    if handler is None:
        if is_notification:
            log.info("unknown notification: %s", method)
            return None
        return _make_error(req_id, -32601, f"Method not found: {method}")
    try:
        result = handler(req)
    except Exception as exc:  # pragma: no cover — defensive
        log.error("handler %s crashed: %s", method, exc)
        return (None if is_notification
                else _make_error(req_id, -32603, f"Internal error: {exc}"))
    return None if is_notification else _make_response(req_id, result)

def _read_one_message() -> Optional[str]:
    """Read one JSON-RPC message body. Returns None on EOF.

    Supports LSP-style Content-Length framing AND line-delimited JSON.
    """
    line = sys.stdin.readline()
    if not line:
        return None
    stripped = line.strip()
    if stripped.lower().startswith("content-length"):
        content_length: Optional[int] = None
        while True:
            head = stripped
            if head == "":
                break
            if ":" in head:
                key, _, value = head.partition(":")
                if key.strip().lower() == "content-length":
                    try:
                        content_length = int(value.strip())
                    except ValueError:
                        content_length = None
            nxt = sys.stdin.readline()
            if not nxt:
                return None
            stripped = nxt.strip()
        if content_length is None or content_length < 0:
            return None
        return _read_exact(content_length)
    return stripped

def _read_exact(n: int) -> Optional[str]:
    """Read exactly n bytes from stdin. Returns None on EOF."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sys.stdin.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return "".join(chunks)

def _write_response(msg: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()

def _parse_http_token() -> str:
    file_cfg = _load_env()
    return os.environ.get("VISION_MCP_TOKEN") or file_cfg.get("VISION_MCP_TOKEN", "")

def _check_http_auth(header: str, token: str) -> bool:
    if not token:
        return True
    prefix = "Bearer "
    return header.startswith(prefix) and header[len(prefix):] == token

def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

class _VisionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: Tuple[str, int], handler_cls: Any,
                 path: str, token: str):
        super().__init__(server_address, handler_cls)
        self.mcp_path = path
        self.auth_token = token
        self.sessions: set[str] = set()

class _VisionHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "vision-mcp/0.3"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("http %s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes = b"",
              content_type: str = "application/json",
              session_id: Optional[str] = None) -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.send_header(
            "Access-Control-Allow-Headers",
            "content-type, authorization, mcp-session-id, mcp-protocol-version",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        if body:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        else:
            self.send_header("Content-Length", "0")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
        self._send(204)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path.rstrip("/") in ("/health", self.server.mcp_path.rstrip("/") + "/health"):
            self._send(200, _json_bytes({"ok": True, "name": "vision-mcp"}))
            return
        if self.path.rstrip("/") == self.server.mcp_path.rstrip("/"):
            auth = self.headers.get("Authorization", "")
            if not _check_http_auth(auth, self.server.auth_token):
                self._send(401, _json_bytes({"error": "unauthorized"}))
                return
            session_id = self.headers.get("Mcp-Session-Id", "")
            if session_id and session_id not in self.server.sessions:
                self._send(404, _json_bytes({"error": "session not found"}))
                return
            self._serve_sse()
            return
        self._send(404, _json_bytes({"error": "not found"}))

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.send_header(
            "Access-Control-Allow-Headers",
            "content-type, authorization, mcp-session-id, mcp-protocol-version",
        )
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(15)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            log.info("http %s - SSE client disconnected", self.address_string())

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path.rstrip("/") != self.server.mcp_path.rstrip("/"):
            self._send(404, _json_bytes({"error": "not found"}))
            return
        auth = self.headers.get("Authorization", "")
        if not _check_http_auth(auth, self.server.auth_token):
            self._send(401, _json_bytes({"error": "unauthorized"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(411, _json_bytes({"error": "invalid content-length"}))
            return
        if length <= 0:
            self._send(400, _json_bytes({"error": "empty request body"}))
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(400, _json_bytes(_make_error(None, -32700, f"Parse error: {exc}")))
            return

        requests = payload if isinstance(payload, list) else [payload]
        has_initialize = any(
            isinstance(req, dict) and req.get("method") == "initialize"
            for req in requests
        )
        session_id = self.headers.get("Mcp-Session-Id", "")
        if not has_initialize and self.server.sessions and session_id not in self.server.sessions:
            self._send(400, _json_bytes({"error": "missing or invalid mcp-session-id"}))
            return
        responses: List[Dict[str, Any]] = []
        for req in requests:
            if not isinstance(req, dict):
                responses.append(_make_error(None, -32600, "request must be an object"))
                continue
            resp = _dispatch(req)
            if resp is not None:
                responses.append(resp)

        if not responses:
            self._send(202)
            return
        body = _json_bytes(responses if isinstance(payload, list) else responses[0])
        response_session_id = None
        if has_initialize:
            response_session_id = session_id if session_id in self.server.sessions else str(uuid.uuid4())
            self.server.sessions.add(response_session_id)
        self._send(200, body, session_id=response_session_id)

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path.rstrip("/") != self.server.mcp_path.rstrip("/"):
            self._send(404, _json_bytes({"error": "not found"}))
            return
        auth = self.headers.get("Authorization", "")
        if not _check_http_auth(auth, self.server.auth_token):
            self._send(401, _json_bytes({"error": "unauthorized"}))
            return
        session_id = self.headers.get("Mcp-Session-Id", "")
        if session_id:
            self.server.sessions.discard(session_id)
        self._send(200, _json_bytes({"ok": True}))

def run_stdio() -> int:
    log.info(
        "starting vision-mcp local stdio proxy (python %s)",
        "%d.%d.%d" % sys.version_info[:3],
    )
    api_key, _, _ = _config()
    if not api_key:
        log.warning(
            "ARK_API_KEY is not set — tool calls will fail until it is. "
            "Edit %s", ENV_FILE,
        )
    while True:
        try:
            raw = _read_one_message()
        except Exception as exc:
            log.error("stdin read error: %s", exc)
            break
        if raw is None:
            log.info("stdin closed; exiting")
            break
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except ValueError as exc:
            log.warning("json parse error: %s", exc)
            _write_response(_make_error(None, -32700, f"Parse error: {exc}"))
            continue
        if not isinstance(req, dict):
            log.warning("non-object JSON-RPC request dropped")
            continue
        try:
            resp = _dispatch(req)
        except Exception as exc:  # pragma: no cover — defensive
            log.error("dispatch error: %s", exc)
            resp = _make_error(req.get("id"), -32603, f"Internal error: {exc}")
        if resp is not None:
            try:
                _write_response(resp)
            except Exception as exc:
                log.error("stdout write error: %s", exc)
                break
    return 0

def run_http(host: str, port: int, path: str, token: str) -> int:
    log.info(
        "starting vision-mcp http proxy at http://%s:%d%s (python %s)",
        host, port, path, "%d.%d.%d" % sys.version_info[:3],
    )
    api_key, _, _ = _config()
    if not api_key:
        log.warning(
            "ARK_API_KEY is not set — tool calls will fail until it is. "
            "Edit %s", ENV_FILE,
        )
    if not token:
        log.warning("VISION_MCP_TOKEN is not set; HTTP endpoint has no bearer-token guard")
    server = _VisionHTTPServer((host, port), _VisionHTTPRequestHandler, path, token)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log.info("interrupt received; shutting down")
    finally:
        server.server_close()
    return 0

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="vision-mcp local MCP proxy")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default=os.environ.get("VISION_MCP_HOST", DEFAULT_HTTP_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VISION_MCP_PORT", DEFAULT_HTTP_PORT)))
    parser.add_argument("--path", default=os.environ.get("VISION_MCP_PATH", DEFAULT_HTTP_PATH))
    parser.add_argument("--token", default=_parse_http_token(),
                        help="Bearer token for HTTP transport; defaults to VISION_MCP_TOKEN/.env")
    args = parser.parse_args(argv)
    if not args.path.startswith("/"):
        parser.error("--path must start with /")
    if args.transport == "http":
        return run_http(args.host, args.port, args.path, args.token)
    return run_stdio()

if __name__ == "__main__":
    sys.exit(main())
