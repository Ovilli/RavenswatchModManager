"""A component's body as named FIELDS, the layer the ability editor edits.

Entity components serialize without field names (the binary serializer passes
a null name to every field call), so names cannot be read out of the exe. What
the exe does give is the ORDER and TYPE of each field: every class's
``Serialize`` (vtable slot 3) is a straight run of typed calls. Reading them
against all 65,226 shipped components (RE 2026-09-25) establishes:

* Every body splits into top-level items: nested objects (a value picker, a
  reference picker, a selector, ...) and the raw primitives between them. For
  the logic classes this shape is identical across the whole corpus (Timer
  1033/1033, Value 8475/8475, Tester 3660/3660, ...), so an item's position IS
  its identity.
* Every body starts with the same 7 bytes from the base class
  (``oCEntityCpntSettings::Serialize`` = FUN_140711650, latest version):
  ``bool +0x81, bool (legacy, discarded), u32 mode +0x84 (0..3), bool +0x32``.

Names below come from the serializer's order plus what the corpus wires into
each slot (a Timer's slot 7 references "... Duration" / "... Delay" /
"... Cooldown" values in 420 of 1033 timers). A name ending in ``?`` is a
reading of that evidence, not a proven meaning. Anything not listed gets a
mechanical name (``ref_3``), so every class is still fully addressable.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import entity_graph as EG

#: The base-class prefix every component body starts with.
BASE = [("flag_81", "bool"), ("_legacy", "bool"), ("mode", "u32"), ("flag_32", "bool")]

_PRIM = {"bool": 1, "u32": 4, "f32": 4}
BASE_BYTES = sum(_PRIM[k] for _n, k in BASE)

#: class -> fields AFTER the base prefix, in serialized order. Kinds:
#: value (oCEntityCpntValuePicker), ref (oCEntityCpntPicker), obj (any other
#: nested object), bool / u32 / f32 / str (raw primitives), and ``<kind>[]``
#: for a list (u32 count, then that many objects). ``ids`` is a poly-pointer
#: vector: u32 count, then object ids of SUB-OBJECTS owned by this component
#: (id i is ``cf.sections[i + 1]``, past the component range). A third element names an
#: earlier bool the field depends on (``"!broadcast"``: only when it is False).
SCHEMAS: dict[str, list[tuple[str, ...]]] = {
    # FUN_14076beb0: seven ref lists (FUN_1402f2740). [0] is what an event or
    # state switches on (4767 users), [6] what runs while the state is active
    # (4219: "State Idle -> Idle Clip"); the other five are rarer readings.
    "oCEntityCpntStateSettings": [
        ("activates", "ref[]"), ("deactivates?", "ref[]"), ("list_2", "ref[]"),
        ("on_exit?", "ref[]"), ("disables_while_active?", "ref[]"), ("on_enter?", "ref[]"),
        ("while_active", "ref[]")],
    # FUN_140781060. With broadcast set the target collector is not written.
    "oCEntityCpntNamedEventSenderSettings": [
        ("event", "str"), ("broadcast", "bool"), ("targets", "obj", "!broadcast"),
        ("flag_1c0", "bool"), ("flag_1c1", "bool"), ("flag_120", "bool"),
        ("payload", "value"), ("flag_1c2", "bool")],
    # FUN_140782200.
    "oCEntityCpntNamedEventListenerSettings": [
        ("event", "str"), ("on_event", "ref"), ("while_state?", "ref"), ("flag_190", "bool"),
        ("mode_191", "u32")],
    # FUN_14072e2f0, latest version (the file's class version is >= 0x15).
    "oCEntityCpntEntitySpawnerSettings": [
        ("template", "obj"), ("position", "obj"), ("attach_mode?", "u32"),
        ("attach_node?", "ref"), ("transform", "obj"), ("target_position?", "obj"),
        ("speed?", "value"), ("game_ui", "ref"), ("ui_window", "obj"), ("selector", "ref"),
        ("spawner_values", "ref[]"), ("flag_19f0", "bool"), ("value_19f8", "value"),
        ("flag_1b8", "bool")],
    # FUN_14075b8e0: mode, entries (FUN_14076f110), two bools, default value.
    "oCEntityCpntValueSelectorSettings": [
        ("mode", "u32"), ("entries", "obj[]"), ("flag_f8", "bool"), ("flag_f9", "bool"),
        ("default", "value")],
    # FUN_14083b040 (class version >= 11): three pickers, a bool, a value, then
    # the attack sub-objects it owns (oCEntityGpnAttackSettings).
    "oCEntityCpntZoneAttackSettings": [
        ("ref_1c0", "ref"), ("ref_200", "ref"), ("ref_180", "ref"), ("flag_f8", "bool"),
        ("value_100", "value"), ("attacks", "ids")],
    "oCEntityCpntValueSettings": [("value", "value"), ("flag", "bool")],
    "oCEntityCpntTimerSettings": [
        ("bias?", "value"), ("count", "value"), ("on_tick", "ref"), ("on_end", "ref"),
        ("state", "ref"), ("paused?", "value"), ("duration", "value"), ("flag", "bool")],
    "oCEntityCpntTesterSettings": [
        ("on_true", "ref"), ("ref_2", "ref"), ("on_false", "ref"), ("ref_4", "ref"),
        ("test", "obj"), ("ref_6", "ref"), ("ref_7", "ref")],
    "oCEntityCpntValueOperationSettings": [
        ("op_type?", "u32"), ("a", "value"), ("op?", "u32"), ("flag?", "u32"), ("b", "value")],
    "oCEntityCpntValueOperationsSettings": [("operations", "obj")],
    "oCEntityCpntRangedRandomSettings": [
        ("int_mode?", "u32"), ("min", "value"), ("max", "value"), ("min_int", "value"),
        ("max_int", "value"), ("flag", "value")],
    "oCEntityCpntModifierSettings": [
        ("modifier_id", "u32"), ("duration", "value"), ("amount", "value"),
        ("targets", "obj"), ("value_4", "value"), ("sources?", "obj"), ("id", "value"),
        ("flag", "bool")],
    "oCEntityCpntGetValueSettings": [
        ("source", "obj"), ("template", "obj"), ("value", "ref"), ("method", "obj")],
    "oCEntityCpntSpawnerValueSettings": [
        ("spawner", "ref"), ("target_value", "ref"), ("value", "value"), ("value_type", "u32"),
        ("template", "obj")],
    "oCEntityCpntSmoothValueSettings": [
        ("source", "value"), ("target", "value"), ("value_type", "u32"), ("speed", "value"),
        ("flag_a", "bool"), ("flag_b", "bool"), ("acceleration", "value"),
        ("braking", "value"), ("value_8", "value"), ("epsilon?", "f32"),
        ("on_change?", "obj"), ("on_changed?", "obj")],
}

_OBJ_KIND = {"oCEntityCpntValuePicker": "value", "oCEntityCpntPicker": "ref"}


@dataclass
class Field:
    name: str
    kind: str                   # value | ref | obj | bool | u32 | f32 | bytes
    offset: int                 # within the component body
    size: int
    text: str                   # human reading of the value
    cls: str = ""               # the nested object's class, for value/ref/obj
    items: list[Field] = field(default_factory=list)   # a list field's elements


def _items(c: EG.Component) -> list[tuple[str, int, int, str]]:
    """Top-level ``(kind, offset, end, class)``: 'raw' spans and nested objects."""
    b, out, depth, i, raw = c.body, [], 0, 0, 0
    start, cls = 0, ""
    while i < len(b):
        if b[i:i + 4] == EG._BEGIN and i + 8 <= len(b):
            if depth == 0:
                if i > raw:
                    out.append(("raw", raw, i, ""))
                ci = struct.unpack_from("<I", b, i + 4)[0]
                start, cls = i, c.classes[ci] if ci < len(c.classes) else f"#{ci}"
            depth += 1
            i += 8
            continue
        if b[i:i + 4] == EG._END and depth > 0:
            depth -= 1
            i += 4
            if depth == 0:
                out.append(("obj", start, i, cls))
                raw = i
            continue
        i += 1
    if raw < len(b):
        out.append(("raw", raw, len(b), ""))
    return out


def _object_text(c: EG.Component, start: int, end: int) -> str:
    sub = EG.Component(0, c.cls, "", "", b"", None, body=c.body[start:end], classes=c.classes)
    toks = EG.tokens(sub)
    refs = [t.text for t in toks if t.kind == "ref" and t.text != "(none)"]
    vals = [t.text for t in toks if t.kind == "value"]
    strs = [repr(t.text) for t in toks if t.kind == "string"]
    parts = vals + [f"<- {r}" for r in refs] + strs
    return "  ".join(parts) if parts else "(none)"


def _prim_text(kind: str, raw: bytes) -> str:
    if kind == "bool":
        return str(bool(raw[0]))
    if kind == "f32":
        return f"{struct.unpack('<f', raw)[0]:g}"
    return str(struct.unpack("<I", raw)[0])


def fields(c: EG.Component) -> list[Field]:
    """``c.body`` as named fields. Uses the class schema when it tiles the body
    exactly, and mechanical names (``value_2``, ``bytes_5``) otherwise — so the
    result always covers every byte, in order."""
    items = _items(c)
    named = _apply(c, items, BASE + SCHEMAS.get(c.cls, [])) if c.cls in SCHEMAS else None
    return named if named is not None else _generic(c, items)


def _apply(c: EG.Component, items, spec) -> list[Field] | None:
    """The body read by ``spec``, or None when the spec does not tile it."""
    objs = {start: (end, cls) for kind, start, end, cls in items if kind == "obj"}
    starts = sorted(objs)
    b, at, out = c.body, 0, []

    def obj_field(name: str, want: str) -> Field | None:
        if at not in objs:
            return None
        end, cls = objs[at]
        got = _OBJ_KIND.get(cls, "obj")
        if want != got:
            return None
        return Field(name, got, at, end - at, _object_text(c, at, end), cls)

    for entry in spec:
        name, want = entry[0], entry[1]
        if len(entry) > 2:                         # present only when a bool says so
            flag = entry[2].lstrip("!")
            seen = next((f.text for f in out if f.name == flag), None)
            if (seen == "True") == entry[2].startswith("!"):
                continue
        if want == "ids":                          # u32 count, then count object ids
            nxt = next((s for s in starts if s >= at), len(b))
            if at + 4 > nxt:
                return None
            n = struct.unpack_from("<I", b, at)[0]
            if at + 4 + 4 * n > nxt:
                return None
            ids = struct.unpack_from(f"<{n}I", b, at + 4)
            out.append(Field(name, "ids", at, 4 + 4 * n, " ".join(f"#{i}" for i in ids)))
            at += 4 + 4 * n
        elif want == "str":
            if at + 4 > len(b) or at in objs:
                return None
            n = struct.unpack_from("<I", b, at)[0]
            nxt = next((s for s in starts if s >= at), len(b))
            if at + 4 + n > nxt:
                return None
            out.append(Field(name, "str", at, 4 + n, b[at + 4:at + 4 + n].decode("latin-1")))
            at += 4 + n
        elif want in _PRIM:
            n = _PRIM[want]
            nxt = next((s for s in starts if s >= at), len(b))
            if at + n > nxt:                       # would run into an object
                return None
            out.append(Field(name, want, at, n, _prim_text(want, b[at:at + n])))
            at += n
        elif want.endswith("[]"):                  # u32 count, then count objects
            if at + 4 > len(b) or at in objs:
                return None
            start, count = at, struct.unpack_from("<I", b, at)[0]
            at += 4
            elems = []
            for k in range(count):
                f = obj_field(f"{name}[{k}]", want[:-2])
                if f is None:
                    return None
                elems.append(f)
                at += f.size
            text = "  |  ".join(e.text for e in elems) if elems else "(empty)"
            out.append(Field(name, want, start, at - start, text, items=elems))
        else:
            f = obj_field(name, want)
            if f is None:
                return None
            out.append(f)
            at += f.size
    return out if at == len(b) else None


def _generic(c: EG.Component, items) -> list[Field]:
    out: list[Field] = []
    for k, (kind, start, end, cls) in enumerate(items, 1):
        if kind == "obj":
            got = _OBJ_KIND.get(cls, "obj")
            out.append(Field(f"{got}_{k}", got, start, end - start,
                             _object_text(c, start, end), cls))
            continue
        at = start
        if start == 0 and end >= BASE_BYTES:
            for name, want in BASE:
                n = _PRIM[want]
                out.append(Field(name, want, at, n, _prim_text(want, c.body[at:at + n])))
                at += n
        if at < end:
            out.append(Field(f"bytes_{k}", "bytes", at, end - at, c.body[at:end].hex(" ")))
    return out

