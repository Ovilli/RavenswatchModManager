#!/usr/bin/env python3
"""Find the engine's INTERFACE METHODS by diffing vtable slots across siblings.

The technique, generalised from how IsUnlocked was found
--------------------------------------------------------
`oIGameUnlockConditionData` leaves slots 10, 11 and 14 as no-op stubs, and
every subclass overrides all three. Slot 14 turned out to be
`bool IsUnlocked(this)` — the gate the hero picker consults. Nothing about
that was special: it is the general shape of a C++ interface in this engine.

So: for each vtable family, find the slots the BASE stubs out and the
SUBCLASSES fill in. Those are the abstract methods. A slot implemented by many
sibling classes is a method the engine actually dispatches on, which makes it
worth a name — and naming one lights up every call site through that slot at
once, across the whole family.

Ranking by "how many vtables share this function" does NOT work: that finds
the ubiquitous no-op stubs (one appears in 4153 vtables). The signal is the
opposite — a slot whose implementations are all DIFFERENT is carrying real
per-class behaviour.

    tools/mine_vtable_interfaces.py                  # ranked report
    tools/mine_vtable_interfaces.py --family Unlock  # one family
    tools/mine_vtable_interfaces.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VFTABLES = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
SYM = REPO / "data" / "symbols.json"

# A function appearing in this many vtables is structural furniture — a
# no-op, a deleting destructor thunk, _guard_check_icall — not behaviour.
STUB_MIN_SHARE = 40

# Non-game code. The binary is full of pplx/PPL task machinery, std::function
# thunks and Stormancer networking templates, and every instantiation gets its
# own vtable — hundreds of them, all answering questions about C++ plumbing
# rather than about Ravenswatch. They swamp any ranking that does not drop them.
NOISE = re.compile(r"^(std|pplx|Concurrency|boost|Stormancer|rapidjson|msgpack)"
                   r"|_Func_impl|_PPLTaskHandle|_TypeSelector|TaskHandle")

# A "family" of this many classes is not a family, it is a naming convention.
# Everything in the engine ends in Settings; that tells you nothing about which
# question a slot answers.
FAMILY_MAX = 60


def load_vftables() -> list[dict]:
    out = []
    for line in VFTABLES.open():
        rec = json.loads(line)
        rec["cls"] = rec["sym"].replace("::vftable", "")
        out.append(rec)
    return out


def stub_functions(vfts: list[dict]) -> set[str]:
    """Functions so widely shared they cannot be carrying class behaviour."""
    share = Counter()
    for v in vfts:
        for s in {x["va"] for x in v["slots"]}:   # once per vtable
            share[s] += 1
    return {va for va, n in share.items() if n >= STUB_MIN_SHARE}


def family_key(cls: str) -> str:
    """Group sibling classes under the concept they implement.

    RTTI names in this engine are strongly suffixed — HeroRankGameLock*
    *ConditionData*, HeroProgressionUnlock*ConditionData*, ... — so the tail of
    the name is a far better family key than the head.
    """
    base = cls.split("::")[-1]
    base = re.sub(r"^(oC|oI|oe|dt)+", "", base)
    for suffix in ("ConditionData", "ConditionSettings", "EntityCpntSettings",
                   "EntityCpnt", "Settings", "Definition", "Data", "Manager",
                   "Component", "Controller", "Resource", "Layer", "Event"):
        if base.endswith(suffix) and len(base) > len(suffix):
            return suffix
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", help="substring filter on the family key")
    ap.add_argument("--min-impls", type=int, default=3,
                    help="slot must be implemented by at least this many classes")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    vfts = load_vftables()
    stubs = stub_functions(vfts)

    known = set()
    if SYM.exists():
        doc = json.loads(SYM.read_text())
        known = {str(s.get("raw") or "") for s in doc["symbols"]}

    fams: dict[str, list[dict]] = defaultdict(list)
    for v in vfts:
        if NOISE.search(v["cls"]):
            continue
        fams[family_key(v["cls"])].append(v)
    fams = {k: m for k, m in fams.items() if len(m) <= FAMILY_MAX}

    findings = []
    for fam, members in fams.items():
        if args.family and args.family.lower() not in fam.lower():
            continue
        if len(members) < args.min_impls:
            continue
        width = max(len(m["slots"]) for m in members)
        for slot in range(width):
            impls: dict[str, list[str]] = defaultdict(list)
            for m in members:
                if slot >= len(m["slots"]):
                    continue
                va = m["slots"][slot]["va"]
                if va in stubs:
                    continue           # the class does not implement it
                impls[va].append(m["cls"])
            # An interface method: many classes, each with its OWN body.
            if len(impls) < args.min_impls:
                continue
            distinct = len(impls)
            shared = sum(1 for v in impls.values() if len(v) > 1)
            unnamed = sum(1 for va in impls
                          if f"FUN_{int(va, 16):x}" not in known)
            findings.append({
                "family": fam, "slot": slot, "implementations": distinct,
                "unnamed": unnamed, "shared_bodies": shared,
                "examples": [
                    {"class": cs[0], "va": va}
                    for va, cs in sorted(impls.items(), key=lambda kv: -len(kv[1]))[:3]
                ],
            })

    # Most implementations first: that is the most-dispatched method, and
    # naming it pays off at every one of those call sites.
    findings.sort(key=lambda f: (-f["implementations"], f["family"], f["slot"]))

    if args.json:
        print(json.dumps(findings[:args.top], indent=1))
        return 0

    print(f"{len(vfts)} vtables, {len(stubs)} shared stubs filtered out\n")
    print(f"{'family':<22} {'slot':>4} {'impls':>6} {'unnamed':>8}  example class")
    for f in findings[:args.top]:
        ex = f["examples"][0]
        print(f"{f['family']:<22} {f['slot']:>4} {f['implementations']:>6} "
              f"{f['unnamed']:>8}  {ex['class'][:46]} @{ex['va']}")
    print(f"\n{len(findings)} interface slot(s) with >= {args.min_impls} "
          f"distinct implementations.")
    print("Decompile a few implementations of one slot; they all answer the "
          "same question, which is what tells you the name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
