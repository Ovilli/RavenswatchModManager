"""The game's bitmap fonts (``*.fnt.Font.fnb`` + one ``*_0~GAM.png`` page).

Layout, read off the shipped Fontin Sans and Germania One files (both
little-endian)::

    u32 16, u32 0, u32 3, f32 1.0      header (meaning unknown, identical in both)
    u32 size, u32 line_height          38/48 Fontin Sans, 63/80 Germania One
    u32 page_w, u32 page_h, u32 pages  512x512x1, 720x720x1
    u32 glyph_count
    glyph_count x 52 bytes:            u32 page, f32 x, y, w, h, xoff, yoff,
                                       xadvance, u32 0, f32 u0, v0, u1, v1
    u32 map_len, map_len x u32         codepoint -> glyph index, 0xffffffff = none
    f32 base, f32 ?, lstr page texture name

Offsets are pixels on the page and relative to the top of a line, as in
AngelCode BMFont. Nothing here writes a font; the editor draws card text with
it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_GLYPH = struct.Struct("<I7fI4f")
_NONE = 0xFFFFFFFF


@dataclass(frozen=True)
class GameFont:
    size: int
    line_height: int
    page_w: int
    page_h: int
    base: float
    page: str
    #: codepoint -> (x, y, w, h, xoff, yoff, xadvance) on the page
    glyphs: dict[int, tuple[float, ...]]


def parse(data: bytes) -> GameFont:
    if len(data) < 40:
        raise ValueError("font file too short")
    size, line_height, page_w, page_h, pages, count = struct.unpack_from("<6I", data, 16)
    if pages != 1:
        raise ValueError(f"font has {pages} pages; only single-page fonts are read")
    if count > 65536 or 40 + count * _GLYPH.size + 4 > len(data):
        raise ValueError("font glyph table does not fit the file")
    rows = [_GLYPH.unpack_from(data, 40 + i * _GLYPH.size) for i in range(count)]
    at = 40 + count * _GLYPH.size
    map_len = struct.unpack_from("<I", data, at)[0]
    at += 4
    if map_len > 0x110000 or at + map_len * 4 + 12 > len(data):
        raise ValueError("font codepoint map does not fit the file")
    index = struct.unpack_from(f"<{map_len}I", data, at)
    at += map_len * 4
    base = struct.unpack_from("<f", data, at)[0]
    n = struct.unpack_from("<I", data, at + 8)[0]
    page = data[at + 12:at + 12 + n].decode("utf-8", "replace")
    glyphs = {}
    for cp, gi in enumerate(index):
        if gi != _NONE and gi < count:
            glyphs[cp] = tuple(round(v, 3) for v in rows[gi][1:8])
    return GameFont(size=size, line_height=line_height, page_w=page_w, page_h=page_h,
                    base=base, page=page, glyphs=glyphs)
