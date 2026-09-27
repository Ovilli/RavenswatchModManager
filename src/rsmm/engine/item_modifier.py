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

import binascii
import functools
import re
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
    """Stat display name -> key: the engine's registered values (generated from
    ``data/stat_keys.json``) plus the game's data-defined ones, read from the
    player's install (:func:`data_value_names`)."""
    from ._stat_keys_gen import STAT_KEYS
    extra = {n: k for n, k in data_value_names().items()
             if n not in STAT_KEYS and k not in STAT_KEYS.values()}
    return {**STAT_KEYS, **extra} if extra else STAT_KEYS


def data_value_key(label: str) -> int:
    """The key of a data-defined entity value, from its label.

    ``ApplicationSettings.ot`` declares ~50 values beyond the engine's own
    registry (``Basic Attack Speed``, ``Has Excalibur``, the ability-charge
    counters, …), which is why 36 modifier keys had no name in
    ``stat_keys.json``. The engine keys each by name: ``c = CRC32(label)``,
    then CRC32 again over ``0, c0, 0, c1, 0, c2, 0, c3`` (FUN_14051f090 called
    as ``(0, c)``; the table is the standard CRC32 one, FUN_14051ef30).
    Checked against three shipped modifiers: Ace of Spades' super effect
    (``0x058e0a5c``) is ``Basic Attack Speed``."""
    c = binascii.crc32(label.encode("utf-8")) & 0xFFFFFFFF
    mixed = bytes(b for i in range(4) for b in (0, (c >> (8 * i)) & 0xFF))
    return binascii.crc32(mixed) & 0xFFFFFFFF


_VALUE_DESC = "oSModifierValueDesc"


@functools.lru_cache(maxsize=1)
def data_value_names() -> dict[str, int]:
    """Label -> key of every data-defined entity value in the install's
    ``ApplicationSettings.ot`` (its pristine copy when a mod replaced it).
    Empty when no install is readable: the labels are game data, so they are
    read from the player's files rather than kept in the repo."""
    from .hero_cook import pristine_app_settings
    try:
        from rsmm.cli.apply_mods import find_game_dir
        game = find_game_dir()
        text = pristine_app_settings(game) if game else None
    except (OSError, ImportError):
        text = None
    if not text:
        return {}
    cls = next((m.group(1) for m in re.finditer(r"^\*Class(\d+)=(\w+)\[", text, re.M)
                if m.group(2) == _VALUE_DESC), None)
    if cls is None:
        return {}
    out: dict[str, int] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^SingleObject\d+=C(\d+)$", line)
        if m:
            current = m.group(1)
        elif current == cls and line.startswith("s|m_sLabel="):
            label = line.split("=", 1)[1].strip()
            if label:
                out.setdefault(label, data_value_key(label))
            current = None
    return out


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

def _format_key(payload: bytes, bank_name: str = _TEXT_BANK) -> str | None:
    """The text key a String Format component shows: ``"Text"``, the bank,
    a u32 row index, then the key."""
    bank = struct.pack("<I", len(bank_name)) + bank_name.encode()
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


# --- card text placeholders --------------------------------------------------

_REF_LABEL = re.compile(rb"([\x05-\xff])\x00\x00\x00(\[[A-Za-z ]+\] [ -~]+)")
_FORMAT_TAIL = b'""\xbb\xaa""\xbb\xaa'
_FORMAT_CLASS = "oCEntityCpntStringFormatValueSettings"
_ENTRY_CLASS = "oCStringFormatEntryPicker"


def _labels(payload: bytes, start: int = 0) -> list[str]:
    """Every ``[Kind] path`` reference label from ``start``, in order."""
    return [payload[m.start(2):m.start(2) + m.group(1)[0]].decode("utf-8", "replace")
            for m in _REF_LABEL.finditer(payload, start)]


@dataclass(frozen=True)
class Placeholder:
    """What fills one ``{N}`` of a card text."""
    node: str            # the node's own name, e.g. ``Vitality Step Value``
    kind: str            # its bracket kind: ``Value``, ``Multi values operations``, ...
    sources: tuple[str, ...] = ()   # the [Value] nodes a computed node reads


@dataclass(frozen=True)
class CardFormat:
    key: str                                  # the text-bank key
    entries: tuple[Placeholder | None, ...]   # {0}, {1}, ...; None = not a named node


def card_formats(cooked_bytes: bytes) -> dict[str, CardFormat]:
    """Every String Format of an item that reads the magical-object text bank,
    by the format's own name (``Descripton Format``, ``Super Effect Descripton
    Format``, ...). See :func:`text_formats`."""
    return dict(text_formats(cooked_bytes, _TEXT_BANK))


def _entry_labels(payload: bytes, start: int, count: int,
                  names: list[str]) -> list[str | None]:
    """The reference label of each of a format's ``count`` entries, None for
    an entry holding an inline value. Each entry is one
    ``oCStringFormatEntryPicker`` object, so the payload is split at those; when
    they cannot be found the labels must line up one-for-one, or all are None."""
    from .cooked import MARK_BEGIN
    if count == 0:
        return []
    if _ENTRY_CLASS in names:
        mark = MARK_BEGIN + struct.pack("<I", names.index(_ENTRY_CLASS))
        starts, i = [], payload.find(mark, start)
        while i >= 0 and len(starts) < count:
            starts.append(i)
            i = payload.find(mark, i + len(mark))
        if len(starts) == count:
            ends = [*starts[1:], len(payload)]
            out = []
            for a, b in zip(starts, ends, strict=True):
                found = _labels(payload[a:b])
                out.append(found[0] if found else None)
            return out
    labels = _labels(payload, start)
    return list(labels) if len(labels) == count else [None] * count


def formats_by_key(cooked_bytes: bytes, bank_name: str) -> dict[str, CardFormat]:
    """Every String Format that reads ``bank_name``, by the text key it shows
    (the first format wins when two show the same key). A hero's talent cards
    are found this way: their keys are known, the formats' names are not."""
    out: dict[str, CardFormat] = {}
    for _name, fmt in text_formats(cooked_bytes, bank_name):
        out.setdefault(fmt.key, fmt)
    return out


def text_formats(cooked_bytes: bytes, bank_name: str) -> list[tuple[str, CardFormat]]:
    """``(format name, format)`` for every String Format reading ``bank_name``.

    After the key a format stores ``u32 count`` and one picker per ``{N}``, in
    order. A picker that points at a node carries that node's ``[Kind] path``
    label; one holding an inline value carries none, and when the labels do not
    line up one-for-one with ``count`` the whole mapping is dropped rather than
    guessed (9 of the 143 shipped formats).
    """
    from . import cooked
    bank = struct.pack("<I", len(bank_name)) + bank_name.encode()
    if bank not in cooked_bytes:
        return []
    cf = cooked.parse(cooked_bytes)
    names = [c.name for c in cf.classes]
    own = {}
    for sec in cf.sections[1:-1]:
        name = _own_name(sec.payload)
        if name:
            own.setdefault(name, sec.payload)
    out: list[tuple[str, CardFormat]] = []
    for sec in cf.sections[1:-1]:
        p = sec.payload
        name = _own_name(p)
        key = _format_key(p, bank_name)
        if not name or key is None or _class_of(p, names) != _FORMAT_CLASS:
            continue
        end = p.find(bank) + len(bank) + 4 + 4 + len(key)
        tail = p[end:end + 12]
        if len(tail) < 12 or tail[:8] != _FORMAT_TAIL:
            out.append((name, CardFormat(key=key, entries=())))
            continue
        count = struct.unpack_from("<I", tail, 8)[0]
        if count > 64:
            out.append((name, CardFormat(key=key, entries=())))
            continue
        labels = _entry_labels(p, end + 12, count, names)
        entries = []
        for label in labels:
            if label is None:
                entries.append(None)
                continue
            kind = label[1:label.index("]")]
            node = label.rsplit("\\", 1)[-1]
            sources: tuple[str, ...] = ()
            if kind != "Value" and node in own:
                sources = tuple(dict.fromkeys(
                    lab.rsplit("\\", 1)[-1] for lab in _labels(own[node])
                    if lab.startswith("[Value] ")))
            entries.append(Placeholder(node=node, kind=kind, sources=sources))
        out.append((name, CardFormat(key=key, entries=tuple(entries))))
    return out
