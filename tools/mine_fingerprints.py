#!/usr/bin/env python3
"""Stamp a build-invariant content fingerprint on every resolvable symbol so it
auto-remaps after a game patch instead of stranding.

Root cause this attacks (bottleneck audit 2026-07-17): the symbol map decays
`ok` -> `unverified` -> unrecoverable every game patch, because the only stored
locator is a PROLOGUE byte pattern — and prologue bytes shift, which is exactly
what mis-fired in July (63/80 symbols relocated mid-instruction). 36% of the map
is now stranded with dead addresses that exist in NO retained corpus. The
knowledge is gone.

A prologue is the wrong fingerprint. What survives a rebuild is CONTENT:
  * distinctive embedded constants (class-hash CRCs, rare immediates) — the game
    embeds the same class hash in the same function across builds.
  * string literals the function references.
  * the set of OTHER NAMED symbols it calls (call-graph anchor) — each callee
    re-resolves by its own pattern next build, so "the function that calls
    {NamedEvent_Dispatch, Crc32_TableInit}" is a stable locator even when every
    address and every prologue byte has moved.

This mines that fingerprint for each symbol from the CURRENT decompiled corpus
and writes data/symbol_fingerprints.json. After a patch,
`remap_symbols`-style tooling can re-locate each symbol by matching its
fingerprint against the new corpus — no prologue dependency.

    tools/mine_fingerprints.py            # mine + write the sidecar
    tools/mine_fingerprints.py --verify   # round-trip: how many are uniquely
                                          # re-findable by their own fingerprint

The --verify count is the honest leading indicator: it is the number of symbols
that would survive the next patch via content fingerprint (vs today's 0, since
no content fingerprint is stored at all).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
OUT = REPO / "data" / "symbol_fingerprints.json"

_CONST_RE = re.compile(r"0x[0-9a-fA-F]{6,8}")
_STR_RE = re.compile(r'"([^"]{5,})"')
_CALL_RE = re.compile(r"\bFUN_([0-9a-fA-F]{9})\b")


def _addr(a) -> int:
    return int(a, 16) if isinstance(a, str) else int(a)


def load_corpus(path=CORPUS):
    """{addr:int -> decompiled code} for the given corpus jsonl."""
    by_addr = {}
    for ln in Path(path).open():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        by_addr[_addr(d["addr"])] = d.get("code", "")
    return by_addr


def load_fingerprints(path=OUT):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def _load_corpus():
    return load_corpus()


def _tokens(code: str):
    consts = set()
    for m in _CONST_RE.findall(code):
        v = int(m, 16)
        # drop plain VAs (0x140.. code/data pointers) — not build-invariant.
        if 0x140000000 <= v <= 0x142000000:
            continue
        consts.add(m.lower())
    strings = set(_STR_RE.findall(code))
    call_addrs = {int(a, 16) for a in _CALL_RE.findall(code)}
    return consts, strings, call_addrs


def _build(symbols, corpus):
    # rarity of each const/string across the whole corpus, so we keep only
    # DISTINCTIVE tokens (a constant in 3000 functions locates nothing).
    freq = Counter()
    per = {}
    for a, code in corpus.items():
        consts, strings, _ = _tokens(code)
        per[a] = (consts, strings)
        for t in consts:
            freq[("c", t)] += 1
        for t in strings:
            freq[("s", t)] += 1

    addr2name = {}
    for s in symbols:
        raw = s.get("raw", "")
        if raw.startswith("FUN_"):
            addr2name[int(raw[4:], 16)] = s["name"]

    # Reverse call-graph: for each of OUR symbols, which NAMED symbols call it.
    # Caller-name sets are build-invariant (the callers re-resolve by their own
    # patterns), so this locates functions that are heavily called but call
    # nothing named (Resource_LookupByPath, NamedEvent_Dispatch, ...).
    callers_of: dict[int, set[str]] = {}
    for a, code in corpus.items():
        cn = addr2name.get(a)
        if not cn:
            continue  # only NAMED callers are stable anchors
        for tgt in {int(x, 16) for x in _CALL_RE.findall(code)}:
            if tgt in addr2name:
                callers_of.setdefault(tgt, set()).add(cn)

    fps = {}
    for s in symbols:
        raw = s.get("raw", "")
        if not raw.startswith("FUN_") or s.get("kind") not in ("function", "event"):
            continue
        a = int(raw[4:], 16)
        code = corpus.get(a)
        if code is None:
            continue
        consts, strings, call_addrs = _tokens(code)
        dc = sorted(t for t in consts if freq[("c", t)] <= 4)
        ds = sorted(t for t in strings if freq[("s", t)] <= 4)
        callees = sorted({addr2name[c] for c in call_addrs
                          if c in addr2name and addr2name[c] != s["name"]})
        callers = sorted(callers_of.get(a, set()) - {s["name"]})
        fps[s["name"]] = {
            "consts": dc[:8],
            "strings": ds[:6],
            "callees": callees,
            "callers": callers,
            "n_calls": len(call_addrs),
        }
    return fps, per, addr2name


def _score(fp, consts, strings, callee_names, caller_names):
    sc = 0
    sc += 3 * len(set(fp["consts"]) & consts)
    sc += 2 * len(set(fp["strings"]) & strings)
    sc += 2 * len(set(fp["callees"]) & callee_names)
    sc += 2 * len(set(fp.get("callers", [])) & caller_names)
    return sc


def _index_corpus(corpus, addr2name):
    """Per-function (consts, strings, callee-names), call-count, and the reverse
    caller-name set — everything the fingerprint scorer needs. `addr2name` maps
    the corpus's addresses to OUR symbol names (at real remap time this is the
    partial map that remap's prologue passes already produced)."""
    fn = {}
    ncalls = {}
    callers_of: dict[int, set[str]] = {}
    for a, code in corpus.items():
        consts, strings, call_addrs = _tokens(code)
        callee_names = {addr2name[c] for c in call_addrs if c in addr2name}
        fn[a] = (consts, strings, callee_names)
        ncalls[a] = len(call_addrs)
        cn = addr2name.get(a)
        if cn:
            for tgt in call_addrs:
                if tgt in addr2name:
                    callers_of.setdefault(tgt, set()).add(cn)
    return fn, ncalls, callers_of


def locate(fps, corpus, addr2name):
    """Locate each fingerprinted symbol in `corpus` by content. Returns
    {name: {"addr": int, "score": int, "unique": bool}} — only entries the
    scorer resolved to a candidate. `unique` is True when the top candidate
    strictly beats the runner-up (safe to auto-apply). This is the function
    remap_symbols calls for symbols its prologue passes could not match.
    """
    fn, ncalls, callers_of = _index_corpus(corpus, addr2name)
    out = {}
    for name, fp in fps.items():
        if not (fp["consts"] or fp["strings"] or fp["callees"] or fp.get("callers")):
            continue  # too weak to locate by content alone
        want_nc = fp.get("n_calls", 0)
        scored = []
        for a, (c, s2, cn) in fn.items():
            sc = _score(fp, c, s2, cn, callers_of.get(a, set()))
            if sc > 0:
                scored.append((sc, -abs(ncalls.get(a, 0) - want_nc), a))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        best = scored[0]
        unique = len(scored) == 1 or (best[0], best[1]) > (scored[1][0], scored[1][1])
        out[name] = {"addr": best[2], "score": best[0], "unique": unique}
    return out


def _verify(symbols, corpus, fps, addr2name):
    """Round-trip: does each fingerprint uniquely pick its OWN function back out
    of the corpus? That count is what survives a patch."""
    name2addr = {s["name"]: int(s["raw"][4:], 16)
                 for s in symbols if s.get("raw", "").startswith("FUN_")}
    located = locate(fps, corpus, addr2name)
    unique = ambiguous = weak = 0
    fails = []
    for name, fp in fps.items():
        if not (fp["consts"] or fp["strings"] or fp["callees"] or fp.get("callers")):
            weak += 1
            fails.append((name, "no distinctive tokens"))
            continue
        r = located.get(name)
        target = name2addr[name]
        if r and r["unique"] and r["addr"] == target:
            unique += 1
        else:
            ambiguous += 1
            got = f"0x{r['addr']:x} score {r['score']}" if r else "no hit"
            fails.append((name, f"top={got} (target 0x{target:x})"))
    return unique, ambiguous, weak, fails


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true",
                    help="round-trip check instead of writing the sidecar")
    a = ap.parse_args(argv)

    symbols = json.loads(SYM.read_text())["symbols"]
    corpus = _load_corpus()
    fps, _per, addr2name = _build(symbols, corpus)

    if a.verify:
        uniq, amb, weak, fails = _verify(symbols, corpus, fps, addr2name)
        tot = len(fps)
        print(f"fingerprinted symbols: {tot}")
        print(f"  UNIQUELY re-findable by fingerprint: {uniq} ({100*uniq//max(tot,1)}%)")
        print(f"  ambiguous (needs a tiebreak):        {amb}")
        print(f"  too weak (no distinctive tokens):    {weak}")
        print("\n  survivors carry: distinctive consts / strings / named-callee sets")
        if fails:
            print("\n  not-yet-unique (first 12):")
            for n, why in fails[:12]:
                print(f"    {n}: {why}")
        return 0

    OUT.write_text(json.dumps(fps, indent=1, ensure_ascii=False) + "\n")
    with_c = sum(1 for v in fps.values() if v["consts"])
    with_s = sum(1 for v in fps.values() if v["strings"])
    with_cg = sum(1 for v in fps.values() if v["callees"])
    print(f"wrote {OUT.relative_to(REPO)}: {len(fps)} fingerprints")
    print(f"  with distinctive consts:  {with_c}")
    print(f"  with string refs:         {with_s}")
    print(f"  with named-callee anchor: {with_cg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
