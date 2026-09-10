#!/usr/bin/env python3
"""Relocate `data/symbols.json` addresses across a game patch, using BinDiff.

The gap this fills. The existing post-patch pipeline
(`scripts/gen_function_patterns.py`, `data/symbol_fingerprints.json`,
`tools/mine_fingerprints.py`, `tools/recover_unverified.py`) re-finds a symbol
whose BYTES survived the rebuild. It cannot re-find one that was recompiled,
re-inlined, or merged — those go `status:"unverified"` and cost a manual RE
session each, which git shows happening three times already.

BinDiff matches on call-graph and basic-block STRUCTURE, not bytes, so it finds
exactly the ones a byte pattern loses. This joins its result to the symbol map:
for every symbol whose `raw` names an address in the OLD build, report where it
landed in the NEW one, with BinDiff's own similarity/confidence and the
algorithm that made the match.

Patch-day recipe (three steps, this tool is the third)::

    # 1. export both builds — the OLD project must be UNLOCKED, so close the
    #    Ghidra GUI and the MCP bridge first (CLAUDE.md says the same thing
    #    about tools/gen_ghidra_vtables.py, for the same reason).
    GH=~/Documents/Programming/ghidra_11.3_PUBLIC
    $GH/support/analyzeHeadless <projdir> <proj> -process Ravenswatch.exe \
        -noanalysis -scriptPath tools/ghidra_scripts \
        -postScript BinExportHeadless.java /tmp/old.BinExport
    # ...import the patched exe, analyze it, then the same call -> /tmp/new.BinExport

    # 2. diff them
    bindiff --primary=/tmp/old.BinExport --secondary=/tmp/new.BinExport \
        --output_dir=/tmp

    # 3. join to the symbol map
    tools/bindiff_remap.py /tmp/old_vs_new.BinDiff
    tools/bindiff_remap.py /tmp/old_vs_new.BinDiff --apply

WHAT `--apply` MAY REWRITE, and why it is safe. Only the `raw` `FUN_<addr>` of a
function symbol whose match clears both thresholds. BinDiff addresses are Ghidra
FUNCTION STARTS on both sides, so a rewritten address can never land
mid-instruction — which is the `false-ok` failure mode CLAUDE.md warns about and
the reason `scripts/verify_symbol_resolve.py` exists. It does NOT touch
`status`: a relocated address is a hypothesis until a pattern is regenerated and
verified, so an `ok` symbol that moved stays `ok` only once::

    rsmm symbols gen && python scripts/verify_symbol_resolve.py

Data globals (`status:"va"`) are skipped and reported: BinDiff matches functions,
and a global's address is not one.
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

#: Defaults chosen to be boring. A structural match this strong is the case the
#: byte-pattern DB would also have caught; the value here is that BinDiff still
#: reports it when the bytes changed. Anything weaker is a shortlist for a
#: human, never an automatic rewrite.
MIN_SIMILARITY = 0.98
MIN_CONFIDENCE = 0.90

_RAW = re.compile(r"^FUN_([0-9a-fA-F]+)$")


def _raw_addr(sym: dict) -> int | None:
    """The old-build address a symbol's `raw` names, or None."""
    m = _RAW.match(str(sym.get("raw", "")))
    return int(m.group(1), 16) if m else None


def load_matches(bindiff_db: Path) -> dict[int, tuple[int, float, float, str]]:
    """`{old_address: (new_address, similarity, confidence, algorithm)}`.

    The `.BinDiff` result really is a SQLite database — `function` holds one row
    per MATCHED pair, so an unmatched function is simply absent, which is the
    distinction this tool reports.
    """
    con = sqlite3.connect(f"file:{bindiff_db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT f.address1, f.address2, f.similarity, f.confidence, "
            "       COALESCE(a.name, '?') "
            "FROM function f LEFT JOIN functionalgorithm a ON a.id = f.algorithm"
        ).fetchall()
    except sqlite3.DatabaseError as e:
        raise SystemExit(
            f"{bindiff_db}: not a BinDiff result database ({e})") from None
    finally:
        con.close()
    return {int(a1): (int(a2), float(sim), float(conf), alg)
            for a1, a2, sim, conf, alg in rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bindiff", type=Path, help="the .BinDiff result database")
    ap.add_argument("--apply", action="store_true",
                    help="rewrite `raw` for unambiguous high-confidence moves")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--min-similarity", type=float, default=MIN_SIMILARITY)
    ap.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    ap.add_argument("--symbols", type=Path, default=SYMBOLS)
    args = ap.parse_args(argv)

    matches = load_matches(args.bindiff)
    doc = json.loads(args.symbols.read_text())
    symbols = doc["symbols"]

    moved, same, lost, skipped = [], [], [], []
    for sym in symbols:
        name, status = sym["name"], sym.get("status")
        if sym.get("kind") != "function" or status == "va":
            skipped.append({"name": name, "why": f"kind={sym.get('kind')} status={status}"})
            continue
        old = _raw_addr(sym)
        if old is None:
            skipped.append({"name": name, "why": f"raw is not FUN_<addr>: {sym.get('raw')!r}"})
            continue
        hit = matches.get(old)
        if hit is None:
            # TWO very different things land here and they must not be read as
            # one. Either the patch removed/split the function (a finding), or
            # the OLD Ghidra project never had a FUNCTION defined at that
            # address, so BinExport never exported it and no match was possible
            # (a gap in this pipeline, not in the game).
            #
            # Measured on the first real run: 15 unmatched, and
            # `HeroStats_OnDamageTaken` was one of them — its own note already
            # says "function bounds taken from .pdata because Ghidra had no
            # function defined there". `scripts/disasm.py --whatis` resolves it
            # to +0x0, so the address is right and the export was simply blind
            # to it. An `ok` symbol here is the suspicious one; `unverified`
            # means the address is known-stale by definition.
            lost.append({"name": name, "old": f"0x{old:x}", "status": status})
            continue
        new, sim, conf, alg = hit
        rec = {"name": name, "old": f"0x{old:x}", "new": f"0x{new:x}",
               "similarity": round(sim, 4), "confidence": round(conf, 4),
               "algorithm": alg, "status": status}
        (same if new == old else moved).append(rec)

    ok = [r for r in moved
          if r["similarity"] >= args.min_similarity
          and r["confidence"] >= args.min_confidence]
    weak = [r for r in moved if r not in ok]

    if args.apply and ok:
        by_name = {r["name"]: r for r in ok}
        for sym in symbols:
            r = by_name.get(sym["name"])
            if r:
                sym["raw"] = f"FUN_{int(r['new'], 16):x}"
        # indent=1 — CLAUDE.md: keep it, or every diff of this file explodes.
        args.symbols.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    if args.json:
        json.dump({"moved": moved, "applied": ok if args.apply else [],
                   "weak": weak, "unchanged": same, "unmatched": lost,
                   "skipped": skipped}, sys.stdout, indent=2)
        print()
        return 0

    print(f"BinDiff: {len(matches)} matched function pair(s)")
    print(f"symbols: {len(same)} unchanged, {len(moved)} moved, "
          f"{len(lost)} unmatched, {len(skipped)} not applicable\n")
    for label, rows in (("MOVED (would apply)", ok),
                        ("MOVED (too weak — confirm by hand)", weak)):
        if not rows:
            continue
        print(f"{label}:")
        for r in sorted(rows, key=lambda r: -r["similarity"]):
            print(f"  {r['name']:<44} {r['old']} -> {r['new']}  "
                  f"sim {r['similarity']:.3f} conf {r['confidence']:.3f}  {r['algorithm']}")
        print()
    if lost:
        print("UNMATCHED — either the patch removed/split it, or the old Ghidra")
        print("project had no FUNCTION at that address so it was never exported.")
        print("Check the second cause first:  scripts/disasm.py --whatis <addr>")
        print("resolving to `<Name>+0x0` means the address is fine and Ghidra is")
        print("blind to it — define the function there and re-export.\n")
        hot = [r for r in lost if r["status"] == "ok"]
        cold = [r for r in lost if r["status"] != "ok"]
        for label, rows in (("  status=ok (investigate)", hot),
                            ("  status!=ok (address already known-stale)", cold)):
            if not rows:
                continue
            print(label)
            for r in sorted(rows, key=lambda r: r["name"]):
                print(f"    {r['name']:<44} {r['old']}  [{r['status']}]")
        print()
    if args.apply:
        print(f"applied {len(ok)} address rewrite(s) to {args.symbols}")
        print("next:  rsmm symbols gen && python scripts/verify_symbol_resolve.py")
    elif ok:
        print(f"re-run with --apply to rewrite {len(ok)} address(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
