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
import struct
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
OUT = REPO / "data" / "symbol_fingerprints.json"

# `\b` and the 9-digit ceiling are load-bearing: without them a 9-digit game VA
# (0x1403a0940) matches as its first 8 digits (0x1403a094), which is a token the
# 0x140.. range filter below can no longer recognise as a VA — so every branch
# target in a function leaks in as a "distinctive constant" that is really just
# this build's address. Measured on the first disassembly-mined symbol: 8 of 8
# consts were truncated VAs. Capping at 9 with a boundary makes an over-long
# literal match nothing at all rather than match a prefix of itself.
_CONST_RE = re.compile(r"0x[0-9a-fA-F]{6,9}\b")
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


def _pdata_ranges(data: bytes, img: int, secs) -> list[tuple[int, int]]:
    """(start, end) VAs from .pdata's RUNTIME_FUNCTION table — the binary's own
    function bounds. A fixed byte window instead would run off the end of the
    function and fingerprint whatever code follows it."""
    pd = next((s for s in secs if s["name"] == ".pdata"), None)
    if pd is None:
        return []
    raw = data[pd["raw_off"]:pd["raw_off"] + pd["raw_size"]]
    out = []
    for o in range(0, len(raw) - 11, 12):
        begin, end, _unwind = struct.unpack_from("<III", raw, o)
        if begin and end > begin:
            out.append((img + begin, img + end))
    out.sort()
    return out


def _cstr_at(data: bytes, img: int, secs, va: int, limit: int = 96) -> str | None:
    import gen_function_patterns as gen
    off = gen.va_to_offset(va, img, secs)
    if off is None:
        return None
    blob = data[off:off + limit]
    end = blob.find(b"\0")
    if end < 5:                      # too short to be a distinctive literal
        return None
    try:
        s = blob[:end].decode("ascii")
    except UnicodeDecodeError:
        return None
    return s if s.isprintable() else None


_RIP_RE = re.compile(r"\[rip \+ (0x[0-9a-f]+)\]")
_HEX_RE = re.compile(r"0x[0-9a-f]+")


def _disasm_code(addrs: set[int], exe: str | None = None) -> dict[int, str]:
    """Fingerprint-source text for functions the decompiled corpus lacks.

    The corpus is a SNAPSHOT (docs/_re/out_new, mined once). Every symbol named
    after it — i.e. every symbol a recent RE session added, exactly the ones
    whose knowledge is freshest and least recoverable — has no corpus entry, and
    `_build` skipped those silently: they got no fingerprint at all and would
    strand on the next game patch with nothing but a dead prologue. That is how
    HeroStats_OnDamageTaken (FUN_1403a0940, named 2026-08-16) came back as "no
    fingerprint" while its own symbols.json note recorded the distinctive
    constant (stat id 0x17df7da0) that would have located it.

    So mine the same three token classes straight from the shipped exe instead:
    immediates, C strings reached by a rip-relative `lea`, and direct call
    targets. Output is a synthetic code blob in the shape `_tokens` already
    parses (bare `0x...` consts, `"..."` strings, `FUN_<9 hex>` calls), so it
    merges into the corpus dict and every downstream stage — rarity counting,
    the reverse call graph, --verify — works on it unchanged.

    Best-effort by design: no capstone or no exe means the affected symbols keep
    today's behaviour (no fingerprint) rather than failing the whole mine.
    """
    if not addrs:
        return {}
    try:
        import capstone
    except ImportError:
        print("capstone not installed (pip install capstone) — "
              f"{len(addrs)} corpus-missing symbol(s) will have no fingerprint",
              file=sys.stderr)
        return {}
    sys.path.insert(0, str(REPO / "scripts"))
    import gen_function_patterns as gen

    exe = exe or gen.DEFAULT_EXE
    if not Path(exe).exists():
        print(f"exe not found: {exe} — {len(addrs)} corpus-missing symbol(s) "
              "will have no fingerprint", file=sys.stderr)
        return {}

    data = Path(exe).read_bytes()
    img, secs = gen.parse_pe(data)
    ranges = _pdata_ranges(data, img, secs)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False

    out: dict[int, str] = {}
    for va in sorted(addrs):
        rng = next(((s, e) for s, e in ranges if s == va), None)
        if rng is None:
            continue                 # not a .pdata function start; leave it out
        start, end = rng
        off = gen.va_to_offset(start, img, secs)
        if off is None:
            continue
        body = data[off:off + (end - start)]
        lines = [f"// disasm-derived fingerprint source for 0x{start:x}"]
        for ins in md.disasm(body, start):
            if ins.mnemonic == "lea":
                m = _RIP_RE.search(ins.op_str)
                if m:
                    s = _cstr_at(data, img, secs,
                                 ins.address + ins.size + int(m.group(1), 16))
                    if s:
                        lines.append(f'  "{s}"')
                        continue
            if ins.mnemonic == "call":
                tgt = _HEX_RE.fullmatch(ins.op_str.strip())
                if tgt:
                    lines.append(f"  FUN_{int(tgt.group(0), 16):09x}();")
                    continue
            if ins.mnemonic.startswith("j"):
                continue             # branch targets are this build's addresses
            for h in _HEX_RE.findall(_RIP_RE.sub("", ins.op_str)):
                lines.append(f"  {h}")
        out[start] = "\n".join(lines)
    return out


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
    ap.add_argument("--exe", default=None,
                    help="game exe to disassemble for symbols the corpus lacks")
    ap.add_argument("--no-disasm", action="store_true",
                    help="corpus only; do not fall back to the exe")
    a = ap.parse_args(argv)

    symbols = json.loads(SYM.read_text())["symbols"]
    corpus = _load_corpus()

    # Fill the corpus gaps from the exe before mining, so a symbol named after
    # the corpus snapshot is fingerprinted like any other (see `_disasm_code`).
    if not a.no_disasm:
        missing = {int(s["raw"][4:], 16) for s in symbols
                   if str(s.get("raw", "")).startswith("FUN_")
                   and s.get("kind") in ("function", "event")
                   and s.get("status") == "ok"
                   and int(s["raw"][4:], 16) not in corpus}
        filled = _disasm_code(missing, a.exe)
        corpus.update(filled)
        if missing:
            print(f"corpus gaps: {len(missing)} ok symbol(s) absent from "
                  f"{CORPUS.name}; {len(filled)} recovered by disassembly")

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
