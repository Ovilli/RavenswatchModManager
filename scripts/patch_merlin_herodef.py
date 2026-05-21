#!/usr/bin/env python3
"""Patch Merlin.herodef.gen to remove unlock conditions (static override).

Reads the cooked .gen binary and replaces the NamedEventGameLockConditionSettings
payloads with empty data, so the hero always appears unlocked.  This approach
works on ALL platforms (Windows, Linux/Proton, macOS) because it's a pure
file-replacement mod — no runtime hook (DLL injection) needed.

Usage:
    python3 scripts/patch_merlin_herodef.py

Writes:
    mods/MerlinUnlock/assets/Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen

Run after:
    ./rsmm apply              # deploys the patched file to the game
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data/uncooked/Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen"
DST = REPO / "mods/MerlinUnlock/assets/Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen"

# Offsets confirmed from gen.txt dump.
# Section 44 (oCGameLockSettings orchestrator): the u32 at payload+4 is the
# condition count.  Set to 0 → no conditions to evaluate → always unlocked.
SECTION44_COUNT = 0x3471

# Section 45 (NamedEventGameLockConditionSettings —
#             "MORGAN_COMPLETED_MERLIN_QUEST"): u32 at payload+0x18 is the
# string length.  Set to 0 → empty event name → no quest to check.
SECTION45_STRLEN = 0x34A9

# Section 48 (NamedEventGameLockConditionSettings — "RUNIC_QUEST_COMPLETE"):
# same layout.
SECTION48_STRLEN = 0x35D6


def patch(data: bytearray) -> bytearray:
    _patch_u32(data, SECTION44_COUNT, 3, 0, "Section 44 condition count")
    # NOTE: NOT patching string lengths in sections 45/48 — the .gen file
    # uses a linear section stream, and shortening a string would shift all
    # subsequent fields within that section, corrupting its deserialization.
    # The condition count of 0 means these condition sections are never
    # instantiated into oIGameUnlockConditionSettings objects, so they just
    # parse as inert blobs.
    return data


def _patch_u32(data: bytearray, offset: int, expected: int, new: int, label: str):
    val = int.from_bytes(data[offset:offset + 4], "little")
    if val != expected:
        print(f"[patch] {label}: expected {expected}, got {val} at 0x{offset:x} — "
              "file layout may have changed; aborting", file=sys.stderr)
        sys.exit(1)
    data[offset:offset + 4] = new.to_bytes(4, "little")
    print(f"[patch] {label}: {val} → {new} @ 0x{offset:x}")


def verify(data: bytearray):
    nb = data.count(b"\x11\x11\xbb\xaa")
    ne = data.count(b"\x22\x22\xbb\xaa")
    ok = "✓" if nb == ne else "✗ MISMATCH"
    print(f"[verify] {nb}x BEGIN / {ne}x END markers {ok}")
    print(f"[verify] patched size: {len(data)} bytes")


def main() -> int:
    if not SRC.is_file():
        print(f"source not found: {SRC}", file=sys.stderr)
        return 1

    data = bytearray(SRC.read_bytes())
    print(f"[main] read {len(data)} bytes from {SRC}")

    patch(data)
    verify(data)

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_bytes(bytes(data))
    print(f"[main] wrote {DST} ({DST.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
