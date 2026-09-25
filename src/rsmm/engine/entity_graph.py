"""An entity-settings file as a graph of components and the links between them.

This is the reader the ability editor is built on. Layout of one component
record (a section of an ``oCEntitySettingsResource``, RE 2026-09-25)::

    u32 class index
    BEGIN oCEntityCpntPicker { 16-byte GUID, lstr path } END   <- override target
    16-byte own GUID
    lstr name     u32 flags     lstr group
    class-specific body

A *picker* (``oCEntityCpntPicker``) is how a component points at another one:
the TARGET's own GUID plus its path ``[Kind] Scope\\Group\\Name`` (an empty
picker is 16 zero bytes and an empty string). The first picker is the
override target: empty for an ordinary component, set when the record
overrides a component of an ancestor entity (skins, inheritance). Every other
picker in the body is an outgoing edge. The engine binds by GUID; the path is
what a human (and a renamed clone) reads.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from . import cooked
from . import entity_strings as ES

_BEGIN = cooked.MARK_BEGIN
_END = cooked.MARK_END
_PATH = re.compile(r"^\[(?P<kind>[^\]]+)\] (?P<scope>[^\\]+)\\(?P<rest>.+)$")


@dataclass
class Ref:
    guid: bytes
    path: str

    @property
    def kind(self) -> str:
        m = _PATH.match(self.path)
        return m["kind"] if m else ""

    @property
    def scope(self) -> str:
        m = _PATH.match(self.path)
        return m["scope"] if m else ""


@dataclass
class Component:
    index: int                  # section index in the file
    cls: str
    name: str
    group: str
    guid: bytes
    override: Ref | None        # set when this record overrides an ancestor's component
    refs: list[Ref] = field(default_factory=list)
    literals: list[str] = field(default_factory=list)   # other strings: events, resources
    body: bytes = b""           # class-specific bytes after the group name
    classes: list[str] = field(default_factory=list, repr=False)

    @property
    def path(self) -> str:
        return f"{self.group}\\{self.name}"


@dataclass
class EntityGraph:
    name: str                   # the entity's scope name, e.g. Hero_Piper
    components: list[Component]

    def by_guid(self) -> dict[bytes, Component]:
        return {c.guid: c for c in self.components}

    def groups(self) -> dict[str, list[Component]]:
        out: dict[str, list[Component]] = {}
        for c in self.components:
            out.setdefault(c.group, []).append(c)
        return out

    def closure(self, seeds: list[Component]) -> list[Component]:
        """Every component in this entity reachable from ``seeds`` by refs."""
        index = self.by_guid()
        seen = {c.guid for c in seeds}
        todo = list(seeds)
        while todo:
            for r in todo.pop().refs:
                t = index.get(r.guid)
                if t is not None and t.guid not in seen:
                    seen.add(t.guid)
                    todo.append(t)
        return [c for c in self.components if c.guid in seen]


def _pickers(payload: bytes, picker_cls: int) -> list[tuple[int, Ref]]:
    """``(offset, Ref)`` for every picker in ``payload``, in order."""
    tag = _BEGIN + struct.pack("<I", picker_cls)
    out: list[tuple[int, Ref]] = []
    i = payload.find(tag)
    while i >= 0:
        body = i + len(tag)
        guid = payload[body:body + 16]
        if len(guid) == 16 and body + 20 <= len(payload):
            n = struct.unpack_from("<I", payload, body + 16)[0]
            text = payload[body + 20:body + 20 + n]
            if n < 4096 and len(text) == n and all(0x20 <= b < 0x7F for b in text):
                out.append((i, Ref(guid, text.decode("ascii"))))
        i = payload.find(tag, i + 1)
    return out


def parse(raw: bytes, name: str = "") -> EntityGraph:
    """Components of a cooked entity-settings file, with their edges."""
    cf = cooked.parse(raw)
    classes = [c.name for c in cf.classes]
    picker_cls = classes.index("oCEntityCpntPicker") if "oCEntityCpntPicker" in classes else -1
    comps: list[Component] = []
    for si, sec in enumerate(cf.sections[1:-1], 1):
        p = sec.payload
        if len(p) < 4 or picker_cls < 0:
            continue
        ci = struct.unpack_from("<I", p, 0)[0]
        if ci >= len(classes):
            continue
        pickers = _pickers(p, picker_cls)
        if not pickers or pickers[0][0] != 4:
            continue                       # not a component record
        first = pickers[0][1]
        # Header picker is fixed-size when empty (16 + 4); its END follows the path.
        after = 4 + 8 + 16 + 4 + len(first.path.encode("ascii")) + 4
        own = p[after:after + 16]
        strs = [(o, s) for o, s in ES._scan_payload(p) if o >= after + 16]
        if len(own) != 16 or len(strs) < 2:
            continue
        cname, group = strs[0][1], strs[1][1]
        body_from = strs[1][0]
        refs = [r for off, r in pickers[1:] if off > body_from and r.path]
        ref_paths = {r.path for r in refs}
        literals = [s for o, s in strs[2:] if s not in ref_paths]
        override = first if first.path else None
        body = p[body_from + 4 + len(group.encode("ascii")):]
        comps.append(Component(si, classes[ci], cname, group, own, override, refs, literals,
                               body, classes))
    return EntityGraph(name, comps)


# --------------------------------------------------------------------------
# the body, as typed tokens
# --------------------------------------------------------------------------

#: oCEntityValueUnion payload: u32 type, u32 (unused), 4-byte value.
_UNION_TYPES = {0: "f32", 1: "int", 2: "bool"}


@dataclass
class Token:
    offset: int                 # within the component body
    kind: str                   # ref | value | string | object | end | bytes
    text: str
    size: int


def tokens(c: Component) -> list[Token]:
    """``c.body`` split into typed tokens: every reference (picker), every
    typed value (value union), every string, every nested object opening, and
    the raw bytes between them. Works for all component classes without a
    per-class layout; offsets are what an edit addresses."""
    b, cls = c.body, c.classes
    out: list[Token] = []
    i = raw_from = 0

    def flush(upto: int) -> None:
        if upto > raw_from:
            out.append(Token(raw_from, "bytes", b[raw_from:upto].hex(" "), upto - raw_from))

    while i < len(b):
        if b[i:i + 4] == _BEGIN and i + 8 <= len(b):
            flush(i)
            ci = struct.unpack_from("<I", b, i + 4)[0]
            name = cls[ci] if ci < len(cls) else f"#{ci}"
            if name == "oCEntityCpntPicker" and i + 28 <= len(b):
                n = struct.unpack_from("<I", b, i + 24)[0]
                path = b[i + 28:i + 28 + n].decode("ascii", "replace")
                size = 8 + 16 + 4 + n + 4
                out.append(Token(i, "ref", path or "(none)", size))
                i += size
            elif name == "oCEntityValueUnion" and i + 21 <= len(b):
                t = struct.unpack_from("<I", b, i + 8)[0]
                kind = _UNION_TYPES.get(t, f"type{t}")
                # A bool stores ONE byte; f32/int four. Then the union's END.
                width = 1 if kind == "bool" else 4
                raw = b[i + 16:i + 16 + width]
                if kind == "f32":
                    text = f"f32 {struct.unpack('<f', raw)[0]:g}"
                elif kind == "bool":
                    text = f"bool {bool(raw[0])}"
                else:
                    text = f"{kind} {struct.unpack('<i', raw)[0]}"
                size = 16 + width + 4
                out.append(Token(i, "value", text, size))
                i += size
            else:
                out.append(Token(i, "object", name, 8))
                i += 8
            raw_from = i
            continue
        if b[i:i + 4] == _END:
            flush(i)
            out.append(Token(i, "end", "", 4))
            i += 4
            raw_from = i
            continue
        if i + 4 <= len(b):
            n = struct.unpack_from("<I", b, i)[0]
            s = b[i + 4:i + 4 + n]
            if 2 <= n <= 512 and len(s) == n and all(0x20 <= x < 0x7F for x in s):
                flush(i)
                out.append(Token(i, "string", s.decode("ascii"), 4 + n))
                i += 4 + n
                raw_from = i
                continue
        i += 1
    flush(len(b))
    return out
