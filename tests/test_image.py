import base64

import pytest

from vision_mcp.image import (
    decode_and_compress,
    BadImage,
    ImageTooLarge,
    MAX_IMAGE_BYTES,
)


def test_decode_valid_png_returns_bytes_and_mime(tiny_png_b64):
    data, mime = decode_and_compress(tiny_png_b64)
    assert mime == "image/png"
    assert isinstance(data, bytes)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_decode_valid_jpeg(tiny_png_bytes, tmp_path):
    from io import BytesIO
    from PIL import Image
    jpeg_buf = BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(jpeg_buf, format="JPEG")
    b64 = base64.b64encode(jpeg_buf.getvalue()).decode("ascii")
    data, mime = decode_and_compress(b64)
    assert mime == "image/jpeg"
    assert data[:3] == b"\xff\xd8\xff"


def test_decode_rejects_empty():
    with pytest.raises(BadImage):
        decode_and_compress("")


def test_decode_rejects_garbage():
    with pytest.raises(BadImage):
        decode_and_compress("not-base64-or-anything-real")


def test_decode_rejects_decoded_b64_not_an_image():
    # Plain text "hello" base64-encoded; b64 is valid, but content is not an image.
    b64 = base64.b64encode(b"hello world this is not an image").decode("ascii")
    with pytest.raises(BadImage):
        decode_and_compress(b64)


def test_decode_compresses_huge_image(huge_png_b64):
    data, mime = decode_and_compress(huge_png_b64)
    assert mime == "image/png"
    # Pillow rescale brings longest side down to 2048 → bytes drop well under 8 MiB.
    assert len(data) <= MAX_IMAGE_BYTES


def test_decode_rejects_bytes_already_over_limit(monkeypatch):
    # Construct a 9 MiB random-looking but valid PNG by patching MAX_IMAGE_BYTES down.
    from vision_mcp import image as image_mod
    monkeypatch.setattr(image_mod, "MAX_IMAGE_BYTES", 1024)  # 1 KiB cap
    from io import BytesIO
    from PIL import Image
    raw = Image.new("RGB", (100, 100), color="red")
    buf = BytesIO()
    raw.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    with pytest.raises(ImageTooLarge):
        decode_and_compress(b64)


def test_decode_rejects_oversized_raw_bytes(tiny_png_b64, monkeypatch):
    """Decoded bytes that fit in base64 but exceed cap after decode → ImageTooLarge."""
    from vision_mcp import image as image_mod
    monkeypatch.setattr(image_mod, "MAX_IMAGE_BYTES", 4)  # 4 bytes cap
    with pytest.raises(ImageTooLarge):
        decode_and_compress(tiny_png_b64)


def test_decode_strips_data_url_prefix(tiny_png_b64):
    prefixed = f"data:image/png;base64,{tiny_png_b64}"
    data, mime = decode_and_compress(prefixed)
    assert mime == "image/png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
