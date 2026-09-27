"""Which stat a magical object's modifiers change, and its super-effect text.

Every ``oCEntityCpntModifierSettings`` record carries a 4-byte **stat key**
(:func:`rsmm.engine.entity_append.modifier_stat_off`; all 496 shipped modifiers,
144 of them on magical objects). It is the key of the entity value the modifier
changes -- the same key ``data/stat_keys.json`` names (``Attack power``,
``Crit chance``, ``Armour`` = 0, ...). Changing the stat is rewriting those 4
bytes: length-preserving, no GUID or reference moves.

* :func:`list_modifiers` -- every modifier of an item, its stat, and whether it
  belongs to the SUPER EFFECT (a state whose name contains "super" owns it:
  ``Child State SuperEffect``, ``Child State Super Effect``, ``State Super
  Effect Active``). Modifier names are unique within each shipped item.
* :func:`set_modifier_stat` -- point one modifier at another stat.
* :func:`super_text_key` / :func:`set_super_text_key` -- the text-bank key the
  item's ``Super Effect Descripton Format`` (the game's spelling) shows, so a
  copy can carry super-effect text of its own.

An older reading of this module ("a modifier carries NO stat type field; the
stat follows the value node it reads") was wrong; :func:`swap_guids` is kept
from it as a generic GUID-swap primitive.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

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


# --- modifier stats ----------------------------------------------------------

_MODIFIER_CLASS = "oCEntityCpntModifierSettings"
_STATE_CLASS = "oCEntityCpntStateSettings"
_SUPER_FORMAT = "Super Effect Descripton Format"   # sic, the game's spelling
_TEXT_BANK = "Magical_Objects~GAM.xls"


class ItemModifierError(ValueError):
    """An edit that does not fit the item it is applied to."""


@dataclass(frozen=True)
class Modifier:
    name: str            # the modifier component's own name
    key: int             # the u32 stat key it stores
    stat: str | None     # the catalog name for ``key``, None when unnamed
    super_effect: bool   # owned by a super-effect state


def stat_catalog() -> dict[str, int]:
    """Stat display name -> key (generated from ``data/stat_keys.json``)."""
    from ._stat_keys_gen import STAT_KEYS
    return STAT_KEYS


def stat_name(key: int) -> str | None:
    return next((n for n, k in stat_catalog().items() if k == key), None)


def resolve_stat(stat: str | int) -> int:
    """A stat as a key: its catalog name (case-insensitive), a ``0x...`` hex
    key, or an int. Unnamed keys are accepted so an item can reuse one that a
    shipped item already stores (22 of them have no catalog name)."""
    if isinstance(stat, bool):
        raise ItemModifierError(f"not a stat: {stat!r}")
    if isinstance(stat, int):
        key = stat
    else:
        text = str(stat).strip()
        cat = stat_catalog()
        if text in cat:
            return cat[text]
        low = {n.lower(): k for n, k in cat.items()}
        if text.lower() in low:
            return low[text.lower()]
        try:
            key = int(text, 16) if text.lower().startswith("0x") else None
        except ValueError:
            key = None
        if key is None:
            raise ItemModifierError(
                f"unknown stat {stat!r}; use a name from data/stat_keys.json "
                f"(e.g. 'Attack power', 'Crit chance', 'Armour') or a 0x key")
    if not 0 <= key <= 0xFFFFFFFF:
        raise ItemModifierError(f"stat key {stat!r} is not a u32")
    return key


def _own_name(payload: bytes) -> str | None:
    from .entity_append import _header_name_at
    at = _header_name_at(payload)
    if at is None or at + 4 > len(payload):
        return None
    n = struct.unpack_from("<I", payload, at)[0]
    if n > 512 or at + 4 + n > len(payload):
        return None
    return payload[at + 4:at + 4 + n].decode("utf-8", "replace")


def _class_of(payload: bytes, names: list[str]) -> str | None:
    if len(payload) < 4:
        return None
    ci = struct.unpack_from("<I", payload, 0)[0]
    return names[ci] if ci < len(names) else None


def list_modifiers(cooked_bytes: bytes) -> list[Modifier]:
    """Every modifier component of an item, in file order."""
    from . import cooked
    from .entity_append import modifier_stat_off

    cf = cooked.parse(cooked_bytes)
    names = [c.name for c in cf.classes]
    mods: list[tuple[str, int]] = []
    super_states: list[bytes] = []
    for sec in cf.sections[1:-1]:
        cls = _class_of(sec.payload, names)
        if cls == _MODIFIER_CLASS:
            name = _own_name(sec.payload)
            if name is None:
                continue
            off = modifier_stat_off(sec.payload, names)
            mods.append((name, struct.unpack_from("<I", sec.payload, off)[0]))
        elif cls == _STATE_CLASS and "super" in (_own_name(sec.payload) or "").lower():
            super_states.append(sec.payload)
    out = []
    for name, key in mods:
        # A state names its modifiers through `[Modifier] <item>\<name>` labels.
        label = ("\\" + name).encode("utf-8")
        out.append(Modifier(name=name, key=key, stat=stat_name(key),
                            super_effect=any(label in p for p in super_states)))
    return out


def set_modifier_stat(cooked_bytes: bytes, modifier: str, stat: str | int) -> bytes:
    """Point the modifier named ``modifier`` at another stat (length-preserving)."""
    from . import cooked
    from .entity_append import EntityAppendError, modifier_stat_off, node_section

    key = resolve_stat(stat)
    cf = cooked.parse(cooked_bytes)
    names = [c.name for c in cf.classes]
    try:
        idx = node_section(cf, modifier)
    except EntityAppendError:
        have = ", ".join(repr(m.name) for m in list_modifiers(cooked_bytes)) or "none"
        raise ItemModifierError(
            f"no modifier named {modifier!r} (this item has: {have})") from None
    sec = cf.sections[idx]
    if _class_of(sec.payload, names) != _MODIFIER_CLASS:
        raise ItemModifierError(f"{modifier!r} is not a modifier")
    off = modifier_stat_off(sec.payload, names)
    sec.payload = sec.payload[:off] + struct.pack("<I", key) + sec.payload[off + 4:]
    out = cooked.emit(cf)
    if len(out) != len(cooked_bytes):
        raise ItemModifierError("stat edit changed the file length")
    return out


# --- super-effect text -------------------------------------------------------

def _format_key(payload: bytes) -> str | None:
    """The text key a String Format component shows: ``"Text"``, the bank,
    a u32 row index, then the key."""
    bank = struct.pack("<I", len(_TEXT_BANK)) + _TEXT_BANK.encode()
    i = payload.find(bank)
    if i < 0:
        return None
    j = i + len(bank) + 4
    if j + 4 > len(payload):
        return None
    n = struct.unpack_from("<I", payload, j)[0]
    raw = payload[j + 4:j + 4 + n]
    if len(raw) != n or not all(0x20 <= b < 0x7F for b in raw):
        return None
    return raw.decode("ascii")


def super_text_key(cooked_bytes: bytes) -> str | None:
    """The key the item's super-effect card text is read from, or None when
    the item has no super effect text (every cursed, legendary and power-up)."""
    from . import cooked
    if _SUPER_FORMAT.encode() not in cooked_bytes:
        return None
    cf = cooked.parse(cooked_bytes)
    for sec in cf.sections[1:-1]:
        if _own_name(sec.payload) == _SUPER_FORMAT:
            return _format_key(sec.payload)
    return None


def set_super_text_key(cooked_bytes: bytes, new_key: str) -> bytes:
    """Repoint the super-effect text at ``new_key`` (every place the item uses
    the old key, e.g. Copy_Card's feedback line too). The row index beside the
    key is left alone: the engine looks text up by key, which is how every
    custom item's own name/description key already works in game."""
    from .magic_item_cook import replace_lstr_any
    old = super_text_key(cooked_bytes)
    if old is None:
        raise ItemModifierError("this item has no super effect text")
    return replace_lstr_any(cooked_bytes, old, new_key)
