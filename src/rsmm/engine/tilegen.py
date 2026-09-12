"""Read and write a chapter's MAP GENERATION RECIPE.

`map_pool` answers "which tiledefs may this chapter draw from"; this answers
everything else about how a map is built — where the tiles may physically go,
how many of each kind, how far apart, and which kinds fit which footprint.

The recipe is not in the mapdef. It is a LEVEL, one per chapter, named
``Map_<Biome>_..._TileGeneration.level.ot``, and it is an ordinary object graph
of the shape `level_placements` already walks. Five classes carry it:

======================================  ===========================================
`oCDtEntityCpntTileSpawnerSettings`     the header: kinds, scenarios, footprint
                                        groups, the mapdef backref, flag quotas
`oCDtTileKind`                          one kind: how many to place, how far
                                        apart, which footprints it may take
`oCDtTileSlotSize`                      one footprint family (3x3, 6x6, …) and
                                        the slots belonging to it
`oCDtTileSlotSettings`                  ONE PHYSICAL SLOT: a world position, a
                                        per-kind allow mask, a per-scenario table
`oCDtTileSlotScenarioKindCompatibility` one row of that table
======================================  ===========================================

Dark Hills is 143 slots, 14 kinds, 4 footprint groups and 4 scenarios; Avalon
is 147 / 16 / 6 / 1. Every dimension cross-checks, which is what makes the
grammar safe to write back:

* a slot's kind mask is exactly ``len(kinds)`` bytes;
* a slot's compatibility table is exactly ``len(scenarios)`` rows of
  ``len(kinds)`` entries;
* a kind's `footprints` mask is exactly ``len(slot_sizes)`` bytes;
* every slot is listed by exactly one footprint group.

`validate()` asserts all four, so a game patch that reshapes any of them fails
loudly rather than writing a recipe the engine will read as something else.

**Where the layout came from.** Not from the bytes: from each class's
`Serialize` at vftable slot 3, read off the live exe, with the field widths
taken from the loader vftable (``+0x60`` lstr, ``+0x68``/``+0x70`` u8,
``+0x78``/``+0x90``/``+0x98`` 4-byte, ``+0xa0`` a nested object). Optional
fields are version-gated on the class version in the file's own class table,
and the gate direction matters: ``jb`` reads the field when the version is high
enough, ``ja`` skips a block that only OLD files carry. Reading `ja` as `jb`
invents fields that are not in the stream.

Proof: all 494 tilegen objects across the three shipped TileGeneration levels
decode and re-encode byte-identically (`tests/test_tilegen.py`).

⚠ The values are recovered; some MEANINGS are not. `Slot.tail`, `TileKind.rule`
and `SpawnerSettings.tail` round-trip verbatim and are named for what they are,
not for what they do.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import cooked
from .level_placements import LevelPlacementError, _graph, _inner

#: Classes this module understands. Anything else in a TileGeneration level is
#: left byte-exact — the walk edits objects, it does not rewrite the file.
KIND_CLASS = "oCDtTileKind"
SLOT_CLASS = "oCDtTileSlotSettings"
SIZE_CLASS = "oCDtTileSlotSize"
COMPAT_CLASS = "oCDtTileSlotScenarioKindCompatibility"
SPAWNER_CLASS = "oCDtEntityCpntTileSpawnerSettings"

#: `oCEntityCpntPicker`, inline ahead of the spawner's own fields. Opaque and
#: fixed-width in all three shipped levels; preserved, never authored.
_PICKER_LEN = 20
#: The spawner's GUID plus the flag run between its name and its kind vector.
_GUID_LEN = 16
_SPAWNER_FLAG_LEN = 15
#: `+0x130`..`+0x14c`: eight 4-byte scalars, two of them floats. Unmined.
_SPAWNER_TAIL = 8


class TileGenError(LevelPlacementError):
    """The level is not a tile-generation recipe this walk can read."""


# --------------------------------------------------------------------------
# Stream cursor
# --------------------------------------------------------------------------

class _R:
    """A read cursor that refuses to run off the end."""

    def __init__(self, b: bytes):
        self.b, self.o = b, 0

    def _need(self, n: int) -> None:
        if self.o + n > len(self.b):
            raise TileGenError(
                f"payload ends mid-field: wanted {n} bytes at {self.o} of {len(self.b)}")

    def u32(self) -> int:
        self._need(4)
        (v,) = struct.unpack_from("<I", self.b, self.o)
        self.o += 4
        return v

    def f32(self) -> float:
        self._need(4)
        (v,) = struct.unpack_from("<f", self.b, self.o)
        self.o += 4
        return v

    def raw(self, n: int) -> bytes:
        self._need(n)
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def lstr(self) -> str:
        n = self.u32()
        if n > len(self.b):
            raise TileGenError(f"string length {n} exceeds the payload")
        return self.raw(n).decode("latin1")

    def begin(self) -> None:
        if self.raw(4) != cooked.MARK_BEGIN:
            raise TileGenError(f"expected MARK_BEGIN at {self.o - 4}")

    def end(self) -> None:
        if self.raw(4) != cooked.MARK_END:
            raise TileGenError(f"expected MARK_END at {self.o - 4}")

    def done(self) -> None:
        if self.o != len(self.b):
            raise TileGenError(
                f"{len(self.b) - self.o} bytes left over; the layout is not what "
                f"this walk understands and a partial read must not be written back")


class _W:
    """The mirror of `_R`. Every reader has one, or the class is read-only."""

    def __init__(self) -> None:
        self.p = bytearray()

    def u32(self, v: int) -> None:
        self.p += struct.pack("<I", v)

    def f32(self, v: float) -> None:
        self.p += struct.pack("<f", v)

    def raw(self, b: bytes) -> None:
        self.p += b

    def lstr(self, t: str) -> None:
        b = t.encode("latin1")
        self.u32(len(b))
        self.raw(b)

    def begin(self) -> None:
        self.p += cooked.MARK_BEGIN

    def end(self) -> None:
        self.p += cooked.MARK_END


# --------------------------------------------------------------------------
# Shared leaf types
# --------------------------------------------------------------------------

@dataclass
class FlagFilter:
    """`oCCustomFlagFilter`: a required list and an excluded list of flags.

    This is how a kind and a footprint family carry their NAME. "Teleporter" is
    not a string field on `oCDtTileKind`; it is the single required flag of the
    kind's filter, which is also what `oCDtTileFlagConstraint` matches against.
    """

    required: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    _ci: int = 0
    _req_ci: int = 0
    _exc_ci: int = 0

    @property
    def name(self) -> str:
        """The one required flag, which is what every caller actually wants."""
        return self.required[0] if self.required else ""


def _rd_flaglist(r: _R) -> tuple[int, list[str]]:
    r.begin()
    ci = r.u32()
    out = [r.lstr() for _ in range(r.u32())]
    r.end()
    return ci, out


def _wr_flaglist(w: _W, ci: int, items: list[str]) -> None:
    w.begin()
    w.u32(ci)
    w.u32(len(items))
    for t in items:
        w.lstr(t)
    w.end()


def _rd_filter(r: _R) -> FlagFilter:
    r.begin()
    ci = r.u32()
    req_ci, req = _rd_flaglist(r)
    exc_ci, exc = _rd_flaglist(r)
    r.end()
    return FlagFilter(required=req, excluded=exc, _ci=ci, _req_ci=req_ci, _exc_ci=exc_ci)


def _wr_filter(w: _W, f: FlagFilter) -> None:
    w.begin()
    w.u32(f._ci)
    _wr_flaglist(w, f._req_ci, f.required)
    _wr_flaglist(w, f._exc_ci, f.excluded)
    w.end()


# --------------------------------------------------------------------------
# The five recipe classes
# --------------------------------------------------------------------------

@dataclass
class TileKind:
    """One kind of thing the generator places, and its quota.

    `count` is how many the generator tries to place and `min_distance` is how
    far apart in metres — the two numbers a modder actually wants. `footprints`
    is one byte per entry of `TileGen.slot_sizes`, in order, and it fits every
    shipped kind: Start and Map_Boss take only the 40x40 and 64x64 groups,
    Crystal only the two small ones, Teleporter only 6x6.
    """

    filter: FlagFilter
    count: int
    min_distance: float
    footprints: list[int]
    rule: int                     # +0x10. 0 on 10 of 14; Key/Key_Keeper share 2.
    _ci: int = 0

    @property
    def name(self) -> str:
        return self.filter.name


def _rd_kind(p: bytes) -> TileKind:
    r = _R(p)
    ci = r.u32()
    filt = _rd_filter(r)
    count = r.u32()
    fp = list(r.raw(r.u32()))
    dist = r.f32()
    rule = r.u32()
    r.done()
    return TileKind(filter=filt, count=count, min_distance=dist,
                    footprints=fp, rule=rule, _ci=ci)


def _wr_kind(k: TileKind) -> bytes:
    w = _W()
    w.u32(k._ci)
    _wr_filter(w, k.filter)
    w.u32(k.count)
    w.u32(len(k.footprints))
    w.raw(bytes(k.footprints))
    w.f32(k.min_distance)
    w.u32(k.rule)
    return bytes(w.p)


@dataclass
class Slot:
    """One physical place a tile can stand, in world coordinates.

    `kinds` is one byte per `TileGen.kinds`, in order: the slot's own vocabulary.
    `compat` is one row per `TileGen.scenarios`, each one entry per kind, and it
    is TRI-STATE — 2 almost everywhere, with a few 0s and 1s — so it is not a
    boolean and must not be rewritten as one.

    A slot with an empty `kinds` mask is a member of the inline 128x128 group
    (`SpawnerSettings.whole_map`), which is 5 slots in Dark Hills and Storm
    Island and 12 in Avalon. Empty is correct for those, not missing data.
    """

    pos: tuple[float, float, float]
    kinds: list[int] = field(default_factory=list)
    compat: list[list[int]] = field(default_factory=list)
    tail: int = 0                 # +0x1c, version 3. Unmined.
    _ci: int = 0
    _compat_ci: int = 0


def _rd_slot(p: bytes) -> Slot:
    r = _R(p)
    ci = r.u32()
    pos = (r.f32(), r.f32(), r.f32())
    mask = list(r.raw(r.u32()))
    rows: list[list[int]] = []
    compat_ci = 0
    for _ in range(r.u32()):
        r.begin()
        compat_ci = r.u32()
        rows.append([r.u32() for _ in range(r.u32())])
        r.end()
    tail = r.u32()
    r.done()
    return Slot(pos=pos, kinds=mask, compat=rows, tail=tail,
                _ci=ci, _compat_ci=compat_ci)


def _wr_slot(s: Slot) -> bytes:
    w = _W()
    w.u32(s._ci)
    for v in s.pos:
        w.f32(v)
    w.u32(len(s.kinds))
    w.raw(bytes(s.kinds))
    w.u32(len(s.compat))
    for row in s.compat:
        w.begin()
        w.u32(s._compat_ci)
        w.u32(len(row))
        for v in row:
            w.u32(v)
        w.end()
    w.u32(s.tail)
    return bytes(w.p)


@dataclass
class SlotSize:
    """A footprint family, and the object ids of the slots that belong to it.

    `slots` are ids into the level's object table, i.e. positions in the stream
    — the same numbering `level_placements` documents. Every slot in a shipped
    level is listed by exactly one group.
    """

    width: int
    height: int
    filter: FlagFilter
    slots: list[int]
    _ci: int = 0

    @property
    def name(self) -> str:
        return self.filter.name


def _rd_size_body(r: _R) -> SlotSize:
    ci = r.u32()
    wd, ht = r.u32(), r.u32()
    filt = _rd_filter(r)
    ids = [r.u32() for _ in range(r.u32())]
    return SlotSize(width=wd, height=ht, filter=filt, slots=ids, _ci=ci)


def _wr_size_body(w: _W, s: SlotSize) -> None:
    w.u32(s._ci)
    w.u32(s.width)
    w.u32(s.height)
    _wr_filter(w, s.filter)
    w.u32(len(s.slots))
    for i in s.slots:
        w.u32(i)


def _rd_size(p: bytes) -> SlotSize:
    r = _R(p)
    s = _rd_size_body(r)
    r.done()
    return s


def _wr_size(s: SlotSize) -> bytes:
    w = _W()
    _wr_size_body(w, s)
    return bytes(w.p)


@dataclass
class Scenario:
    """One column set of the per-slot compatibility table.

    Shipped names are `Scenario 01`..`04` with labels `Enemy Camp Difficulty
    01`..`04`, so a scenario is a difficulty variant of the same physical map.
    Avalon ships ONE; Dark Hills and Storm Island ship four.
    """

    id: str
    label: str
    _ci: int = 0


@dataclass
class FlagQuota:
    """`oCDtTileFlagConstraint`: at most `limit` tiles carrying these flags.

    A second, independent cap alongside `TileKind.count` — Dark Hills allows one
    `Wishing_Well` and two `Boss` no matter how the kind quotas fall out.
    """

    flags: list[str]
    limit: int
    _ci: int = 0
    _list_ci: int = 0


@dataclass
class SpawnerSettings:
    """The recipe header. Everything that is not a slot or a kind body."""

    kind_ids: list[int]
    scenarios: list[Scenario]
    size_ids: list[int]
    whole_map: SlotSize           # +0x190, inline: the 128x128 group
    mapdef: tuple[str, str]       # +0x0f8 resref, e.g. ("Definitions", "Maps\\...")
    quotas: list[FlagQuota]
    tail: tuple[int, ...]         # +0x130..+0x14c. Unmined.
    _ci: int = 0
    _picker_ci: int = 0
    _picker: bytes = b""
    _guid: bytes = b""
    _name: str = ""
    _flags: bytes = b""


def _rd_spawner(p: bytes) -> SpawnerSettings:
    r = _R(p)
    ci = r.u32()
    r.begin()
    picker_ci = r.u32()
    picker = r.raw(_PICKER_LEN)
    r.end()
    guid = r.raw(_GUID_LEN)
    name = r.lstr()
    flags = r.raw(_SPAWNER_FLAG_LEN)
    kind_ids = [r.u32() for _ in range(r.u32())]
    scen: list[Scenario] = []
    for _ in range(r.u32()):
        r.begin()
        sci = r.u32()
        scen.append(Scenario(id=r.lstr(), label=r.lstr(), _ci=sci))
        r.end()
    size_ids = [r.u32() for _ in range(r.u32())]
    r.begin()
    whole = _rd_size_body(r)
    r.end()
    mapdef = (r.lstr(), r.lstr())
    quotas: list[FlagQuota] = []
    for _ in range(r.u32()):
        r.begin()
        qci = r.u32()
        lci, fl = _rd_flaglist(r)
        quotas.append(FlagQuota(flags=fl, limit=r.u32(), _ci=qci, _list_ci=lci))
        r.end()
    tail = tuple(r.u32() for _ in range(_SPAWNER_TAIL))
    r.done()
    return SpawnerSettings(
        kind_ids=kind_ids, scenarios=scen, size_ids=size_ids, whole_map=whole,
        mapdef=mapdef, quotas=quotas, tail=tail, _ci=ci, _picker_ci=picker_ci,
        _picker=picker, _guid=guid, _name=name, _flags=flags)


def _wr_spawner(s: SpawnerSettings) -> bytes:
    w = _W()
    w.u32(s._ci)
    w.begin()
    w.u32(s._picker_ci)
    w.raw(s._picker)
    w.end()
    w.raw(s._guid)
    w.lstr(s._name)
    w.raw(s._flags)
    w.u32(len(s.kind_ids))
    for i in s.kind_ids:
        w.u32(i)
    w.u32(len(s.scenarios))
    for sc in s.scenarios:
        w.begin()
        w.u32(sc._ci)
        w.lstr(sc.id)
        w.lstr(sc.label)
        w.end()
    w.u32(len(s.size_ids))
    for i in s.size_ids:
        w.u32(i)
    w.begin()
    _wr_size_body(w, s.whole_map)
    w.end()
    w.lstr(s.mapdef[0])
    w.lstr(s.mapdef[1])
    w.u32(len(s.quotas))
    for q in s.quotas:
        w.begin()
        w.u32(q._ci)
        _wr_flaglist(w, q._list_ci, q.flags)
        w.u32(q.limit)
        w.end()
    w.raw(struct.pack(f"<{_SPAWNER_TAIL}I", *s.tail))
    return bytes(w.p)


# --------------------------------------------------------------------------
# The whole recipe
# --------------------------------------------------------------------------

@dataclass
class TileGen:
    """One chapter's generation recipe, keyed by object id throughout."""

    spawner: SpawnerSettings
    kinds: dict[int, TileKind]
    sizes: dict[int, SlotSize]
    slots: dict[int, Slot]

    @property
    def kind_names(self) -> list[str]:
        """Kind names in the order every per-kind mask is indexed by."""
        return [self.kinds[i].name for i in self.spawner.kind_ids]

    @property
    def size_names(self) -> list[str]:
        """Footprint groups in the order `TileKind.footprints` is indexed by."""
        return [f"{self.sizes[i].width}x{self.sizes[i].height}"
                for i in self.spawner.size_ids]

    def slots_for(self, kind: str) -> list[int]:
        """Object ids of every slot whose own mask admits `kind`.

        The mask is only the first of the gates — the kind's `footprints` and
        the per-scenario table narrow it further — so this is "where could it
        possibly go", not "where will it go".
        """
        order = self.kind_names
        if kind not in order:
            raise TileGenError(f"no kind named {kind!r}; have {order}")
        k = order.index(kind)
        return [i for i, s in self.slots.items() if len(s.kinds) > k and s.kinds[k]]


def _class_names(g) -> list[str]:
    """The level's class table, in index order."""
    ct = g.blocks[g.ot - 1][2]
    (n,) = struct.unpack_from("<I", ct, 0)
    o, out = 4, []
    for _ in range(n):
        (ln,) = struct.unpack_from("<I", ct, o)
        o += 4
        out.append(ct[o:o + ln].decode("latin1"))
        o += ln + 16
    return out


def read(level_bytes: bytes) -> TileGen:
    """Decode a `*_TileGeneration.level.ot` into its recipe, or raise."""
    _cf, _sec, inner = _inner(level_bytes)
    g = _graph(inner)
    names = _class_names(g)
    spawner = None
    kinds: dict[int, TileKind] = {}
    sizes: dict[int, SlotSize] = {}
    slots: dict[int, Slot] = {}
    for i, (_b, _e, p) in enumerate(g.objects):
        nm = names[g.class_idx[i]]
        if nm == SPAWNER_CLASS:
            if spawner is not None:
                raise TileGenError("level carries two tile spawners")
            spawner = _rd_spawner(p)
        elif nm == KIND_CLASS:
            kinds[i] = _rd_kind(p)
        elif nm == SIZE_CLASS:
            sizes[i] = _rd_size(p)
        elif nm == SLOT_CLASS:
            slots[i] = _rd_slot(p)
    if spawner is None:
        raise TileGenError("not a tile-generation level: no spawner settings")
    tg = TileGen(spawner=spawner, kinds=kinds, sizes=sizes, slots=slots)
    validate(tg)
    return tg


def validate(tg: TileGen) -> None:
    """Assert every cross-dimension the engine relies on, or raise.

    These are not style checks. A kind mask one byte short of the kind count is
    read by the engine as a different kind's permission, silently.
    """
    nk, ns = len(tg.spawner.kind_ids), len(tg.spawner.scenarios)
    for i in tg.spawner.kind_ids:
        if i not in tg.kinds:
            raise TileGenError(f"kind id {i} is not a kind object")
    for i in tg.spawner.size_ids:
        if i not in tg.sizes:
            raise TileGenError(f"slot-size id {i} is not a slot-size object")
    for k in tg.kinds.values():
        if len(k.footprints) != len(tg.spawner.size_ids):
            raise TileGenError(
                f"kind {k.name!r} carries {len(k.footprints)} footprint bytes "
                f"for {len(tg.spawner.size_ids)} groups")
    listed: set[int] = set(tg.spawner.whole_map.slots)
    for i in tg.spawner.size_ids:
        listed |= set(tg.sizes[i].slots)
    if listed != set(tg.slots):
        raise TileGenError(
            f"{len(set(tg.slots) - listed)} slots belong to no footprint group "
            f"and {len(listed - set(tg.slots))} listed ids are not slots")
    empty = {i for i, s in tg.slots.items() if not s.kinds}
    if empty != set(tg.spawner.whole_map.slots):
        raise TileGenError(
            "the slots with an empty kind mask are not exactly the inline "
            "whole-map group; the recipe's shape is not what this walk expects")
    for i, s in tg.slots.items():
        if s.kinds and len(s.kinds) != nk:
            raise TileGenError(
                f"slot {i} masks {len(s.kinds)} kinds against {nk} declared")
        if s.kinds and len(s.compat) != ns:
            raise TileGenError(
                f"slot {i} carries {len(s.compat)} scenario rows against {ns}")
        for row in s.compat:
            if len(row) != nk:
                raise TileGenError(
                    f"slot {i} compatibility row is {len(row)} wide, not {nk}")


def write(level_bytes: bytes, tg: TileGen) -> bytes:
    """Re-emit `level_bytes` with `tg`'s objects replaced in place.

    Object COUNT is unchanged, so no id moves and no vector needs growing —
    the trap `level_placements.add_placement` documents does not arise here.
    Adding a slot is a different operation and is deliberately not this one.
    """
    validate(tg)
    cf, sec, inner = _inner(level_bytes)
    g = _graph(inner)
    names = _class_names(g)
    out = bytearray(inner[:g.blocks[g.ot][0]])
    out += inner[g.blocks[g.ot][0]:g.blocks[g.ot][1]]     # the object table, verbatim
    for i, (_b, _e, p) in enumerate(g.objects):
        nm = names[g.class_idx[i]]
        if nm == SPAWNER_CLASS:
            body = _wr_spawner(tg.spawner)
        elif nm == KIND_CLASS:
            body = _wr_kind(tg.kinds[i])
        elif nm == SIZE_CLASS:
            body = _wr_size(tg.sizes[i])
        elif nm == SLOT_CLASS:
            body = _wr_slot(tg.slots[i])
        else:
            body = p
        out += cooked.MARK_BEGIN + body + cooked.MARK_END
    out += inner[g.root[0]:]
    new_sec = bytearray(sec[:16]) + bytes(out)
    struct.pack_into("<II", new_sec, 8, len(out), len(out))
    cf.sections[-1] = cooked.Section(payload=bytes(new_sec))
    return cooked.emit(cf)
