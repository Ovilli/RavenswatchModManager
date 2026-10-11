#!/usr/bin/env python3
"""Make the `status=va` data globals survive a game patch.

Function symbols re-find themselves: their bytes are in the pattern DB and the
loader scans for them. A `va` global has no bytes of its own — it is an
absolute address into .data/.rdata — so after every patch each one had to be
re-derived by hand, and until then everything built on it (R.options, event
payload decoding, the item-grant registries, net peer slots, ...) stays off
behind the loader's va-gate.

This records, while the address is still known-good, HOW to find each global
again, in two independent ways:

  rtti  A vftable is preceded by a pointer to its RTTI complete object locator,
        which names the class (`.?AVoCEntityHitData@@`) and the subobject
        offset. The class name survives a patch, so the vftable is re-found by
        name. Exact and unambiguous, no code involved.

  ref   Every other global is read by code: `mov rax, [rip+disp]`. Each such
        instruction sits inside a function the pattern DB can re-find. We keep
        that function's pattern, the instruction's shape (bytes with the disp
        wildcarded) and its ordinal among same-shaped instructions in the
        function. After the patch: re-find the function, re-find the
        instruction, decode its disp -> the global's new address. Several
        sites per global, in different functions, so they can outvote one
        another; recovery only applies when they AGREE.

Anchor functions are accepted only when their pattern matches EXACTLY ONCE in
the capture exe — a `match_index` > 0 depends on match order, which a patch
reshuffles — and recovery again demands exactly one hit in the new exe.

  python tools/va_locators.py capture            # today, on the known-good exe
  python tools/va_locators.py verify             # recover on the SAME exe == identity
  python tools/va_locators.py recover --exe NEW  # patch day: report
  python tools/va_locators.py recover --exe NEW --apply   # write agreed VAs

`--apply` rewrites only `va`; a recovered address is still a hypothesis until
the loader runs against it, so follow with `rsmm symbols gen` and a launch.
The locator file is game-derived (instruction bytes) and gitignored, like
data/symbol_fingerprints.json.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import gen_function_patterns as gen  # noqa: E402

SYM = REPO / "data/symbols.json"
DB = REPO / "data/function_patterns.json"
OUT = REPO / "data/va_locators.json"

#: Only EXACT references count. Accepting nearby ones (`[g-0x40]`, "a field of
#: a struct global") was tried and is wrong in both directions here: for the
#: vftables they were references to the NEIGHBOURING vftable, and for a global
#: that is already stale (no code reads it — see the UNREFERENCED notes) they
#: manufactured a locator out of proximity, which would carry a wrong address
#: forward with votes behind it. A global no code reads exactly is reported
#: as not recoverable, which is the truth.
NEAR = 0
#: Sites kept per global. More sites = more independent votes after a patch.
MAX_SITES = 6


class Exe:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.base, self.secs = gen.parse_pe(self.data)
        t = next(s for s in self.secs if s["name"] == ".text")
        self.text = self.data[t["raw_off"]:t["raw_off"] + t["raw_size"]]
        self.tva = self.base + t["rva"]
        self._pdata()

    def _pdata(self) -> None:
        p = next(s for s in self.secs if s["name"] == ".pdata")
        blob = self.data[p["raw_off"]:p["raw_off"] + p["raw_size"]]
        rng = []
        for off in range(0, len(blob) - 11, 12):
            b, e, _u = struct.unpack_from("<III", blob, off)
            if b and e > b:
                rng.append((self.base + b, self.base + e))
        rng.sort()
        self.fn_starts = [r[0] for r in rng]
        self.fn_ends = [r[1] for r in rng]

    def fn_end(self, start: int) -> int | None:
        i = bisect.bisect_left(self.fn_starts, start)
        if i < len(self.fn_starts) and self.fn_starts[i] == start:
            return self.fn_ends[i]
        return None

    def containing(self, va: int) -> int | None:
        i = bisect.bisect_right(self.fn_starts, va) - 1
        if i >= 0 and va < self.fn_ends[i]:
            return self.fn_starts[i]
        return None

    def read(self, va: int, n: int) -> bytes | None:
        rva = va - self.base
        for s in self.secs:
            if s["rva"] <= rva < s["rva"] + s["raw_size"]:
                o = s["raw_off"] + rva - s["rva"]
                return self.data[o:o + n]
        return None

    def q(self, va: int) -> int | None:
        b = self.read(va, 8)
        return struct.unpack("<Q", b)[0] if b and len(b) == 8 else None

    def hits(self, pattern: str) -> list[int]:
        return [self.tva + m.start() for m in gen.pattern_regex(pattern).finditer(self.text)]

    # -- RTTI -------------------------------------------------------------
    def col_of_vftable(self, vft: int):
        """(type-descriptor name, subobject offset) if `vft` is a real vftable."""
        col = self.q(vft - 8)
        hdr = self.read(col, 24) if col else None
        if not hdr or len(hdr) < 24:
            return None
        sig, off, _cd, td_rva = struct.unpack_from("<IIII", hdr)
        if sig != 1:
            return None
        name = self.read(self.base + td_rva + 0x10, 256)
        if not name or not name.startswith(b".?A"):
            return None
        return name.split(b"\0", 1)[0].decode("ascii", "replace"), off

    def vftables_named(self, name: str, sub_off: int) -> list[int]:
        """Every vftable whose COL names `name` at subobject offset `sub_off`."""
        needle = name.encode() + b"\0"
        tds = []
        pos = self.data.find(needle)
        while pos >= 0:
            # The name lives at TypeDescriptor+0x10; map the file offset to a VA.
            for s in self.secs:
                if s["raw_off"] <= pos - 0x10 < s["raw_off"] + s["raw_size"]:
                    tds.append(s["rva"] + (pos - 0x10 - s["raw_off"]))
            pos = self.data.find(needle, pos + 1)
        out = []
        for td_rva in tds:
            pat = struct.pack("<I", 1) + struct.pack("<I", sub_off)
            for s in self.secs:
                if s["name"] not in (".rdata", ".data"):
                    continue
                blob = self.data[s["raw_off"]:s["raw_off"] + s["raw_size"]]
                p = blob.find(pat)
                while p >= 0:
                    if p % 4 == 0 and struct.unpack_from("<I", blob, p + 12)[0] == td_rva:
                        col = self.base + s["rva"] + p
                        out += self._ptrs_to(col)
                    p = blob.find(pat, p + 1)
        return sorted(set(out))

    def _ptrs_to(self, target: int) -> list[int]:
        needle = struct.pack("<Q", target)
        out = []
        for s in self.secs:
            if s["name"] not in (".rdata", ".data"):
                continue
            blob = self.data[s["raw_off"]:s["raw_off"] + s["raw_size"]]
            p = blob.find(needle)
            while p >= 0:
                if p % 8 == 0:
                    out.append(self.base + s["rva"] + p + 8)
                p = blob.find(needle, p + 1)
        return out


def _cs():
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    return md, capstone


def _rip_refs(md, cs, exe: Exe, start: int, end: int):
    """(insn_va, insn_bytes, disp_offset_in_insn, target) for every RIP-relative memory operand."""
    code = exe.text[start - exe.tva:end - exe.tva]
    for ins in md.disasm(code, start):
        for op in ins.operands:
            if op.type == cs.x86.X86_OP_MEM and op.mem.base == cs.x86.X86_REG_RIP:
                tgt = ins.address + ins.size + op.mem.disp
                yield ins.address, bytes(ins.bytes), ins.disp_offset, tgt


def _shape(insn: bytes, disp_off: int) -> str:
    """Instruction bytes with the 4-byte disp wildcarded (an immediate after it is kept)."""
    return " ".join("??" if disp_off <= i < disp_off + 4 else f"{b:02x}"
                    for i, b in enumerate(insn))


def _va_symbols() -> tuple[dict, list[dict]]:
    doc = json.loads(SYM.read_text())
    return doc, [s for s in doc["symbols"] if s.get("status") == "va"]


# -- capture ---------------------------------------------------------------
def capture(exe: Exe, force: bool) -> int:
    if OUT.exists() and not force:
        prev = json.loads(OUT.read_text())
        if prev.get("exe_sha256") != exe.sha:
            print(f"refusing: {OUT.name} was captured from exe {prev.get('exe_sha256','?')[:12]}, "
                  f"this is {exe.sha[:12]}. Capturing from a patched exe whose `va`s are not "
                  "re-derived yet records garbage — run `recover` first. --force to override.",
                  file=sys.stderr)
            return 2
    md, cs = _cs()
    _doc, syms = _va_symbols()
    want: dict[int, list[str]] = {}
    for s in syms:            # two names may share one address
        want.setdefault(int(s["va"], 16), []).append(s["name"])
    sorted_vas = sorted(want)

    pats = json.loads(DB.read_text())
    by_addr = {int(p["addr"], 16): p for p in pats}

    # Pass 1: cheap byte scan for any 32-bit value that, as a rip disp ending
    # 4..8 bytes later, lands near a wanted global. Pass 2 confirms with capstone.
    lo, hi = sorted_vas[0] - NEAR, sorted_vas[-1] + NEAR
    cand_fns: set[int] = set()
    t, tva = exe.text, exe.tva
    for i in range(len(t) - 4):
        d = int.from_bytes(t[i:i + 4], "little", signed=True)
        base = tva + i + 4 + d
        if base + 4 < lo or base > hi:
            continue
        for k in range(5):
            tgt = base + k
            j = bisect.bisect_left(sorted_vas, tgt - NEAR)
            if j < len(sorted_vas) and sorted_vas[j] <= tgt + NEAR:
                f = exe.containing(tva + i)
                if f is not None:
                    cand_fns.add(f)
                break

    pat_cache: dict[int, tuple[str, str] | None] = {}

    def anchor(f: int) -> tuple[str, str] | None:
        """(name, pattern) matching exactly once. The DB's own pattern when it is
        unique; otherwise one built here with the DB's builder, grown until it is
        — most functions that read a global have no DB entry at all."""
        if f in pat_cache:
            return pat_cache[f]
        res = None
        p = by_addr.get(f)
        if p and len(exe.hits(p["pattern"])) == 1:
            res = (p["name"], p["pattern"])
        else:
            end = exe.fn_end(f) or f
            body = exe.text[f - exe.tva:end - exe.tva]
            for n in (32, 64, 128, 256, 512):
                pat, used = gen.make_pattern(body, f, min(n, len(body)))
                if pat and len(exe.hits(pat)) == 1:
                    res = (p["name"] if p else f"FUN_{f:x}", pat)
                    break
                if used >= len(body):
                    break
        pat_cache[f] = res
        return res

    sites: dict[str, list[dict]] = {s["name"]: [] for s in syms}
    for f in sorted(cand_fns):
        p = by_addr.get(f)
        fname = p["name"] if p else f"FUN_{f:x}"
        end = exe.fn_end(f)
        if end is None:
            continue
        refs = list(_rip_refs(md, cs, exe, f, end))
        shapes = Counter()
        for ia, ib, doff, tgt in refs:
            sh = _shape(ib, doff)
            ordinal = shapes[sh]
            shapes[sh] += 1
            j = bisect.bisect_left(sorted_vas, tgt - NEAR)
            for g in sorted_vas[j:]:
                if g > tgt + NEAR:
                    break
                for gname in want[g]:
                    sites[gname].append({
                        "fn": fname, "fn_old": hex(f),
                        "insn_off": ia - f, "shape": sh, "ordinal": ordinal,
                        "delta": g - tgt, "rank": (0 if not fname.startswith("FUN_")
                                                   else 1 if p else 2),
                    })

    out_syms = {}
    for s in syms:
        va, name = int(s["va"], 16), s["name"]
        loc: dict = {"va": hex(va)}
        col = exe.col_of_vftable(va)
        if col:
            hits = exe.vftables_named(*col)
            if hits == [va]:
                loc["rtti"] = {"class": col[0], "sub_off": col[1]}
        # Rank: exact refs first; named symbols, then DB functions, then ones we
        # pattern ourselves; one site per function.
        ranked = sorted(sites[name], key=lambda x: (x["delta"] != 0, x["rank"], x["fn"]))
        chosen, seen = [], set()
        for c in ranked:
            if c["fn"] in seen:
                continue
            a = anchor(int(c["fn_old"], 16))
            if a is None:
                continue
            seen.add(c["fn"])
            chosen.append({**{k: v for k, v in c.items() if k != "rank"}, "pattern": a[1]})
            if len(chosen) >= MAX_SITES:
                break
        if chosen:
            loc["refs"] = chosen
        out_syms[name] = loc

    OUT.write_text(json.dumps({"exe_sha256": exe.sha, "symbols": out_syms},
                              indent=1, ensure_ascii=False) + "\n")
    n_rtti = sum(1 for v in out_syms.values() if "rtti" in v)
    n_ref = sum(1 for v in out_syms.values() if v.get("refs"))
    multi = sum(1 for v in out_syms.values() if len(v.get("refs", [])) >= 2)
    none = [n for n, v in out_syms.items() if "rtti" not in v and not v.get("refs")]
    print(f"wrote {OUT.relative_to(REPO)} for exe {exe.sha[:12]}: {len(out_syms)} va globals")
    print(f"  rtti locator:          {n_rtti}")
    print(f"  code-ref locator:      {n_ref}  ({multi} with >=2 independent sites)")
    print(f"  NOT recoverable:       {len(none)}" + (f"  {none}" if none else ""))
    return 0


# -- recover ---------------------------------------------------------------
def _recover_ref(md, cs, exe: Exe, r: dict) -> tuple[int | None, str]:
    hits = exe.hits(r["pattern"])
    if len(hits) != 1:
        return None, f"{r['fn']}: pattern hits {len(hits)}x"
    f = hits[0]
    end = exe.fn_end(f) or f + 0x4000
    same = [(ia, tgt) for ia, ib, doff, tgt in _rip_refs(md, cs, exe, f, end)
            if _shape(ib, doff) == r["shape"]]
    # Same offset first (function body unchanged), then the same ordinal.
    for ia, tgt in same:
        if ia - f == r["insn_off"]:
            return tgt + r["delta"], f"{r['fn']}@+{r['insn_off']:#x}"
    if r["ordinal"] < len(same):
        ia, tgt = same[r["ordinal"]]
        return tgt + r["delta"], f"{r['fn']}@+{ia - f:#x} (ordinal {r['ordinal']}, moved)"
    return None, f"{r['fn']}: instruction shape gone"


def recover(exe: Exe, apply: bool, quiet_same: bool = False) -> int:
    loc = json.loads(OUT.read_text())
    md, cs = _cs()
    doc, _ = _va_symbols()
    by_name = {s["name"]: s for s in doc["symbols"]}
    agreed, problems = {}, []
    for name, L in loc["symbols"].items():
        votes: Counter = Counter()
        why = []
        if "rtti" in L:
            v = exe.vftables_named(L["rtti"]["class"], L["rtti"]["sub_off"])
            if len(v) == 1:
                votes[v[0]] += 2          # exact by construction: weighs as two sites
                why.append("rtti")
            else:
                why.append(f"rtti {len(v)} hits")
        for r in L.get("refs", []):
            va, w = _recover_ref(md, cs, exe, r)
            if va is not None:
                votes[va] += 1
            why.append(w)
        old = int(L["va"], 16)
        if not votes:
            problems.append((name, "no locator resolved", why))
            continue
        top, n = votes.most_common(1)[0]
        dissent = sum(votes.values()) - n
        if dissent or n < 2:
            problems.append((name, f"{hex(top)} weak: {n} vote(s), {dissent} dissent", why))
            continue
        agreed[name] = top
        if not (quiet_same and top == old):
            print(f"  {name:48s} {hex(old)} -> {hex(top)}  ({n} votes)")

    print(f"\nagreed: {len(agreed)}/{len(loc['symbols'])}")
    for name, msg, why in problems:
        print(f"  ?? {name:45s} {msg}")
        for w in why[:4]:
            print(f"       {w}")
    if apply and agreed:
        changed = 0
        for name, va in agreed.items():
            s = by_name.get(name)
            if s and int(s["va"], 16) != va:
                s["va"] = hex(va)
                changed += 1
        SYM.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        print(f"applied {changed} new va(s) to {SYM.relative_to(REPO)} — now run "
              "`rsmm symbols gen` and prove them in a launch")
    return 0 if not problems else 1


def verify(exe: Exe) -> int:
    """Recover on the capture exe: every agreed address must equal today's."""
    loc = json.loads(OUT.read_text())
    if loc["exe_sha256"] != exe.sha:
        print("verify needs the capture exe; use `recover` for a different build", file=sys.stderr)
        return 2
    md, cs = _cs()
    bad = 0
    for name, L in loc["symbols"].items():
        old = int(L["va"], 16)
        if "rtti" in L:
            v = exe.vftables_named(L["rtti"]["class"], L["rtti"]["sub_off"])
            if v != [old]:
                print(f"  FAIL {name}: rtti -> {[hex(x) for x in v]}")
                bad += 1
        for r in L.get("refs", []):
            va, w = _recover_ref(md, cs, exe, r)
            if va != old:
                print(f"  FAIL {name}: {w} -> {hex(va) if va else None}")
                bad += 1
    n = sum(("rtti" in L) + len(L.get("refs", [])) for L in loc["symbols"].values())
    print(f"verify: {n - bad}/{n} locators reproduce today's address")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["capture", "verify", "recover"])
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    exe = Exe(Path(a.exe))
    if a.cmd == "capture":
        return capture(exe, a.force)
    if a.cmd == "verify":
        return verify(exe)
    return recover(exe, a.apply)


if __name__ == "__main__":
    raise SystemExit(main())
