"""Hero **skill** (talent) row cloning inside a cooked herodef.

A hero's skills ("talents") are serialised as a flat run of self-contained
nodes inside ``Definitions/Heroes/<Hero>.herodef.ot.DtHeroDefinition.gen``. Each
row is a ``1111bbaa <u32 class=4> 00 <lstring name> <16B GUID#1> ... <16B GUID#2>
00*N 2222bbaa`` blob (see ``docs/_re/kinds/skills-system.md`` for the full RE):

* ``name``     length-prefixed ascii ``"Skill Controller <X>"`` (the skill key)
* ``GUID #1``  the skill's IDENTITY handle (16 bytes, right after the name)
* ``GUID #2``  a REF handle (16 bytes, near the row end) -> effect/def entity
* upgrade/legendary tiers are *extra rows* named ``"... Upgrade <n>"``

This module clones a row to make a NEW skill that is hero-specific by
construction (it lives in one hero's herodef) and shows in the hero page. Two
modes:

* :func:`repoint_skill` — rewrite an EXISTING row in place (count-neutral,
  byte-safe, the conservative path). Keeps the slot's tier/upgrade wiring.
* :func:`clone_skill` — duplicate a row and splice the copy in (a *net-new*
  skill). EXPERIMENTAL: the skill-vector's count/terminator representation is
  not confirmable offline (no plain count field precedes the rows), so a freshly
  inserted row must be proven to load in-game. See the module's ``CAVEAT``.

The companion runtime layer binds custom *behaviour* to a cloned skill's GUID#1
via ``R.talent.on_pick("<lo>:<hi>", ...)`` (the asset supplies the visible card;
the Lua supplies the effect). Identity GUIDs are reminted with
:func:`mint_guid` unless the caller supplies one.

CAVEAT (clone_skill): inserting a row assumes the deserialiser reads skill rows
until the next non-skill node (marker/terminator-delimited), not from a leading
count. If a hidden count exists, the extra row is ignored until that count is
bumped. This is gated EXPERIMENTAL and must be validated by an in-game hero-page
check before being trusted.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

_BEGIN = bytes.fromhex("1111bbaa")
_END = bytes.fromhex("2222bbaa")
_ROW_CLASS = 4  # the <u32 class> after BEGIN that opens a skill-controller row
_NAME_PREFIX = b"Skill Controller "
#: How far back from a name lstring to look for the row's opening BEGIN marker.
_BEGIN_LOOKBACK = 12


class SkillCloneError(ValueError):
    """Raised on malformed input or an unresolvable skill row."""


@dataclass(frozen=True)
class SkillRow:
    """One skill row located in a herodef blob."""

    name: str
    begin: int  # offset of the row's 1111bbaa
    end: int  # offset just AFTER the row's closing 2222bbaa
    name_off: int  # offset of the name lstring's u32 length prefix
    guid1_off: int  # offset of identity GUID (16 bytes, right after the name)

    @property
    def size(self) -> int:
        return self.end - self.begin

    def raw(self, blob: bytes) -> bytes:
        return blob[self.begin:self.end]


def mint_guid(seed: bytes | None = None) -> bytes:
    """A fresh 16-byte identity GUID (random, or deterministic from ``seed``)."""
    if seed is None:
        return os.urandom(16)
    import hashlib

    return hashlib.sha256(seed).digest()[:16]


def _iter_name_offsets(blob: bytes):
    """Yield (offset, name) for every ``Skill Controller <X>`` length-prefixed
    string in ``blob``, in order."""
    i = 0
    n = len(blob)
    while i + 4 <= n:
        ln = struct.unpack_from("<I", blob, i)[0]
        if 4 <= ln <= 96 and i + 4 + ln <= n:
            chunk = blob[i + 4:i + 4 + ln]
            if chunk.startswith(_NAME_PREFIX) and all(0x20 <= b < 0x7F for b in chunk):
                yield i, chunk.decode("ascii")
                i += 4 + ln
                continue
        i += 1


def _row_end(blob: bytes, begin: int, limit: int) -> int:
    """Depth-match the closing ``2222bbaa`` for the row opened at ``begin``.

    Markers inside a skill-controller row are balanced; the scan is capped at
    ``limit`` (the next row's begin or EOF) so a stray sentinel can't run away."""
    i = begin
    depth = 0
    while i < limit:
        if blob[i:i + 4] == _BEGIN:
            depth += 1
            i += 8  # BEGIN + u32 class
            continue
        if blob[i:i + 4] == _END:
            depth -= 1
            i += 4
            if depth == 0:
                return i
            continue
        i += 1
    raise SkillCloneError(f"unterminated skill row at {begin:#x}")


def list_skill_rows(blob: bytes) -> list[SkillRow]:
    """Locate every skill-controller row in a herodef blob, in file order."""
    names = list(_iter_name_offsets(blob))
    rows: list[SkillRow] = []
    for idx, (name_off, name) in enumerate(names):
        begin = blob.rfind(_BEGIN, max(0, name_off - _BEGIN_LOOKBACK), name_off)
        if begin < 0:
            raise SkillCloneError(f"no row BEGIN before {name!r} @ {name_off:#x}")
        cls = struct.unpack_from("<I", blob, begin + 4)[0]
        if cls != _ROW_CLASS:
            raise SkillCloneError(
                f"row {name!r}: unexpected class {cls:#x} (want {_ROW_CLASS:#x})")
        ln = struct.unpack_from("<I", blob, name_off)[0]
        guid1_off = name_off + 4 + ln
        # cap end scan at the next row's name (rows are contiguous siblings)
        nxt = names[idx + 1][0] if idx + 1 < len(names) else len(blob)
        end = _row_end(blob, begin, nxt)
        rows.append(SkillRow(name, begin, end, name_off, guid1_off))
    return rows


def find_skill(blob: bytes, name: str) -> SkillRow:
    """Locate a single skill row by exact (case-insensitive) name."""
    want = name.lower()
    key = want if want.startswith("skill controller ") else f"skill controller {want}"
    for row in list_skill_rows(blob):
        if row.name.lower() == key:
            return row
    raise SkillCloneError(f"skill row {name!r} not found")


def _row_with(blob: bytes, row: SkillRow, new_name: str,
              new_guid1: bytes | None) -> bytes:
    """Build a row blob from ``row`` with a renamed key and (optionally) a new
    identity GUID. All other bytes (flags, GUID#2, tier wiring) are preserved."""
    if not new_name:
        raise SkillCloneError("new skill name is empty")
    key = new_name
    if not key.lower().startswith("skill controller "):
        key = f"Skill Controller {new_name}"
    enc = key.encode("ascii")
    raw = bytearray(row.raw(blob))
    base = row.begin
    # splice the new name lstring (variable length) at the name field
    name_lo = row.name_off - base
    old_ln = struct.unpack_from("<I", raw, name_lo)[0]
    name_hi = name_lo + 4 + old_ln
    raw[name_lo:name_hi] = struct.pack("<I", len(enc)) + enc
    # GUID#1 sits immediately after the (new) name field
    if new_guid1 is not None:
        if len(new_guid1) != 16:
            raise SkillCloneError("guid must be 16 bytes")
        g1 = name_lo + 4 + len(enc)
        raw[g1:g1 + 16] = new_guid1
    return bytes(raw)


def repoint_skill(blob: bytes, src_name: str, new_name: str, *,
                  new_guid1: bytes | None = None) -> bytes:
    """Rewrite an existing skill row IN PLACE (count-neutral, byte-safe).

    The slot keeps its position, tier and upgrade wiring; only its key (and,
    if given, identity GUID) change. The conservative way to repurpose a skill
    into a custom one. Returns the patched herodef bytes."""
    row = find_skill(blob, src_name)
    new_row = _row_with(blob, row, new_name, new_guid1)
    return blob[:row.begin] + new_row + blob[row.end:]


def clone_skill(blob: bytes, src_name: str, new_name: str, *,
                new_guid1: bytes | None = None,
                remint: bool = False) -> tuple[bytes, bytes]:
    """Duplicate ``src_name`` as a NEW skill row spliced in after it.

    EXPERIMENTAL net-new path (see module CAVEAT). Returns
    ``(patched_blob, guid1)``.

    By DEFAULT the clone KEEPS the source's identity GUID (``remint=False``):
    reminting an unresolvable GUID is what broke a cloned item's load
    (``item-clone-pipeline-verified``) and is the prime suspect for a cloned
    skill bricking its hero — distinct identity comes from the new controller
    NAME, not a fresh GUID. Pass ``remint=True`` (or an explicit ``new_guid1``)
    only once a fresh skill GUID is known to be resolvable. The clone always
    keeps the source's effect ref (GUID#2), so it behaves like the source until
    repointed."""
    row = find_skill(blob, src_name)
    if new_guid1 is None:
        new_guid1 = (mint_guid(new_name.encode("utf-8")) if remint
                     else blob[row.guid1_off:row.guid1_off + 16])
    new_row = _row_with(blob, row, new_name, new_guid1)
    patched = blob[:row.end] + new_row + blob[row.end:]
    return patched, new_guid1
