#!/usr/bin/env python3
"""Write the fingerprint corpus from the game exe, no Ghidra needed.

tools/mine_fingerprints.py reads docs/_re/out_new/decompiled_new.jsonl: one
line per function, used for rarity counting and the --verify round trip. That
file came from a one-off Ghidra decompile and is gitignored, so a machine
without it cannot mine at all. This disassembles every .pdata function start
with capstone through the miner's own `_disasm_code` and writes the same
{"addr", "code"} lines, so every reader of the corpus works on it unchanged.

    tools/build_disasm_corpus.py [--exe <Ravenswatch.exe>] [--out <path>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gen_function_patterns as gen
import mine_fingerprints as mf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--out", default=str(mf.CORPUS))
    a = ap.parse_args(argv)

    data = Path(a.exe).read_bytes()
    img, secs = gen.parse_pe(data)
    starts = {s for s, _ in mf._pdata_ranges(data, img, secs)}
    code = mf._disasm_code(starts, a.exe)
    if not code:
        print("no functions disassembled", file=sys.stderr)
        return 1

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for va in sorted(code):
            f.write(json.dumps({"addr": f"0x{va:x}", "code": code[va]}) + "\n")
    tmp.replace(out)
    print(f"wrote {len(code)} of {len(starts)} .pdata functions to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
