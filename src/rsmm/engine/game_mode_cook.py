"""Custom **game-mode** (run chapter sequence) cook — re-order the chapters.

A run's chapter order is one ``GameModeDefaultDefinition`` (asset
``*.gamemodedefaultdef.ot``; the shipped one is ``All_Chapters``). Its leaf codec
(:mod:`rsmm.engine.cooked_schemas.definitions` ``gamemodedefaultdef.json``)
exposes ``field_a`` and preserves the body tail in ``_tail_hex``; that tail is a
simple ``u32 count`` followed by ``count`` × ``u32`` chapter index — the ordered
list of chapters the run plays (vanilla ``[0, 1, 2, 3]`` = the four biomes:
Dark Hills, Avalon, Storm Island, Baba Yaga).

Rewriting the list re-sequences / repeats / shortens the run (Heredos #10), e.g.
``[2, 0, 1, 3]`` reorders, ``[0, 0, 0]`` repeats the first biome, ``[3]`` is a
one-chapter run. Indices must reference existing chapters (``0 .. original-1``).

This is a FIXED custom order — true per-run randomization can't live in static
data (it would need engine RNG and would have to stay multiplayer-deterministic,
see [[multiplayer-netcode]]); a fixed reordering is data-safe and apply-time.
"""

from __future__ import annotations

import struct

from . import cooked
from .cooked_schemas import definitions as _defs

CLASS = "GameModeDefaultDefinition"
GEN_SUFFIX = ".gamemodedefaultdef.ot.meModeDefaultDefinition.gen"


class GameModeCookError(ValueError):
    pass


def read_sequence(base_cooked: bytes) -> list[int]:
    """Return the chapter-index list of a ``GameModeDefaultDefinition``."""
    seq, _ = _decode(base_cooked)
    return seq


def _decode(base_cooked: bytes) -> tuple[list[int], int]:
    cf = cooked.parse(base_cooked)
    if not cf.sections:
        raise GameModeCookError("base def has no sections")
    body = _defs._SPECS[CLASS].decode_body(cf.sections[-1].payload)
    tail = bytes.fromhex(body["_tail_hex"])
    if len(tail) < 4:
        raise GameModeCookError("tail too short for a chapter list")
    count = struct.unpack_from("<I", tail, 0)[0]
    end = 4 + 4 * count
    if end > len(tail):
        raise GameModeCookError(
            f"chapter count {count} overruns tail ({len(tail)} bytes) — "
            "this def's tail is not a plain u32 list."
        )
    seq = list(struct.unpack_from(f"<{count}I", tail, 4))
    return seq, end


def set_chapter_sequence(base_cooked: bytes, sequence: list[int]) -> bytes:
    """Re-emit ``base_cooked`` with its chapter list replaced by ``sequence``.

    Each index must reference an existing chapter (``0 .. original_count-1``).
    Any bytes after the original list are preserved verbatim.
    """
    if not sequence:
        raise GameModeCookError("chapter sequence must be non-empty")
    cf = cooked.parse(base_cooked)
    body = _defs._SPECS[CLASS].decode_body(cf.sections[-1].payload)
    tail = bytes.fromhex(body["_tail_hex"])
    orig_count = struct.unpack_from("<I", tail, 0)[0]
    trailing = tail[4 + 4 * orig_count :]  # data beyond the list, if any

    for idx in sequence:
        if not isinstance(idx, int) or idx < 0 or idx >= orig_count:
            raise GameModeCookError(
                f"chapter index {idx!r} out of range — the run defines "
                f"{orig_count} chapters (valid 0..{orig_count - 1})."
            )

    new_tail = struct.pack("<I", len(sequence))
    new_tail += struct.pack(f"<{len(sequence)}I", *sequence)
    new_tail += trailing
    body["_tail_hex"] = new_tail.hex()
    cf.sections[-1] = cooked.Section(payload=_defs._SPECS[CLASS].encode_body(body))
    return cooked.emit(cf)
