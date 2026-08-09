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

Slot conventions found so far (a slot number means the same thing across a
whole family, so one identification names N functions at once):

  Definition  slot 18  PostLoad   — resolve typed refs, then register the
                                    instance in the class registry. 13 impls,
                                    all named.
  Definition  slot 19  PreUnload  — release refs, then
                                    Registry_UnregisterInstance. 13 impls.
  Controller  slot 11  cast-by-type-hash — compares an int type id against the
                                    class's own hashes and returns
                                    `this + <base offset>` for the matching
                                    sub-object. 22 impls.
  unlock cond slot 14  IsUnlocked — see data/symbols.json. 5 impls; the
                                    AdditionalContent one is the ownership
                                    check and is deliberately unnamed.

Most slots are NOT like this. Scalar deleting destructors and static
type-descriptor getters dominate, which is what `classify()` filters: the first
full run reported 117 "interface" slots and only 82 survived that filter. Do
not name a slot until you have read two or three implementations and they
plainly answer the same question.

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


# Compiler-generated or trivial bodies. A slot whose implementations are all
# one of these is a C++ convention, not a decision the engine makes: naming 23
# of them buys nothing. Measured on the first full run — the large majority of
# "interface" slots are exactly this, which is why the tool has to say so
# rather than hand back 117 equally-ranked rows.
_DELETING_DTOR = re.compile(r"param_2 & 1|uParam2 & 1")
_CONST_GETTER = re.compile(r"^\s*return (DAT_|_DAT_|&?[A-Za-z_]\w*);\s*$", re.M)


def classify(body: str) -> str:
    """boilerplate | trivial | behaviour"""
    if not body:
        return "trivial"
    n = body.count("\n")
    if _DELETING_DTOR.search(body) and n < 25:
        return "boilerplate"          # scalar deleting destructor
    if n <= 9 and _CONST_GETTER.search(body):
        return "boilerplate"          # returns a static type/desc global
    if n <= 4:
        return "trivial"              # empty or `return 0`
    return "behaviour"


def load_corpus() -> dict:
    out = {}
    for line in CORPUS.open():
        rec = json.loads(line)
        out[int(rec["addr"], 16)] = rec.get("code") or ""
    return out


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
    code = load_corpus()

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
            kinds = Counter(classify(code.get(int(va, 16), "")) for va in impls)
            if kinds["behaviour"] < args.min_impls:
                continue          # all boilerplate: a convention, not a method
            findings.append({
                "family": fam, "slot": slot, "implementations": distinct,
                "behaviour": kinds["behaviour"], "boilerplate": kinds["boilerplate"],
                "unnamed": unnamed, "shared_bodies": shared,
                "examples": [
                    {"class": cs[0], "va": va}
                    for va, cs in sorted(impls.items(), key=lambda kv: -len(kv[1]))[:3]
                ],
            })

    # Most implementations first: that is the most-dispatched method, and
    # naming it pays off at every one of those call sites.
    # Rank by how many implementations carry real behaviour, not by raw count.
    findings.sort(key=lambda f: (-f["behaviour"], f["family"], f["slot"]))

    if args.json:
        print(json.dumps(findings[:args.top], indent=1))
        return 0

    print(f"{len(vfts)} vtables, {len(stubs)} shared stubs filtered out\n")
    print(f"{'family':<22} {'slot':>4} {'behav':>6} {'boiler':>7} {'unnamed':>8}  example")
    for f in findings[:args.top]:
        ex = f["examples"][0]
        print(f"{f['family']:<22} {f['slot']:>4} {f['behaviour']:>6} "
              f"{f['boilerplate']:>7} {f['unnamed']:>8}  {ex['class'][:40]} @{ex['va']}")
    print(f"\n{len(findings)} interface slot(s) with >= {args.min_impls} "
          f"distinct implementations.")
    print("Decompile a few implementations of one slot; they all answer the "
          "same question, which is what tells you the name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
