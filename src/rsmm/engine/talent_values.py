"""Talent (in-game "Skill") value discovery + patching.

Ravenswatch talents are internally "Skills". A hero's talent *roster* (which
nodes exist + their tree slots) lives as ``Skill Controller <X>`` nodes inside
the herodef (``Definitions/Heroes/<Hero>.herodef...gen``). The talent *effect
magnitudes* — the numbers people want to change — live inside the hero's cooked
**entity** files under
``EntitySettings/Heroes/Hero_<Hero>/*.entity.ot.EntitySettingsResource.gen``.

Node shape (RE'd 2026-09-12 against the class table, superseding an earlier
label-and-scan heuristic)
-------------------------------------------------------------------------

An authored magnitude is a *pair* of nested nodes that follows the node's name:

    <u32 len><label "Skill ... Value"> ...
        1111bbaa <idx oCEntityCpntValuePicker>  <flag ...>
        1111bbaa <idx oCEntityValueUnion>       <u32 type><u32 sub><value>
        2222bbaa

Two facts make this readable, and getting either wrong is what produced silent
no-ops and file corruption before:

* **The u32 after a ``1111bbaa`` BEGIN marker is an index into the file's own
  class table, not a global class id.** The same class sits at a different
  index in every file (``oCEntityCpntValuePicker`` is 0x0e in the Damage_Power
  magical object, 0x44 in Hero_Red, 0x3f in Hero_Juliet, …), so a node can only
  be identified by resolving that index through :func:`rsmm.engine.cooked.parse`
  and comparing the class *name*. The previous implementation hardcoded 0x0e/0x0f
  — the indices that happen to be right for Damage_Power — so on hero files it
  was inspecting ``oCEntityCpntTimerSettings`` and its shadow check never fired.

* **``oCEntityValueUnion`` carries an explicit type code** as the first u32 of
  its payload. Only three of the eight observed codes are numeric; the rest are
  asset references and strings whose bytes are not a number at all:

      0  f32      860 nodes   'Appear Value'
      1  int32     78 nodes   'Skill Attack Flurry Active Count'
      2  bool      32 nodes   'Skill Swirling Value'
      3  vector     4         'Start Pos Value'
      4  color     18         'Minimap Marker Color Value'
      5  string    12         'Title Label Value'
      6  texture   14         'Weapon Shield Quest Upgraded Texture Value'
      9  resource 301         'Weapon Material Value'

  Guessing f32-vs-int32 from the bit pattern instead (an int32 reinterprets as a
  tiny subnormal) misses every int-typed node whose value is ``0``, because
  ``0`` is a valid f32 too.

Shadowed values
---------------

``oCEntityCpntValuePicker``'s payload is a single ``0x00`` when the union's
inline value is what the game uses, and ``0x01`` + a reference when the value is
*sourced from elsewhere* (a Value Selector / curve / card-count amount) — in
which case the inline number is dead and editing it has no in-game effect.
:func:`clear_value_override` collapses the picker back to the inline form.

The patch is written in place, length-preserving, so a talent mod is just a
byte-edited copy of the vanilla entity shipped as a plain asset override (no
re-cook).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import cooked

_END = b"\x22\x22\xbb\xaa"
_BEGIN = b"\x11\x11\xbb\xaa"

#: Class names of the two nested nodes that hold an authored value.
_PICKER = "oCEntityCpntValuePicker"
_UNION = "oCEntityValueUnion"

#: ``oCEntityValueUnion`` type codes we can read and write as a number.
TYPE_F32 = 0
TYPE_INT32 = 1
TYPE_BOOL = 2
#: Payload size of each numeric type, in bytes, after the 8-byte type header.
_NUMERIC = {TYPE_F32: 4, TYPE_INT32: 4, TYPE_BOOL: 1}

#: Max bytes between a value label and the BEGIN of its picker node. Observed
#: worst case ~120 (a parent-name lstring plus two small headers); 200 is slack.
_MAX_LABEL_GAP = 200
#: Max bytes between the picker BEGIN and the union BEGIN (the picker's flag, or
#: flag + a 5-byte reference).
_MAX_PICKER_GAP = 64


@dataclass(frozen=True)
class TalentValue:
    label: str
    value: float
    #: Absolute byte offset of the value in the cooked file (for patching/debug).
    offset: int
    #: True for ``... Spawner Value`` runtime slots (always ~0.0, not authored).
    is_spawner: bool
    #: True when the field is an int32 count, not an f32 magnitude (e.g.
    #: ``Objective Count`` = 7). ``value`` then holds the integer as a float.
    is_int: bool = False
    #: True when the value is sourced from a selector/reference (the picker's
    #: override flag is set), so the inline ``value`` is *shadowed* — editing it
    #: does nothing in game. See :func:`clear_value_override`.
    is_overridden: bool = False
    #: Raw ``oCEntityValueUnion`` type code (0 f32 / 1 int32 / 2 bool).
    type_code: int = TYPE_F32


#: Suffixes that mark an authored gameplay magnitude/count node. Value covers
#: f32 effect magnitudes; the rest catch int32 counts and common stat fields.
_VALUE_SUFFIXES = ("Value", "Count", "Required", "Max", "Stock", "Object",
                   "Cooldown", "Duration", "Radius", "Range", "Multiplier",
                   "Ratio", "Chance", "Threshold", "Distance", "Amount",
                   # `<X> Damage` is an oCDtEntityCpntDamageSettings node whose
                   # first picker/union is the damage channel (105 in the hero
                   # corpus, e.g. the Ice Clone's `Explosion Damage`). Safe to
                   # match broadly now that a node must resolve structurally.
                   "Damage")
#: Structural node names that carry a number but are wiring, not authored data.
_STRUCT_NAMES = ("Operation", "Selector", "Listener", "Modifier", "Tester",
                 "Traverser", "Store", "Picker", "Format", "Computer", "State")


def _is_authored_value_label(s: str) -> bool:
    """True for a node name that looks like an authored magnitude/count (not a
    structural/wiring node or a scoped ``[...]`` reference)."""
    if s.startswith("[") or "Get" in s or any(k in s for k in _STRUCT_NAMES):
        return False
    return any(s.endswith(suf) for suf in _VALUE_SUFFIXES)


def class_names(data: bytes) -> list[str] | None:
    """Return the file's class table as an index-ordered list of class names,
    or ``None`` when the container cannot be parsed.

    Every ``1111bbaa`` BEGIN marker is followed by an index into this list, so
    nothing in a cooked body can be identified without it.
    """
    try:
        return [c.name for c in cooked.parse(data).classes]
    except (ValueError, IndexError, struct.error):
        return None


def _class_at(data: bytes, names: list[str], begin: int) -> str | None:
    """Resolve the class name for the BEGIN marker at ``begin``."""
    if begin + 8 > len(data):
        return None
    idx = struct.unpack_from("<I", data, begin + 4)[0]
    return names[idx] if idx < len(names) else None


def _resolve_value_node(data: bytes, names: list[str], after_label: int):
    """Resolve the picker/union value node that follows a label.

    ``after_label`` is the offset just past the label's length-prefixed string.
    Returns ``(type_code, value_offset, value_size, shadowed)`` or ``None`` when
    this label does not front a numeric value node — which is the common case
    (most matching strings are names in a list, not value nodes at all).
    Fails closed: anything unexpected returns ``None`` rather than a guess.
    """
    p1 = data.find(_BEGIN, after_label, after_label + _MAX_LABEL_GAP)
    if p1 < 0:
        return None
    # An END before the picker means we already left this label's node.
    stop = data.find(_END, after_label, p1)
    if stop >= 0:
        return None
    if _class_at(data, names, p1) != _PICKER:
        return None
    p2 = data.find(_BEGIN, p1 + 8, p1 + 8 + _MAX_PICKER_GAP)
    if p2 < 0 or _class_at(data, names, p2) != _UNION:
        return None
    end = data.find(_END, p2 + 8)
    if end < 0 or end - (p2 + 8) < 8:
        return None
    type_code = struct.unpack_from("<I", data, p2 + 8)[0]
    size = _NUMERIC.get(type_code)
    if size is None:
        return None  # asset ref / string / colour / vector — not a number
    value_off = p2 + 16  # skip the union's u32 type + u32 sub-type
    if end - value_off != size:
        return None  # payload is not the fixed width this type implies
    shadowed = any(data[p1 + 8:p2])
    return type_code, value_off, size, shadowed


def _read_value(data: bytes, type_code: int, off: int) -> float:
    if type_code == TYPE_INT32:
        return float(struct.unpack_from("<i", data, off)[0])
    if type_code == TYPE_BOOL:
        return float(data[off])
    return struct.unpack_from("<f", data, off)[0]


def _pack_value(type_code: int, value: float) -> bytes:
    if type_code == TYPE_INT32:
        return struct.pack("<i", int(round(value)))
    if type_code == TYPE_BOOL:
        return bytes([1 if value else 0])
    return struct.pack("<f", value)


def _iter_lstrings(data: bytes):
    """Yield ``(offset, text)`` for every length-prefixed printable ASCII run."""
    i, n = 0, len(data)
    while i + 4 <= n:
        ln = struct.unpack_from("<I", data, i)[0]
        if 4 <= ln <= 80 and i + 4 + ln <= n:
            chunk = data[i + 4: i + 4 + ln]
            if all(0x20 <= b < 0x7f for b in chunk):
                yield i, chunk.decode("ascii")
                i += 4 + ln
                continue
        i += 1


def _iter_value_nodes(data: bytes, names: list[str]):
    """Yield ``(label, offset, type_code, value_off, size, shadowed)`` for every
    resolvable numeric value node, in file order.

    De-duped by label *and* by the value's offset. The offset half matters
    because a node is laid out as ``<own name> <header> <scope name> <header>
    picker union``, and a scope name can itself look like a value name — so
    ``Skill Power Range Move Speed Increase Ratio`` and the scope string
    ``Skill Power Range`` both resolve to the same field. The node's own name
    comes first, so first claim wins and the scope string is dropped (3 such
    collisions in the shipped hero corpus)."""
    seen: set[str] = set()
    claimed: set[int] = set()
    for off, s in _iter_lstrings(data):
        if s in seen or not _is_authored_value_label(s):
            continue
        node = _resolve_value_node(data, names, off + 4 + len(s.encode("ascii")))
        if node is None or node[1] in claimed:
            continue
        seen.add(s)
        claimed.add(node[1])
        yield (s, off, *node)


def list_talent_values(data: bytes, *, include_spawner: bool = False) -> list[TalentValue]:
    """Discover editable talent magnitudes in one cooked hero-entity file.

    Only nodes that genuinely resolve to ``oCEntityCpntValuePicker`` ->
    ``oCEntityValueUnion`` with a numeric type code are returned; a label that
    merely looks like a value name (most of them are entries in a name list) is
    skipped rather than reported as ``0.0``. Returns ``[]`` when the container's
    class table cannot be parsed, because without it no node can be identified.
    By default drops ``... Spawner Value`` runtime slots (always 0.0). De-dupes
    by label, first occurrence wins.
    """
    names = class_names(data)
    if names is None:
        return []
    out: list[TalentValue] = []
    for label, _off, tc, voff, _size, shadowed in _iter_value_nodes(data, names):
        is_spawner = label.endswith("Spawner Value")
        if is_spawner and not include_spawner:
            continue
        v = _read_value(data, tc, voff)
        if v != v:  # NaN
            continue
        out.append(TalentValue(
            label=label,
            value=v if tc != TYPE_F32 else round(v, 4),
            offset=voff,
            is_spawner=is_spawner,
            is_int=tc == TYPE_INT32,
            is_overridden=shadowed,
            type_code=tc,
        ))
    return out


def is_label_overridden(data: bytes, label: str) -> bool:
    """Public check: is the value node named ``label`` *shadowed* (its picker's
    override flag set, so its inline value is ignored in game)?

    Returns ``False`` when the label has no resolvable value node (nothing to
    shadow). Used by the item cook path so a manifest ``value_patches`` edit
    can't silently no-op on a shadowed node.
    """
    names = class_names(data)
    if names is None:
        return False
    for lbl, _off, _tc, _voff, _size, shadowed in _iter_value_nodes(data, names):
        if lbl == label:
            return shadowed
    return False


def set_talent_value(data: bytes, label: str, new_value: float,
                     *, expect: float | None = None,
                     allow_shadowed: bool = False) -> bytes:
    """Patch one talent magnitude by label, length-preserving.

    The field is written as f32, int32 or bool to match the union's declared
    type code — never guessed from the bit pattern, because an int32 holding
    ``0`` is indistinguishable from an f32 holding ``0.0`` and writing an f32
    into an int slot turns a requested ``5`` into ``1084227584`` in game. If
    ``expect`` is given, the current value must match it (guards against
    base-data drift).

    Refuses to patch a *shadowed* value (one whose picker override flag is set,
    so the inline number is ignored in game). Pass ``allow_shadowed=True`` to
    force the write anyway, or call :func:`clear_value_override` first to make
    the inline value authoritative. Raises ``ValueError`` if the label has no
    resolvable value node.
    """
    names = class_names(data)
    if names is None:
        raise ValueError("not a parseable cooked container (no class table)")
    for lbl, _off, tc, voff, size, shadowed in _iter_value_nodes(data, names):
        if lbl != label:
            continue
        cur = _read_value(data, tc, voff)
        if expect is not None and abs(cur - expect) > 1e-4:
            raise ValueError(
                f"{label!r}: current value {cur} != expected {expect}")
        if shadowed and not allow_shadowed:
            raise ValueError(
                f"{label!r} is shadowed: its value is sourced from a "
                f"selector/reference (picker override set), so editing the "
                f"inline value has NO in-game effect. Call "
                f"clear_value_override(data, {label!r}) first to make the "
                f"inline value authoritative, or pass allow_shadowed=True to "
                f"force the (likely useless) write.")
        packed = _pack_value(tc, new_value)
        assert len(packed) == size
        return data[:voff] + packed + data[voff + size:]
    raise ValueError(f"talent value label {label!r} not found")


def list_union_values(data: bytes, label: str, *,
                      limit: int = 64) -> list[tuple[int, float, int]]:
    """Every ``oCEntityValueUnion`` inside the node named ``label``, in order.

    Returns ``(offset, value, type_code)`` per union. Unlike
    :func:`list_talent_values`, which resolves the ONE picker/union pair that a
    value node fronts, this walks a container that holds SEVERAL — a
    ``oCEntityCpntValueSelectorSettings`` with one
    ``oCEntityCpntValueSelectorEntrySettings`` per rarity tier, each entry's
    condition picker keyed to a ``[Dt Skill Controller]`` GUID and its unions
    carrying that tier's numbers. Red's
    ``Skill Primary Finisher Finisher Damage Multiplier Selector`` is the shape:
    an enabled-bool plus a damage multiplier per tier, 0.7 / 0.6 / 0.5 / 0.4.

    The walk is bounded by marker DEPTH, not by a byte window: it stops at the
    END that closes the node the label sits in. Without that it runs straight
    into the next selector's entries and indices silently mean nothing.
    """
    names = class_names(data)
    if names is None:
        return []
    pat = struct.pack("<I", len(label)) + label.encode("ascii")
    lo = data.find(pat)
    if lo < 0:
        raise ValueError(f"node label {label!r} not found")
    pos = lo + len(pat)
    depth = 0
    out: list[tuple[int, float, int]] = []
    while len(out) < limit:
        nb = data.find(_BEGIN, pos)
        ne = data.find(_END, pos)
        if ne < 0 and nb < 0:
            break
        if ne >= 0 and (nb < 0 or ne < nb):
            depth -= 1
            if depth < 0:
                break  # closed the node the label lives in
            pos = ne + 4
            continue
        depth += 1
        if _class_at(data, names, nb) == _UNION:
            end = data.find(_END, nb + 8)
            type_code = struct.unpack_from("<I", data, nb + 8)[0]
            size = _NUMERIC.get(type_code)
            if end >= 0 and size is not None and end - (nb + 8) == 8 + size:
                voff = nb + 16
                out.append((voff, _read_value(data, type_code, voff), type_code))
                depth -= 1  # this union's own END is consumed below
                pos = end + 4
                continue
        pos = nb + 8
    return out


def set_union_value(data: bytes, label: str, index: int, new_value: float,
                    *, expect: float | None = None) -> bytes:
    """Patch the ``index``-th ``oCEntityValueUnion`` under ``label``, in place.

    This reaches the per-rarity-tier numbers inside a value selector, which
    :func:`set_talent_value` cannot: that resolves a value node's single
    picker/union pair, while a selector holds one union per tier. Written as
    f32/int32/bool to match the union's own type code, length-preserving. If
    ``expect`` is given the current value must match it.
    """
    unions = list_union_values(data, label)
    if not 0 <= index < len(unions):
        raise ValueError(
            f"{label!r}: union index {index} out of range "
            f"(node has {len(unions)} numeric union(s))")
    voff, cur, type_code = unions[index]
    if expect is not None and abs(cur - expect) > 1e-4:
        raise ValueError(
            f"{label!r} union {index}: current value {cur} != expected {expect}")
    packed = _pack_value(type_code, new_value)
    return data[:voff] + packed + data[voff + len(packed):]


def clear_value_override(data: bytes, label: str) -> bytes:
    """Disable a value node's picker override so its inline value becomes
    authoritative (variable-length edit; the node ends up shaped like a normal
    authored value node). This is the fix for a shadowed value: after calling
    it, :func:`set_talent_value` for ``label`` takes effect in game.

    Side effect: dropping the override unbinds the value from its source
    selector/curve — e.g. for a card-count "amount-per-stack" value this turns
    the scaling into a flat value. Intended; that is what makes the inline
    number the one the game reads. Raises ``ValueError`` if ``label`` has no
    resolvable value node or is not actually overridden.
    """
    from .entity_edit import EntityEdit

    ed = EntityEdit(data)
    c = ed.concat
    names = class_names(data)
    if names is None:
        raise ValueError("not a parseable cooked container (no class table)")
    pat = struct.pack("<I", len(label)) + label.encode("ascii")
    lo = c.find(pat)
    if lo < 0:
        raise ValueError(f"value label {label!r} not found")
    after = lo + len(pat)
    p1 = c.find(_BEGIN, after, after + _MAX_LABEL_GAP)
    if p1 < 0 or _class_at(c, names, p1) != _PICKER:
        raise ValueError(f"{label!r} has no value-picker node")
    p2 = c.find(_BEGIN, p1 + 8, p1 + 8 + _MAX_PICKER_GAP)
    if p2 < 0 or _class_at(c, names, p2) != _UNION:
        raise ValueError(f"{label!r}: malformed picker/union pair")
    payload = c[p1 + 8:p2]
    if not payload or payload[0] == 0:
        raise ValueError(f"{label!r} is not overridden (nothing to clear)")
    ed.queue(p1 + 8, len(payload), b"\x00")  # collapse to the disabled form
    return ed.emit()
