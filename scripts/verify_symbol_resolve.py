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

import argparse
import json
import re
import sys
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


def _anchor_parent_name(doc: dict, anchor: dict) -> str:
    """Map an anchor's `raw` (FUN_<addr>) back to the symbol that owns it.

    The anchor records the parent by its Ghidra name; the pattern DB is keyed
    by semantic name, so the two have to be joined through symbols.json.
    """
    raw = str(anchor.get("raw", ""))
    for s in doc["symbols"]:
        if str(s.get("raw", "")) == raw and not s.get("anchor"):
            return str(s["name"])
    return raw


def _is_instruction_boundary(md, text: bytes, tva: int, start: int,
                             target: int) -> bool:
    """Walk instructions from `start`; is `target` a boundary we land on?

    Linear disassembly from a known-good function start is reliable here: x86
    is variable-length, so an offset that looks plausible can sit inside an
    instruction. Bounded so a malformed stream cannot spin.
    """
    if target <= start:
        return target == start
    pos = start
    while pos < target and pos - start < 0x2000:
        ins = next(md.disasm(text[pos:pos + 16], tva + pos, count=1), None)
        if ins is None:
            return False
        pos += ins.size
    return pos == target


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
    anchors_checked = 0
    for s in doc["symbols"]:
        if s.get("status") != "ok" or s.get("kind") not in ("function", "event"):
            continue

        # Anchor symbols (inlined routine = parent pattern + offset) carry no
        # top-level `raw`, so `raw.startswith("FUN_")` skipped them entirely —
        # they were verified by NO gate. `symbols audit` cannot see them either
        # (the loader dumps the pattern DB, and an anchor has no pattern of its
        # own), so a broken offset was invisible everywhere. MagicalObject_
        # SpawnAllObjects was landing 2 bytes inside a 5-byte call.
        anchor = s.get("anchor")
        if anchor and not str(s.get("raw", "")).startswith("FUN_"):
            parent = pats.get(_anchor_parent_name(doc, anchor))
            if not parent:
                bad.append((s["name"], "anchor parent has no pattern in DB"))
                continue
            hits = [m.start() for m in _rx(parent["pattern"]).finditer(text)]
            mi = parent.get("match_index", 0)
            if mi >= len(hits):
                bad.append((s["name"], "anchor parent pattern resolves to 0 hits"))
                continue
            off = hits[mi] + int(str(anchor["offset"]), 16)
            anchors_checked += 1
            # An internal entry point is NOT a function start, so the prologue
            # and terminator checks below do not apply. What must hold is that
            # it is a real instruction boundary — detouring mid-instruction
            # corrupts the stream.
            if not _is_instruction_boundary(md, text, tva, hits[mi], off):
                bad.append((s["name"],
                            f"anchor offset {anchor['offset']} is NOT an instruction "
                            f"boundary (lands inside an instruction) — a detour here "
                            f"would splice mid-instruction"))
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
        # A function start is preceded by a TERMINATOR of the previous function:
        # ret (c3), ret imm16 (c2 ..), int3 padding (cc), nop (90), OR a tail
        # call — jmp rel32 (e9 + 4 disp bytes) / jmp rel8 (eb + 1). The tail-jmp
        # case is common (a function whose last act is `jmp helper`) and was a
        # false-positive before: e.g. EntityValueStore_InitBaseValues sits right
        # after `... 41 5e e9 50 ab fc ff` (pop r14; jmp helper).
        boundary = (
            prev.endswith((b"\xcc", b"\xc3", b"\x90"))
            or prev[-1:] == b"\xc2"
            or prev[-5:-4] == b"\xe9"          # jmp rel32 ends exactly at off
            or prev[-2:-1] == b"\xeb"          # jmp rel8 ends exactly at off
        )
        # Robust terminator check: disassemble the 16 bytes before `off`; if any
        # instruction ends EXACTLY at off and is a control-flow terminator
        # (ret / any jmp form, incl. INDIRECT tail calls like `jmp [rax+0x10]`
        # = ff /4, which the byte checks above miss), it's a real boundary. This
        # caught GoPtrOwnerRelay_ForwardCall, preceded by `jmp qword ptr [rax+0x10]`.
        if not boundary:
            for start in range(max(0, off - 16), off):
                pi = next(md.disasm(text[start:off], tva + start, count=1), None)
                if pi is None:
                    continue
                if start + pi.size == off and (
                    pi.mnemonic == "ret" or pi.mnemonic.startswith("jmp")
                    or pi.mnemonic == "int3"
                ):
                    boundary = True
                    break
        ins = list(md.disasm(text[off:off + 16], tva + off, count=1))
        first = ins[0].mnemonic if ins else "?"
        prologue = first in PROLOGUE_FIRST
        if not (boundary and prologue):
            bad.append((s["name"],
                        f"0x{tva + off:x} first={first} boundary={boundary} "
                        f"(mid-instruction / not a function start)"))

    print(f"checked {checked} ok function symbols "
          f"+ {anchors_checked} anchor entry point(s)")
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
