#!/usr/bin/env python3
"""Backfill structured `locator` blocks by mining the notes already in the map.

`tools/backfill_locators.py` holds the locators someone typed out by hand while
relocating a symbol. Most `status=ok` symbols never got that treatment, yet
their `note` usually still carries the anchor that found them — a quoted log
string, a vftable class and slot, a neighbour in the call graph, a struct
offset set. This reads those notes, turns each anchor into a candidate locator,
and KEEPS ONLY the ones that resolve, in today's corpus, to exactly the address
the map already records.

That last clause is the whole honesty of it. A mined locator is a hypothesis
lifted out of prose; it earns a place in `data/symbols.json` by re-finding the
function on its own, uniquely. Anything ambiguous, wrong or unresolvable is
reported and dropped — an anchor that cannot re-find its symbol today would not
have survived the next game patch either, which is the only thing locators are
for.

    tools/mine_locators.py                 # report what would be written
    tools/mine_locators.py --apply         # write them into data/symbols.json
    tools/mine_locators.py --check         # re-verify EVERY locator in the map
    tools/mine_locators.py --only Name     # one symbol, verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_locate import Build, mine_anchors, resolve_locator  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
VFTABLES = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"

# How many of each anchor class a candidate may carry. Notes sometimes name a
# dozen offsets; taking all of them makes an over-fitted locator that a rebuild
# breaks for reasons that have nothing to do with the symbol moving.
MAX_STRINGS, MAX_OFFSETS, MAX_SYMS, MAX_CONSTS = 3, 6, 3, 2
#: A shortlist no bigger than this is worth trying to split by function size.
TIE_BREAK_MAX = 6
#: How broad a candidate's *anchor* keys may be before its offsets are doing
#: all the work. `strings: ["Unknown"]` matches thousands of functions, and
#: ranking those by a struct-offset set is the global offset scoring that made
#: the first locator useless — it lands on one function and cannot say why.
#: So a candidate is thrown away unless its anchors alone already narrow the
#: corpus to a neighbourhood; offsets are then a tie-break, not the selector.
MAX_ANCHOR_POOL = 200


def _hex(v: int) -> str:
    return f"0x{v:x}"


def candidates(a, located: dict[str, int], self_name: str) -> list[dict]:
    """Candidate locators for one symbol, most decisive key first."""
    strings = sorted(a.strings, key=len, reverse=True)[:MAX_STRINGS]
    consts = sorted(a.consts)[:MAX_CONSTS]
    offsets = [_hex(o) for o in sorted(a.offsets)[:MAX_OFFSETS]]
    syms = [n for n in sorted(a.symbols) if n in located and n != self_name][:MAX_SYMS]

    seeds: list[dict] = []
    if a.vft:
        seeds.append({"vftable": {"class": a.vft[0], "slot": a.vft[1]}})
    for s in strings:
        seeds.append({"strings": [s]})
    if len(strings) > 1:
        seeds.append({"strings": strings})
    for c in consts:
        seeds.append({"consts": [_hex(c)]})
    # Direction is not recoverable from prose — "called from X" and "calls X"
    # read the same in a note half the time — so both are offered and the
    # corpus decides which one is true.
    for n in syms:
        seeds.append({"called_by": [n]})
        seeds.append({"calls": [n]})
    if len(syms) > 1:
        seeds.append({"called_by": syms})
        seeds.append({"calls": syms})
    for s in strings[:2]:
        for n in syms[:2]:
            seeds.append({"strings": [s], "called_by": [n]})
            seeds.append({"strings": [s], "calls": [n]})
    if len(offsets) >= 4:
        seeds.append({"offsets": offsets})

    out: list[dict] = []
    for seed in seeds:
        out.append(seed)
        if offsets and "offsets" not in seed:
            # Offsets never select on their own here; they rank inside whatever
            # the seed narrowed to, which is exactly what breaks a two-way tie.
            out.append({**seed, "offsets": offsets})
    return out


def _anchors_are_narrow(b: Build, loc: dict, located: dict[str, int]) -> bool:
    """True if the candidate's anchors (offsets and size bounds aside) already
    select a neighbourhood rather than the whole binary."""
    core = {k: v for k, v in loc.items()
            if k not in ("offsets", "lines_min", "lines_max")}
    if not core:
        return True          # an offsets-only seed is gated by its own key count
    hits, _why = resolve_locator(b, core, located)
    return 0 < len(hits) <= MAX_ANCHOR_POOL


def mine_one(b: Build, sym: dict, located: dict[str, int],
             known: set[str], verbose: bool = False) -> tuple[dict | None, str]:
    """Best verified locator for one symbol, or (None, why-not)."""
    truth = located.get(sym["name"])
    if truth is None:
        return None, "no FUN_ address to verify against"
    a = mine_anchors(sym.get("note") or "", known, sym["name"])
    if not a.any_constraint() and len(a.offsets) < 4:
        return None, "note carries no machine-usable anchor"

    best_ambiguous = 0
    shortlists: list[dict] = []
    for loc in candidates(a, located, sym["name"]):
        if not _anchors_are_narrow(b, loc, located):
            continue
        hits, why = resolve_locator(b, loc, located)
        if verbose and hits:
            print(f"    {len(hits):5} hits  {json.dumps(loc)}  via {why}")
        if hits == [truth]:
            return loc, why
        if truth in hits:
            best_ambiguous = max(best_ambiguous, len(hits))
            if len(hits) <= TIE_BREAK_MAX:
                shortlists.append(loc)

    # Last resort: separate a near-miss by SHAPE. A note's anchor often lands
    # on a small family of near-identical routines (the ContainsAll/ContainsAny
    # pair in backfill_locators is the canonical case), and nothing in the
    # prose tells them apart — but their sizes do. Bounds are deliberately
    # tight: a rebuild that moves the routine then FAILS the locator loudly
    # instead of quietly handing back its sibling.
    span = b.lines(truth)
    if span:
        lo, hi = int(span * 0.9), int(span * 1.1) + 1
        for loc in shortlists:
            tight = {**loc, "lines_min": lo, "lines_max": hi}
            hits, why = resolve_locator(b, tight, located)
            if verbose:
                print(f"    {len(hits):5} hits  {json.dumps(tight)}  via {why}")
            if hits == [truth]:
                return tight, why

    if best_ambiguous:
        return None, f"never unique (best shortlist: {best_ambiguous} hits)"
    return None, "no candidate resolved to the mapped address"


def check(b: Build, doc: dict, located: dict[str, int]) -> int:
    """Re-verify every locator in the map. Returns the number of failures."""
    bad = 0
    checked = 0
    for sym in doc["symbols"]:
        loc = sym.get("locator")
        if not loc:
            continue
        truth = located.get(sym["name"])
        if truth is None:
            continue
        checked += 1
        hits, why = resolve_locator(b, loc, located)
        if hits == [truth]:
            continue
        if truth in hits:
            print(f"  AMBIGUOUS  {sym['name']}: {len(hits)} hits (truth included) via {why}")
        elif hits:
            bad += 1
            print(f"  WRONG      {sym['name']}: {[hex(h) for h in hits[:4]]} "
                  f"!= 0x{truth:x} via {why}")
        else:
            bad += 1
            print(f"  UNRESOLVED {sym['name']}: {why}")
    print(f"\nchecked {checked} locators, {bad} that no longer find their symbol")
    return bad


def break_cycles(found: dict[str, tuple[dict, str]]) -> list[str]:
    """Drop mined locators that only resolve each other.

    Two symbols anchored on one another (`A: calls B` / `B: called by A`) are
    fine while either is found by its byte pattern, and a deadlock when the
    patch that strands one strands both. The pair is broken by dropping the
    thinner locator — the one carrying the fewest independent keys — which
    leaves the survivor pointing at a symbol the pattern DB still finds.
    Returns the names dropped.
    """
    dropped: list[str] = []
    while True:
        refs = {n: {m for k in ("calls", "called_by", "co_called_with")
                    for m in (loc.get(k) or []) if m in found}
                for n, (loc, _w) in found.items()}
        cycle = next(((n, m) for n, ms in refs.items()
                      for m in ms if n in refs.get(m, ())), None)
        if cycle is None:
            return dropped
        weakest = min(cycle, key=lambda n: len(found[n][0]))
        del found[weakest]
        dropped.append(weakest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the verified locators into data/symbols.json")
    ap.add_argument("--check", action="store_true",
                    help="re-verify every locator already in the map (CI-able)")
    ap.add_argument("--only", help="mine just this symbol, showing every candidate")
    args = ap.parse_args()

    doc = json.loads(SYM.read_text())
    by_name = {s["name"]: s for s in doc["symbols"]}
    build = Build(CORPUS, VFTABLES)
    located = {
        s["name"]: int(str(s["raw"]).split("_", 1)[1], 16)
        for s in doc["symbols"]
        if str(s.get("raw") or "").startswith("FUN_")
    }
    known = set(by_name)

    if args.check:
        return 1 if check(build, doc, located) else 0

    if args.only:
        sym = by_name.get(args.only)
        if sym is None:
            print(f"no such symbol: {args.only}", file=sys.stderr)
            return 2
        targets = [sym]
    else:
        targets = [s for s in doc["symbols"]
                   if s.get("status") == "ok" and not s.get("locator")]

    found: dict[str, tuple[dict, str]] = {}
    reasons: dict[str, int] = {}
    for sym in targets:
        if args.only:
            print(f"{sym['name']}  (mapped to {sym.get('raw')})")
        loc, why = mine_one(build, sym, located, known, verbose=bool(args.only))
        if loc is None:
            reasons[why.split(" (")[0]] = reasons.get(why.split(" (")[0], 0) + 1
            if args.only:
                print(f"  no locator: {why}")
            continue
        found[sym["name"]] = (loc, why)
        print(f"  + {sym['name']}: {json.dumps(loc)}")
        print(f"      via {why}")

    for name in break_cycles(found):
        print(f"  - {name}: dropped, its only anchor was a symbol it anchors back")

    print(f"\n{len(targets)} symbol(s) without a locator")
    print(f"  mined and verified unique : {len(found)}")
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {why:26}: {n}")

    if args.apply and found:
        for name, (loc, _why) in found.items():
            by_name[name]["locator"] = loc
        SYM.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {len(found)} locator(s) to {SYM}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
