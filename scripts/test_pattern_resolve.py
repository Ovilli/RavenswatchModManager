#!/usr/bin/env python3
"""
Resolve a function VA by scanning Ravenswatch.exe for its
pattern-signature. Same algorithm the loader DLL will use at runtime,
implemented in Python so we can validate pattern uniqueness + match-
index correctness without rebuilding the native loader.

Usage:
    scripts/test_pattern_resolve.py FUN_140001130
    scripts/test_pattern_resolve.py 0x14073df80     # by address
    scripts/test_pattern_resolve.py --all           # validate every entry
"""

import argparse
import json
import os
import struct
import sys

DEFAULT_EXE = os.path.expanduser(
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
    "common/Ravenswatch/Ravenswatch.exe"
)


def parse_pe(data: bytes):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    coff_off = e_lfanew + 4
    n_sec = struct.unpack_from("<H", data, coff_off + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff_off + 16)[0]
    img_base = struct.unpack_from("<Q", data, coff_off + 20 + 24)[0]
    sec_off = coff_off + 20 + opt_size
    text = None
    for i in range(n_sec):
        o = sec_off + i * 40
        name = data[o:o + 8].rstrip(b"\x00").decode("ascii", "ignore")
        if name == ".text":
            text = {
                "rva": struct.unpack_from("<I", data, o + 12)[0],
                "vsize": struct.unpack_from("<I", data, o + 8)[0],
                "raw_off": struct.unpack_from("<I", data, o + 20)[0],
                "raw_size": struct.unpack_from("<I", data, o + 16)[0],
            }
            break
    return img_base, text


def compile_pattern(pat: str):
    """'40 53 ?? 8d' -> (bytes, mask)."""
    toks = pat.split()
    b = bytearray()
    m = bytearray()
    for t in toks:
        if t == "??":
            b.append(0)
            m.append(0)
        else:
            b.append(int(t, 16))
            m.append(0xFF)
    return bytes(b), bytes(m)


def find_all(haystack: bytes, pat: bytes, mask: bytes, start: int, end: int):
    """Naive masked scan (Python). Loader DLL will SSE-vectorize this in
    C++ — the algorithm is the same. Returns list of offsets."""
    matches = []
    plen = len(pat)
    # Anchor on the first non-wildcard byte for speed.
    anchor_off = next((i for i, mb in enumerate(mask) if mb), 0)
    anchor_b = pat[anchor_off]
    i = start
    while i <= end - plen:
        # Find next anchor byte occurrence.
        i = haystack.find(bytes([anchor_b]), i, end)
        if i < 0 or i - anchor_off + plen > end:
            break
        base = i - anchor_off
        ok = True
        for k in range(plen):
            if mask[k] and haystack[base + k] != pat[k]:
                ok = False
                break
        if ok:
            matches.append(base)
        i = i + 1
    return matches


def resolve(haystack: bytes, text: dict, img_base: int, entry: dict) -> int | None:
    pat, mask = compile_pattern(entry["pattern"])
    text_start = text["raw_off"]
    text_end = text["raw_off"] + text["raw_size"]
    hits = find_all(haystack, pat, mask, text_start, text_end)
    if not hits:
        return None
    idx = entry.get("match_index", 0)
    if idx >= len(hits):
        return None
    off = hits[idx]
    rva = (off - text["raw_off"]) + text["rva"]
    return img_base + rva


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="function name or 0xADDR")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--patterns", default="data/function_patterns.json")
    args = ap.parse_args()

    with open(args.exe, "rb") as f:
        data = f.read()
    img_base, text = parse_pe(data)
    if text is None:
        sys.exit(".text section not found")
    with open(args.patterns) as f:
        pats = json.load(f)

    if args.all:
        # Fast path: scan each unique pattern once via regex, then
        # compare hit-list against recorded VAs.
        import re
        text_bytes = data[text["raw_off"]:text["raw_off"] + text["raw_size"]]
        def to_regex(pat: str):
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
        by_pat: dict[str, list] = {}
        for e in pats:
            by_pat.setdefault(e["pattern"], []).append(e)
        ok = fail = 0
        scanned = 0
        for pat, entries in by_pat.items():
            rx = to_regex(pat)
            hits = [img_base + text["rva"] + m.start() for m in rx.finditer(text_bytes)]
            for e in entries:
                idx = e.get("match_index", 0)
                want = int(e["addr"], 16)
                got = hits[idx] if 0 <= idx < len(hits) else None
                if got == want:
                    ok += 1
                else:
                    fail += 1
                    if fail < 5:
                        print(f"MISMATCH {e['name']} want={e['addr']} got={hex(got) if got else None} idx={idx}/{len(hits)}")
            scanned += 1
            if scanned % 2000 == 0:
                print(f"  scanned {scanned}/{len(by_pat)} ok={ok} fail={fail}", file=sys.stderr)
        print(f"ALL DONE ok={ok} fail={fail} ({100 * ok / (ok + fail):.2f}%)")
        return

    if not args.query:
        sys.exit("provide a function name or 0xADDR")
    if args.query.startswith("0x"):
        wanted_va = int(args.query, 16)
        entry = next((p for p in pats if int(p["addr"], 16) == wanted_va), None)
    else:
        entry = next((p for p in pats if p["name"] == args.query), None)
    if entry is None:
        sys.exit(f"no entry for {args.query}")
    va = resolve(data, text, img_base, entry)
    print(f"name={entry['name']}")
    print(f"recorded_addr={entry['addr']}")
    print(f"resolved_addr={hex(va) if va else None}")
    print(f"match_index={entry.get('match_index', 0)}")
    print(f"pattern_bytes={len(entry['pattern'].split())}")
    if va == int(entry["addr"], 16):
        print("OK")


if __name__ == "__main__":
    main()
