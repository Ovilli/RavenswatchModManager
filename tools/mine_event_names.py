#!/usr/bin/env python3
"""Mine the oCGameNamedEvent name catalog out of Ravenswatch.exe.

Why this exists: the loader's gameplay-bus detour republishes EVERY named
event the engine dispatches, keyed by the plaintext name it reads off the
event object — so `R.on("gameplay:<NAME>", cb)` already works for hundreds of
events. But NOTHING listed those names, so from a mod author's seat the bus
was invisible: `rsmm symbols events` showed 16 analytics names and nothing
else, and the only way to discover a name was to play with the loader
attached and read the log.

The names are plain `[A-Z0-9_]` string literals in `.rdata`. So:

  1. harvest NUL-terminated literals in .rdata/.data matching the bus
     alphabet,
  2. cluster them by address — the compiler emits the string pool in source
     order, so the event names land in dense runs while unrelated
     SCREAMING_CASE constants (KEY_*, *_SHAPE_PROXYTYPE, RakNet status codes)
     sit in their own,
  3. keep only the clusters that contain a name we have CONFIRMED fires on
     the bus. That anchor is what separates the event pool from every other
     screaming-case pool, and it is checked, not assumed.

Note for anyone extending this: the names are NOT reachable by scanning .text
for `lea reg, [rip+str]`. The engine builds an event id from the name's CRC
and stores the pointer in a table, so a reference scan finds ~0 of them — an
earlier version of this script filtered on exactly that and reported 0/6
known names. Clustering is the signal.

`--verify` fails if any confirmed name is missing from the output.

Usage:
  python tools/mine_event_names.py                 # summary + clusters
  python tools/mine_event_names.py --json out.json # machine-readable
  python tools/mine_event_names.py --verify        # assert the known names
  python tools/mine_event_names.py --exe PATH      # explicit exe
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# Names confirmed to fire on the bus in a real session (playtests + the RE
# notes in docs/_re/kinds/events-bus.md). The miner must find all of them.
KNOWN = [
    "GIVE_MAGICAL_OBJECT",
    "NETWORK_DAMAGE",
    "GAIN_HEALTH",
    "ABILITY_EXIT",
    "COMBO_LINK",
    "INTERACTION_VALIDATE",
    "NETWORK_DAMAGE_RESPONSE",
    "CINE_START",
    "GAIN_DREAM_SHARDS",
    "POWER_UP_COLLECT_REQUEST",
]

# The bus alphabet, from the loader's own gameplay_event_name() validator.
NAME_RE = re.compile(rb"^[A-Z][A-Z0-9_]{2,63}$")


def _default_exe() -> Path | None:
    try:
        from rsmm.engine.paths import default_game_dir
    except ImportError:
        return None
    game = default_game_dir()
    if not game:
        return None
    exe = Path(game) / "Ravenswatch.exe"
    return exe if exe.exists() else None


class PE:
    """Just enough PE parsing to map sections; stdlib only."""

    def __init__(self, data: bytes):
        self.data = data
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
            raise ValueError("not a PE file")
        coff = e_lfanew + 4
        n_sections, = struct.unpack_from("<H", data, coff + 2)
        opt_size, = struct.unpack_from("<H", data, coff + 16)
        opt = coff + 20
        magic, = struct.unpack_from("<H", data, opt)
        if magic != 0x20B:
            raise ValueError("not PE32+ (64-bit)")
        self.image_base, = struct.unpack_from("<Q", data, opt + 24)
        sec_off = opt + opt_size
        self.sections = []
        for i in range(n_sections):
            off = sec_off + i * 40
            name = data[off : off + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off + 8)
            self.sections.append(
                {"name": name, "va": self.image_base + vaddr,
                 "vsize": vsize, "raw": rawptr, "rawsize": rawsize}
            )

    def section(self, name: str):
        for s in self.sections:
            if s["name"] == name:
                return s
        return None


def harvest_strings(pe: PE, sec) -> dict[int, str]:
    """VA -> literal, for NUL-terminated strings matching the bus alphabet."""
    blob = pe.data[sec["raw"] : sec["raw"] + sec["rawsize"]]
    out: dict[int, str] = {}
    start = 0
    while True:
        end = blob.find(b"\0", start)
        if end < 0:
            break
        cand = blob[start:end]
        if NAME_RE.match(cand):
            out[sec["va"] + start] = cand.decode("ascii")
        # Strings are NUL-separated; skip past this one (and any run of NULs).
        start = end + 1
        while start < len(blob) and blob[start] == 0:
            start += 1
        if start >= len(blob):
            break
    return out


def cluster(vas: list[int], gap: int = 0x400) -> list[list[int]]:
    """Group sorted addresses into runs separated by more than `gap`."""
    runs: list[list[int]] = []
    for va in sorted(vas):
        if runs and va - runs[-1][-1] <= gap:
            runs[-1].append(va)
        else:
            runs.append([va])
    return runs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None,
                    help="write {name: {va}} here")
    ap.add_argument("--verify", action="store_true",
                    help="exit nonzero unless every KNOWN name is found")
    ap.add_argument("--min-cluster", type=int, default=4,
                    help="ignore anchored clusters smaller than this")
    ap.add_argument("--gap", type=lambda x: int(x, 0), default=0x200,
                    help="max address gap within one string pool")
    args = ap.parse_args()

    exe = args.exe or _default_exe()
    if not exe or not exe.exists():
        print("Ravenswatch.exe not found (pass --exe PATH)", file=sys.stderr)
        return 2

    pe = PE(exe.read_bytes())

    strings: dict[int, str] = {}
    for name in (".rdata", ".data"):
        sec = pe.section(name)
        if sec:
            strings.update(harvest_strings(pe, sec))
    print(f"{exe}")
    print(f"  candidate SCREAMING_CASE literals: {len(strings)}")

    runs = cluster(list(strings), gap=args.gap)
    known = set(KNOWN)
    pools, other = [], 0
    for run in runs:
        names = [strings[va] for va in run]
        hits = sorted(known.intersection(names))
        if hits and len(run) >= args.min_cluster:
            pools.append((run, names, hits))
        else:
            other += len(run)
    pools.sort(key=lambda p: len(p[0]), reverse=True)

    used = {}
    for run, names, _ in pools:
        for va, nm in zip(run, names, strict=True):
            used[va] = nm
    print(f"  clusters anchored by a confirmed event name: {len(pools)}")
    print(f"  event names mined: {len(used)}  (rejected {other} unanchored)\n")

    for idx, (run, names, hits) in enumerate(pools):
        print(f"pool {idx}: {len(run):4d} names @ 0x{run[0]:x}-0x{run[-1]:x}")
        print(f"   anchors: {', '.join(hits)}")
        print("   " + ", ".join(sorted(names)[:12]) + (" ..." if len(names) > 12 else ""))

    found = {n for n in used.values()}
    missing = [k for k in KNOWN if k not in found]
    print(f"\nknown-name check: {len(KNOWN) - len(missing)}/{len(KNOWN)} found")
    for k in missing:
        print(f"  MISSING {k}")

    if args.json:
        payload = {used[va]: {"va": f"0x{va:x}"} for va in sorted(used)}
        args.json.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        print(f"\nwrote {args.json} ({len(payload)} names)")

    if args.verify and missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
