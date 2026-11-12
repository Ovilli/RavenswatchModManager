"""The hot-path rewrites (guid map, asset-ref split, BC3 decode, texture
tint) against the straightforward versions they replaced, kept here as the
reference. Real-install checks sample a few files and skip without a game."""

from __future__ import annotations

import random
import struct
import time

import pytest

from rsmm.engine import cooked, corpus, hero_cook, icon_decode
from rsmm.engine.cooked_schemas import asset_refs

# ---------------------------------------------------------------- references


def _ref_apply_guid_map(raw, mapping):
    cf = cooked.parse(raw)
    for sec in cf.sections:
        pl = sec.payload
        for old, new in mapping.items():
            if old in pl:
                pl = pl.replace(old, new)
        sec.payload = pl
    return cooked.emit(cf)


def _ref_looks_like_ref(s):
    if not (asset_refs._MIN_REF <= len(s) <= asset_refs._MAX_REF):
        return False
    if not all(32 <= c < 127 for c in s):
        return False
    low = s.lower()
    if b"\\" in s or b"/" in s:
        return True
    return any(low.endswith(e.encode()) for e in asset_refs._ASSET_EXTS)


def _ref_split_refs(concat):
    literals, refs, offsets = [], [], []
    n = len(concat)
    i = 0
    lit_start = 0
    while i + 4 <= n:
        ln = struct.unpack_from("<I", concat, i)[0]
        if 0 < ln <= asset_refs._MAX_REF and i + 4 + ln <= n:
            cand = concat[i + 4:i + 4 + ln]
            if _ref_looks_like_ref(cand):
                literals.append(concat[lit_start:i].hex())
                refs.append(cand.decode("utf-8", errors="replace"))
                offsets.append(i + 4)
                i = i + 4 + ln
                lit_start = i
                continue
        i += 1
    literals.append(concat[lit_start:].hex())
    return literals, refs, offsets


def _ref_decode_bc3(px, width, height):
    out = bytearray(width * height * 4)
    for bi, ox, oy in icon_decode._blocks(width, height):
        o = bi * 16
        a0, a1 = px[o], px[o + 1]
        abits = int.from_bytes(px[o + 2:o + 8], "little")
        atable = icon_decode._alpha_table(a0, a1)
        c0, c1, cbits = struct.unpack_from("<HHI", px, o + 8)
        ctable = icon_decode._color_table(c0, c1, punchthrough=False)
        for i in range(16):
            x, y = ox + (i & 3), oy + (i >> 2)
            if x >= width or y >= height:
                continue
            r, g, b, _ = ctable[(cbits >> (2 * i)) & 3]
            a = atable[(abits >> (3 * i)) & 7]
            d = (y * width + x) * 4
            out[d:d + 4] = bytes((r, g, b, a))
    return out


def _ref_tint(px, rgb):
    r, g, b = rgb
    out = bytearray(len(px))
    for i in range(0, len(px), 4):
        lum = max(px[i], px[i + 1], px[i + 2]) / 255
        out[i] = int(r * lum * 255)
        out[i + 1] = int(g * lum * 255)
        out[i + 2] = int(b * lum * 255)
        out[i + 3] = px[i + 3]
    return out


def _installed():
    if corpus.cooking_dir() is None:
        pytest.skip("no game install")


def _sample(rels, n, seed=1):
    rels = sorted(rels)
    random.Random(seed).shuffle(rels)
    return rels[:n]


# ------------------------------------------------------------- apply_guid_map


def _guid(i):
    return bytes([i]) * 16


def _container(payloads):
    cf = cooked.CookedFile(
        variant="A", hdr_a=1, flags=0, classes=[],
        sections=[cooked.Section(payload=p) for p in payloads])
    return cooked.emit(cf)


GUID_CASES = [
    ([b"xx" + _guid(1) + b"yy" + _guid(2) + _guid(1)], {_guid(1): _guid(9), _guid(2): _guid(8)}),
    ([b"no guids here"], {_guid(1): _guid(9)}),
    ([b""], {_guid(1): _guid(9)}),
    ([_guid(1) * 3, _guid(2)], {_guid(1): _guid(1), _guid(2): _guid(3)}),     # self map
    ([_guid(1) + _guid(2)], {_guid(1): _guid(2), _guid(2): _guid(3)}),        # chain: order matters
    ([_guid(2) + _guid(1)], {_guid(1): _guid(2), _guid(2): _guid(3)}),
    ([b"\x01" * 24], {b"\x01" * 16: _guid(5)}),                               # overlapping hits
    ([b"abc" + _guid(1)], {}),
    ([b"abc" + _guid(1) + b"zz"], {_guid(1): b"short", b"ab": b"XY"}),        # mixed lengths
    ([_guid(4)[:8] + _guid(7)[:8] + _guid(4)[8:]], {_guid(4): _guid(7), _guid(7): _guid(6)}),
]


@pytest.mark.parametrize("payloads,mapping", GUID_CASES)
def test_apply_guid_map_matches_sequential(payloads, mapping):
    raw = _container(payloads)
    assert hero_cook.apply_guid_map(raw, mapping) == _ref_apply_guid_map(raw, mapping)


def test_apply_guid_map_random_payloads():
    rng = random.Random(7)
    guids = [rng.randbytes(16) for _ in range(12)]
    mapping = {g: rng.randbytes(16) for g in guids[:9]}
    mapping[guids[3]] = guids[3]
    mapping[guids[4]] = guids[5]          # a value that is also a key
    for _ in range(25):
        pl = bytearray(rng.randbytes(rng.randrange(0, 400)))
        for _ in range(rng.randrange(0, 6)):
            at = rng.randrange(0, len(pl) + 1)
            pl[at:at] = rng.choice(guids)
        raw = _container([bytes(pl), bytes(pl)[::-1]])
        assert hero_cook.apply_guid_map(raw, mapping) == _ref_apply_guid_map(raw, mapping)


def test_apply_guid_map_real_entities():
    _installed()
    rels = _sample(corpus.rels("", ".EntitySettingsResource.gen"), 12)
    raws = [b for b in (corpus.read(r) for r in rels) if b]
    assert len(raws) == 12
    mapping = hero_cook.family_guid_map(raws, "hot-paths")
    assert mapping
    t0 = time.perf_counter()
    for raw in raws:
        assert hero_cook.apply_guid_map(raw, mapping) == _ref_apply_guid_map(raw, mapping)
    assert time.perf_counter() - t0 < 20


# --------------------------------------------------------------- _split_refs


def _s(text, ln=None):
    t = text.encode("latin-1")
    return struct.pack("<I", len(t) if ln is None else ln) + t


SPLIT_CASES = [
    b"",
    b"\x04\x00\x00",
    _s("Materials\\Foo.mat.ot"),
    b"\xff\xfe" + _s("a/b/c.png") + b"\x00\x00" + _s("Objects\\Bar.entity.ot") + b"tail",
    _s("abcd"),                                  # printable, no separator/ext
    _s("name.PNG") + _s("X.Mat"),                # case-insensitive extension
    _s("ab"),                                    # too short
    _s("a/" + "b" * 298),                        # 300 chars, the maximum
    _s("a/" + "b" * 299),                        # 301: over the maximum
    struct.pack("<I", 20) + b"a/b",              # length runs past the end
    _s("a\x80/b.png"),                           # not printable
    b"\x2c\x01\x00\x00" + b"/" * 300,            # 300 via the high byte
    b"\x2d\x01\x00\x00" + b"/" * 301,
    b"\x01\x00\x00\x00/" + _s("dir/file.tga"),
    b"\x08\x00\x00\x00" + b"\x08\x00\x00\x00ab/cd.ot",   # nested candidate
    b"\x00\x00\x00\x00" * 5 + _s("x\\y.gen"),
    b"\x07\x00\x00\x00ab\\cdef\x05\x00\x00\x00q/rst",      # back-to-back refs
]


@pytest.mark.parametrize("data", SPLIT_CASES)
def test_split_refs_matches_scan(data):
    assert asset_refs._split_refs(data) == _ref_split_refs(data)
    for i in range(0, len(data), 3):
        chunk = data[i:i + 20]
        assert asset_refs._looks_like_ref(chunk) == _ref_looks_like_ref(chunk)


def test_split_refs_random_bytes():
    rng = random.Random(3)
    pieces = [_s("Materials\\A.mat.ot"), _s("x/y"), b"\x05\x00\x00\x00", b"\x2c\x01\x00\x00",
              b"\x00", b"\xff", _s("n.png"), _s("zzzz")]
    for _ in range(300):
        data = b"".join(
            rng.choice(pieces) if rng.random() < 0.5 else rng.randbytes(rng.randrange(1, 9))
            for _ in range(rng.randrange(0, 30)))
        assert asset_refs._split_refs(data) == _ref_split_refs(data), data.hex()


def test_split_refs_real_files():
    _installed()
    rels = _sample(corpus.rels("", ".Material.gen")
                   + corpus.rels("", ".ScheduledVfxSettings.gen"), 8)
    t0 = time.perf_counter()
    for r in rels:
        raw = corpus.read(r)
        if not raw:
            continue
        concat = b"".join(s.payload for s in cooked.parse(raw).sections)
        assert asset_refs._split_refs(concat) == _ref_split_refs(concat)
    assert time.perf_counter() - t0 < 20


# ---------------------------------------------------------------- BC3 decode


@pytest.mark.parametrize("w,h", [(4, 4), (8, 4), (16, 16), (5, 5), (7, 3), (1, 1), (13, 9),
                                 (64, 32)])
def test_decode_bc3_matches_reference(w, h):
    rng = random.Random(w * 100 + h)
    px = rng.randbytes(((w + 3) // 4) * ((h + 3) // 4) * 16)
    got = icon_decode._decode_bc3(px, w, h)
    assert isinstance(got, bytearray)
    assert got == _ref_decode_bc3(px, w, h)


def test_decode_bc3_endpoint_modes():
    # a0 > a1 and a0 <= a1 alpha modes, c0 <= c1 and c0 > c1 colour modes
    blocks = b""
    modes = [(200, 10, 0x1234, 0xFFFF), (10, 200, 0xFFFF, 0x1234), (5, 5, 7, 7), (0, 255, 0, 0)]
    for a0, a1, c0, c1 in modes:
        blocks += bytes([a0, a1]) + bytes(range(1, 7)) + struct.pack("<HHI", c0, c1, 0x1B1B1B1B)
    assert icon_decode._decode_bc3(blocks, 8, 8) == _ref_decode_bc3(blocks, 8, 8)


def _textures(limit):
    from rsmm.engine.cooked_schemas.texture import TextureHandler
    for r in _sample(corpus.rels("", ".Texture.dxt"), 60, seed=5):
        raw = corpus.read(r)
        if not raw:
            continue
        try:
            sch = TextureHandler.parse_payload(cooked.parse(raw).sections[-1].payload)
        except (ValueError, KeyError, IndexError):
            continue
        if sch.format_name == "BC3" and sch.width * sch.height <= 128 * 128:
            yield r, raw, sch
            limit -= 1
            if limit <= 0:
                return


def test_decode_bc3_real_textures():
    _installed()
    seen = 0
    for _r, _raw, sch in _textures(4):
        assert icon_decode._decode_bc3(sch.pixels, sch.width, sch.height) == \
            _ref_decode_bc3(sch.pixels, sch.width, sch.height)
        seen += 1
    if not seen:
        pytest.skip("no small BC3 textures sampled")


# ------------------------------------------------------------ _tinted_texture


@pytest.mark.parametrize("rgb", [(1.0, 0.0, 1.0), (0.48, 0.82, 1.0), (0.0, 0.0, 0.0),
                                 (1.0, 1.0, 1.0), (122 / 255, 208 / 255, 1.0)])
def test_tint_matches_per_pixel(rgb, monkeypatch):
    from rsmm.engine import prop_cook
    from rsmm.sdk.kinds import heros
    rng = random.Random(11)
    px = bytearray(rng.randbytes(4 * 64 * 64))
    px[:16] = bytes([0, 0, 0, 5, 255, 255, 255, 9, 1, 0, 0, 7, 0, 0, 255, 8])
    seen = {}
    monkeypatch.setattr(icon_decode, "decode_to_rgba", lambda *a: bytearray(px))
    monkeypatch.setattr(icon_decode, "rgba_to_png",
                        lambda rgba, w, h: seen.update(rgba=rgba) or b"")
    monkeypatch.setattr(prop_cook, "cook_texture", lambda png: b"")
    from rsmm.engine.cooked_schemas.texture import TextureHandler
    monkeypatch.setattr(TextureHandler, "parse_payload", staticmethod(
        lambda payload: type("S", (), {"pixels": b"", "width": 64, "height": 64,
                                       "format_name": "RGBA8"})()))
    monkeypatch.setattr(cooked, "parse", lambda raw: type(
        "C", (), {"sections": [type("S", (), {"payload": b""})()]})())
    heros._tinted_texture(b"", rgb)
    assert seen["rgba"] == bytes(_ref_tint(px, rgb))


def test_tinted_texture_real():
    _installed()
    from rsmm.engine import prop_cook as PC
    from rsmm.sdk.kinds import heros
    for _r, raw, sch in _textures(1):
        tint = (0.48, 0.82, 1.0)
        got = heros._tinted_texture(raw, tint)
        px = icon_decode.decode_to_rgba(sch.pixels, sch.width, sch.height, sch.format_name)
        px, w, h = icon_decode.resize_to_max(px, sch.width, sch.height, 512)
        want = PC.cook_texture(icon_decode.rgba_to_png(bytes(_ref_tint(px, tint)), w, h))
        assert got == want
        return
    pytest.skip("no small BC3 textures sampled")
