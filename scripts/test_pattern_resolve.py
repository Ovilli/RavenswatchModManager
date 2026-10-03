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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
try:   # the autodetected install (RSMM_GAME_DIR, Steam), as the other scripts use
    from rsmm.engine.paths import default_game_dir
    DEFAULT_EXE = str(default_game_dir() / "Ravenswatch.exe")
except ImportError:  # pragma: no cover - no package on the path
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
    ap.add_argument("--workers", type=int, help="processes for --all (default: cores-1)")
    args = ap.parse_args()

    with open(args.exe, "rb") as f:
        data = f.read()
    img_base, text = parse_pe(data)
    if text is None:
        sys.exit(".text section not found")
    with open(args.patterns) as f:
        pats = json.load(f)

    if args.all:
        # Scan each distinct pattern once, in parallel, with the loader's own
        # counting (overlapping matches), then compare against recorded VAs.
        import gen_function_patterns as gen
        text_bytes = data[text["raw_off"]:text["raw_off"] + text["raw_size"]]
        text_va = img_base + text["rva"]
        hits_by_pat = gen.scan_many(text_bytes, (e["pattern"] for e in pats), args.workers)
        ok = fail = 0
        for e in pats:
            hits = hits_by_pat[e["pattern"]]
            idx = e.get("match_index", 0)
            want = int(e["addr"], 16)
            got = text_va + hits[idx] if 0 <= idx < len(hits) else None
            if got == want:
                ok += 1
            else:
                fail += 1
                if fail < 5:
                    got_hex = hex(got) if got else None
                    print(f"MISMATCH {e['name']} want={e['addr']} "
                          f"got={got_hex} idx={idx}/{len(hits)}")
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
