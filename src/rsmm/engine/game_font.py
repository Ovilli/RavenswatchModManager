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


def fits(font: GameFont, rgba: bytes, width: int, height: int, *, min_cover: float = 0.97) -> bool:
    """Is this decoded page the one ``font``'s glyph table was cut from?

    A table drawn over the wrong page renders real glyph strokes in the wrong
    places (unreadable text that still looks like a font), so a reader must
    check the pair before trusting it. Each locale ships its own page at its
    own size (Fontin Sans: 512 default, 600 RU, 800 PL), which a size check
    catches; a same-size page cut differently is caught by requiring nearly
    every opaque pixel to fall inside some glyph's rectangle (1.000 on every
    matched pair shipped).
    """
    if (width, height) != (font.page_w, font.page_h) or len(rgba) < width * height * 4:
        return False
    inside = bytearray(width * height)
    for x, y, w, h, *_ in font.glyphs.values():
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(width, int(x + w) + 1), min(height, int(y + h) + 1)
        if x1 > x0:
            for row in range(y0, y1):
                inside[row * width + x0:row * width + x1] = b"\1" * (x1 - x0)
    opaque = hit = 0
    for i, a in enumerate(rgba[3::4]):
        if a > 127:
            opaque += 1
            hit += inside[i]
    return opaque > 0 and hit >= opaque * min_cover


def load(rel: str) -> tuple[GameFont, bytearray, int, int] | None:
    """A font's glyph table and its decoded page, checked to belong together.

    ``rel`` is the table's decoded path (``...~GAM.fnt.Font.fnb``). Returns
    ``(font, rgba, width, height)`` or None.

    The two are separate files, and read one by one they can come from
    different stores: the mirror has the table but not the page texture, and a
    `.rsmm.bak` made before a game update (or a font mod's leftovers) is a
    different build from the live file beside it. Every glyph is drawn as a
    slice of the page at the table's coordinates, so a mismatched pair is not a
    little off: every letter is the wrong letter. Each table copy is tried with
    each page copy, live install first (what the game draws with), and only a
    pair `fits` accepts is returned.
    """
    from itertools import product

    from . import cooked, corpus, icon_decode
    from .cooked_schemas.texture import TextureHandler

    tables = corpus.install_copies(rel) + [p for p in (corpus.mirror_path(rel),) if p]
    for table_path, page_kind in product(tables, (0, 1)):
        try:
            f = parse(table_path.read_bytes())
            pages = corpus.install_copies(rel.rsplit("/", 1)[0] + "/" + f.page + ".Texture.dxt")
            if page_kind >= len(pages):
                continue
            cf = cooked.parse(pages[page_kind].read_bytes())
            tex = TextureHandler.parse_payload(cf.sections[-1].payload)
            rgba = icon_decode.decode_to_rgba(tex.pixels, tex.width, tex.height, tex.format_name)
        except (OSError, ValueError, KeyError, IndexError):
            continue
        if fits(f, rgba, tex.width, tex.height):
            return f, rgba, tex.width, tex.height
    return None
