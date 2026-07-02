"""Image decoding, validation, and Pillow-based compression.

Hard cap: decoded size must be at most ``MAX_IMAGE_BYTES``. Anything larger
raises :class:`ImageTooLarge`. Pillow downscales long-side > ``MAX_DIMENSION``
to keep typical photos under the cap without lossy recompression.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MiB
MAX_DIMENSION = 2048
JPEG_QUALITY = 85

_MIME_BY_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class BadImage(ValueError):
    """The input is not a valid encoded image."""


class ImageTooLarge(ValueError):
    """The image, after decoding, exceeds MAX_IMAGE_BYTES."""


def _strip_data_url(s: str) -> str:
    if s.startswith("data:") and ";base64," in s:
        return s.split(";base64,", 1)[1]
    return s


def decode_and_compress(b64_or_data_url: str) -> tuple[bytes, str]:
    raw = _strip_data_url(b64_or_data_url.strip())

    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise BadImage("input is not valid base64") from exc

    if not decoded:
        raise BadImage("input is empty after base64 decode")

    if len(decoded) > MAX_IMAGE_BYTES:
        raise ImageTooLarge(
            f"image exceeds {MAX_IMAGE_BYTES} bytes after decode "
            f"({len(decoded)} bytes)"
        )

    try:
        img = Image.open(io.BytesIO(decoded))
        img.load()
    except Exception as exc:  # PIL raises a variety of exceptions
        raise BadImage(f"could not decode image: {exc}") from exc

    fmt = (img.format or "").upper()
    mime = _MIME_BY_FORMAT.get(fmt)
    if mime is None:
        raise BadImage(f"unsupported image format: {fmt or 'unknown'}")

    # Re-encode so we control size; downscale large images first.
    if max(img.size) > MAX_DIMENSION:
        ratio = MAX_DIMENSION / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    target_format = fmt if fmt in ("PNG", "JPEG", "WEBP", "GIF") else "PNG"
    save_kwargs: dict = {"format": target_format, "optimize": True}
    if target_format == "JPEG":
        if img.mode != "RGB":
            img = img.convert("RGB")
        save_kwargs["quality"] = JPEG_QUALITY
    img.save(buf, **save_kwargs)
    out = buf.getvalue()

    if len(out) > MAX_IMAGE_BYTES:
        raise ImageTooLarge(
            f"image exceeds {MAX_IMAGE_BYTES} bytes after compression "
            f"({len(out)} bytes)"
        )
    return out, mime
