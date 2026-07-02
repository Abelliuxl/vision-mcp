"""Volcano Ark upstream client (OpenAI-compatible)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

import httpx
from openai import APITimeoutError, OpenAI

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com"


class _ConfigLike(Protocol):
    ark_base_url: str
    ark_api_key: str
    ark_model: str


class UpstreamError(RuntimeError):
    """Raised when the upstream returns a non-retryable failure (4xx/5xx)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"upstream {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class UpstreamTimeoutError(TimeoutError):
    """Raised when the upstream times out."""


def build_openai_client(cfg: _ConfigLike) -> OpenAI:
    """Construct an OpenAI SDK client pointed at Ark.

    Timeouts: connect 5s, read 45s, write 5s, pool 5s. Read-heavy because we
    stream images in and a single response back; the bulk of the wait is the
    model thinking.

    Retries are disabled (``max_retries=0``): we surface 5xx as ``UpstreamError``
    immediately so we don't pile partial image bodies in memory.
    """
    timeout = httpx.Timeout(connect=5.0, read=45.0, write=5.0, pool=5.0)
    return OpenAI(
        base_url=f"{cfg.ark_base_url.rstrip('/')}/api/v3",
        api_key=cfg.ark_api_key,
        timeout=timeout,
        max_retries=0,
    )


def vision_chat(
    cfg: _ConfigLike,
    system_prompt: str,
    user_text: str,
    image_b64: str,
    mime: str,
    max_tokens: int,
) -> str:
    """Send a single multimodal chat completion to Ark and return the text reply.

    Retries on network/5xx errors are intentionally disabled to avoid piling
    partial image bodies in memory.
    """
    client = build_openai_client(cfg)
    image_data_url = f"data:{mime};base64,{image_b64}"

    try:
        response = client.chat.completions.create(
            model=cfg.ark_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
    except (httpx.TimeoutException, APITimeoutError) as exc:
        raise UpstreamTimeoutError("upstream timed out") from exc
    except Exception as exc:
        # The openai SDK raises BadRequestError / AuthenticationError / APIStatusError
        # etc. We surface status code where we can.
        status = getattr(exc, "status_code", None)
        message = str(exc)
        if status is None:
            raise UpstreamError(0, message) from exc
        raise UpstreamError(int(status), message) from exc

    if not response.choices:
        raise UpstreamError(0, "upstream returned no choices")
    return response.choices[0].message.content or ""