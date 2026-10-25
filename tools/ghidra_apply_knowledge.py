#!/usr/bin/env python3
"""Carry what we know about the game into a new build's Ghidra program.

A patch-day import is ~60k ``FUN_`` blobs: none of the symbol map's names or
notes, and none of the renames made by hand in the previous build's program.
This builds ``knowledge.json`` for ``tools/ghidra_scripts/ApplyRsmmKnowledge.java``
from two sources, strongest first:

1. ``data/symbols.json`` — every ``ok`` function and ``va`` global, named, with
   its status, signature and note as the plate comment (the decompiler prints
   it above the function, so an MCP decompile shows the RE notes). Forced:
   the map is the source of truth.
2. a BinDiff result (old build -> new build) — every function the OLD program
   had a real name for, matched with similarity and confidence at or above the
   thresholds, onto a new function that still has a default name. A name that
   would land on two functions is dropped, never guessed.

Then (project UNLOCKED: stop tools/ghidra_mcp/serve.sh first)::

    support/launch.sh fg jdk Ghidra-Headless 6G "" \\
        ghidra.app.util.headless.AnalyzeHeadless ghidra_project Ravenswatch-New \\
        -process <program> -noanalysis -scriptPath tools/ghidra_scripts \\
        -postScript ApplyRsmmKnowledge.java <knowledge.json> [dry]

``unverified`` symbols are skipped: their addresses are from an older build.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYMBOLS = REPO / "data" / "symbols.json"

#: Lower than bindiff_remap's bar on purpose: a ported NAME is a reading aid
#: (and says where it came from), not an address the loader will hook.
MIN_SIMILARITY = 0.90
MIN_CONFIDENCE = 0.90
NOTE_MAX = 4000

_RAW = re.compile(r"^FUN_([0-9a-fA-F]+)$")
#: Ghidra's own names: nothing a human learned.
_DEFAULT = re.compile(r"^(FUN|thunk_FUN|LAB|[Ss][Uu][Bb]|DAT|PTR|switchD|caseD|Catch|Unwind|"
                      r"entry|_?guard_|__)")


def symbol_entries(symbols: list[dict]) -> list[dict]:
    out = []
    for s in symbols:
        st = s.get("status")
        if st == "ok" and (m := _RAW.match(str(s.get("raw", "")))):
            addr, kind = int(m.group(1), 16), "function"
        elif st == "va" and s.get("va"):
            addr, kind = int(str(s["va"]), 16), "data"
        else:
            continue
        head = f"[rsmm {st}] {s['name']}"
        if s.get("signature"):
            head += f" :: {s['signature']}"
        note = head + ("\n" + s["note"] if s.get("note") else "")
        out.append({"addr": f"0x{addr:x}", "name": s["name"], "kind": kind,
                    "force": True, "note": note[:NOTE_MAX]})
    return out


def bindiff_entries(db: Path, taken: set[str], taken_addrs: set[int], *,
                    min_sim: float, min_conf: float, old_tag: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT address1, address2, similarity, confidence, name1, name2 "
                           "FROM function").fetchall()
    finally:
        con.close()
    cand: dict[str, list[tuple[int, float, float]]] = {}
    for _a1, a2, sim, conf, n1, n2 in rows:
        if sim < min_sim or conf < min_conf or not n1 or _DEFAULT.match(n1):
            continue
        if n2 and not _DEFAULT.match(n2):
            continue  # the new program already names it
        if n1 in taken or int(a2) in taken_addrs:
            continue
        cand.setdefault(n1, []).append((int(a2), float(sim), float(conf)))
    out = []
    for name, hits in sorted(cand.items()):
        if len({a for a, _s, _c in hits}) != 1:
            continue
        a2, sim, conf = hits[0]
        out.append({"addr": f"0x{a2:x}", "name": name, "kind": "function", "force": False,
                    "note": f"[rsmm ported] name from build {old_tag} via BinDiff "
                            f"(sim {sim:.3f}, conf {conf:.3f}); not in data/symbols.json"})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--bindiff", type=Path, help="old->new .BinDiff result to port names from")
    ap.add_argument("--old-tag", default="previous", help="label for the old build in notes")
    ap.add_argument("--min-similarity", type=float, default=MIN_SIMILARITY)
    ap.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    args = ap.parse_args(argv)

    entries = symbol_entries(json.loads(SYMBOLS.read_text(encoding="utf-8"))["symbols"])
    ported = []
    if args.bindiff:
        ported = bindiff_entries(args.bindiff, {e["name"] for e in entries},
                                 {int(e["addr"], 16) for e in entries},
                                 min_sim=args.min_similarity, min_conf=args.min_confidence,
                                 old_tag=args.old_tag)
    args.out.write_text(json.dumps({"entries": entries + ported}, indent=1), encoding="utf-8")
    print(f"{len(entries)} symbol-map entries + {len(ported)} ported name(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
