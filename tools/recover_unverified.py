#!/usr/bin/env python3
"""Relocate `unverified` symbols in the CURRENT build from anchors in their notes.

The bottleneck this attacks (measured 2026-07-17): 50/140 symbols in
data/symbols.json are `status:"unverified"` — the analysis was already done (the
note carries string/class-hash/vtable evidence) but the ADDRESS is 1-2 builds
stale, so the loader fails closed and the capability gets re-reverse-engineered
from scratch. Git shows that manual re-recovery happening 3× already.

This reads each unverified function-symbol's note, extracts machine-usable
anchors, and finds the function in the CURRENT decompiled corpus
(docs/_re/out_new/decompiled_new.jsonl) that embeds them — turning "re-RE from
zero" (hours) into "confirm a ranked 1-3 candidate shortlist" (seconds).

Anchors used, strongest first:
  * class-hash / 32-bit UID constant in the note (game embeds the same class
    hash across builds) — filtered to the class-hash range so CRC polynomials,
    FNV multipliers, VAs and 0xffffffff don't false-match.
  * quoted string literal in the note (rip-referenced by the function).
  * vtable RTTI name in the note (maps via vftables.jsonl to slot functions).

A candidate that is only a trivial hash *getter* (`return 0x...;`) is demoted —
the real target is the ctor/serializer that USES the hash. `--apply` rewrites
`raw` and flips unverified→ok ONLY for an unambiguous single non-trivial
candidate; everything else is reported for human confirmation. Corpus
membership guarantees the address is a real function start, so an applied
address can never be mid-instruction (the false-ok failure mode). Re-runnable;
idempotent.

    tools/recover_unverified.py            # report shortlists
    tools/recover_unverified.py --apply    # rewrite the unambiguous ones
    tools/recover_unverified.py --json      # machine-readable report

After --apply, run:  rsmm symbols gen  &&  python scripts/verify_symbol_resolve.py
to (re)build patterns and prove the flipped symbols resolve to real prologues.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
VFT = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"

# Class-hash space: the game CRCs class names into 0x15xxxxxx..0x1axxxxxx (seen
# throughout the notes: 0x176debb7 EnemyDefinition, 0x18ababa6 BookController,
# 0x15a9d9be CustomFlagList...). Constants outside this window that show up in
# notes are generic (CRC32 poly 0x04c11db7, FNV 0xde5fb9d2, sentinels) and must
# NOT be used as anchors.
_HASH_LO, _HASH_HI = 0x15000000, 0x1B000000
_GENERIC = {0xFFFFFFFF, 0x04C11DB7, 0xDE5FB9D2, 0x0000001B3}  # sentinel, CRC32 poly, FNV bits


def _addr_int(a) -> int:
    return int(a, 16) if isinstance(a, str) else int(a)


# .rdata vftable VA window — a ctor stores its class vftable, so the function
# that embeds this VA IS the ctor (the DATA-xref recovery trick, generalized).
_VFT_LO, _VFT_HI = 0x140E00000, 0x141600000


def _extract_anchors(note: str):
    hashes, strings, vtables, vft_vas = set(), set(), set(), set()
    for h in re.findall(r"0x[0-9a-fA-F]{8,9}", note):
        v = int(h, 16)
        if _VFT_LO <= v < _VFT_HI:
            vft_vas.add(v)                     # class vftable VA -> ctor anchor
            continue
        if 0x140000000 <= v <= 0x142000000:
            continue                            # some other code/data VA, skip
        if _HASH_LO <= v < _HASH_HI and v not in _GENERIC:
            hashes.add(v)
    for s in re.findall(r'"([^"]{4,})"', note):
        # skip note prose in quotes (literals are identifier/path-ish).
        if " " not in s or "\\" in s or s.isupper() or "_" in s:
            strings.add(s)
    for vt in re.findall(r"([A-Za-z_][\w:]*::vftable|oC[A-Za-z]+_vftable)", note):
        vtables.add(vt)
    return hashes, strings, vtables, vft_vas


def _load_corpus():
    funcs = []  # (addr, name, code, size)
    for ln in CORPUS.open():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        funcs.append((_addr_int(d["addr"]), d.get("name", ""), d.get("code", ""),
                      d.get("size", 0)))
    return funcs


def _is_trivial_getter(code: str) -> bool:
    body = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return body.count("return 0x") == 1 and len(body) < 160


def _vtable_slot_funcs():
    m: dict[str, list[int]] = {}
    if not VFT.exists():
        return m
    for ln in VFT.open():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        sym = d.get("sym", "")
        m.setdefault(sym, [])
        for s in d.get("slots", []):
            m[sym].append(_addr_int(s["va"]))
    return m


def recover(apply: bool):
    doc = json.loads(SYM.read_text())
    syms = doc["symbols"]
    corpus = _load_corpus()
    vslots = _vtable_slot_funcs()

    results = []
    for s in syms:
        if s.get("status") != "unverified" or s.get("kind") not in ("function", "event"):
            continue
        note = s.get("note", "") or ""
        hashes, strings, vtables, vft_vas = _extract_anchors(note)
        # a named vtable in the note -> its slot functions are candidates too.
        slot_addrs = set()
        for vt in vtables:
            for cand_sym, addrs in vslots.items():
                if vt.split("::")[0] in cand_sym or vt in cand_sym:
                    slot_addrs.update(addrs)
        if not (hashes or strings or vft_vas or slot_addrs):
            results.append((s["name"], "NO-ANCHOR", []))
            continue
        # score every corpus function by how many anchors it embeds.
        scored = []
        for addr, cname, code, _size in corpus:
            score = 0
            why = []
            for h in hashes:
                if f"0x{h:x}" in code:
                    score += 3
                    why.append(f"hash 0x{h:x}")
            for va in vft_vas:
                if f"0x{va:x}" in code:
                    score += 3
                    why.append(f"vftable 0x{va:x}")
            for st in strings:
                if st in code:
                    score += 2
                    why.append(f'str "{st}"')
            if addr in slot_addrs:
                score += 1
                why.append("vtable slot")
            if score == 0:
                continue
            if _is_trivial_getter(code):
                score -= 2  # a bare `return hash` getter is not the target
                why.append("(trivial getter)")
            scored.append((score, addr, cname, why))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = scored[:3]
        if not top or top[0][0] <= 0:
            results.append((s["name"], "NONE", []))
            continue
        # unambiguous = a single best candidate strictly above the runner-up.
        unambiguous = (
            len(top) == 1 or top[0][0] > (top[1][0] if len(top) > 1 else 0)
        ) and top[0][0] >= 3
        verdict = "UNIQUE" if unambiguous else "AMBIGUOUS"
        results.append((s["name"], verdict, top))
        if apply and unambiguous:
            new_addr = top[0][1]
            s["raw"] = f"FUN_{new_addr:x}"
            s["status"] = "ok"
            tag = (f" [recover_unverified 2026-07-17: relocated to "
                   f"0x{new_addr:x} via {top[0][3][0]}]")
            if tag not in note:
                s["note"] = note + tag

    if apply:
        # match the canonical serialization (indent=1, ascii-escaped) so the
        # diff is the changed symbols only, not a unicode-escaping churn.
        SYM.write_text(json.dumps(doc, indent=1) + "\n")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="rewrite raw+status for unambiguous candidates in symbols.json")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    a = ap.parse_args(argv)

    results = recover(a.apply)
    uniq = [r for r in results if r[1] == "UNIQUE"]
    amb = [r for r in results if r[1] == "AMBIGUOUS"]
    none = [r for r in results if r[1] in ("NONE", "NO-ANCHOR")]

    if a.json:
        print(json.dumps([
            {"name": n, "verdict": v,
             "candidates": [{"addr": f"0x{c[1]:x}", "score": c[0], "why": c[3]} for c in cands]}
            for n, v, cands in results
        ], indent=2))
        return 0

    print(f"unverified function-symbols examined: {len(results)}")
    print(f"  UNIQUE current-build candidate: {len(uniq)}"
          + ("  (APPLIED)" if a.apply else ""))
    print(f"  AMBIGUOUS (needs human pick):   {len(amb)}")
    print(f"  no anchor / no corpus match:    {len(none)}\n")
    for n, _v, cands in uniq:
        c = cands[0]
        print(f"  UNIQUE   {n:34} -> 0x{c[1]:x}  ({', '.join(c[3])})")
    for n, _v, cands in amb:
        opts = "  ".join(f"0x{c[1]:x}(s{c[0]})" for c in cands)
        print(f"  AMBIG    {n:34} -> {opts}")
    if not a.apply and uniq:
        print(f"\n{len(uniq)} symbol(s) are one --apply from live. Then:")
        print("  rsmm symbols gen && python scripts/verify_symbol_resolve.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
