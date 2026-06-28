"""Custom **game-modifier** ("negative mode") cook — clone + identity remint.

A GameModifier is a run mutator (No boss timer, No minimap, More experience,
...). The cooked def is an ``oe::dt::GameModifierDefinition`` (asset ext
``*.gamemodifierdef.ot``); the leaf codec lives in
:mod:`rsmm.engine.cooked_schemas.definitions` (it types ``icon_ref`` /
``field_a`` / ``text_ref`` and preserves the rest of the body verbatim in
``_tail_hex``). That opaque tail carries three identity strings — the title
text-key, the desc text-key and the trailing id-name — plus the modifier's
BEHAVIOUR key (``1111bbaa 04 <u32>``): the literal entity-value id whose
hardcoded C++ branch implements the effect (see ``docs/_re/kinds/game-modifiers.md``;
e.g. ``NoBossTimer`` carries ``0x1a7945fc``).

Cloning a vanilla def under a new id yields a NET-NEW selectable modifier that
reuses an existing behaviour; pointing it at a different behaviour key reuses a
different existing effect. Brand-new behaviour is layered in Lua via
``R.modifier`` gating (``src/loader/lib/rsmm.lua``).

Reminting only ever rewrites whole ASCII identity strings (matched exactly) and,
optionally, the 4-byte behaviour key — every binary marker/count/length is
copied byte-for-byte — so the codec stays format-agnostic across the corpus and
never desyncs a tail it doesn't fully understand.
"""

from __future__ import annotations

import struct

from . import cooked
from .cooked_schemas import definitions as _defs

CLASS = "GameModifierDefinition"
GEN_SUFFIX = ".gamemodifierdef.ot.meModifierDefinition.gen"

#: ``1111bbaa`` field marker followed by a u32 length of 4 — the framing that
#: precedes the behaviour entity-value key in the tail. Unique in a modifier
#: def (other ``1111bbaa`` markers carry lengths 5/6), so the first occurrence
#: locates the behaviour key.
_BEHAVIOR_MARK = bytes.fromhex("1111bbaa") + struct.pack("<I", 4)


class GameModifierCookError(ValueError):
    pass


def _is_ascii_id(b: bytes) -> bool:
    return len(b) > 0 and all(0x20 <= c <= 0x7E for c in b)


def _rewrite_tail_strings(tail: bytes, repl: dict[str, str]) -> tuple[bytes, int]:
    """Rewrite length-prefixed ASCII lstrings in ``tail`` whose full content is a
    key of ``repl`` (exact match). Non-string bytes — and ASCII strings not in
    ``repl`` — are copied verbatim. Returns ``(new_tail, n_rewritten)``.

    A length-prefixed string is ``<u32 len><len bytes>``; we only treat a run as
    one when ``len`` is small and every byte is printable ASCII, so binary
    markers / counts / the behaviour key (non-ASCII) are never reinterpreted.
    Because non-replaced runs are emitted unchanged either way, a false-positive
    ASCII match is harmless unless it equals a (distinctive, long) ``repl`` key.
    """
    out = bytearray()
    o, n, hits = 0, len(tail), 0
    while o < n:
        if o + 4 <= n:
            ln = struct.unpack_from("<I", tail, o)[0]
            if 0 < ln <= 128 and o + 4 + ln <= n:
                s = tail[o + 4 : o + 4 + ln]
                if _is_ascii_id(s):
                    key = s.decode("ascii")
                    if key in repl:
                        nv = repl[key].encode("ascii")
                        out += struct.pack("<I", len(nv)) + nv
                        hits += 1
                    else:
                        out += tail[o : o + 4 + ln]
                    o += 4 + ln
                    continue
        out.append(tail[o])
        o += 1
    return bytes(out), hits


def _behavior_key(tail: bytes) -> int | None:
    """Read the modifier's behaviour entity-value key (first ``1111bbaa 04``
    framing), or None if absent."""
    idx = tail.find(_BEHAVIOR_MARK)
    if idx < 0 or idx + 8 + 4 > len(tail):
        return None
    return struct.unpack_from("<I", tail, idx + 8)[0]


def _swap_behavior_key(tail: bytes, new_key: int) -> bytes:
    idx = tail.find(_BEHAVIOR_MARK)
    if idx < 0:
        raise GameModifierCookError("no behaviour-key framing (1111bbaa 04) in def tail")
    o = idx + 8
    return tail[:o] + struct.pack("<I", new_key & 0xFFFFFFFF) + tail[o + 4 :]


def clone(
    base_cooked: bytes,
    base_id: str,
    new_id: str,
    *,
    effect_key: int | None = None,
    relabel_text: bool = False,
) -> tuple[bytes, int | None]:
    """Clone a vanilla ``.gamemodifierdef.ot`` under ``new_id``.

    Renames the embedded id-name (``base_id`` -> ``new_id``); when
    ``relabel_text`` also renames the ``GameModifier_<id>_Title`` / ``_Desc``
    text keys so the clone carries its own display strings (caller appends the
    values to the text bank). ``effect_key`` repoints the behaviour to a
    different existing entity-value id (default keeps the base's).

    Returns ``(cooked_bytes, base_behavior_key)``.
    """
    cf = cooked.parse(base_cooked)
    if not cf.sections:
        raise GameModifierCookError("base def has no sections")
    spec = _defs._SPECS[CLASS]
    try:
        body = spec.decode_body(cf.sections[-1].payload)
    except (ValueError, IndexError) as e:
        raise GameModifierCookError(f"failed to decode base def: {e}") from e

    tail = bytes.fromhex(body["_tail_hex"])
    base_key = _behavior_key(tail)

    repl = {base_id: new_id}
    if relabel_text:
        repl[f"GameModifier_{base_id}_Title"] = f"GameModifier_{new_id}_Title"
        repl[f"GameModifier_{base_id}_Desc"] = f"GameModifier_{new_id}_Desc"
    tail, hits = _rewrite_tail_strings(tail, repl)
    if hits == 0:
        raise GameModifierCookError(
            f"base id {base_id!r} not found as an identity string in the def tail "
            "— pass the modifier's embedded id (its filename stem)."
        )

    if effect_key is not None and effect_key != base_key:
        tail = _swap_behavior_key(tail, effect_key)

    body["_tail_hex"] = tail.hex()
    cf.sections[-1] = cooked.Section(payload=spec.encode_body(body))
    return cooked.emit(cf), base_key
