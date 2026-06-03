"""Talent (in-game "Skill") value discovery + patching.

Ravenswatch talents are internally "Skills". A hero's talent *roster* (which
nodes exist + their tree slots) lives as ``Skill Controller <X>`` nodes inside
the herodef (``Definitions/Heroes/<Hero>.herodef...gen``). The talent *effect
magnitudes* — the numbers people want to change — live as little-endian f32s
inside the hero's cooked **entity** files under
``EntitySettings/Heroes/Hero_<Hero>/*.entity.ot.EntitySettingsResource.gen``.

Each magnitude is an ``oCEntityCpntValueSettings`` node whose value sits at the
very end of the node body, immediately before the closing ``2222bbaa`` END
marker:

    <u32 len><label "Skill ... Value"> ... 1111bbaa <clsid> 00
        1111bbaa <subid> 00 .. 00 <FLOAT> 2222bbaa 2222bbaa

So the reliable read is: anchor on the ``... Value`` label, scan forward to the
next ``2222bbaa``, take the 4 bytes before it. (The older item heuristic in
:mod:`magic_item_cook` reads the f32 a few bytes *after* the label — correct
for items, wrong for these entity nodes, which is why it surfaced noise.)

Two label families:

* ``Skill <X> ... Value`` (no "Spawner") — an authored magnitude (e.g. ``Skill
  Power Cone Damage Range Value`` = 7.0). **Editable.**
* ``... Spawner Value`` — a runtime spawner slot, always 0.0 at rest. These are
  written by code at spawn time; patching them does nothing. Filtered out by
  default.

The patch is f32->f32, length-preserving, so a talent mod is just a byte-edited
copy of the vanilla entity shipped as a plain asset override (no re-cook). The
writer is :func:`rsmm.engine.magic_item_cook.set_value_after_label`, which
anchors on label + exact old-value bytes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_END = b"\x22\x22\xbb\xaa"
_BEGIN = b"\x11\x11\xbb\xaa"
#: A value node carries an ``0e``-type sub-section just before its ``0f`` value
#: section. Its payload is a single ``0x00`` when the inline float is what the
#: game uses, or a non-zero flag + a 4-byte reference when the value is *sourced
#: from elsewhere* (a Value Selector / curve / card-count amount) — in which
#: case the inline float is dead and editing it has no in-game effect. Detecting
#: this is what stops a modder silently patching a shadowed value (the
#: Damage_Power "Damage Value" bug).
_OVERRIDE_TAG = _BEGIN + struct.pack("<I", 0x0e)
#: Max bytes between a value label and its closing END marker. Observed worst
#: case ~80 (label, two node headers, padding, the f32); 160 is slack.
_MAX_NODE_SPAN = 160


@dataclass(frozen=True)
class TalentValue:
    label: str
    value: float
    #: Absolute byte offset of the value in the cooked file (for patching/debug).
    offset: int
    #: True for ``... Spawner Value`` runtime slots (always ~0.0, not authored).
    is_spawner: bool
    #: True when the 4 bytes are an int32 count, not an f32 magnitude (e.g.
    #: ``Objective Count`` = 7). ``value`` then holds the integer as a float.
    is_int: bool = False
    #: True when the node's value is sourced from a selector/reference (its ``0e``
    #: override sub-field is enabled), so the inline ``value`` here is *shadowed*
    #: — editing it does nothing in game. Disable the override (see
    #: :func:`clear_value_override`) to make the inline value authoritative.
    is_overridden: bool = False


#: Suffixes that mark an authored gameplay magnitude/count node. Value covers
#: f32 effect magnitudes; the rest catch int32 counts and common stat fields.
_VALUE_SUFFIXES = ("Value", "Count", "Required", "Max", "Stock", "Object",
                   "Cooldown", "Duration", "Radius", "Range", "Multiplier",
                   "Ratio", "Chance", "Threshold", "Distance", "Amount")
#: Structural node names that carry a number but are wiring, not authored data.
_STRUCT_NAMES = ("Operation", "Selector", "Listener", "Modifier", "Tester",
                 "Traverser", "Store", "Picker", "Format", "Computer", "State")


def _is_authored_value_label(s: str) -> bool:
    """True for a node name that looks like an authored magnitude/count (not a
    structural/wiring node or a scoped ``[...]`` reference)."""
    if s.startswith("[") or "Get" in s or any(k in s for k in _STRUCT_NAMES):
        return False
    return any(s.endswith(suf) for suf in _VALUE_SUFFIXES)


def _classify(raw4: bytes) -> tuple[float, bool]:
    """Return ``(value, is_int)`` for a 4-byte value field.

    A count node stores an int32 whose f32 reinterpretation is a subnormal
    (e.g. int 7 -> 9.8e-45). We treat the field as int when the f32 is a tiny
    subnormal *and* the int32 is a small positive count; otherwise f32.
    """
    fv = struct.unpack("<f", raw4)[0]
    iv = struct.unpack("<i", raw4)[0]
    if 0 < abs(fv) < 1e-30 and 1 <= iv <= 1_000_000:
        return float(iv), True
    return fv, False


def _value_is_overridden(cooked: bytes, body_start: int, value_end: int) -> bool:
    """True when the value node in ``[body_start, value_end)`` has its ``0e``
    override sub-field enabled (value comes from a selector/reference, so the
    inline float just before ``value_end`` is shadowed and not used in game).

    The ``0e`` section payload is a lone ``0x00`` when the inline value is
    authoritative (the normal case, e.g. every working talent/crit node) and
    ``0x01 ...<ref>`` when overridden (e.g. Damage_Power's card-count Damage
    Value). Compared this way it stays a conservative warning: it only fires
    when the inline value genuinely cannot take effect.
    """
    h = cooked.find(_OVERRIDE_TAG, body_start, value_end)
    if h < 0:
        return False
    p = h + len(_OVERRIDE_TAG)
    nxt = cooked.find(_BEGIN, p, value_end)
    if nxt < 0:
        return False
    payload = cooked[p:nxt]
    return bool(payload) and payload[0] != 0


def is_label_overridden(cooked: bytes, label: str) -> bool:
    """Public check: is the value node named ``label`` *shadowed* (its ``0e``
    override sub-field enabled, so its inline float is ignored in game)?

    Resolves the label to its node body and reuses :func:`_value_is_overridden`.
    Returns ``False`` when the label or its END marker isn't found (nothing to
    shadow). Used by the item cook path (:func:`magic_item_cook.build_magic_item`)
    so a manifest ``value_patches`` edit can't silently no-op on a shadowed node.
    """
    pat = struct.pack("<I", len(label)) + label.encode("ascii")
    lo = cooked.find(pat)
    if lo < 0:
        return False
    body = lo + len(pat)
    end = cooked.find(_END, body)
    if end < 0:
        return False
    return _value_is_overridden(cooked, body, end)


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


def list_talent_values(cooked: bytes, *, include_spawner: bool = False) -> list[TalentValue]:
    """Discover editable talent magnitudes in one cooked hero-entity file.

    Returns the f32 sitting just before each value node's END marker. By
    default drops ``... Spawner Value`` runtime slots (always 0.0). De-dupes by
    label, first occurrence wins.
    """
    out: list[TalentValue] = []
    seen: set[str] = set()
    for off, s in _iter_lstrings(cooked):
        if s in seen or not _is_authored_value_label(s):
            continue
        start = off + 4 + len(s.encode("ascii"))
        end = cooked.find(_END, start)
        if end < 0 or end - start > _MAX_NODE_SPAN or end < start + 4:
            continue
        v, is_int = _classify(cooked[end - 4:end])
        if v != v or (not is_int and abs(v) >= 1e9):  # NaN / implausible
            continue
        is_spawner = s.endswith("Spawner Value")
        if is_spawner and not include_spawner:
            seen.add(s)
            continue
        seen.add(s)
        overridden = _value_is_overridden(cooked, start, end)
        out.append(TalentValue(s, v if is_int else round(v, 4),
                               end - 4, is_spawner, is_int, overridden))
    return out


def set_talent_value(cooked: bytes, label: str, new_value: float,
                     *, expect: float | None = None,
                     allow_shadowed: bool = False) -> bytes:
    """Patch one talent magnitude by label, length-preserving.

    Unlike :func:`magic_item_cook.set_value_after_label` (which overwrites the
    first matching old-value bytes after the label — unreliable here, because a
    talent node's value sits before the END marker and an identical value can
    appear in a nearer field), this overwrites the exact field that
    :func:`list_talent_values` resolves for ``label``. The field is written as
    int32 or f32 to match the node's detected kind (count nodes like
    ``Objective Count`` are int32). If ``expect`` is given, the current value
    must match it (guards against base-data drift).

    Refuses to patch a *shadowed* value (one whose ``0e`` override sub-field is
    enabled, so the inline float is ignored in game) — this is the guard that
    stops the silent no-op that hit Damage_Power's "Damage Value". Pass
    ``allow_shadowed=True`` to force the write anyway, or call
    :func:`clear_value_override` first to make the inline value authoritative.
    Raises ``ValueError`` if the label has no resolvable value.
    """
    for tv in list_talent_values(cooked, include_spawner=True):
        if tv.label != label:
            continue
        if expect is not None and abs(tv.value - expect) > 1e-4:
            raise ValueError(
                f"{label!r}: current value {tv.value} != expected {expect}")
        if tv.is_overridden and not allow_shadowed:
            raise ValueError(
                f"{label!r} is shadowed: its value is sourced from a "
                f"selector/reference (0e override enabled), so editing the "
                f"inline float has NO in-game effect. Call "
                f"clear_value_override(cooked, {label!r}) first to make the "
                f"inline value authoritative, or pass allow_shadowed=True to "
                f"force the (likely useless) write.")
        off = tv.offset
        packed = (struct.pack("<i", int(round(new_value))) if tv.is_int
                  else struct.pack("<f", new_value))
        return cooked[:off] + packed + cooked[off + 4:]
    raise ValueError(f"talent value label {label!r} not found")


def clear_value_override(cooked: bytes, label: str) -> bytes:
    """Disable a value node's ``0e`` override sub-field so its inline float
    becomes authoritative (variable-length edit; the node ends up shaped like a
    normal authored value node). This is the fix for a shadowed value: after
    calling it, :func:`set_talent_value` for ``label`` takes effect in game.

    Side effect: dropping the override unbinds the value from its source
    selector/curve — e.g. for a card-count "amount-per-stack" value this turns
    the scaling into a flat value. Intended; that is what makes the inline
    number the one the game reads. Raises ``ValueError`` if ``label`` has no
    resolvable value or is not actually overridden.
    """
    from .entity_edit import EntityEdit

    ed = EntityEdit(cooked)
    c = ed.concat
    pat = struct.pack("<I", len(label)) + label.encode("ascii")
    lo = c.find(pat)
    if lo < 0:
        raise ValueError(f"value label {label!r} not found")
    body = lo + len(pat)
    end = c.find(_END, body)
    if end < 0:
        raise ValueError(f"no END marker after {label!r}")
    h = c.find(_OVERRIDE_TAG, body, end)
    if h < 0:
        raise ValueError(f"{label!r} has no 0e sub-section")
    p = h + len(_OVERRIDE_TAG)
    nxt = c.find(_BEGIN, p, end)
    if nxt < 0:
        raise ValueError(f"{label!r}: malformed 0e sub-section")
    payload = c[p:nxt]
    if not payload or payload[0] == 0:
        raise ValueError(f"{label!r} is not overridden (nothing to clear)")
    ed.queue(p, len(payload), b"\x00")  # collapse to the disabled form
    return ed.emit()
