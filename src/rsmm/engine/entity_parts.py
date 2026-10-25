"""Write entity components from field values instead of copying them.

Every item builder used to copy its parts (a modifier, a timer, a listener)
out of a shipped item, so a custom item depended on that item staying as it
was. This module writes those parts itself, from the field layouts
``entity_fields`` reads (the order of each class's ``Serialize``), so the only
thing a part depends on is the engine's own serialization.

A value picker, the nested object behind every number, has exactly three
encodings across all 554,529 in the shipped files (survey 2026-10-22):

* ``00`` + value union                          a plain number;
* ``01 00`` + reference + u32 accessor + union  read from another component
  (the union is the fallback);
* ``01 01`` + u32 key + union                   read from a global value.

``decode`` / ``encode`` are exact inverses on every component of the classes in
``ROUNDTRIP`` (``tests/test_entity_parts.py`` checks the whole corpus), which is
what makes a part written here the same thing the game writes.
"""

from __future__ import annotations

import functools
import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from . import cooked
from . import entity_fields as EF
from . import entity_graph as EG

_B, _E = cooked.MARK_BEGIN, cooked.MARK_END
#: Namespace of the GUIDs written parts get (any fixed UUID works).
_NS = uuid.UUID("2b8e6f0a-5d3c-4c1e-9a7f-0e4d3c2b1a99")
PICKER, VALUE_PICKER, UNION = "oCEntityCpntPicker", "oCEntityCpntValuePicker", "oCEntityValueUnion"

#: The classes whose every shipped component this codec round-trips.
ROUNDTRIP = ("oCEntityCpntStateSettings", "oCEntityCpntValueSettings",
             "oCEntityCpntModifierSettings", "oCEntityCpntTimerSettings",
             "oCEntityCpntTesterSettings", "oCEntityCpntNamedEventListenerSettings",
             "oCGameEventListenerEntityCpntSettings", "oCEntityCpntGetValueSettings")

#: Value union type codes (``entity_graph._UNION_TYPES``).
F32, INT, BOOL = 0, 1, 2


class PartError(ValueError):
    pass


@dataclass(frozen=True)
class Link:
    """A reference picker: the target's GUID and its path (empty = none)."""
    guid: bytes = bytes(16)
    path: str = ""

    @property
    def empty(self) -> bool:
        return not self.path and self.guid == bytes(16)


@dataclass(frozen=True)
class Num:
    """A value picker. ``value`` is the union's payload as stored; ``source``
    is a Link (read from that component through ``key``, the accessor) or None;
    ``glob`` marks the ``01 01`` form, where ``key`` names a global value.
    ``unit`` is the union's second u32, how the game's editor shows the number:
    0 plain, 1 an angle ("Angle Max Value"), 2 a ratio (modifier amounts,
    "... Scale Value"); read 2026-10-22 from where each occurs."""
    type: int
    value: bytes
    unit: int = 0
    source: Link | None = None
    key: int | None = None
    glob: bool = False

    @classmethod
    def f32(cls, v: float, unit: int = 0) -> Num:
        return cls(F32, struct.pack("<f", v), unit)

    @classmethod
    def int(cls, v: int) -> Num:
        return cls(INT, struct.pack("<i", v))

    def number(self) -> float:
        if self.type == F32:
            return struct.unpack("<f", self.value)[0]
        if self.type == INT:
            return struct.unpack("<i", self.value)[0]
        if self.type == BOOL:
            return float(self.value[0])
        raise PartError(f"union type {self.type} is not a number")


# --- decoding ----------------------------------------------------------------

def _link(b: bytes, at: int) -> tuple[Link, int]:
    """A picker object at ``at`` (BEGIN cls guid lstr END) -> (Link, end)."""
    guid = b[at + 8:at + 24]
    n = struct.unpack_from("<I", b, at + 24)[0]
    path = b[at + 28:at + 28 + n].decode("latin-1")
    end = at + 28 + n
    if b[end:end + 4] != _E:
        raise PartError("a reference picker is not closed where expected")
    return Link(guid, path), end + 4


def _union(b: bytes, at: int) -> tuple[int, bytes, int, int]:
    """A value union at ``at`` -> (type, value, unit, end)."""
    t, unit = struct.unpack_from("<II", b, at + 8)
    close = b.find(_E, at + 16) if t not in EG._UNION_WIDTH else at + 16 + EG._UNION_WIDTH[t]
    if close < 0 or b[close:close + 4] != _E:
        raise PartError("a value union is not closed where expected")
    return t, b[at + 16:close], unit, close + 4


def _num(b: bytes, at: int) -> Num:
    """A value picker object spanning ``b[at:]`` (from its BEGIN)."""
    i = at + 8
    if b[i] == 0:
        t, v, unit, end = _union(b, i + 1)
        num = Num(t, v, unit)
    elif b[i:i + 2] == b"\x01\x00":
        link, j = _link(b, i + 2)
        key = struct.unpack_from("<I", b, j)[0]
        t, v, unit, end = _union(b, j + 4)
        num = Num(t, v, unit, source=link, key=key)
    elif b[i:i + 2] == b"\x01\x01":
        key = struct.unpack_from("<I", b, i + 2)[0]
        t, v, unit, end = _union(b, i + 6)
        num = Num(t, v, unit, key=key, glob=True)
    else:
        raise PartError(f"unknown value picker form {b[i:i + 2].hex()}")
    if b[end:end + 4] != _E:
        raise PartError("a value picker is not closed where expected")
    return num


def decode(c: EG.Component) -> dict[str, object]:
    """``c``'s body as ``{field: value}`` in serialized order: bool / int /
    float / str for primitives, ``Num`` for values, ``Link`` (and lists of
    them) for references, ``list[int]`` for owned sub-object ids, and the raw
    bytes for any other nested object. Raises when the class schema does not
    tile the body."""
    fs = EF.fields(c)
    if c.cls not in EF.SCHEMAS or not {f.name for f in fs} <= _schema_names(c.cls):
        raise PartError(f"{c.name!r}: no exact field layout for {c.cls}")
    b, out = c.body, {}
    for f in fs:
        raw = b[f.offset:f.offset + f.size]
        if f.kind == "bool":
            out[f.name] = raw[0]
        elif f.kind == "u32":
            out[f.name] = struct.unpack("<I", raw)[0]
        elif f.kind == "f32":
            out[f.name] = struct.unpack("<f", raw)[0]
        elif f.kind == "str":
            out[f.name] = raw[4:].decode("latin-1")
        elif f.kind == "value":
            out[f.name] = _num(b, f.offset)
        elif f.kind == "ref":
            out[f.name] = _link(b, f.offset)[0]
        elif f.kind == "ref[]":
            out[f.name] = [_link(b, e.offset)[0] for e in f.items]
        elif f.kind == "ids":
            n = struct.unpack_from("<I", raw)[0]
            out[f.name] = list(struct.unpack_from(f"<{n}I", raw, 4))
        else:
            out[f.name] = bytes(raw)
    return out


def _schema_names(cls: str) -> set[str]:
    return {e[0] for e in EF.BASE + EF.SCHEMAS[cls]}


# --- encoding ----------------------------------------------------------------

ClassIndex = Callable[[str], int]


def _lstr(s: str) -> bytes:
    b = s.encode("latin-1")
    return struct.pack("<I", len(b)) + b


def link_bytes(link: Link, ci: ClassIndex) -> bytes:
    return _B + struct.pack("<I", ci(PICKER)) + link.guid + _lstr(link.path) + _E


def num_bytes(num: Num, ci: ClassIndex) -> bytes:
    union = _B + struct.pack("<III", ci(UNION), num.type, num.unit) + num.value + _E
    if num.glob:
        head = b"\x01\x01" + struct.pack("<I", num.key)
    elif num.source is not None:
        head = b"\x01\x00" + link_bytes(num.source, ci) + struct.pack("<I", num.key or 0)
    else:
        head = b"\x00"
    return _B + struct.pack("<I", ci(VALUE_PICKER)) + head + union + _E


def encode(cls: str, values: dict[str, object], ci: ClassIndex) -> bytes:
    """The body of a ``cls`` component with these field values (``decode``'s
    shape). A field the class may leave out (a later version's tail, or one a
    flag switches off) is written only when present in ``values``."""
    out = bytearray()
    for entry in EF.BASE + EF.SCHEMAS[cls]:
        name, kind = entry[0], entry[1]
        if name not in values:
            if len(entry) > 2:
                continue
            raise PartError(f"{cls}: no value for {name!r}")
        v = values[name]
        if kind == "bool":
            out += bytes([int(v)])
        elif kind == "u32":
            out += struct.pack("<I", v)
        elif kind == "f32":
            out += struct.pack("<f", v)
        elif kind == "str":
            out += _lstr(v)
        elif kind == "value":
            out += num_bytes(v, ci)
        elif kind == "ref":
            out += link_bytes(v, ci)
        elif kind == "ref[]":
            out += struct.pack("<I", len(v)) + b"".join(link_bytes(x, ci) for x in v)
        elif kind == "ids":
            out += struct.pack(f"<I{len(v)}I", len(v), *v)
        else:
            out += v
    return bytes(out)


def header(cls_index: int, name: str, group: str, guid: bytes, ci: ClassIndex, *,
           override: Link | None = None, flags: int = 0) -> bytes:
    """A component record's head: class, override picker, own GUID, name,
    flags, group (``entity_graph``'s record layout)."""
    return (struct.pack("<I", cls_index) + link_bytes(override or Link(), ci) + guid
            + _lstr(name) + struct.pack("<I", flags) + _lstr(group))


# --- writing parts into an entity ----------------------------------------------

def class_source(name: str) -> cooked.CookedFile:
    """A shipped entity whose class table has ``name``: where a class missing
    from an item's table is copied from (its id, version and parent are the
    engine's, not that entity's)."""
    hit = _class_sources().get(name)
    if hit is None:
        raise PartError(f"no shipped entity uses {name}; its class entry is unknown")
    from . import corpus
    return cooked.parse(corpus.read(hit))


@functools.cache
def _class_sources() -> dict[str, str]:
    from . import corpus
    out: dict[str, str] = {}
    for rel in corpus.rels("EntitySettings/", ".EntitySettingsResource.gen"):
        raw = corpus.read(rel)
        if not raw:
            continue
        for c in cooked.parse(raw).classes:
            out.setdefault(c.name, rel)
    return out


#: The base-class prefix (``entity_fields.BASE``) every written part carries:
#: the values every shipped item part has.
_PREFIX = {"flag_81": 0, "_legacy": 0, "mode": 1, "flag_32": 0}
BASE_PREFIX = b"\x00\x00" + struct.pack("<I", 1) + b"\x00"


class PartWriter:
    """Adds components and sub-objects to an ``EntityFile`` from field values.

    GUIDs are minted from ``seed`` and the part's name, so a link to a part can
    be made before the part exists and a rebuild is byte-identical."""

    def __init__(self, ef, seed: str):
        self.ef, self.seed = ef, seed

    def ci(self, name: str) -> int:
        i = self.ef._class_index(name)
        if i < 0:
            from .entity_components import extend_class_table
            extend_class_table(self.ef.cf, class_source(name), {name})
            i = self.ef._class_index(name)
        return i

    def guid(self, name: str) -> bytes:
        return uuid.uuid5(_NS, f"{self.seed}:{name}").bytes

    def link(self, name: str, cls: str, group: str = "") -> Link:
        """A reference to the part ``name`` of class ``cls`` this writer adds."""
        from .entity_graph_edit import kind_label
        path = f"{group}\\{name}" if group else name
        return Link(self.guid(name), f"[{kind_label(cls)}] {self.ef._scope()}\\{path}")

    def sub(self, cls: str, body: bytes) -> int:
        """Add a sub-object (owned by a component through its id); its id."""
        self.ef.objects.append(bytearray(struct.pack("<I", self.ci(cls)) + body))
        return len(self.ef.objects) - 1

    def add(self, cls: str, name: str, values: dict[str, object] | None = None, *,
            flags: int, group: str = "", override: Link | None = None,
            body: bytes | None = None) -> Link:
        """Add a component; the link to it. ``values`` are its fields (after the
        common prefix); a class with no field layout takes its ``body`` after
        the prefix instead. ``override`` is the ancestor component it overrides."""
        if body is None:
            body = encode(cls, {**_PREFIX, **(values or {})}, self.ci)
        else:
            body = BASE_PREFIX + body
        self.ef.objects.append(bytearray(
            header(self.ci(cls), name, group, self.guid(name), self.ci, flags=flags,
                   override=override) + body))
        from .entity_append import component_vector
        voff, ids = component_vector(bytes(self.ef.trailer))
        ids = [*ids, len(self.ef.objects) - 1]
        self.ef.trailer[voff:voff + 4 * len(ids)] = struct.pack(f"<I{len(ids)}I", len(ids), *ids)
        from .entity_graph_edit import EntityEditError
        try:
            return self.link(name, cls, group)
        except EntityEditError:         # a class nothing references (Dt data)
            return Link(self.guid(name), "")

    # -- nested objects --

    def obj(self, cls: str, body: bytes) -> bytes:
        return _B + struct.pack("<I", self.ci(cls)) + body + _E

    def ids(self, cls: str, ids: list[int]) -> bytes:
        """A collector / combiner list object: ``u32 count, ids``."""
        return self.obj(cls, struct.pack(f"<I{len(ids)}I", len(ids), *ids))

    def flags(self, names: list[str]) -> bytes:
        return self.obj("oCCustomFlagList",
                        struct.pack("<I", len(names)) + b"".join(_lstr(n) for n in names))
