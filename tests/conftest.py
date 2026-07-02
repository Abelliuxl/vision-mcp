"""Shared pytest fixtures."""

from __future__ import annotations

import base64

import pytest
from PIL import Image


@pytest.fixture
def tiny_png_bytes() -> bytes:
    """Return bytes of a 2x2 red PNG."""
    img = Image.new("RGB", (2, 2), color="red")
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def tiny_png_b64(tiny_png_bytes) -> str:
    return base64.b64encode(tiny_png_bytes).decode("ascii")


@pytest.fixture
def huge_png_bytes() -> bytes:
    """Return bytes of a 4000x4000 RGB PNG (well over 8 MiB)."""
    img = Image.new("RGB", (4000, 4000), color="green")
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@pytest.fixture
def huge_png_b64(huge_png_bytes) -> str:
    return base64.b64encode(huge_png_bytes).decode("ascii")
