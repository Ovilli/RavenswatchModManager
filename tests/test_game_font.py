"""The game's bitmap fonts, as the editor's card preview draws them."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import corpus, game_font


def _font(glyphs: dict[int, tuple[float, ...]], page: str = "Tiny_0~GAM.png") -> bytes:
    """A font file in the shipped layout, one glyph row per codepoint given."""
    out = struct.pack("<3If", 16, 0, 3, 1.0)
    out += struct.pack("<6I", 20, 24, 64, 64, 1, len(glyphs))
    order = sorted(glyphs)
    for cp in order:
        out += struct.pack("<I7fI4f", 0, *glyphs[cp], 0, 0.0, 0.0, 0.0, 0.0)
    span = max(order) + 1
    index = [0xFFFFFFFF] * span
    for i, cp in enumerate(order):
        index[cp] = i
    out += struct.pack(f"<I{span}I", span, *index)
    name = page.encode()
    return out + struct.pack("<ffI", 18.0, -1.0, len(name)) + name


def test_a_font_maps_codepoints_to_their_glyphs():
    f = game_font.parse(_font({65: (1, 2, 3, 4, -1, 5, 6), 97: (7, 8, 9, 10, 0, 1, 11)}))
    assert (f.size, f.line_height, f.page_w, f.page_h) == (20, 24, 64, 64)
    assert f.page == "Tiny_0~GAM.png" and f.base == 18.0
    assert f.glyphs == {65: (1, 2, 3, 4, -1, 5, 6), 97: (7, 8, 9, 10, 0, 1, 11)}


@pytest.mark.parametrize("cut", [10, 60, 100])
def test_a_cut_font_is_refused(cut):
    with pytest.raises(ValueError):
        game_font.parse(_font({65: (1, 2, 3, 4, 0, 0, 5)})[:cut])


def test_the_shipped_card_fonts_parse():
    raw = corpus.read("Fonts/Fontin Sans/Fontin_Sans_RG~GAM.fnt.Font.fnb")
    if raw is None:
        pytest.skip("game fonts not available (no mirror, no install)")
    f = game_font.parse(raw)
    assert f.page == "Fontin_Sans_RG_0~GAM.png"
    assert all(ord(c) in f.glyphs for c in "Aa0+%•")
