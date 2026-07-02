# tests/test_upstream.py
import base64
import httpx
import pytest
import respx

from vision_mcp.upstream import (
    UpstreamError,
    UpstreamTimeoutError,
    vision_chat,
    build_openai_client,
    DEFAULT_BASE_URL,
)


@pytest.fixture
def cfg():
    from dataclasses import dataclass

    @dataclass
    class C:
        ark_base_url = "https://ark.example.com"
        ark_api_key = "test-key"
        ark_model = "doubao-seed-2-0-mini-260215"

    return C()


def test_build_openai_client_uses_ark_base_url(cfg):
    client = build_openai_client(cfg)
    assert "ark.example.com" in str(client.base_url)


def test_vision_chat_sends_correct_request_shape(cfg, tiny_png_b64):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello back."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    with respx.mock(base_url=cfg.ark_base_url) as mock:
        mock.post("/api/v3/chat/completions").mock(side_effect=handler)
        result = vision_chat(
            cfg,
            system_prompt="sys",
            user_text="describe this",
            image_b64=tiny_png_b64,
            mime="image/png",
            max_tokens=512,
        )

    assert result == "Hello back."
    import json
    body = json.loads(captured["body"])
    assert body["model"] == cfg.ark_model
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0.2
    assert body["messages"][0]["role"] == "system"
    user_content = body["messages"][1]["content"]
    assert isinstance(user_content, list)
    image_url = next(c for c in user_content if c["type"] == "image_url")["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    text = next(c for c in user_content if c["type"] == "text")["text"]
    assert text == "describe this"


def test_vision_chat_4xx_raises_upstream_error(cfg, tiny_png_b64):
    with respx.mock(base_url=cfg.ark_base_url) as mock:
        mock.post("/api/v3/chat/completions").respond(400, json={"error": {"message": "bad"}})
        with pytest.raises(UpstreamError) as ei:
            vision_chat(cfg, "sys", "hi", tiny_png_b64, "image/png", 512)
        assert ei.value.status_code == 400


def test_vision_chat_5xx_no_retry(cfg, tiny_png_b64):
    """5xx must be raised immediately; retries are disabled by design."""
    from vision_mcp.upstream import UpstreamError

    with respx.mock(base_url=cfg.ark_base_url) as mock:
        route = mock.post("/api/v3/chat/completions").respond(503, json={"error": "down"})
        with pytest.raises(UpstreamError) as ei:
            vision_chat(cfg, "sys", "hi", tiny_png_b64, "image/png", 512)
        assert ei.value.status_code == 503
        assert route.call_count == 1


def test_vision_chat_429_raises_upstream_error(cfg, tiny_png_b64):
    with respx.mock(base_url=cfg.ark_base_url) as mock:
        mock.post("/api/v3/chat/completions").respond(429, json={"error": "slow down"})
        with pytest.raises(UpstreamError) as ei:
            vision_chat(cfg, "sys", "hi", tiny_png_b64, "image/png", 512)
        assert ei.value.status_code == 429


def test_vision_chat_timeout_raises(cfg, tiny_png_b64):
    with respx.mock(base_url=cfg.ark_base_url) as mock:
        mock.post("/api/v3/chat/completions").mock(side_effect=httpx.TimeoutException("slow"))
        with pytest.raises(UpstreamTimeoutError):
            vision_chat(cfg, "sys", "hi", tiny_png_b64, "image/png", 512)


def test_default_base_url_constant():
    assert DEFAULT_BASE_URL.startswith("https://")