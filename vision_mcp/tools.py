"""The three MCP tools: ocr_image, describe_image, answer_image."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .image import decode_and_compress
from .upstream import vision_chat, UpstreamError, UpstreamTimeoutError


OCR_SYSTEM_PROMPT = (
    "Your only task is to extract every character of text in the image, verbatim. "
    "Output the extracted text only, in reading order. Do not translate, "
    "summarize, or comment. Preserve line breaks."
)

DESCRIBE_SYSTEM_PROMPT = (
    "Describe the image objectively, in present tense, third person. "
    "Length caps depend on the requested detail level: "
    "short ≤ 60 CJK chars or ≤ 120 Latin chars; "
    "medium ≤ 180 CJK chars or ≤ 360 Latin chars; "
    "long ≤ 600 CJK chars or ≤ 1200 Latin chars. "
    "Do not infer intent. Do not invent text. Do not begin with phrases like "
    "'The image ...'. Begin directly with the subject."
)

ANSWER_SYSTEM_PROMPT = (
    "You are a visual QA assistant. Answer based solely on what is in the image. "
    "If the image does not contain enough information, respond with 'The image "
    "does not provide enough information.' Do not guess."
)


def _render(cfg, *, system_prompt: str, user_text: str, image_b64: str, max_tokens: int) -> str:
    image_bytes, mime = decode_and_compress(image_b64)
    # Convert the bytes back to a clean base64 string the upstream SDK can embed.
    import base64
    reencoded_b64 = base64.b64encode(image_bytes).decode("ascii")
    return vision_chat(
        cfg,
        system_prompt=system_prompt,
        user_text=user_text,
        image_b64=reencoded_b64,
        mime=mime,
        max_tokens=max_tokens,
    )


def register_tools(mcp: FastMCP, cfg) -> None:
    """Register the three tools on the given FastMCP instance."""

    @mcp.tool(name="ocr_image", description="Extract text from an image verbatim.")
    def ocr_image(
        image_base64: str,
        lang: Literal["zh", "en", "auto"] = "auto",
    ) -> str:
        decoded, mime = decode_and_compress(image_base64)
        import base64
        b64 = base64.b64encode(decoded).decode("ascii")
        prompt_user = (
            f"Language hint: {lang}. Return the extracted text only."
        )
        try:
            return vision_chat(
                cfg,
                system_prompt=OCR_SYSTEM_PROMPT,
                user_text=prompt_user,
                image_b64=b64,
                mime=mime,
                max_tokens=2048,
            )
        except UpstreamTimeoutError as exc:
            return f"Upstream temporarily unavailable, please retry ({exc})."
        except UpstreamError as exc:
            return f"Upstream rejected request ({exc.status_code}): {exc.message}"

    @mcp.tool(name="describe_image", description="Describe an image objectively.")
    def describe_image(
        image_base64: str,
        detail: Literal["short", "medium", "long"] = "medium",
    ) -> str:
        decoded, mime = decode_and_compress(image_base64)
        import base64
        b64 = base64.b64encode(decoded).decode("ascii")
        prompt_user = f"Detail level: {detail}. Begin directly with the subject."
        try:
            return vision_chat(
                cfg,
                system_prompt=DESCRIBE_SYSTEM_PROMPT,
                user_text=prompt_user,
                image_b64=b64,
                mime=mime,
                max_tokens=1024,
            )
        except UpstreamTimeoutError as exc:
            return f"Upstream temporarily unavailable, please retry ({exc})."
        except UpstreamError as exc:
            return f"Upstream rejected request ({exc.status_code}): {exc.message}"

    @mcp.tool(name="answer_image", description="Answer a question grounded in the image.")
    def answer_image(
        image_base64: str,
        question: str = "",
        context: str | None = None,
    ) -> str:
        if not question or not question.strip():
            return "Missing required argument: question"
        decoded, mime = decode_and_compress(image_base64)
        import base64
        b64 = base64.b64encode(decoded).decode("ascii")
        user_text = question.strip()
        if context and context.strip():
            user_text = f"{user_text}\n\nContext: {context.strip()}"
        try:
            return vision_chat(
                cfg,
                system_prompt=ANSWER_SYSTEM_PROMPT,
                user_text=user_text,
                image_b64=b64,
                mime=mime,
                max_tokens=2048,
            )
        except UpstreamTimeoutError as exc:
            return f"Upstream temporarily unavailable, please retry ({exc})."
        except UpstreamError as exc:
            return f"Upstream rejected request ({exc.status_code}): {exc.message}"
