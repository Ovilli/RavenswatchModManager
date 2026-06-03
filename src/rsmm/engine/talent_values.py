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
#: Max bytes between a value label and its closing END marker. Observed worst
#: case ~80 (label, two node headers, padding, the f32); 160 is slack.
_MAX_NODE_SPAN = 160


@dataclass(frozen=True)
class TalentValue:
    label: str
    value: float
    #: Absolute byte offset of the f32 in the cooked file (for patching/debug).
    offset: int
    #: True for ``... Spawner Value`` runtime slots (always ~0.0, not authored).
    is_spawner: bool


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
        if not s.endswith("Value") or s.startswith("[") or "Get" in s or s in seen:
            continue
        start = off + 4 + len(s.encode("ascii"))
        end = cooked.find(_END, start)
        if end < 0 or end - start > _MAX_NODE_SPAN or end < start + 4:
            continue
        v = struct.unpack_from("<f", cooked, end - 4)[0]
        if v != v or abs(v) >= 1e9:  # NaN / implausible -> not a real magnitude
            continue
        is_spawner = s.endswith("Spawner Value")
        if is_spawner and not include_spawner:
            seen.add(s)
            continue
        seen.add(s)
        out.append(TalentValue(s, round(v, 4), end - 4, is_spawner))
    return out


def set_talent_value(cooked: bytes, label: str, new_value: float,
                     *, expect: float | None = None) -> bytes:
    """Patch one talent magnitude by label, length-preserving.

    Unlike :func:`magic_item_cook.set_value_after_label` (which overwrites the
    first matching old-value bytes after the label — unreliable here, because a
    talent node's f32 sits before the END marker and an identical value can
    appear in a nearer field), this overwrites the exact f32 that
    :func:`list_talent_values` resolves for ``label``. If ``expect`` is given,
    the current value must match it (guards against a base-data drift). Raises
    ``ValueError`` if the label has no resolvable value.
    """
    for tv in list_talent_values(cooked, include_spawner=True):
        if tv.label != label:
            continue
        if expect is not None and abs(tv.value - expect) > 1e-4:
            raise ValueError(
                f"{label!r}: current value {tv.value} != expected {expect}")
        off = tv.offset
        return cooked[:off] + struct.pack("<f", new_value) + cooked[off + 4:]
    raise ValueError(f"talent value label {label!r} not found")
