#!/usr/bin/env python3
"""
Re-locate every function symbol in data/symbols.json after a game update.

For each symbol with a ``raw`` (or ``anchor.raw``) FUN_<addr> reference we:
  1. read the function's prologue bytes from the PREVIOUS build's .text
     (dumped from the Ghidra project via docs/_re/scripts/dump_text_section.py
     — the project keeps the old program even after Steam replaces the exe),
  2. wildcard relocation-sensitive operand bytes (same algorithm as
     scripts/gen_function_patterns.py, whose make_pattern we reuse),
  3. scan the CURRENT exe's .text for that pattern, ranking multi-match
     patterns by occurrence index in the OLD .text (match_index semantics —
     assumes relative ordering of duplicate-pattern functions survives the
     patch, which holds for compiler-emitted code),
  4. emit an old→new address map.

Usage:
  scripts/remap_symbols.py                  # report only
  scripts/remap_symbols.py --write out.json # write the map
  scripts/remap_symbols.py --update-symbols # rewrite data/symbols.json
                                            # raw/anchor/addr fields in place

The written map is consumed by the symbols.json updater and by
scripts/add_function_patterns.py-style DB alias generation.
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
OLD_TEXT_BIN = REPO / "docs/_re/out/text_section.bin"
OLD_TEXT_META = REPO / "docs/_re/out/text_section.json"
SYMBOLS_JSON = REPO / "data/symbols.json"

PROLOGUE_TRY = (32, 48, 64, 96, 128)  # grow until unique in old .text


def pattern_to_regex(pat: str) -> re.Pattern[bytes]:
    parts: list[bytes] = []
    for t in pat.split():
        if t == "??":
            parts.append(b".")
        else:
            b = int(t, 16)
            if b in (0x5C, 0x5B, 0x5D, 0x5E, 0x24, 0x2E, 0x7C, 0x3F,
                     0x2A, 0x2B, 0x28, 0x29, 0x7B, 0x7D):
                parts.append(b"\\" + bytes([b]))
            else:
                parts.append(bytes([b]))
    return re.compile(b"".join(parts), re.DOTALL)


def collect_targets(symbols: list[dict]) -> dict[int, list[str]]:
    """old_addr -> [symbol names referencing it] for every raw/anchor parent."""
    targets: dict[int, list[str]] = {}
    for s in symbols:
        raw = s.get("raw") or (s.get("anchor") or {}).get("raw")
        if not raw:
            continue
        addr = int(raw.split("_", 1)[1], 16)
        targets.setdefault(addr, []).append(s["name"])
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE, help="current game exe")
    ap.add_argument("--write", type=Path, help="write old->new map JSON here")
    ap.add_argument("--update-symbols", action="store_true",
                    help="rewrite data/symbols.json raw/anchor refs in place")
    args = ap.parse_args()

    meta = json.loads(OLD_TEXT_META.read_text())
    old_text = OLD_TEXT_BIN.read_bytes()
    old_text_va = int(meta["text_va"], 16)

    new_data = Path(args.exe).read_bytes()
    img_base, sections = gen.parse_pe(new_data)
    text = sections[0]
    new_text = new_data[text["raw_off"]:text["raw_off"] + text["raw_size"]]
    new_text_va = img_base + text["rva"]

    doc = json.loads(SYMBOLS_JSON.read_text())
    targets = collect_targets(doc["symbols"])
    print(f"{len(targets)} unique old function addresses to remap", file=sys.stderr)

    mapping: dict[str, dict] = {}
    unmatched: list[str] = []
    moved = same = 0

    for old_addr in sorted(targets):
        off = old_addr - old_text_va
        if not (0 <= off < len(old_text)):
            unmatched.append(f"0x{old_addr:x} (outside old .text)")
            continue

        result = None
        for plen in PROLOGUE_TRY:
            prologue = old_text[off:off + plen + 16]
            pat, _used = gen.make_pattern(prologue, old_addr, plen)
            if pat is None:
                continue
            rx = pattern_to_regex(pat)
            old_hits = [m.start() for m in rx.finditer(old_text)]
            if off not in old_hits:
                continue  # pattern somehow doesn't self-match; try longer
            new_hits = [m.start() for m in rx.finditer(new_text)]
            if not new_hits:
                continue  # too strict / code changed; try longer won't help but harmless
            if len(old_hits) == 1 and len(new_hits) == 1:
                result = (new_hits[0], pat, 0, 1)
                break
            if len(old_hits) == len(new_hits):
                # Same duplicate-count: map by rank.
                rank = old_hits.index(off)
                result = (new_hits[rank], pat, rank, len(new_hits))
                break
            # Counts differ — grow the pattern and retry.
        if result is None:
            unmatched.append(f"0x{old_addr:x} ({', '.join(targets[old_addr])})")
            continue

        new_off, pat, rank, nhits = result
        new_addr = new_text_va + new_off
        mapping[f"0x{old_addr:x}"] = {
            "new_addr": f"0x{new_addr:x}",
            "symbols": targets[old_addr],
            "pattern": pat,
            "match_rank": rank,
            "matches": nhits,
        }
        if new_addr == old_addr:
            same += 1
        else:
            moved += 1

    # Pass 2 — for addresses whose pattern duplicate-count changed between
    # builds (rank mapping unusable), predict the new address from the shift
    # delta of the nearest confirmed neighbor and accept the scan hit closest
    # to that prediction. Compiler-emitted code shifts piecewise-linearly, so
    # neighbor deltas are accurate to a few hundred bytes; requiring an exact
    # pattern hit keeps this safe.
    confirmed = sorted(
        (int(o, 16), int(v["new_addr"], 16) - int(o, 16)) for o, v in mapping.items()
    )

    def neighbor_delta(addr: int) -> int:
        best = min(confirmed, key=lambda t: abs(t[0] - addr))
        return best[1]

    WINDOW = 1 << 20  # accept hits within 1MB of the prediction
    still_unmatched: list[str] = []
    for entry in unmatched:
        old_addr = int(entry.split()[0], 16)
        off = old_addr - old_text_va
        resolved = False
        for plen in PROLOGUE_TRY:
            prologue = old_text[off:off + plen + 16]
            pat, _used = gen.make_pattern(prologue, old_addr, plen)
            if pat is None:
                continue
            rx = pattern_to_regex(pat)
            new_hits = [m.start() for m in rx.finditer(new_text)]
            if not new_hits:
                continue
            predicted = old_addr + neighbor_delta(old_addr) - new_text_va
            hit = min(new_hits, key=lambda h: abs(h - predicted))
            if abs(hit - predicted) > WINDOW:
                continue
            new_addr = new_text_va + hit
            mapping[f"0x{old_addr:x}"] = {
                "new_addr": f"0x{new_addr:x}",
                "symbols": targets[old_addr],
                "pattern": pat,
                "match_rank": new_hits.index(hit),
                "matches": len(new_hits),
                "via": "neighbor-delta",
            }
            moved += 1
            resolved = True
            break
        if not resolved:
            still_unmatched.append(entry)
    unmatched = still_unmatched

    print(f"remapped {len(mapping)}: {same} unmoved, {moved} moved; "
          f"{len(unmatched)} unmatched", file=sys.stderr)
    for u in unmatched:
        print(f"  UNMATCHED {u}", file=sys.stderr)

    if args.write:
        args.write.write_text(json.dumps(mapping, indent=1))
        print(f"wrote {args.write}", file=sys.stderr)

    if args.update_symbols:
        remap = {old: v["new_addr"] for old, v in mapping.items()}

        def swap(fun_name: str) -> str:
            old = "0x" + fun_name.split("_", 1)[1]
            new = remap.get(old.lower()) or remap.get(old)
            return f"FUN_{new[2:]}" if new else fun_name

        changed = 0
        for s in doc["symbols"]:
            if s.get("raw"):
                new_name = swap(s["raw"])
                if new_name != s["raw"]:
                    s["raw"] = new_name
                    changed += 1
            if s.get("anchor", {}).get("raw") if s.get("anchor") else None:
                new_name = swap(s["anchor"]["raw"])
                if new_name != s["anchor"]["raw"]:
                    s["anchor"]["raw"] = new_name
                    changed += 1
        SYMBOLS_JSON.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"updated data/symbols.json: {changed} refs rewritten", file=sys.stderr)

    return 0 if not unmatched else 1


if __name__ == "__main__":
    sys.exit(main())
