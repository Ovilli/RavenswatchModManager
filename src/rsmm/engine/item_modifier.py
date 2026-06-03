"""Swap which stat a magical object's base vs super-effect modifier applies.

Ghidra (``oCEntityCpntModifierSettings``, ctor ``FUN_140729f10``) showed an
item's modifier carries **no** in-item "stat type" field — the stat a modifier
applies is carried by the **value node** it reads (``Damage Value`` -> attack
damage, ``Attack Speed Value`` -> attack speed), resolved hero-side. So to swap
which stat is always-on (base) vs gated (super-effect), swap the identity of the
two value nodes the modifiers read.

In the cooked stream a value node appears as ``<16-byte GUID><u32 namelen><name>``
at every site that uses it (the GUID-then-name identity is repeated, there is no
bare-pointer form). :func:`swap_guids` exchanges two value-node GUIDs at **every**
occurrence — the generalised, length-preserving form of the Ace-of-Spades hand
swap. Names are NOT unique (``Damage Value`` exists as both a gameplay node and a
card-count node), so the swap is GUID-targeted; resolve the right GUID with
:func:`value_node_guids` and pick the one at the gameplay modifier site.

VERIFICATION: this rests on the empirical "stat follows the value node" finding;
it still needs an in-game check per item. If wrong, the alternative is renaming
the nodes via :class:`rsmm.engine.entity_edit.EntityEdit` (variable length).
"""

from __future__ import annotations

import struct

_MARKERS = (b"\x11\x11\xbb\xaa", b"\x22\x22\xbb\xaa")


def _name_sites(data: bytes, node_name: str) -> list[int]:
    """Offsets of every ``<u32 namelen><name>`` occurrence of ``node_name``."""
    pat = struct.pack("<I", len(node_name)) + node_name.encode("utf-8")
    out, i = [], 0
    while True:
        j = data.find(pat, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def _guid_before(data: bytes, name_off: int) -> bytes:
    g = data[name_off - 16:name_off]
    if name_off < 16 or g == b"\x00" * 16 or any(m in g for m in _MARKERS):
        raise ValueError(f"no GUID precedes name at {name_off}")
    return g


def value_node_guids(cooked: bytes, node_name: str) -> list[bytes]:
    """Every DISTINCT identity GUID that appears before ``node_name``.

    Node names are NOT unique — e.g. ``Damage Value`` is both the gameplay
    modifier's node and a card-count/description node, each with its own GUID.
    A by-name swap would hit both, so the caller must pick the right GUID (the
    gameplay one) before swapping. Order = first appearance.
    """
    seen, out = set(), []
    for o in _name_sites(cooked, node_name):
        g = _guid_before(cooked, o)
        if g not in seen:
            seen.add(g)
            out.append(g)
    if not out:
        raise ValueError(f"value node {node_name!r} not found")
    return out


def swap_guids(cooked: bytes, guid_a: bytes, guid_b: bytes) -> bytes:
    """Swap two 16-byte value-node GUIDs everywhere they appear, length-
    preserving. This re-points every consumer of node A at node B and vice
    versa (the generalised, GUID-targeted form of the Ace-of-Spades swap).

    The caller resolves the right GUIDs via :func:`value_node_guids` (and, when
    a name is ambiguous, by inspecting which GUID sits at the gameplay modifier
    site). Returns patched bytes; raises if a GUID isn't present.
    """
    if len(guid_a) != 16 or len(guid_b) != 16:
        raise ValueError("GUIDs must be 16 bytes")
    if guid_a == guid_b:
        raise ValueError("guid_a and guid_b are identical")
    if guid_a not in cooked or guid_b not in cooked:
        raise ValueError("one or both GUIDs not present in the cooked bytes")

    def _all(sub: bytes) -> list[int]:
        out, i = [], 0
        while (j := cooked.find(sub, i)) >= 0:
            out.append(j)
            i = j + 1
        return out

    # snapshot offsets on the original so the two passes don't interfere
    offs_a, offs_b = _all(guid_a), _all(guid_b)
    buf = bytearray(cooked)
    for o in offs_a:
        buf[o:o + 16] = guid_b
    for o in offs_b:
        buf[o:o + 16] = guid_a
    assert len(buf) == len(cooked)
    return bytes(buf)
