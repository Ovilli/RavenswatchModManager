#!/usr/bin/env python3
"""Measure the locator against the hand-confirmed relocations.

`relocate_stale_symbols.CONFIRMED` holds 29 symbols whose current addresses
were each read in Ghidra against the symbol's note. That is ground truth, so
it is also a test set: replay each symbol's ORIGINAL note through the locator
and see whether the right address comes back, and at what rank.

This is the only honest way to claim the tool improved. Run it after touching
any constraint in tools/symbol_locate.py.

    tools/eval_symbol_locate.py            # summary
    tools/eval_symbol_locate.py --verbose  # per-symbol, with the misses
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relocate_stale_symbols import CONFIRMED  # noqa: E402
from symbol_locate import Build, locate  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
VFTABLES = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"


def original_note(note: str) -> str:
    """Strip the RELOCATED/evidence tail this tool's own --apply appended.

    Without this the evaluation is circular: the appended text names the new
    address and repeats the evidence, so the locator would be scored on a note
    that already contains the answer.
    """
    for marker in (" [RELOCATED", " [relocated"):
        i = note.find(marker)
        if i != -1:
            note = note[:i]
    return note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    doc = json.loads(SYM.read_text())
    by_name = {s["name"]: s for s in doc["symbols"]}

    build = Build(CORPUS, VFTABLES)

    # What the locator is allowed to know: symbols located in an EARLIER pass.
    # Feeding it every current address would leak the answers, since several of
    # the 29 were found via each other.
    located: dict[str, int] = {}
    for s in doc["symbols"]:
        raw = str(s.get("raw") or "")
        if raw.startswith("FUN_") and s["name"] not in CONFIRMED:
            located[s["name"]] = int(raw.split("_", 1)[1], 16)

    hit1 = hitn = miss = nopool = 0
    rows = []
    for name, (raw, _evidence) in sorted(CONFIRMED.items()):
        sym = by_name.get(name)
        if sym is None:
            continue
        truth = int(raw.split("_", 1)[1], 16)
        note = original_note(str(sym.get("note") or ""))
        cands, anchors = locate(build, note, located, self_name=name, top=args.top)

        addrs = [c.addr for c in cands]
        if not addrs:
            nopool += 1
            verdict = "NO-POOL"
        elif addrs[0] == truth:
            hit1 += 1
            verdict = "RANK-1"
        elif truth in addrs:
            hitn += 1
            verdict = f"RANK-{addrs.index(truth) + 1}"
        else:
            miss += 1
            verdict = "MISS"
        rows.append((verdict, name, truth, cands, anchors))

    total = hit1 + hitn + miss + nopool
    for verdict, name, truth, cands, anchors in rows:
        if not args.verbose and verdict in ("RANK-1",):
            continue
        print(f"{verdict:8} {name}  (truth 0x{truth:x})")
        if args.verbose or verdict in ("MISS", "NO-POOL"):
            if not cands:
                print(f"           anchors: {len(anchors.strings)} string(s), "
                      f"{len(anchors.consts)} const(s), "
                      f"{len(anchors.symbols)} symbol ref(s), vft={anchors.vft}")
            for c in cands[:3]:
                print(f"           0x{c.addr:x} score={c.score:.1f} "
                      f"off={c.offsets_hit}/{c.offsets_total} via {c.via[:70]}")

    print(f"\n{total} confirmed relocations replayed from their ORIGINAL notes")
    print(f"  rank 1        : {hit1:3}  ({hit1 / total:.0%})")
    print(f"  in top {args.top}     : {hit1 + hitn:3}  ({(hit1 + hitn) / total:.0%})")
    print(f"  wrong pool    : {miss:3}")
    print(f"  no constraint : {nopool:3}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
