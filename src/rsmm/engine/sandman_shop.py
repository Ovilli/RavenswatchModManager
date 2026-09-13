"""Read and edit the Sandman shop — the game's in-run vendor.

The shop is data, in two places:

* **What it offers** lives on the Sandman NPC
  (``EntitySettings/Allies/NPC_Sandman/NPC_Sandman.entity.ot``) as seven
  ``oCDtEntityCpntMagicalObjectsDropSettings`` components, one per offer
  generator ("Minor Offer Gen", "Medium Offer Gen Duplicate", …). Each one
  rolls ``count`` magical objects from ``g_MagicalObjectPool``, choosing a
  quality from six weights and keeping only objects whose flags match its
  ``pool`` filter.
* **What each offer costs** lives on the offered item itself, as the int union
  of its ``Powerup Price`` value node
  (``EntitySettings/Objects/Magical_Objects/Powerups/Power_Up_Sandman_*``).

Field meaning comes from the runtime, not from declaration order. Traced
2026-09-13 against the live exe:

* the generator ``0x1402d9280`` loops ``count`` times (clamped to at least 1)
  and calls the quality roll ``0x1402d9d70`` then the pool search
  ``0x140259340`` with the include-flag filter;
* the quality names are the engine's own table at ``0x140ed8b30``:
  Common, Rare, Epic, Legendary, Cursed, PowerUp;
* the price function ``0x1402d4200`` multiplies the item's ``Powerup Price`` by
  the hero's "Reduce all dream shard prices", the hero's "Reduce Sandman dream
  shard prices" (only inside the shop) and the run's "Dream Shard Costs
  Modifier", then rounds.

A generator's unions sit in one fixed order, and :func:`read_offer_gens` checks
all sixteen type codes before trusting any of them. A game patch that moves a
field makes it raise rather than write a number into the wrong slot. Only the
three fields whose meaning the runtime confirms are exposed; the rest (two
enable bools, an exclude filter, two ints, a grant flag list) are left untouched.

Both files are overridden in place (the vanilla paths already exist in
``asset_map.json``), so no registration is involved.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import cooked
from .entity_edit import EntityEdit
from .talent_values import class_names

_BEGIN = b"\x11\x11\xbb\xaa"
_END = b"\x22\x22\xbb\xaa"

NPC_ASSET = "EntitySettings/Allies/NPC_Sandman/NPC_Sandman.entity.ot.EntitySettingsResource.gen"
ITEM_DIR_ASSET = "EntitySettings/Objects/Magical_Objects/Powerups"
ITEM_PREFIX = "Power_Up_Sandman_"
ITEM_SUFFIX = ".entity.ot.EntitySettingsResource.gen"

#: Manifest key -> the generator component's node name on the Sandman NPC.
GENERATORS: dict[str, str] = {
    "minor": "Minor Offer Gen",
    "medium": "Medium Offer Gen",
    "medium_duplicate": "Medium Offer Gen Duplicate",
    "medium_object": "Medium Offer Gen Object",
    "major": "Major Offer Gen",
    "major_duplicate": "Major Offer Gen Duplicate",
    "major_object": "Major Offer Gen Object",
}

#: The fewest items a generator's roll must produce, where the engine needs more
#: than one. The Sandman menu controller's open routine (``0x14036e320``, at
#: ``0x14036eb1a``) picks two DIFFERENT indices from the first generator's rolled
#: list — ``rand(n)`` then ``rand(n - 1)`` — with no guard, so a Minor roll of a
#: single item is ``rand(0)``: an integer divide by zero that takes the game down
#: the moment the shop opens (crash dump 5934cf61, 2026-09-13). Both the count and
#: the pool behind it have to allow two.
MIN_ROLLED: dict[str, int] = {"minor": 2}

#: Weights that roll only the ``powerup`` quality. An object slot that is given
#: an item list needs these: its shipped weights ask for Common/Rare/… objects,
#: and a quality with nothing in the pool rolls nothing.
POWERUP_ONLY = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0)

#: Weight index -> quality, in the engine's own order (table at 0x140ed8b30).
QUALITIES = ("common", "rare", "epic", "legendary", "cursed", "powerup")

_T_F32, _T_INT, _T_BOOL, _T_STR = 0, 1, 2, 5
#: The union type codes of one generator, in file order. Index 0 is the count,
#: 1..6 the quality weights, 9 the include-flag pool filter.
_SHAPE = (_T_INT, _T_F32, _T_F32, _T_F32, _T_F32, _T_F32, _T_F32,
          _T_BOOL, _T_BOOL, _T_STR, _T_BOOL, _T_STR, _T_INT, _T_INT, _T_BOOL, _T_STR)
_COUNT, _WEIGHT0, _POOL = 0, 1, 9

_DROP_CLASS = "oCDtEntityCpntMagicalObjectsDropSettings"
_UNION_CLASS = "oCEntityValueUnion"
#: A generator's node name follows its first child node within this many bytes.
_NAME_WINDOW = 160


@dataclass
class OfferGen:
    key: str
    name: str
    count: int
    weights: tuple[float, ...]
    pool: str
    #: Concat offsets of the value bytes for count, each weight, and the pool
    #: string's u32 length prefix.
    count_off: int
    weight_offs: tuple[int, ...]
    pool_off: int


def _class_index(names: list[str], name: str) -> int:
    try:
        return names.index(name)
    except ValueError:
        raise ValueError(f"{name} is not in this file's class table") from None


def _parse_gen(payload: bytes, base: int, key: str, name: str,
               union_idx: int) -> OfferGen:
    """Decode one generator section. ``base`` is the payload's concat offset."""
    tag = _BEGIN + struct.pack("<I", union_idx)
    unions: list[tuple[int, int]] = []   # (type code, value offset in payload)
    pos = 0
    while True:
        at = payload.find(tag, pos)
        if at < 0:
            break
        unions.append((struct.unpack_from("<I", payload, at + 8)[0], at + 16))
        pos = at + 8
    shape = tuple(t for t, _ in unions)
    if shape != _SHAPE:
        raise ValueError(
            f"Sandman generator {name!r}: union layout {shape} does not match the "
            f"traced {_SHAPE}. The game data changed; re-check before editing.")
    count = struct.unpack_from("<i", payload, unions[_COUNT][1])[0]
    woffs = tuple(off for _, off in unions[_WEIGHT0:_WEIGHT0 + len(QUALITIES)])
    weights = tuple(round(struct.unpack_from("<f", payload, o)[0], 4) for o in woffs)
    poff = unions[_POOL][1]
    plen = struct.unpack_from("<I", payload, poff)[0]
    if poff + 4 + plen > len(payload):
        raise ValueError(f"Sandman generator {name!r}: pool string runs past its section")
    pool = payload[poff + 4:poff + 4 + plen].decode("utf-8")
    return OfferGen(key, name, count, weights, pool, base + unions[_COUNT][1],
                    tuple(base + o for o in woffs), base + poff)


def read_offer_gens(npc_bytes: bytes) -> dict[str, OfferGen]:
    """Decode all seven generators from the Sandman NPC's cooked entity.

    Each generator is one top-level section of the container (a section's
    payload opens with its class index), so every offset this returns lies
    inside a single section and a length-changing edit to it cannot move a
    section boundary. Offsets are in :class:`EntityEdit`'s concat space.
    """
    names = class_names(npc_bytes)
    if names is None:
        raise ValueError("not a parseable cooked entity (no class table)")
    drop_idx = _class_index(names, _DROP_CLASS)
    union_idx = _class_index(names, _UNION_CLASS)

    by_name = {v: k for k, v in GENERATORS.items()}
    found: dict[str, OfferGen] = {}
    base = 0
    for sec in cooked.parse(npc_bytes).sections:
        p = sec.payload
        if len(p) >= 4 and struct.unpack_from("<I", p, 0)[0] == drop_idx:
            window = p[:_NAME_WINDOW]
            for name, key in by_name.items():
                if struct.pack("<I", len(name)) + name.encode() in window:
                    if key in found:
                        raise ValueError(f"Sandman generator {name!r} appears twice")
                    found[key] = _parse_gen(p, base, key, name, union_idx)
                    break
        base += len(p)
    missing = sorted(set(GENERATORS) - set(found))
    if missing:
        raise ValueError(f"Sandman generators not found: {missing}")
    return found


def edit_offer_gens(npc_bytes: bytes, edits: dict[str, dict]) -> bytes:
    """Apply ``{key: {count?, weights?, pool?}}`` to the Sandman NPC.

    ``weights`` is a full 6-tuple in :data:`QUALITIES` order; merging a partial
    table with the vanilla one is the caller's job.
    """
    gens = read_offer_gens(npc_bytes)
    ed = EntityEdit(npc_bytes)
    for key, e in edits.items():
        if key not in gens:
            raise ValueError(f"unknown Sandman generator {key!r}; known: {sorted(GENERATORS)}")
        g = gens[key]
        if "count" in e:
            ed.queue(g.count_off, 4, struct.pack("<i", int(e["count"])))
        if "weights" in e:
            ws = tuple(float(w) for w in e["weights"])
            if len(ws) != len(QUALITIES):
                raise ValueError(f"{g.name}: weights need {len(QUALITIES)} values")
            for off, w in zip(g.weight_offs, ws, strict=True):
                ed.queue(off, 4, struct.pack("<f", w))
        if "pool" in e:
            old = 4 + len(g.pool.encode("utf-8"))
            new = str(e["pool"]).encode("utf-8")
            ed.queue(g.pool_off, old, struct.pack("<I", len(new)) + new)
    return ed.emit()


#: The label of a magical object's own flag list (``[Value] …\\Flags``).
_FLAGS_LABEL = "Flag Value"
#: Prefix of the pool tag a customised generator filters on. One tag per
#: generator, so moving an item into a Sandman row never has to touch the flags
#: other vendors read ("Grimoire; Medium" shares its "Medium" with the Sandman).
ROW_TAG_PREFIX = "RSMM_Shop_"


def row_tag(key: str) -> str:
    if key not in GENERATORS:
        raise ValueError(f"unknown Sandman generator {key!r}")
    return ROW_TAG_PREFIX + key


def split_flags(text: str) -> list[str]:
    """A flag string as the engine reads it (``0x14066b160``): ``,`` counts as
    ``;``, entries are trimmed, empties dropped."""
    return [p.strip() for p in text.replace(",", ";").split(";") if p.strip()]


def pool_matches(pool: str, flags: list[str]) -> bool:
    """Does an item carrying ``flags`` pass a generator's ``pool`` filter?

    ``0x1402d21f0``: the item's list must contain ALL include flags and NONE of
    the ``!``-prefixed exclude flags. Quality and ownership gates are separate.
    """
    have = set(flags)
    wanted = split_flags(pool)
    include = {f for f in wanted if not f.startswith("!")}
    exclude = {f[1:] for f in wanted if f.startswith("!")}
    return include <= have and not (exclude & have)


def _flags_union(item_bytes: bytes) -> tuple[int, str]:
    """Concat offset of the flag string's u32 length prefix, and the string.

    Only an item's OWN flag node is editable; one that inherits its flags has
    no node here and raises.
    """
    names = class_names(item_bytes)
    if names is None:
        raise ValueError("not a parseable cooked entity (no class table)")
    union = _BEGIN + struct.pack("<I", _class_index(names, _UNION_CLASS))
    label = struct.pack("<I", len(_FLAGS_LABEL)) + _FLAGS_LABEL.encode()
    base = 0
    for sec in cooked.parse(item_bytes).sections:
        p = sec.payload
        at = p.find(label)
        if at >= 0:
            u = p.find(union, at)
            if u < 0:
                raise ValueError(f"{_FLAGS_LABEL!r} has no value union in its section")
            if struct.unpack_from("<I", p, u + 8)[0] != _T_STR:
                raise ValueError(f"{_FLAGS_LABEL!r} is not a string union")
            off = u + 16
            ln = struct.unpack_from("<I", p, off)[0]
            if off + 4 + ln > len(p):
                raise ValueError(f"{_FLAGS_LABEL!r} runs past its section")
            return base + off, p[off + 4:off + 4 + ln].decode("utf-8")
        base += len(p)
    raise ValueError(f"this item has no {_FLAGS_LABEL!r} node of its own")


def read_flags(item_bytes: bytes) -> list[str]:
    return split_flags(_flags_union(item_bytes)[1])


def has_own_flags(item_bytes: bytes) -> bool:
    try:
        _flags_union(item_bytes)
    except ValueError:
        return False
    return True


def set_flags(item_bytes: bytes, flags: list[str]) -> bytes:
    """Rewrite an item's own flag list, joined the way the game writes it."""
    off, old = _flags_union(item_bytes)
    new = "; ".join(flags).encode("utf-8")
    ed = EntityEdit(item_bytes)
    ed.queue(off, 4 + len(old.encode("utf-8")), struct.pack("<I", len(new)) + new)
    return ed.emit()


def read_price(item_bytes: bytes) -> int:
    """The ``Powerup Price`` of one shop item."""
    from .talent_values import list_union_values

    unions = list_union_values(item_bytes, "Powerup Price", limit=2)
    if len(unions) != 1 or unions[0][2] != _T_INT:
        raise ValueError(f"expected one int 'Powerup Price' union, found {unions}")
    return int(unions[0][1])


def set_price(item_bytes: bytes, price: int) -> bytes:
    """Rewrite one shop item's ``Powerup Price`` (length-preserving)."""
    from .talent_values import set_union_value

    return set_union_value(item_bytes, "Powerup Price", 0, int(price),
                           expect=read_price(item_bytes))
