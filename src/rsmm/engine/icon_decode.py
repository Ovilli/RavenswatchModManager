"""Cooked texture -> PNG, in pure stdlib.

``scripts/extract_uncooked.py`` does the same job with ``texture2ddecoder`` +
``Pillow``, but those are developer tools. This module runs inside the shipped
CLI, which declares no runtime dependencies and is frozen into the desktop
app's sidecar — so the block decoders and the PNG writer are implemented here
rather than imported.

Only what item icons actually need is implemented: BC1 and BC3 (every shipped
magical-object icon is BC3 192x192 with no mips) plus straight RGBA8. An
unsupported format raises rather than returning a plausible-looking wrong
image, because a silently mis-decoded icon in a picker is a mislabelled ban.
"""

from __future__ import annotations

import struct
import zlib
from typing import Final

__all__ = ["decode_to_rgba", "rgba_to_png", "resize_to_max", "texture_to_png"]

#: ``TextureSchema.format_name`` values this module can decode.
SUPPORTED: Final = ("BC1", "BC3", "RGBA8", "RGBA")


def _color_table(c0: int, c1: int, *, punchthrough: bool) -> list[tuple[int, int, int, int]]:
    """Expand a BC1 endpoint pair into its 4-entry RGB table.

    ``punchthrough`` selects the 3-colour + transparent mode BC1 uses when
    ``c0 <= c1``. BC3's colour half never takes that mode (its alpha lives in
    the separate block), so callers pass False for it.
    """
    def rgb(c: int) -> tuple[int, int, int]:
        r = (c >> 11) & 0x1F
        g = (c >> 5) & 0x3F
        b = c & 0x1F
        return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)

    r0, g0, b0 = rgb(c0)
    r1, g1, b1 = rgb(c1)
    if punchthrough and c0 <= c1:
        return [
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
            (0, 0, 0, 0),
        ]
    return [
        (r0, g0, b0, 255),
        (r1, g1, b1, 255),
        ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255),
        ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255),
    ]


def _alpha_table(a0: int, a1: int) -> list[int]:
    """Expand a BC3/BC4 alpha endpoint pair into its 8-entry table."""
    if a0 > a1:
        # a[2+i] = ((6-i)*a0 + (1+i)*a1) / 7, i = 0..5
        return [a0, a1] + [((6 - i) * a0 + (1 + i) * a1) // 7 for i in range(6)]
    # 6-interpolated mode: a[2+i] = ((4-i)*a0 + (1+i)*a1) / 5, then 0 and 255
    return ([a0, a1] + [((4 - i) * a0 + (1 + i) * a1) // 5 for i in range(4)]
            + [0, 255])


def _blocks(width: int, height: int):
    """Yield ``(block_index, base_x, base_y)`` in the order block formats store
    them: left to right, top to bottom, 4x4 each."""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    for by in range(bh):
        for bx in range(bw):
            yield by * bw + bx, bx * 4, by * 4


def _decode_bc1(px: bytes, width: int, height: int) -> bytearray:
    out = bytearray(width * height * 4)
    for bi, ox, oy in _blocks(width, height):
        o = bi * 8
        c0, c1, bits = struct.unpack_from("<HHI", px, o)
        table = _color_table(c0, c1, punchthrough=True)
        for i in range(16):
            x, y = ox + (i & 3), oy + (i >> 2)
            if x >= width or y >= height:
                continue
            r, g, b, a = table[(bits >> (2 * i)) & 3]
            d = (y * width + x) * 4
            out[d:d + 4] = bytes((r, g, b, a))
    return out


def _decode_bc3(px: bytes, width: int, height: int) -> bytearray:
    out = bytearray(width * height * 4)
    for bi, ox, oy in _blocks(width, height):
        o = bi * 16
        a0, a1 = px[o], px[o + 1]
        # The 16 three-bit alpha indices are a little-endian 48-bit field.
        abits = int.from_bytes(px[o + 2:o + 8], "little")
        atable = _alpha_table(a0, a1)
        c0, c1, cbits = struct.unpack_from("<HHI", px, o + 8)
        # BC3's colour half is always 4-colour: alpha is carried separately, so
        # the c0 <= c1 punchthrough encoding does not apply.
        ctable = _color_table(c0, c1, punchthrough=False)
        for i in range(16):
            x, y = ox + (i & 3), oy + (i >> 2)
            if x >= width or y >= height:
                continue
            r, g, b, _ = ctable[(cbits >> (2 * i)) & 3]
            a = atable[(abits >> (3 * i)) & 7]
            d = (y * width + x) * 4
            out[d:d + 4] = bytes((r, g, b, a))
    return out


def decode_to_rgba(pixels: bytes, width: int, height: int, fmt: str) -> bytearray:
    """Decode a cooked texture payload into straight RGBA8 rows."""
    f = (fmt or "").upper()
    if f == "BC1":
        return _decode_bc1(pixels, width, height)
    if f == "BC3":
        return _decode_bc3(pixels, width, height)
    if f in ("RGBA8", "RGBA"):
        need = width * height * 4
        if len(pixels) < need:
            raise ValueError(f"RGBA8 payload too short: {len(pixels)} < {need}")
        return bytearray(pixels[:need])
    raise ValueError(f"unsupported texture format {fmt!r} "
                     f"(supported: {', '.join(SUPPORTED)})")


def resize_to_max(rgba: bytes, width: int, height: int, max_edge: int
                  ) -> tuple[bytearray, int, int]:
    """Box-average ``rgba`` down so neither edge exceeds ``max_edge``.

    Source ranges are computed with integer division rather than a fixed
    divisor, because the shipped icons are NOT one size — most are 192x192 but
    the power-up art is 164x164, and an integer-factor-only resize refuses
    those outright (which silently cost 17 of 74 icons the first time round).
    Images already within the bound are returned untouched.
    """
    if max_edge <= 0 or (width <= max_edge and height <= max_edge):
        return bytearray(rgba), width, height
    scale = max(width, height) / max_edge
    nw = max(1, int(width / scale))
    nh = max(1, int(height / scale))
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy0, sy1 = y * height // nh, max(y * height // nh + 1, (y + 1) * height // nh)
        for x in range(nw):
            sx0, sx1 = x * width // nw, max(x * width // nw + 1, (x + 1) * width // nw)
            r = g = b = a = n = 0
            for sy in range(sy0, sy1):
                row = (sy * width) * 4
                for sx in range(sx0, sx1):
                    o = row + sx * 4
                    r += rgba[o]
                    g += rgba[o + 1]
                    b += rgba[o + 2]
                    a += rgba[o + 3]
                    n += 1
            d = (y * nw + x) * 4
            out[d:d + 4] = bytes((r // n, g // n, b // n, a // n))
    return out, nw, nh


def _chunk(tag: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + tag + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))


def rgba_to_png(rgba: bytes, width: int, height: int) -> bytes:
    """Encode RGBA8 rows as a PNG (filter type 0 on every scanline)."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)                       # filter: None
        raw += rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def texture_to_png(cooked_bytes: bytes, *, max_edge: int = 0) -> bytes:
    """Cooked ``oCTexture`` container -> PNG bytes, optionally resized down."""
    from . import cooked as _cooked
    from .cooked_schemas.texture import TextureHandler

    schema = TextureHandler.parse_payload(_cooked.parse(cooked_bytes).sections[-1].payload)
    rgba = decode_to_rgba(schema.pixels, schema.width, schema.height,
                          schema.format_name)
    rgba, w, h = resize_to_max(rgba, schema.width, schema.height, max_edge)
    return rgba_to_png(rgba, w, h)
