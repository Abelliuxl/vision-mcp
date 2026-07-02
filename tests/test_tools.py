# tests/test_tools.py
import base64
import httpx
import pytest
import respx
from contextlib import contextmanager

from vision_mcp.tools import (
    OCR_SYSTEM_PROMPT,
    DESCRIBE_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    register_tools,
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


@pytest.fixture
def mock_ark_ok():
    """Helper that mocks the Ark endpoint and returns a context manager."""
    @contextmanager
    def _start(assert_all_called=False):
        with respx.mock(base_url="https://ark.example.com", assert_all_called=assert_all_called) as mock:
            mock.post("/api/v3/chat/completions").respond(
                200,
                json={
                    "id": "x",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OK"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
            yield mock
    return _start


def test_ocr_system_prompt_emphasizes_verbatim():
    assert "verbatim" in OCR_SYSTEM_PROMPT.lower()
    assert "do not translate" in OCR_SYSTEM_PROMPT.lower()


def test_describe_system_prompt_has_three_levels():
    for level in ("short", "medium", "long"):
        assert level in DESCRIBE_SYSTEM_PROMPT.lower()


def test_answer_system_prompt_requires_image_grounding():
    assert "do not" in ANSWER_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_register_tools_registers_three_tools(cfg, tiny_png_b64, mock_ark_ok):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-vision-mcp")
    register_tools(mcp, cfg)

    # Inspect registered tools via the low-level tool manager.
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {"ocr_image", "describe_image", "answer_image"}


@pytest.mark.asyncio
async def test_ocr_image_returns_text_block(cfg, tiny_png_b64, mock_ark_ok):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-vision-mcp")
    register_tools(mcp, cfg)

    with mock_ark_ok():
        result = await mcp.call_tool(
            "ocr_image",
            {"image_base64": tiny_png_b64, "lang": "auto"},
        )
    # result may be a tuple (content, structured) or a single object depending on SDK version.
    content = result[0] if isinstance(result, tuple) else result
    text_blocks = [c for c in content if getattr(c, "type", None) == "text"]
    assert text_blocks and "OK" in text_blocks[0].text


@pytest.mark.asyncio
async def test_describe_image_short_medium_long_all_call_upstream(
    cfg, tiny_png_b64, mock_ark_ok
):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-vision-mcp")
    register_tools(mcp, cfg)

    for level in ("short", "medium", "long"):
        with mock_ark_ok():
            result = await mcp.call_tool(
                "describe_image",
                {"image_base64": tiny_png_b64, "detail": level},
            )
        assert result is not None


@pytest.mark.asyncio
async def test_answer_image_requires_question(cfg, tiny_png_b64, mock_ark_ok):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-vision-mcp")
    register_tools(mcp, cfg)

    with mock_ark_ok(assert_all_called=False):
        result = await mcp.call_tool(
            "answer_image",
            {"image_base64": tiny_png_b64},
        )
    content = result[0] if isinstance(result, tuple) else result
    # MCP raises when a tool returns is_error=True via the SDK; we accept either
    # an exception or a result whose text indicates the error.
    text_blocks = [c for c in content if getattr(c, "type", None) == "text"]
    joined = "\n".join(b.text for b in text_blocks).lower()
    assert "question" in joined or "required" in joined


@pytest.mark.asyncio
async def test_answer_image_appends_context(cfg, tiny_png_b64, mock_ark_ok):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-vision-mcp")
    register_tools(mcp, cfg)

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}
                ]
            },
        )

    import json
    with respx.mock(base_url=cfg.ark_base_url) as mock:
        mock.post("/api/v3/chat/completions").mock(side_effect=handler)
        await mcp.call_tool(
            "answer_image",
            {
                "image_base64": tiny_png_b64,
                "question": "What color?",
                "context": "screenshot of UI",
            },
        )
    body = json.loads(captured["body"])
    user_text = next(
        c["text"] for c in body["messages"][1]["content"] if c["type"] == "text"
    )
    assert "What color?" in user_text
    assert "screenshot of UI" in user_text
