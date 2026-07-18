#!/usr/bin/env python3
"""Local disassembler over the live Ravenswatch exe — Ghidra-independent RE.

The Ghidra MCP bridge holds a DIFFERENT/older program than the running build,
so "No function found" and stale decompiles are constant. This reads the ACTUAL
game exe, resolves symbols through the current pattern DB (ground truth for THIS
build), and disassembles by game VA — annotating call/jmp targets with semantic
names from data/symbols.json.

    scripts/disasm.py 0x1406e3210 [count]     # disasm at a game VA (default 40 insns)
    scripts/disasm.py --resolve NAME [count]  # where NAME's pattern lands, + prologue
    scripts/disasm.py --whatis 0x1406e3246    # nearest semantic symbol covering a VA
    scripts/disasm.py --calls NAME            # list call targets out of NAME's body

Options: --exe PATH (default: game Ravenswatch.exe), --raw (no symbol annotation).
Needs capstone (`pip install capstone`) — a dev tool, not shipped in the CLI.
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

_ADDR_RE = re.compile(r"0x1[0-9a-fA-F]{7,9}")


def _rx(pat: str) -> re.Pattern[bytes]:
    return re.compile(
        b"".join(b"." if t == "??" else re.escape(bytes([int(t, 16)])) for t in pat.split()),
        re.DOTALL)


class Image:
    """The exe's .text loaded once, with pattern-resolution + VA<->offset maps."""

    def __init__(self, exe: str):
        data = Path(exe).read_bytes()
        self.img, self.secs = gen.parse_pe(data)
        t = self.secs[0]
        self.text = data[t["raw_off"]:t["raw_off"] + t["raw_size"]]
        self.tva = self.img + t["rva"]
        self._data = data

    def va_bytes(self, va: int, n: int) -> bytes | None:
        off = gen.va_to_offset(va, self.img, self.secs)
        if off is None:
            return None
        return self._data[off:off + n]

    def resolve_pattern(self, pat: dict) -> int | None:
        hits = [m.start() for m in _rx(pat["pattern"]).finditer(self.text)]
        mi = pat.get("match_index", 0)
        if mi >= len(hits):
            return None
        return self.tva + hits[mi]


def _load_symbol_map(img: Image) -> dict[int, str]:
    """{resolved_game_va: name}. Pattern-resolved against THIS build where a
    pattern exists (exact); falls back to the stored raw FUN_<addr> (may be a
    build behind — marked with a '~' by callers)."""
    doc = json.loads(SYM.read_text())
    pats = {p["name"]: p for p in json.loads(DB.read_text()) if not p["name"].startswith("FUN_")}
    out: dict[int, str] = {}
    for s in doc["symbols"]:
        name = s.get("name")
        if not name:
            continue
        p = pats.get(name)
        va = img.resolve_pattern(p) if p else None
        if va is None:
            raw = str(s.get("raw", ""))
            if raw.startswith("FUN_"):
                try:
                    va = int(raw[4:], 16)
                except ValueError:
                    va = None
        if va is not None:
            out.setdefault(va, name)
    return out


def _nearest(sorted_vas: list[int], table: dict[int, str], va: int, max_delta=0x8000):
    import bisect
    i = bisect.bisect_right(sorted_vas, va) - 1
    if i < 0:
        return None
    k = sorted_vas[i]
    if va - k > max_delta:
        return None
    return table[k], va - k


def _disasm(img: Image, start_va: int, count: int, symmap, annotate: bool):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    code = img.va_bytes(start_va, count * 16 + 32)
    if code is None:
        print(f"0x{start_va:x} is not in a mapped section", file=sys.stderr)
        return
    vas = sorted(symmap)
    for ins in md.disasm(code, start_va, count=count):
        line = f"  0x{ins.address:x}:  {ins.mnemonic:<8} {ins.op_str}"
        if annotate:
            for m in _ADDR_RE.finditer(ins.op_str):
                tgt = int(m.group(0), 16)
                exact = symmap.get(tgt)
                if exact:
                    line += f"   ; {exact}"
                else:
                    near = _nearest(vas, symmap, tgt, 0x200)
                    if near:
                        line += f"   ; ~{near[0]}+0x{near[1]:x}"
        print(line)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="disasm", description=__doc__)
    ap.add_argument("va", nargs="?", help="game VA to disassemble (e.g. 0x1406e3210)")
    ap.add_argument("count", nargs="?", type=int, default=40, help="instruction count")
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--resolve", metavar="NAME", help="disassemble where NAME's pattern resolves")
    ap.add_argument("--whatis", metavar="VA", help="nearest semantic symbol covering a VA")
    ap.add_argument("--calls", metavar="NAME", help="list call targets out of NAME's body")
    ap.add_argument("--raw", action="store_true", help="no symbol annotation")
    a = ap.parse_args(argv)

    try:
        import capstone  # noqa: F401
    except ImportError:
        print("capstone not installed (pip install capstone)", file=sys.stderr)
        return 2

    if not Path(a.exe).exists():
        print(f"exe not found: {a.exe}", file=sys.stderr)
        return 2
    img = Image(a.exe)
    symmap = {} if a.raw else _load_symbol_map(img)
    vas = sorted(symmap)

    if a.whatis:
        va = int(a.whatis, 16)
        near = _nearest(vas, symmap, va)
        if near:
            print(f"0x{va:x}  =  {near[0]}+0x{near[1]:x}")
        else:
            print(f"0x{va:x}  =  (no semantic symbol within 0x8000)")
        return 0

    if a.resolve or a.calls:
        name = a.resolve or a.calls
        pats = {p["name"]: p for p in json.loads(DB.read_text())}
        p = pats.get(name)
        if not p:
            print(f"no pattern for '{name}' in {DB.name}", file=sys.stderr)
            return 1
        va = img.resolve_pattern(p)
        if va is None:
            print(f"'{name}' pattern does not resolve in this build", file=sys.stderr)
            return 1
        if a.calls:
            import capstone
            md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            code = img.va_bytes(va, 0x1200)
            print(f"call targets out of {name} @ 0x{va:x}:")
            seen = set()
            for ins in md.disasm(code, va):
                if ins.mnemonic == "ret":
                    break
                if ins.mnemonic == "call":
                    for m in _ADDR_RE.finditer(ins.op_str):
                        tgt = int(m.group(0), 16)
                        if tgt in seen:
                            continue
                        seen.add(tgt)
                        tag = symmap.get(tgt) or (
                            lambda nr: f"~{nr[0]}+0x{nr[1]:x}" if nr else "?"
                        )(_nearest(vas, symmap, tgt, 0x200))
                        print(f"  0x{ins.address:x}  call 0x{tgt:x}   {tag}")
            return 0
        print(f"{name} resolves to 0x{va:x}:")
        _disasm(img, va, a.count, symmap, not a.raw)
        return 0

    if not a.va:
        ap.print_help()
        return 2
    start = int(a.va, 16)
    _disasm(img, start, a.count, symmap, not a.raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
