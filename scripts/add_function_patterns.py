#!/usr/bin/env python3
"""
Append byte-pattern signatures for a few explicitly-named functions to
data/function_patterns.json, for functions that exist in the live Ghidra
project but are absent from the (stale) docs/_re/out/symbols.json export
that scripts/gen_function_patterns.py reads.

Reuses gen_function_patterns.py's PE parsing + make_pattern so the entries
are byte-identical in shape to the generator's. Recomputes match_index for
the *new* entries against a full .text scan (same algorithm the loader uses).

Usage:
    scripts/add_function_patterns.py FUN_1401f0f10:0x1401f0f10 FUN_140154c20:0x140154c20
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_function_patterns as gen  # type: ignore  # noqa: E402


def pattern_to_regex(pat: str) -> "re.Pattern[bytes]":
    parts = []
    for t in pat.split():
        if t == "??":
            parts.append(b".")
        else:
            b = int(t, 16)
            if b in (0x5c, 0x5b, 0x5d, 0x5e, 0x24, 0x2e, 0x7c, 0x3f,
                     0x2a, 0x2b, 0x28, 0x29, 0x7b, 0x7d):
                parts.append(b"\\" + bytes([b]))
            else:
                parts.append(bytes([b]))
    return re.compile(b"".join(parts), re.DOTALL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", help="NAME:0xADDR pairs")
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--out", default="data/function_patterns.json")
    args = ap.parse_args()

    with open(args.exe, "rb") as f:
        data = f.read()
    img_base, sections = gen.parse_pe(data)
    text = sections[0]
    text_bytes = data[text["raw_off"]:text["raw_off"] + text["raw_size"]]

    with open(args.out) as f:
        out = json.load(f)
    existing = {e["name"] for e in out}

    added = []
    for tgt in args.targets:
        name, addr_s = tgt.split(":")
        va = int(addr_s, 16)
        if name in existing:
            print(f"skip {name}: already present")
            continue
        off = gen.va_to_offset(va, img_base, sections)
        if off is None:
            print(f"FAIL {name}: addr not in a mapped section")
            continue
        prologue = data[off:off + gen.PROLOGUE_BYTES_MAX + 16]
        # Extend length until the pattern locates this VA uniquely (or max).
        for target_len in range(gen.PROLOGUE_BYTES_DEFAULT,
                                 gen.PROLOGUE_BYTES_MAX + 1, 16):
            pat, used = gen.make_pattern(prologue, va, target_len)
            if pat is None:
                break
            rx = pattern_to_regex(pat)
            va_hits = [img_base + text["rva"] + m.start()
                       for m in rx.finditer(text_bytes)]
            if va in va_hits:
                idx = va_hits.index(va)
                if len(va_hits) == 1 or target_len == gen.PROLOGUE_BYTES_MAX:
                    out.append({"name": name, "addr": hex(va), "size": used,
                                "pattern": pat, "used_bytes": used,
                                "match_index": idx})
                    added.append((name, hex(va), idx, len(va_hits), used))
                    break
            else:
                print(f"WARN {name}: va not found at len {target_len} "
                      f"(hits={len(va_hits)})")
        else:
            print(f"FAIL {name}: could not build a locating pattern")

    if added:
        with open(args.out, "w") as f:
            json.dump(out, f)
        print(f"appended {len(added)} entries to {args.out}:")
        for name, addr, idx, nhits, used in added:
            print(f"  {name} {addr} match_index={idx}/{nhits} bytes={used}")
    else:
        print("nothing appended")


if __name__ == "__main__":
    main()
