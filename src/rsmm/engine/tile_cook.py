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
    f32   weight                     TIER, not a spawn rate (see below)
    f32   ratio                      second weight-ish scalar (1.0 on 204/237)
    u32   child_count
    child[child_count]               nested BEGIN..END composite-tile blocks
    tresptr icon                     u8 resolved + lstr category + lstr path
    bytes rest[40]                   editor tint RGBA + 6 unmined scalars

Validated by parsing **all 237 shipped tiledefs with zero failures**, and every
one re-emits byte-for-byte (``tests/test_tile_cook.py``).

The ``kinds`` list is the join key to mapgen: a map's tile-generation level
declares which *kinds* each slot accepts (``Altar_Of_Heroes``, ``Wishing_Well``,
``Camp``, …), and a tile is eligible for a slot when one of its kinds matches.
Which concrete tiles a map may draw from at all is a separate list that lives in
the **mapdef** — see :mod:`rsmm.engine.map_pool`.

Field semantics beyond the layout are only partly mined. ``kinds``, ``width``,
``height`` and ``icon`` are certain (name strings match the map's slot
vocabulary exactly; width/height match the ``NxN_`` filename prefix on every
tile that has one; icon paths resolve to real shipped textures). ``weight`` is a **tier**
field, not a spawn rate: every tier-suffixed family in the corpus — cauldrons,
grimoires and wishing wells, across all three biomes — carries exactly
T1=0.0 / T2=0.333 / T3=0.667 with no exceptions, and T1 tiles plainly do appear
in game. An earlier reading of it as "mapgen pick weight, 0 = never rolled" was
wrong; how often a tile turns up is governed by how many pool entries share its
kind. The 40-byte ``rest`` is preserved verbatim; its first four floats are an
RGBA that co-varies with the ``Editor`` icon category, so it reads as an editor
tint rather than anything gameplay-facing.
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


class TileCookError(ValueError):
    pass


@dataclass
class TileDef:
    """Typed view of a ``oCDtTileDefinition`` body."""

    entity_ref: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    weight: float = 0.0
    ratio: float = 1.0
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
    td.weight = r.f32()
    td.ratio = r.f32()

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


def build_tail(td: TileDef) -> bytes:
    """Inverse of :func:`parse_tail`."""
    out = bytearray(_BEGIN)
    out += struct.pack("<II", _KIND_PRELUDE, len(td.kinds))
    for k in td.kinds:
        raw = k.encode("latin1")
        out += struct.pack("<I", len(raw)) + raw
    out += _END
    out += struct.pack("<IIff", td.width, td.height, td.weight, td.ratio)
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
    doc["_tail_hex"] = build_tail(td).hex()
    handler = _defs.DefinitionHandler(_defs._SPECS[CLASS])
    return handler.encode_container(json.dumps(doc).encode("utf-8"))
