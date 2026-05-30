"""Block-compressed decode + PNG encode (`rsmm.engine.image`).

Pure format helpers — no Ravenswatch install needed. Each test builds a
DDS via `dds.write`, decodes the base mip to RGBA8, and checks texel 0.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from rsmm.engine import dds, image

_RED565 = (31 << 11) | (0 << 5) | 0  # 5-bit R max, G/B zero


def _solid_bc1(color565: int) -> bytes:
    # c0=color, c1=0, all indices 0 -> every texel = color0.
    return struct.pack("<HHI", color565, 0, 0)


def test_png_header_and_size() -> None:
    png = image.encode_png(2, 2, bytes([10, 20, 30, 40]) * 4)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    for tag in (b"IHDR", b"IDAT", b"IEND"):
        assert tag in png
    # IHDR declares 2x2, 8-bit, color type 6 (RGBA).
    w, h, depth, ctype = struct.unpack_from(">IIBB", png, 16)
    assert (w, h, depth, ctype) == (2, 2, 8, 6)


def test_png_rejects_wrong_buffer_len() -> None:
    with pytest.raises(ValueError):
        image.encode_png(2, 2, b"\x00\x00\x00")


def test_png_idat_roundtrips_to_filtered_scanlines() -> None:
    rgba = bytes(range(16))  # 2x2
    png = image.encode_png(2, 2, rgba)
    # Pull the IDAT payload back out and inflate it.
    i = png.index(b"IDAT")
    ln = struct.unpack_from(">I", png, i - 4)[0]
    raw = zlib.decompress(png[i + 4:i + 4 + ln])
    # Each scanline = 1 filter byte (0) + 2 px * 4 ch = 9 bytes; 2 rows.
    assert len(raw) == 2 * (1 + 8)
    assert raw[0] == 0 and raw[9] == 0
    assert raw[1:9] == rgba[0:8]


def test_bc1_solid_color() -> None:
    out = dds.write(_solid_bc1(_RED565), 4, 4, dds.by_name("BC1"))
    w, h, rgba = image.decode_dds_to_rgba(dds.read(out))
    assert (w, h) == (4, 4)
    assert rgba[0:4] == bytes([255, 0, 0, 255])
    assert len(rgba) == 4 * 4 * 4


def test_bc1_punchthrough_alpha() -> None:
    # c0 <= c1 selects the 3-color + transparent-black mode; index 3 = (0,0,0,0).
    block = struct.pack("<HHI", 0, _RED565, 0xFFFFFFFF)  # all indices = 3
    out = dds.write(block, 4, 4, dds.by_name("BC1"))
    _, _, rgba = image.decode_dds_to_rgba(dds.read(out))
    assert rgba[0:4] == bytes([0, 0, 0, 0])


def test_bc3_color_plus_alpha() -> None:
    alpha = bytes([255, 255, 0, 0, 0, 0, 0, 0])      # a0=a1=255 -> all 255
    color = _solid_bc1(_RED565)
    out = dds.write(alpha + color, 4, 4, dds.by_name("BC3"))
    _, _, rgba = image.decode_dds_to_rgba(dds.read(out))
    assert rgba[0:4] == bytes([255, 0, 0, 255])


def test_bc4_grayscale() -> None:
    block = bytes([128, 128, 0, 0, 0, 0, 0, 0])  # both endpoints 128
    out = dds.write(block, 4, 4, dds.by_name("BC4U"))
    _, _, rgba = image.decode_dds_to_rgba(dds.read(out))
    assert rgba[0:4] == bytes([128, 128, 128, 255])


def test_rgba8_stored_bgra_is_swapped() -> None:
    # Stored as B,G,R,A = (0,0,255,255); decode swaps to R,G,B,A red.
    out = dds.write(bytes([0, 0, 255, 255]) * 16, 4, 4, dds.by_name("RGBA8"))
    _, _, rgba = image.decode_dds_to_rgba(dds.read(out))
    assert rgba[0:4] == bytes([255, 0, 0, 255])


def test_bc7_not_yet_supported() -> None:
    out = dds.write(b"\x00" * 16, 4, 4, dds.by_name("BC7"))
    with pytest.raises(NotImplementedError):
        image.decode_dds_to_rgba(dds.read(out))


def test_png_encode_decode_roundtrip():
    from rsmm.engine import image
    # 3x2 RGBA gradient with varying alpha.
    w, h = 3, 2
    rgba = bytes([
        255, 0, 0, 255,   0, 255, 0, 128,   0, 0, 255, 0,
        10, 20, 30, 40,   200, 100, 50, 255, 1, 2, 3, 4,
    ])
    png = image.encode_png(w, h, rgba)
    w2, h2, out = image.decode_png(png)
    assert (w2, h2) == (w, h)
    assert out == rgba


def test_decode_png_rgb_fills_opaque_alpha():
    # Build a color-type-2 (RGB) PNG by hand via zlib.
    import struct
    import zlib

    from rsmm.engine import image
    w, h = 2, 1
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes([255, 0, 0, 0, 255, 0])  # filter 0 + 2 RGB px
    idat = zlib.compress(raw, 9)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    _, _, rgba = image.decode_png(png)
    assert rgba == bytes([255, 0, 0, 255, 0, 255, 0, 255])


def test_decode_png_rejects_bad_magic():
    from rsmm.engine import image
    try:
        image.decode_png(b"not a png at all 1234")
    except ValueError:
        return
    raise AssertionError("expected ValueError on bad PNG magic")
