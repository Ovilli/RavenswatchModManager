"""**Map tile pool** — the per-chapter list of tiles mapgen may draw from.

A chapter's playable map is assembled at run start from *tiles* (see
:mod:`rsmm.engine.tile_cook`). Two separate things decide what can appear:

1. The map's tile-generation level (``Map_<Biome>_..._TileGeneration.level.ot``)
   declares the **slots** and, per scenario, which tile *kinds* each slot
   accepts — ``Altar_Of_Heroes``, ``Wishing_Well``, ``Teleporter``, ``Camp``, ….
2. The **mapdef** (``*.mapdef.ot``) carries an explicit list of the concrete
   tiledefs this map is allowed to use at all.

(2) is what this module edits, and it is the whole reason a Dark Hills shrine
does not turn up in Avalon despite both maps accepting the same kind: the kind
vocabulary is shared (43 of 91 kinds appear in more than one biome) but the tile
*pool* is per-map. Add a tile ref to a map's pool and that tile becomes eligible
wherever its kind matches a slot.

That this works cross-biome is not a guess — retail already does it. Dark Hills'
pool contains ``Tiles\\Storm_Island\\6x6_Dark_Hills_Refugee_01.tiledef.ot``, a
tile filed under a different biome's directory.

Layout: the pool is the **last** field of the mapdef body tail —

.. code-block:: text

    …                                        tribes, loading screen, name ref
    u32   tile_count
    tile_count × { lstr category, lstr path }        e.g. "Definitions",
                                                     "Tiles\\Dark_Hills\\6x6_Teleporter_01.tiledef.ot"

Everything before the count is preserved verbatim, so this module never has to
model the tribe/loading-screen fields it does not touch. The count is located by
scanning for the only offset whose ``u32`` is followed by exactly that many
well-formed string pairs ending at end-of-tail — an unambiguous anchor that
fails closed rather than guessing an offset that drifts with a game patch.

Shipped pools: Dark Hills 77, Avalon 96, Storm Island 64. Baba Yaga is the
scripted boss arena and has no pool at all (it is not tile-generated), so
:func:`read_pool` returns ``None`` for it.
"""

from __future__ import annotations

import struct

from . import cooked
from .cooked_schemas import definitions as _defs

CLASS = "oCDtMapDefinition"
GEN_SUFFIX = ".mapdef.ot.DtMapDefinition.gen"

#: Resource category every tile ref in a shipped pool uses.
TILE_CATEGORY = "Definitions"

#: Upper bounds used to reject implausible parses. Generous versus the shipped
#: maxima (96 tiles, 83-char paths) but tight enough that random binary data
#: cannot satisfy the "consumes exactly to end-of-tail" anchor by chance.
_MAX_TILES = 4096
_MAX_STR = 300


class MapPoolError(ValueError):
    pass


def _try_pool_at(tail: bytes, pos: int) -> list[list[str]] | None:
    """Parse a tile vector at ``pos``; return it only if it ends exactly at EOF."""
    count = struct.unpack_from("<I", tail, pos)[0]
    if not 0 < count <= _MAX_TILES:
        return None
    i = pos + 4
    refs: list[list[str]] = []
    for _ in range(count):
        pair = []
        for _ in range(2):
            if i + 4 > len(tail):
                return None
            n = struct.unpack_from("<I", tail, i)[0]
            i += 4
            if n > _MAX_STR or i + n > len(tail):
                return None
            raw = tail[i : i + n]
            i += n
            if not all(0x20 <= c < 0x7F for c in raw):
                return None
            pair.append(raw.decode("latin1"))
        refs.append(pair)
    return refs if i == len(tail) else None


def split_pool(tail: bytes) -> tuple[bytes, list[list[str]]] | None:
    """Split a mapdef ``_tail_hex`` blob into ``(head, tile_refs)``.

    Returns ``None`` when the map carries no tile pool (Baba Yaga). Scans from
    the end so the first hit is the outermost — a shorter trailing run of pairs
    could also parse, but only the true count consumes every byte from its own
    offset to EOF *and* is the earliest such offset.
    """
    for pos in range(len(tail) - 4, -1, -1):
        refs = _try_pool_at(tail, pos)
        if refs is not None:
            return tail[:pos], refs
    return None


def join_pool(head: bytes, refs: list[list[str]]) -> bytes:
    out = bytearray(head)
    out += struct.pack("<I", len(refs))
    for pair in refs:
        if len(pair) != 2:
            raise MapPoolError(f"tile ref must be [category, path], got {pair!r}")
        for s in pair:
            raw = s.encode("latin1")
            if len(raw) > _MAX_STR:
                raise MapPoolError(f"tile ref component too long: {s!r}")
            out += struct.pack("<I", len(raw)) + raw
    return bytes(out)


def _body(base_cooked: bytes):
    cf = cooked.parse(base_cooked)
    if not cf.sections:
        raise MapPoolError("mapdef has no sections")
    return cf, _defs._SPECS[CLASS].decode_body(cf.sections[-1].payload)


def read_pool(base_cooked: bytes) -> list[str] | None:
    """Return the map's tile paths (``Tiles\\<Biome>\\<Name>.tiledef.ot``).

    ``None`` means this map is not tile-generated.
    """
    _cf, body = _body(base_cooked)
    split = split_pool(bytes.fromhex(body["_tail_hex"]))
    if split is None:
        return None
    return [path for _cat, path in split[1]]


def set_pool(base_cooked: bytes, paths: list[str]) -> bytes:
    """Re-emit ``base_cooked`` with its tile pool replaced by ``paths``."""
    cf, body = _body(base_cooked)
    split = split_pool(bytes.fromhex(body["_tail_hex"]))
    if split is None:
        raise MapPoolError(
            "this mapdef has no tile pool — it is not a tile-generated map "
            "(Baba Yaga is the scripted boss arena), so there is nothing to add to."
        )
    head, _old = split
    if not paths:
        raise MapPoolError("tile pool must be non-empty")
    body["_tail_hex"] = join_pool(head, [[TILE_CATEGORY, p] for p in paths]).hex()
    cf.sections[-1] = cooked.Section(payload=_defs._SPECS[CLASS].encode_body(body))
    return cooked.emit(cf)


def add_to_pool(base_cooked: bytes, paths: list[str]) -> bytes:
    """Append ``paths`` to the map's tile pool, skipping ones already present.

    Order is preserved and existing entries are never reordered, so the diff
    against vanilla is purely additive.
    """
    current = read_pool(base_cooked)
    if current is None:
        raise MapPoolError(
            "this mapdef has no tile pool — it is not a tile-generated map "
            "(Baba Yaga is the scripted boss arena), so there is nothing to add to."
        )
    merged = list(current)
    have = set(current)
    for p in paths:
        if p not in have:
            merged.append(p)
            have.add(p)
    return set_pool(base_cooked, merged)
