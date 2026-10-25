"""Custom **challenge** cook — a ChallengeDefinition clone with its own modifiers.

A challenge is a fixed bundle of game modifiers on the challenge screen
(DodgeIt = DashLowCooldown + LessHealing + StrongerLowLifeEnemies). The cooked
def is ``oe::dt::ChallengeDefinition`` (``*.challengedef.ot``, class id
0x1a5d81e4). Ghidra (b9c3642884a8, 2026-10-16) — deserializer FUN_140320580 —
gives the body after the leaf codec's ``field_a`` / ``text_ref``:

    u32  row                 title key's row in the text bank (a HINT: on load
                             FUN_140688260 looks the key up by string and
                             overwrites the row, so a wrong row is harmless)
    lstr title               e.g. ``Challenge_DodgeIt_Title``
    u32  slot count          always 5 — the challenge screen's 5-modifier cap
    5 x (lstr root, lstr path)   ``Definitions`` /
                             ``GameModifiers\\X.gamemodifierdef.ot``; an empty
                             slot is two zero-length strings
    16   guid                the def's identity (progress is keyed by it, so a
                             clone gets its own)
    ...  rest                u32 + u8, copied verbatim

The challenge page lists every loaded ChallengeDefinition
(``Registry_EnumInstances`` in FUN_140423290), so a clone registered in
``UsedRscList`` shows up with no list to edit.
"""

from __future__ import annotations

import struct

from . import cooked
from .cooked_schemas import definitions as _defs

CLASS = "ChallengeDefinition"
GEN_SUFFIX = ".challengedef.ot.allengeDefinition.gen"
SLOTS = 5
_MOD_ROOT = "Definitions"


class ChallengeCookError(ValueError):
    pass


def _lstr(b: bytes, o: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("<I", b, o)
    s = b[o + 4:o + 4 + n]
    if len(s) != n:
        raise ChallengeCookError("truncated string in challenge def")
    return s.decode("ascii"), o + 4 + n


def _put(s: str) -> bytes:
    e = s.encode("ascii")
    return struct.pack("<I", len(e)) + e


def parse_tail(tail: bytes) -> dict:
    (row,) = struct.unpack_from("<I", tail, 0)
    title, o = _lstr(tail, 4)
    (count,) = struct.unpack_from("<I", tail, o)
    if count != SLOTS:
        raise ChallengeCookError(f"expected {SLOTS} modifier slots, found {count}")
    o += 4
    slots = []
    for _ in range(count):
        root, o = _lstr(tail, o)
        path, o = _lstr(tail, o)
        slots.append((root, path))
    guid = tail[o:o + 16]
    if len(guid) != 16:
        raise ChallengeCookError("challenge def has no GUID after its modifier slots")
    return {"row": row, "title": title, "slots": slots, "guid": guid, "rest": tail[o + 16:]}


def build_tail(d: dict) -> bytes:
    out = struct.pack("<I", d["row"]) + _put(d["title"]) + struct.pack("<I", len(d["slots"]))
    for root, path in d["slots"]:
        out += _put(root) + _put(path)
    return out + d["guid"] + d["rest"]


def modifier_slot(stem: str) -> tuple[str, str]:
    return _MOD_ROOT, f"GameModifiers\\{stem}.gamemodifierdef.ot"


def _tail(cf) -> bytes:
    body = _defs._SPECS[CLASS].decode_body(cf.sections[-1].payload)
    return bytes.fromhex(body["_tail_hex"])


def modifiers_of(cooked_bytes: bytes) -> list[str]:
    """Modifier stems a challenge def names, in slot order."""
    t = _tail(cooked.parse(cooked_bytes))
    return [p.split("\\")[-1].split(".")[0] for _r, p in parse_tail(t)["slots"] if p]


def clone(base_cooked: bytes, *, title_key: str, modifiers: list[str], guid: bytes) -> bytes:
    """``base_cooked`` with a new title key, modifier list and GUID."""
    if not 1 <= len(modifiers) <= SLOTS:
        raise ChallengeCookError(f"a challenge holds 1 to {SLOTS} modifiers, got {len(modifiers)}")
    if len(guid) != 16:
        raise ChallengeCookError("guid must be 16 bytes")
    cf = cooked.parse(base_cooked)
    if not cf.sections:
        raise ChallengeCookError("base def has no sections")
    spec = _defs._SPECS[CLASS]
    body = spec.decode_body(cf.sections[-1].payload)
    d = parse_tail(bytes.fromhex(body["_tail_hex"]))
    d["title"] = title_key
    d["slots"] = [modifier_slot(m) for m in modifiers] + [("", "")] * (SLOTS - len(modifiers))
    d["guid"] = guid
    body["_tail_hex"] = build_tail(d).hex()
    cf.sections[-1] = cooked.Section(payload=spec.encode_body(body))
    return cooked.emit(cf)
