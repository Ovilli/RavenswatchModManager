"""**Tile definition** cook — the POI / structure records mapgen places.

A ``oCDtTileDefinition`` (``*.tiledef.ot``) is one placeable chunk of a
generated map: an enemy camp, a shrine, a teleporter, a blocker, a stairwell.
The ones that carry a minimap icon are what players call **points of interest**;
the ones that don't are structural filler. Both are the same class.

The leaf codec (:mod:`rsmm.engine.cooked_schemas.definitions` ``tiledef.json``)
exposes only ``entity_ref`` — the prefab that actually gets instantiated — and
keeps everything else in ``_tail_hex``. This module types that tail:

.. code-block:: text

    BEGIN
      u32   prelude          always 4
      u32   kind_count
      lstr  kinds[kind_count]        e.g. ["Teleporter"], ["Special", "Leprechaun_Cauldron", ...]
    END
    u32   width                      slot footprint, in tile units (3, 6, 20, 40, 50, 64)
    u32   height
    f32   band_lo                    tier band, low end (see below)
    f32   band_hi                    tier band, high end
    u32   child_count
    child[child_count]               nested BEGIN..END composite-tile blocks
    u8    underground                1 = an off-map ROOM (live +0x2f0; the
                                     generator only gives an underground
                                     constraint a tile with this set). Kept as
                                     ``icon[0]`` for compatibility.
    tresptr icon                     lstr category + lstr path
    bytes rest[40]                   f32 tint[4], u32 x2, f32 pick_weight, u32 x3

Validated by parsing **all 237 shipped tiledefs with zero failures**, and every
one re-emits byte-for-byte (``tests/test_tile_cook.py``).

**Live-object offsets** (in-game, 2026-08-23). The same record exists as a live
``oCDtTileDefinition`` while the game runs, and the engine's own serializer
writes it back out (see ``R.serialize`` / ``Object_SaveToFile``). Confirmed by
mutation, not by reading: setting ``obj+0x2e0`` to a sentinel and saving
produced a cooked file whose decoded ``width`` was that sentinel, one byte
different from the baseline and nothing else touched.

.. code-block:: text

    obj + 0x2e0   u32  width      (the pair is contiguous, as in the file)
    obj + 0x2e4   u32  height

That makes the write path for a tile: mutate the live def, call
``R.serialize.save``, then ``cooked.promote_to_cooked`` for the retail header —
no need for this module to understand the payload it does not decode, because
the engine writes those bytes itself.

The ``kinds`` list is the join key to mapgen: a map's tile-generation level
declares which *kinds* each slot accepts (``Altar_Of_Heroes``, ``Wishing_Well``,
``Camp``, …), and a tile is eligible for a slot when one of its kinds matches.
Which concrete tiles a map may draw from at all is a separate list that lives in
the **mapdef** — see :mod:`rsmm.engine.map_pool`.

Field semantics beyond the layout are only partly mined. ``kinds``, ``width``,
``height`` and ``icon`` are certain (name strings match the map's slot
vocabulary exactly; width/height match the ``NxN_`` filename prefix on every
tile that has one; icon paths resolve to real shipped textures).

``band_lo`` / ``band_hi`` are the two ends of the **tier band**: the range of
placement values the tile may be placed at. Every tier-suffixed family in the
corpus (cauldrons, grimoires, wishing wells, across all three biomes) carries
T1 ``[0, 0.33]``, T2 ``[0.33, 0.67]``, T3 ``[0.67, 1]`` (stored as 0.33 or
0.333, 0.66 or 0.667). Untiered tiles carry the range they may appear in:
``[0, 1]`` for blockers and most others, ``[0.33, 1]`` for thieves' stash
entrances (they only appear with a yellow or red ring). ``band_lo`` was earlier
read on its own as a tier value, and before that as a pick weight; both
readings were of half the pair.

The 40-byte ``rest`` is preserved verbatim. Its first four floats are an RGBA
that co-varies with the ``Editor`` icon category (an editor tint). The float at
offset 24 is :attr:`TileDef.pick_weight`, the relative pick weight among
tiles that answer the same slot: ``1.0`` on every tile except a few families of
variants (thieves' stash rooms Combat / Cursed / Gold 0.5 / 0.4 / 0.1; Dark
Hills Straw / Wood / Stone house 0.33 each).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import cooked
from .cooked_schemas import definitions as _defs

CLASS = "oCDtTileDefinition"
GEN_SUFFIX = ".tiledef.ot.DtTileDefinition.gen"

_BEGIN = bytes.fromhex("1111bbaa")
_END = bytes.fromhex("2222bbaa")

#: Sub-object prelude on the kind block. Constant across all 237 shipped tiles;
#: a different value means the tail is not the shape this module understands.
_KIND_PRELUDE = 4

#: The trailing blob is a fixed 40 bytes on every shipped tile. Enforced so a
#: game patch that grows the record fails loudly instead of silently truncating.
_REST_LEN = 40
#: Where the pick weight sits in ``rest``: after the f32 tint[4] and two u32.
_PICK_WEIGHT_OFF = 24


class TileCookError(ValueError):
    pass


@dataclass
class TileDef:
    """Typed view of a ``oCDtTileDefinition`` body."""

    entity_ref: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    #: Tier band: the range of placement values the tile may be placed at.
    band_lo: float = 0.0
    band_hi: float = 1.0
    #: Nested composite-tile blocks, kept as raw hex. These reference other
    #: tiles by name (corridors attached to a stairwell, etc.); nothing in the
    #: SDK edits them yet, so they round-trip untouched.
    children: list[str] = field(default_factory=list)
    #: ``(resolved, category, path)`` — the minimap icon. An empty category and
    #: path means "no icon", which is how structural tiles are stored.
    icon: tuple[int, str, str] = (0, "", "")
    rest_hex: str = ""
    #: Everything the leaf codec exposes besides ``entity_ref``, kept so a
    #: rebuild reproduces the source document exactly.
    _doc: dict = field(default_factory=dict)

    @property
    def has_icon(self) -> bool:
        return bool(self.icon[2])

    @property
    def pick_weight(self) -> float:
        """Relative pick weight among same-slot variants (``rest`` offset 24)."""
        return struct.unpack_from("<f", bytes.fromhex(self.rest_hex), _PICK_WEIGHT_OFF)[0]

    @pick_weight.setter
    def pick_weight(self, value: float) -> None:
        rest = bytearray(bytes.fromhex(self.rest_hex))
        struct.pack_into("<f", rest, _PICK_WEIGHT_OFF, float(value))
        self.rest_hex = rest.hex()


class _Reader:
    def __init__(self, buf: bytes) -> None:
        self.b = buf
        self.i = 0

    def u8(self) -> int:
        if self.i >= len(self.b):
            raise TileCookError(f"tail truncated reading u8 at {self.i:#x}")
        v = self.b[self.i]
        self.i += 1
        return v

    def u32(self) -> int:
        if self.i + 4 > len(self.b):
            raise TileCookError(f"tail truncated reading u32 at {self.i:#x}")
        v = struct.unpack_from("<I", self.b, self.i)[0]
        self.i += 4
        return v

    def f32(self) -> float:
        if self.i + 4 > len(self.b):
            raise TileCookError(f"tail truncated reading f32 at {self.i:#x}")
        v = struct.unpack_from("<f", self.b, self.i)[0]
        self.i += 4
        return v

    def lstr(self) -> str:
        n = self.u32()
        if self.i + n > len(self.b):
            raise TileCookError(f"tail truncated reading {n}-byte string at {self.i:#x}")
        raw = self.b[self.i : self.i + n]
        self.i += n
        return raw.decode("latin1")

    def mark(self, want: bytes, what: str) -> None:
        got = self.b[self.i : self.i + 4]
        if got != want:
            raise TileCookError(
                f"{what}: expected marker {want.hex()} at {self.i:#x}, got {got.hex()}"
            )
        self.i += 4

    def balanced_block(self) -> bytes:
        """Consume one BEGIN..END block, including nested pairs, and return it raw."""
        start = self.i
        depth = 0
        while True:
            if self.i + 4 > len(self.b):
                raise TileCookError(f"unterminated child block from {start:#x}")
            chunk = self.b[self.i : self.i + 4]
            if chunk == _BEGIN:
                depth += 1
                self.i += 4
            elif chunk == _END:
                depth -= 1
                self.i += 4
                if depth == 0:
                    return self.b[start : self.i]
            else:
                # Blocks contain arbitrary payload; step one byte so a marker
                # that is not 4-byte aligned is still found.
                self.i += 1


def parse_tail(tail: bytes) -> TileDef:
    """Parse a decoded ``_tail_hex`` blob into a :class:`TileDef` (no entity_ref)."""
    r = _Reader(tail)
    r.mark(_BEGIN, "kind block")
    prelude = r.u32()
    if prelude != _KIND_PRELUDE:
        raise TileCookError(
            f"kind block prelude is {prelude}, expected {_KIND_PRELUDE} — "
            "this tiledef tail is not the shape rsmm understands."
        )
    kind_count = r.u32()
    if kind_count > 64:
        raise TileCookError(f"implausible kind count {kind_count}")
    kinds = [r.lstr() for _ in range(kind_count)]
    r.mark(_END, "kind block close")

    td = TileDef(kinds=kinds)
    td.width = r.u32()
    td.height = r.u32()
    td.band_lo = r.f32()
    td.band_hi = r.f32()

    child_count = r.u32()
    if child_count > 64:
        raise TileCookError(f"implausible child count {child_count}")
    td.children = [r.balanced_block().hex() for _ in range(child_count)]

    td.icon = (r.u8(), r.lstr(), r.lstr())

    rest = tail[r.i :]
    if len(rest) != _REST_LEN:
        raise TileCookError(
            f"trailing blob is {len(rest)} bytes, expected {_REST_LEN} — "
            "the tiledef record changed shape (game patch?); refusing to guess."
        )
    td.rest_hex = rest.hex()
    return td


@dataclass
class Constraint:
    """One entry of a tile's ``children``: a TILE CONSTRAINT.

    When the generator places a tile, each constraint asks for ``count`` more
    tiles carrying every flag in ``required`` (and none in ``excluded``),
    placed between ``min_dist`` and ``max_dist`` metres away (``-1`` = no
    limit). This is how an entrance pulls in its underground room: the Ghoul
    den entrance asks for one ``Boss_Ghoul_Underground`` tile, and that tile
    lands in one of the recipe's off-map ``whole_map`` slots. The same record
    makes a Start tile place a ``Story`` tile, a Thieves' stash entrance its
    room and a corpse master its refugee (``rsmm.engine.tilegen``).

    Layout, decoded from all shipped children (every one re-encodes exactly)::

        BEGIN u32 5
          BEGIN u32 6
            BEGIN u32 4  u32 n  lstr required[n]  END
            BEGIN u32 4  u32 m  lstr excluded[m]  END
          END
          u32 count  f32 min_dist  f32 max_dist  u8 flag
        END
    """

    required: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    count: int = 1
    min_dist: float = -1.0
    max_dist: float = -1.0
    #: The cooked class-table indexes the block names (oCLinkedTile,
    #: oCCustomFlagFilter, oCCustomFlagList) — per FILE, not constants: 5/6/4 in
    #: every shipped tile that has constraints, but a tile without any has no
    #: oCLinkedTile/oCCustomFlagFilter rows at all (see :func:`write`).
    ci: tuple[int, int, int] = (5, 6, 4)
    #: 1 = the wanted tile goes UNDERGROUND (an off-map ``whole_map`` slot:
    #: every den, stash room, cave and stair corridor); 0 = it is placed on
    #: the map within the distance band (Start -> Story, pig houses ->
    #: materials, corpse master -> refugee). 27 / 22 across the corpus.
    flag: int = 1


def _lstr_list(r: _Reader) -> tuple[int, list[str]]:
    r.mark(_BEGIN, "flag list")
    ci = r.u32()
    out = [r.lstr() for _ in range(r.u32())]
    r.mark(_END, "flag list close")
    return ci, out


def parse_constraint(block: bytes) -> Constraint:
    """Decode one raw ``children`` block (see :class:`Constraint`)."""
    r = _Reader(block)
    r.mark(_BEGIN, "constraint")
    linked = r.u32()
    r.mark(_BEGIN, "constraint filter")
    filt = r.u32()
    (lci, req), (lci2, exc) = _lstr_list(r), _lstr_list(r)
    if lci != lci2:
        raise TileCookError("constraint flag lists name two different classes")
    r.mark(_END, "constraint filter close")
    c = Constraint(req, exc, r.u32(), r.f32(), r.f32(), ci=(linked, filt, lci))
    c.flag = r.u8()
    r.mark(_END, "constraint close")
    if r.i != len(block):
        raise TileCookError(f"constraint block has {len(block) - r.i} trailing byte(s)")
    return c


def build_constraint(c: Constraint) -> bytes:
    """Inverse of :func:`parse_constraint`."""
    linked, filt, lci = c.ci

    def flags(names: list[str]) -> bytes:
        out = bytearray(_BEGIN) + struct.pack("<II", lci, len(names))
        for n in names:
            raw = n.encode("latin1")
            out += struct.pack("<I", len(raw)) + raw
        return bytes(out + _END)
    return (_BEGIN + struct.pack("<I", linked) + _BEGIN + struct.pack("<I", filt)
            + flags(c.required) + flags(c.excluded) + _END
            + struct.pack("<IffB", c.count, c.min_dist, c.max_dist, c.flag & 0xFF) + _END)


#: The class rows a constraint needs, as every shipped constraint-bearing tile
#: declares them (class id, version major/minor, parent id = oISerializable).
_CONSTRAINT_CLASSES = (
    ("oCLinkedTile", 394456273, 1, 0, 1941868),
    ("oCCustomFlagFilter", 363452863, 1, 0, 1941868),
)


def _with_ci(c: Constraint, ci: tuple[int, int, int]) -> Constraint:
    c.ci = ci
    return c


def build_tail(td: TileDef) -> bytes:
    """Inverse of :func:`parse_tail`."""
    out = bytearray(_BEGIN)
    out += struct.pack("<II", _KIND_PRELUDE, len(td.kinds))
    for k in td.kinds:
        raw = k.encode("latin1")
        out += struct.pack("<I", len(raw)) + raw
    out += _END
    out += struct.pack("<IIff", td.width, td.height, td.band_lo, td.band_hi)
    out += struct.pack("<I", len(td.children))
    for c in td.children:
        out += bytes.fromhex(c)
    resolved, cat, path = td.icon
    out += struct.pack("<B", resolved & 0xFF)
    for s in (cat, path):
        raw = s.encode("latin1")
        out += struct.pack("<I", len(raw)) + raw
    rest = bytes.fromhex(td.rest_hex)
    if len(rest) != _REST_LEN:
        raise TileCookError(f"rest blob must be {_REST_LEN} bytes, got {len(rest)}")
    out += rest
    return bytes(out)


def read(base_cooked: bytes) -> TileDef:
    """Decode a cooked ``*.tiledef.ot`` file into a :class:`TileDef`."""
    import json

    handler = _defs.DefinitionHandler(_defs._SPECS[CLASS])
    doc = json.loads(handler.decode_cooked(base_cooked))
    td = parse_tail(bytes.fromhex(doc["_tail_hex"]))
    td.entity_ref = list(doc.get("entity_ref") or [])
    td._doc = doc
    return td


def write(td: TileDef) -> bytes:
    """Re-emit a :class:`TileDef` as a full cooked ``*.tiledef.ot`` byte string.

    Requires the :class:`TileDef` to have come from :func:`read` — the source
    document carries the container template and the leaf fields this module
    does not model.
    """
    import json

    if not td._doc:
        raise TileCookError("write() needs a TileDef produced by read()")
    doc = dict(td._doc)
    doc["entity_ref"] = list(td.entity_ref)
    if td.children:
        # ⚠ A constraint names its classes by index into THIS file's class
        # table. A tile that ships without constraints has no oCLinkedTile /
        # oCCustomFlagFilter rows, so a constraint written into it pointed at
        # classes the file never declares: the tiledef failed to load and was
        # silently missing from the pool — measured 2026-11-15, every mod tile
        # carrying `needs` was never placed. Declare the classes, then encode
        # every block with the real indexes.
        container = dict(doc["_container"])
        classes = [list(c) for c in container["classes"]]
        names = [c[0] for c in classes]
        for row in _CONSTRAINT_CLASSES:
            if row[0] not in names:
                classes.append(list(row))
                names.append(row[0])
        container["classes"] = classes
        doc["_container"] = container
        ci = (names.index("oCLinkedTile"), names.index("oCCustomFlagFilter"),
              names.index("oCCustomFlagList"))
        td = TileDef(**{**td.__dict__, "children": [
            build_constraint(_with_ci(parse_constraint(bytes.fromhex(ch)), ci)).hex()
            for ch in td.children]})
    doc["_tail_hex"] = build_tail(td).hex()
    handler = _defs.DefinitionHandler(_defs._SPECS[CLASS])
    return handler.encode_container(json.dumps(doc).encode("utf-8"))
