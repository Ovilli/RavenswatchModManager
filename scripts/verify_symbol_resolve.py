#!/usr/bin/env python3
"""Sanity gate: every status=ok function symbol's byte-pattern must resolve, in
the live exe, to a genuine FUNCTION BOUNDARY (padding/ret before it + a plausible
prologue at it) — NOT mid-instruction.

Why this exists: the game-update remap (scripts/remap_symbols.py) builds prologue
patterns from an OLD .text dump. If that dump is stale, the "prologue" is really
mid-function bytes, and the pattern then resolves mid-instruction in the new
build. `rsmm symbols gen --check` never catches this — it only checks the
generated artifacts agree with data/symbols.json, never that an address is real.
The July-9 remap shipped ~63 mis-placed symbols this way (see the
symbol-remap-false-ok memory). Run this after every remap, before publishing.

Exit nonzero if any ok symbol resolves to a non-boundary address.

Usage:  scripts/verify_symbol_resolve.py [--exe PATH]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_function_patterns as gen  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data/symbols.json"
DB = REPO / "data/function_patterns.json"

PROLOGUE_FIRST = ("push", "sub", "mov", "lea", "xor", "test", "cmp", "and", "or",
                  "ret", "jmp", "movss", "movaps", "movsxd", "movzx", "inc", "dec",
                  "call", "lock", "xchg", "int3")


def _rx(pat: str) -> re.Pattern[bytes]:
    return re.compile(
        b"".join(b"." if t == "??" else re.escape(bytes([int(t, 16)])) for t in pat.split()),
        re.DOTALL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    args = ap.parse_args()

    try:
        import capstone
    except ImportError:
        print("capstone not installed; skipping resolve gate", file=sys.stderr)
        return 0

    data = Path(args.exe).read_bytes()
    img, secs = gen.parse_pe(data)
    t = secs[0]
    text = data[t["raw_off"]:t["raw_off"] + t["raw_size"]]
    tva = img + t["rva"]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

    pats = {p["name"]: p for p in json.loads(DB.read_text()) if not p["name"].startswith("FUN_")}
    doc = json.loads(SYM.read_text())

    bad = []
    checked = 0
    for s in doc["symbols"]:
        if s.get("status") != "ok" or s.get("kind") not in ("function", "event"):
            continue
        if not str(s.get("raw", "")).startswith("FUN_"):
            continue
        p = pats.get(s["name"])
        if not p:
            bad.append((s["name"], "no pattern in DB for status=ok symbol"))
            continue
        hits = [m.start() for m in _rx(p["pattern"]).finditer(text)]
        mi = p.get("match_index", 0)
        if mi >= len(hits):
            bad.append((s["name"], f"pattern resolves to 0 hits (match_index {mi})"))
            continue
        off = hits[mi]
        checked += 1
        prev = text[max(0, off - 8):off]
        boundary = prev.endswith((b"\xcc", b"\xc3", b"\x90")) or prev[-1:] in (b"\xc2",)
        ins = list(md.disasm(text[off:off + 16], tva + off, count=1))
        first = ins[0].mnemonic if ins else "?"
        prologue = first in PROLOGUE_FIRST
        if not (boundary and prologue):
            bad.append((s["name"],
                        f"0x{tva + off:x} first={first} boundary={boundary} "
                        f"(mid-instruction / not a function start)"))

    print(f"checked {checked} ok function symbols")
    if bad:
        print(f"\n{len(bad)} SYMBOL(S) FAIL the resolve gate:", file=sys.stderr)
        for n, why in bad:
            print(f"  {n}: {why}", file=sys.stderr)
        print("\nThese resolve mid-instruction — the loader would call/detour into "
              "garbage. Recover the correct address or downgrade to 'unverified' + "
              "strip the pattern. See the symbol-remap-false-ok memory.", file=sys.stderr)
        return 1
    print("OK: every ok function symbol resolves to a function boundary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
