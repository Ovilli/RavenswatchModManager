"""Edit an entity-settings file as a graph: the ability editor's primitives.

``EntityFile`` holds a cooked entity as its objects and lets you:

* ``clone``     copy components (from this file or another entity) under new
                names, with their own GUIDs, their links among themselves
                rewired to the copies, and every sub-object they own copied too;
* ``set_value`` change a field's literal (a value picker's union, or a raw
                bool / u32 / f32);
* ``set_ref``   point a reference field at another component (or at nothing);
* ``add_ref`` / ``remove_ref``   grow or shrink a reference list (a State's
                ``activates`` and friends).

Fields are addressed by the names ``entity_fields`` gives them.

Invariants every edit keeps (``to_bytes`` re-checks them):

* the object table (section 0) lists every object with its class;
* new components are appended to the trailer's component vector, or they are
  orphans the engine never instantiates (see entity_append);
* component GUIDs are unique in the file;
* a class a copied record names exists in the class table.

Sub-objects (RE 2026-09-25). A file's objects are its components (the
trailer's vector; ids ``0..k-1`` in every shipped file) and SUB-OBJECTS a component owns: a
Tester's conditions, an Fx's setups, a spawner's retrievers. 1615 of 4700
shipped entities have them (Piper: 468). An owner points at one with a
poly-pointer, which in a cooked file is the sub-object's u32 id: either a
vector (``u32 count, count * u32 id``) or a single ``u32 id``. Ids are not
allocated in any order a clone could rely on, so ownership is READ: every
vector whose ids are all sub-object ids, and every single u32 equal to a
sub-object id that occurs exactly once in the file outside strings, pickers and
value unions. A sub-object whose pointer cannot be pinned down that way is
AMBIGUOUS, and cloning anything that might own it is refused rather than
guessed: a clone that shares a sub-object with its original, or remaps a
number that was not a pointer, would load and misbehave with nothing logged.
"""

from __future__ import annotations

import struct
import uuid
from collections import defaultdict
from dataclasses import dataclass
from functools import cache, lru_cache

from . import cooked
from . import entity_fields as EF
from . import entity_graph as EG
from .entity_append import (
    EntityAppendError,
    _Accessors,
    _directory,
    component_vector,
    fix_accessor,
    fix_format_slot,
    validate_layout,
)
from .entity_components import _remap_class_tags, class_closure, extend_class_table

_B, _E = cooked.MARK_BEGIN, cooked.MARK_END
_NS = uuid.UUID("5f0c6a2e-4a55-4f0e-9d0a-6c1b1f5e7a11")


class EntityEditError(ValueError):
    pass


@dataclass
class Pointer:
    owner: int          # object id, or len(objects) for the trailer
    offset: int         # of the u32 id within the owner's payload


def _lstr(s: str) -> bytes:
    b = s.encode("latin-1")
    return struct.pack("<I", len(b)) + b


class EntityFile:
    def __init__(self, raw: bytes, name: str = ""):
        self.cf = cooked.parse(raw)
        validate_layout(self.cf)
        self.objects = [bytearray(s.payload) for s in self.cf.sections[1:-1]]
        self.trailer = bytearray(self.cf.sections[-1].payload)
        self.name = name

    # ---- reading ---------------------------------------------------------

    @property
    def component_ids(self) -> list[int]:
        return component_vector(bytes(self.trailer))[1]

    def to_bytes(self) -> bytes:
        n = len(self.objects)
        classes = [struct.unpack_from("<I", o, 0)[0] for o in self.objects]
        directory = struct.pack(f"<I{n}I", n, *classes)
        self.cf.sections = ([cooked.Section(directory)]
                            + [cooked.Section(bytes(o)) for o in self.objects]
                            + [cooked.Section(bytes(self.trailer))])
        out = cooked.emit(self.cf)
        self._check(out)
        return out

    def graph(self) -> EG.EntityGraph:
        return EG.parse(self.to_bytes(), self.name)

    def component(self, name: str) -> EG.Component:
        """The unique component called ``name`` (or ``Group\\Name``)."""
        hits = [c for c in self.graph().components if name in (c.name, c.path)]
        if len(hits) != 1:
            raise EntityEditError(f"{len(hits)} components named {name!r}")
        return hits[0]

    def _class(self, obj: int) -> str:
        return self.cf.classes[struct.unpack_from("<I", self.objects[obj], 0)[0]].name

    def _payload(self, obj: int) -> bytearray:
        return self.trailer if obj == len(self.objects) else self.objects[obj]

    # ---- sub-object ownership --------------------------------------------

    def pointers(self) -> tuple[dict[int, Pointer], dict[int, list[Pointer]]]:
        """``(owned, ambiguous)``: each sub-object id's pointer, and the
        candidates for those whose pointer could not be pinned down."""
        n = len(self.objects)
        comps = set(self.component_ids)
        is_sub = [x not in comps for x in range(n)]
        names = [c.name for c in self.cf.classes]
        special = {names.index(x) for x in ("oCEntityCpntPicker", "oCEntityValueUnion")
                   if x in names}
        vec: dict[int, list[Pointer]] = defaultdict(list)
        single: dict[int, list[Pointer]] = defaultdict(list)
        for o in range(n + 1):
            p = self._payload(o)
            start = 4
            if o == n:
                voff, ids = component_vector(bytes(p))
                start = voff + 4 + 4 * len(ids)
            for a, b in _raw_spans(p, special):
                i = max(a, start)
                while i + 4 <= b:
                    c = struct.unpack_from("<I", p, i)[0]
                    if 1 <= c <= 4096 and i + 4 + 4 * c <= b:
                        ids = struct.unpack_from(f"<{c}I", p, i + 4)
                        if all(x < n and is_sub[x] for x in ids):
                            for j, x in enumerate(ids):
                                vec[x].append(Pointer(o, i + 4 + 4 * j))
                            i += 4 + 4 * c
                            continue
                    if c < n and is_sub[c]:
                        single[c].append(Pointer(o, i))
                    i += 1
        owned: dict[int, Pointer] = {}
        ambiguous: dict[int, list[Pointer]] = {}
        for x in (x for x in range(n) if is_sub[x]):
            if len(vec[x]) == 1:
                owned[x] = vec[x][0]
            elif not vec[x] and len(single[x]) == 1:
                owned[x] = single[x][0]
            else:
                ambiguous[x] = vec[x] + single[x]
        # A class owns the same kinds of sub-object throughout a file (a
        # Tester its conditions, an Fx its setups), so pairs read off the
        # unambiguous pointers narrow a candidate list whose id also occurs as
        # plain data (0x400 and 0x500 are common numbers).
        pairs = {(self._owner_class(p.owner), self._class(x)) for x, p in owned.items()}
        for x, cands in list(ambiguous.items()):
            fit = [p for p in cands if (self._owner_class(p.owner), self._class(x)) in pairs]
            if len(fit) == 1 and not (vec[x] and fit[0] not in vec[x]):
                owned[x] = fit[0]
                del ambiguous[x]
        return owned, ambiguous

    def _owner_class(self, obj: int) -> str:
        return "(entity)" if obj == len(self.objects) else self._class(obj)

    def subtree(self, objs: set[int]) -> list[int]:
        """Every sub-object ``objs`` own, transitively. Fails closed when one
        of them might own an ambiguous sub-object."""
        owned, ambiguous = self.pointers()
        for x, cands in ambiguous.items():
            if any(p.owner in objs for p in cands):
                raise EntityEditError(
                    f"cannot tell whether sub-object #{x} ({self._class(x)}) belongs to "
                    f"what is being copied ({len(cands)} candidate pointers)")
        out: list[int] = []
        todo = sorted(objs)
        seen = set(objs)
        while todo:
            o = todo.pop(0)
            for x, p in sorted(owned.items()):
                if p.owner == o and x not in seen:
                    seen.add(x)
                    out.append(x)
                    todo.append(x)
        return out

    # ---- clone -------------------------------------------------------------

    def clone(self, names: list[str], *, rename: dict[str, str] | None = None,
              group: dict[str, str] | None = None, seed: str = "",
              source: EntityFile | None = None) -> dict[str, str]:
        """Copy the named components (and everything they own) into this file.

        ``rename`` maps old component names to new ones; ``group`` maps old
        group names to new ones. Links among the copied components point at
        the copies; links out of the set are left alone. ``source`` copies from
        another entity (the class table is extended as needed). Returns
        ``{old path: new path}``. Every copy gets a fresh GUID derived from
        ``seed`` (keep it stable to rebuild byte-identically)."""
        src = source or self
        rename, group = rename or {}, group or {}
        g = src.graph()
        by_name = {}
        for want in names:
            hits = [c for c in g.components if want in (c.name, c.path)]
            if len(hits) != 1:
                raise EntityEditError(f"{len(hits)} components named {want!r}")
            by_name[hits[0].index - 1] = hits[0]
        comps = sorted(by_name)
        subs = src.subtree(set(comps))
        owned, _amb = src.pointers()

        base = len(self.objects)
        new_id = {old: base + i for i, old in enumerate(comps + subs)}
        guid = {c.guid: _mint(seed, c.guid) for c in by_name.values()}
        taken = {c.guid for c in self.graph().components}
        if any(v in taken for v in guid.values()):
            raise EntityEditError("a minted GUID collides; change the seed")
        paths: dict[str, str] = {}
        for c in by_name.values():
            ng, nn = group.get(c.group, c.group), rename.get(c.name, c.name)
            paths[c.path] = f"{ng}\\{nn}" if ng else nn

        payloads: list[bytearray] = []
        for old in comps + subs:
            p = bytearray(src.objects[old])
            for x, ptr in owned.items():              # re-point owned sub-objects
                if ptr.owner == old and x in new_id:
                    struct.pack_into("<I", p, ptr.offset, new_id[x])
            payloads.append(p)
        for i, old in enumerate(comps + subs):
            p = payloads[i]
            for a, b in guid.items():                 # own GUID + links to copies
                p[:] = p.replace(a, b)
            p[:] = _rewrite_ref_paths(bytes(p), src.cf, paths, set(guid.values()))
            if old in by_name:
                c = by_name[old]
                p[:] = _rewrite_header(bytes(p), rename.get(c.name, c.name),
                                       group.get(c.group, c.group))
            if src is not self:
                extend_class_table(self.cf, src.cf, class_closure(bytes(p), src.cf))
                p[:] = _remap_class_tags(bytes(p), src.cf, self.cf)
        self.objects.extend(payloads)
        voff, ids = component_vector(bytes(self.trailer))
        ids = ids + [new_id[o] for o in comps]
        self.trailer[voff:voff + 4 + 4 * (len(ids) - len(comps))] = (
            struct.pack("<I", len(ids)) + struct.pack(f"<{len(ids)}I", *ids))
        self.to_bytes()
        return paths

    # ---- fields ------------------------------------------------------------

    def _field(self, comp: str, field: str) -> tuple[EG.Component, EF.Field, int]:
        c = self.component(comp)
        fs = {f.name: f for f in EF.fields(c)}
        base, _, idx = field.partition("[")
        if base not in fs:
            raise EntityEditError(f"{c.name!r} has no field {base!r}; have {', '.join(fs)}")
        f = fs[base]
        if idx:
            f = f.items[int(idx.rstrip("]"))]
        return c, f, len(self.objects[c.index - 1]) - len(c.body)

    def set_value(self, comp: str, field: str, value) -> None:
        """Set a literal: a raw bool/u32/f32 field, or the union inside a value
        field (keeping its type; ints and floats convert)."""
        c, f, at = self._field(comp, field)
        p = self.objects[c.index - 1]
        if f.kind in EF._PRIM:
            struct.pack_into({"bool": "<?", "u32": "<I", "f32": "<f"}[f.kind], p,
                             at + f.offset, _as(f.kind, value))
            return
        if f.kind != "value":
            raise EntityEditError(f"{field!r} is a {f.kind}, not a literal")
        sub = EG.Component(0, c.cls, "", "", b"", None,
                           body=c.body[f.offset:f.offset + f.size], classes=c.classes)
        u = next((t for t in EG.tokens(sub) if t.kind == "value"), None)
        if u is None:
            raise EntityEditError(f"{field!r} holds no literal")
        kind = u.text.split()[0]
        fmt = {"f32": "<f", "int": "<i", "bool": "<?", "vec2": "<2f", "vec3": "<3f",
               "vec4": "<4f"}.get(kind)
        if fmt is None:
            raise EntityEditError(f"{field!r} is a {kind}; only numbers and vectors are set")
        vals = value if isinstance(value, (list, tuple)) else [value]
        conv = {"f32": float, "int": int, "bool": bool}.get(kind, float)
        struct.pack_into(fmt, p, at + f.offset + u.offset + 16, *[conv(v) for v in vals])

    def set_ref(self, comp: str, field: str, target: str | None) -> None:
        """Point a reference (``ref`` field, list element ``name[i]``, or the
        reference inside a value field) at component ``target`` or at nothing."""
        c, f, at = self._field(comp, field)
        a, b = self._picker_span(c, f)
        obj = c.index - 1
        old = bytes(self.objects[obj][at + a:at + b])
        new = self._picker(target)
        self.objects[obj][at + a:at + b] = new
        # A reference inside a value picker is followed by the ACCESSOR the
        # target is read with, which depends on the target's class and value
        # type; a stale one reads the new target with the wrong method and
        # returns garbage (entity_append.fix_accessor has the RE).
        label_end = at + a + len(new) - 4
        p = bytes(self.objects[obj])
        try:
            acc = _Accessors(cooked.parse(self.to_bytes()))
            p = fix_accessor(p, label_end, old[8:24], new[8:24], acc,
                             _picker_path(old), _picker_path(new))
            p = fix_format_slot(p, at + a, label_end, new[8:24], acc)
        except (EntityAppendError, EntityEditError) as e:
            self.objects[obj][at + a:at + a + len(new)] = old      # leave the file as it was
            raise EntityEditError(f"cannot point {c.name}.{field} at {target!r}: {e}") from e
        self.objects[obj][:] = p

    def add_ref(self, comp: str, field: str, target: str) -> None:
        c, f, at = self._field(comp, field)
        if f.kind != "ref[]":
            raise EntityEditError(f"{field!r} is a {f.kind}, not a reference list")
        p = self.objects[c.index - 1]
        n = struct.unpack_from("<I", p, at + f.offset)[0]
        end = at + f.offset + f.size
        p[end:end] = self._picker(target)
        struct.pack_into("<I", p, at + f.offset, n + 1)

    def remove_ref(self, comp: str, field: str, index: int) -> None:
        c, f, at = self._field(comp, field)
        if f.kind != "ref[]":
            raise EntityEditError(f"{field!r} is a {f.kind}, not a reference list")
        e = f.items[index]
        p = self.objects[c.index - 1]
        del p[at + e.offset:at + e.offset + e.size]
        struct.pack_into("<I", p, at + f.offset, len(f.items) - 1)

    def _picker_span(self, c: EG.Component, f: EF.Field) -> tuple[int, int]:
        """``(start, end)`` in the body of the oCEntityCpntPicker ``f`` is or holds."""
        if f.kind == "ref":
            return f.offset, f.offset + f.size
        if f.kind == "value":
            sub = EG.Component(0, c.cls, "", "", b"", None,
                               body=c.body[f.offset:f.offset + f.size], classes=c.classes)
            r = next((t for t in EG.tokens(sub) if t.kind == "ref"), None)
            if r is None:
                raise EntityEditError(
                    f"{f.name!r} holds a literal, not a reference; a value field only "
                    "re-points a reference it already has")
            return f.offset + r.offset, f.offset + r.offset + r.size
        raise EntityEditError(f"{f.name!r} is a {f.kind}, not a reference")

    def _picker(self, target: str | None) -> bytes:
        names = [x.name for x in self.cf.classes]
        head = _B + struct.pack("<I", names.index("oCEntityCpntPicker"))
        if target is None:
            return head + bytes(16) + _lstr("") + _E
        t = self.component(target)
        return head + t.guid + _lstr(f"[{self._label(t.cls)}] {self._scope()}\\{t.path}") + _E

    def _label(self, cls: str) -> str:
        """The ``[Kind]`` label for ``cls``: from this file's own references
        when one names such a component, else learned from the corpus."""
        g = self.graph()
        idx = g.by_guid()
        for c in g.components:
            for r in c.refs:
                t = idx.get(r.guid)
                if t is not None and t.cls == cls and r.kind:
                    return r.kind
        return kind_label(cls)

    def _scope(self) -> str:
        """The scope this file's own references use (``Hero_Piper``)."""
        g = self.graph()
        mine = g.by_guid()
        for c in g.components:
            for r in c.refs:
                if r.guid in mine and r.scope:
                    return r.scope
        if self.name:
            return self.name
        raise EntityEditError("cannot tell this entity's scope; pass name=")

    def _splice(self, c: EG.Component, a: int, b: int, new: bytes) -> None:
        self.objects[c.index - 1][a:b] = new

    # ---- invariants --------------------------------------------------------

    def _check(self, raw: bytes) -> None:
        cf = cooked.parse(raw)
        validate_layout(cf)
        g = EG.parse(raw)
        k = len(component_vector(cf.sections[-1].payload)[1])
        if len(g.components) != k:
            raise EntityEditError(f"{len(g.components)} components parse, vector has {k}")
        guids = [c.guid for c in g.components]
        if len(set(guids)) != len(guids):
            raise EntityEditError("two components share a GUID")
        n, _idx = _directory(cf)
        if n != len(self.objects):
            raise EntityEditError("object table and objects disagree")


# --------------------------------------------------------------------------


def _picker_path(picker: bytes) -> str:
    n = struct.unpack_from("<I", picker, 24)[0]
    return picker[28:28 + n].decode("latin-1")


def _mint(seed: str, guid: bytes) -> bytes:
    return uuid.uuid5(_NS, f"{seed}:{guid.hex()}").bytes


def _as(kind: str, value):
    return {"bool": bool, "u32": int, "f32": float}[kind](value)


def _raw_spans(p: bytes, special: set[int]) -> list[tuple[int, int]]:
    """Spans of ``p`` outside markers, lstrings, pickers and value unions —
    where a poly-pointer id can sit."""
    spans: list[tuple[int, int]] = []
    i = start = 0
    n = len(p)
    while i < n:
        mark = p[i:i + 4]
        if mark in (_B, _E):
            if i > start:
                spans.append((start, i))
            if mark == _B and i + 8 <= n and struct.unpack_from("<I", p, i + 4)[0] in special:
                j = p.find(_E, i + 8)
                i = j + 4 if j >= 0 else n
            else:
                i += 8 if mark == _B else 4
            start = i
            continue
        if i + 4 <= n:
            m = struct.unpack_from("<I", p, i)[0]
            s = p[i + 4:i + 4 + m]
            if 2 <= m <= 512 and len(s) == m and all(32 <= x < 127 for x in s):
                if i > start:
                    spans.append((start, i))
                i += 4 + m
                start = i
                continue
        i += 1
    if start < n:
        spans.append((start, n))
    return spans


def _rewrite_ref_paths(p: bytes, cf: cooked.CookedFile, paths: dict[str, str],
                       new_guids: set[bytes]) -> bytes:
    """Rename the ``Group\\Name`` tail of every picker that targets a copy."""
    names = [x.name for x in cf.classes]
    if "oCEntityCpntPicker" not in names:
        return p
    out, last = bytearray(), 0
    for off, ref in EG._pickers(p, names.index("oCEntityCpntPicker")):
        if ref.guid not in new_guids:
            continue
        m = EG._PATH.match(ref.path)
        if not m or m["rest"] not in paths:
            continue
        new = f"[{m['kind']}] {m['scope']}\\{paths[m['rest']]}"
        s = off + 8 + 16                              # BEGIN, class, GUID
        n = struct.unpack_from("<I", p, s)[0]
        out += p[last:s] + _lstr(new)
        last = s + 4 + n
    return bytes(out + p[last:])


def _rewrite_header(p: bytes, name: str, group: str) -> bytes:
    """``p`` with the record header's name and group replaced."""
    pk = EG._pickers(p, struct.unpack_from("<I", p, 8)[0])
    first = pk[0][1] if pk and pk[0][0] == 4 else None
    if first is None:
        raise EntityEditError("record has no header picker")
    at = 4 + 8 + 16 + 4 + len(first.path.encode("latin-1")) + 4 + 16
    head = EG._header_strings(p, at)
    if head is None:
        raise EntityEditError("record header does not parse")
    _old_name, _old_group, body = head
    flags_at = at + 4 + struct.unpack_from("<I", p, at)[0]
    return (p[:at] + _lstr(name) + p[flags_at:flags_at + 4] + _lstr(group) + p[body:])


@cache
def _kind_labels() -> dict[str, str]:
    """Component class -> the ``[Kind]`` label references to it carry, learned
    from the shipped corpus (the label is the editor's display name for the
    class, which the exe does not hold)."""
    from . import corpus
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rel in corpus.rels("EntitySettings/"):
        if not rel.endswith(".EntitySettingsResource.gen"):
            continue
        g = EG.parse(corpus.read(rel))
        idx = g.by_guid()
        for c in g.components:
            for r in c.refs:
                t = idx.get(r.guid)
                if t is not None and r.kind:
                    votes[t.cls][r.kind] += 1
    return {cls: max(v, key=v.get) for cls, v in votes.items()}


def kind_label(cls: str) -> str:
    got = _kind_labels().get(cls)
    if got is None:
        raise EntityEditError(f"no reference in the game names a {cls}; cannot label one")
    return got
