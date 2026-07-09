#!/usr/bin/env python3
"""
Recover functions whose own prologue changed too much for a direct
byte-pattern scan (scripts/remap_symbols.py leaves these unmatched) by
following CALL edges from functions that DID remap.

Method (per target old function F):
  1. Scan the OLD .text for every direct call to F: `e8 <rel32>` where
     site+5+rel32 == F, and `ff 15 <rip-rel32>` indirect-through-IAT is
     ignored (only direct calls are position-portable).
  2. Each call site lives inside some old function G. Remap G by prologue
     pattern (on demand, cached). Skip if G doesn't remap.
  3. In the NEW build's G, near the same function-relative offset, find an
     `e8` whose preceding bytes match the old site's context, decode its
     rel32 -> candidate F_new.
  4. Candidates vote; a clear majority (>=2 and strictly > runner-up) wins.

This works because a called function's ENTRY moves, but the CALLERS'
instruction shape is stable, so their call displacement in the new build
points straight at the new entry.

Usage:
  scripts/recover_by_callsite.py [--exe NEW.exe] [--write out.json]
                                 [--update-symbols]
Requires the old .text dump (docs/_re/out/text_section.{bin,json}) and the
old symbol export (docs/_re/out/symbols.json) for function boundaries.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_function_patterns as gen  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OLD_TEXT_BIN = REPO / "docs/_re/out/text_section.bin"
OLD_TEXT_META = REPO / "docs/_re/out/text_section.json"
OLD_SYMS = REPO / "docs/_re/out/symbols.json"
SYMBOLS_JSON = REPO / "data/symbols.json"

PROLOGUE_TRY = (32, 48, 64, 96, 128)
SITE_WINDOW = 160     # how far a call site may drift inside its function
CTX = 5               # bytes of context before the e8 opcode to anchor on


def _rx(pat: str) -> re.Pattern[bytes]:
    return re.compile(
        b"".join(b"." if t == "??" else re.escape(bytes([int(t, 16)]))
                 for t in pat.split()),
        re.DOTALL,
    )


def find_call_sites(text: bytes, target_off: int) -> list[int]:
    """Offsets of `e8 rel32` direct calls whose target == target_off."""
    sites = []
    start = 0
    while True:
        i = text.find(b"\xe8", start)
        if i < 0 or i + 5 > len(text):
            break
        rel = struct.unpack_from("<i", text, i + 1)[0]
        if i + 5 + rel == target_off:
            sites.append(i)
        start = i + 1
    return sites


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--write", type=Path)
    ap.add_argument("--update-symbols", action="store_true")
    args = ap.parse_args()

    meta = json.loads(OLD_TEXT_META.read_text())
    old_text = OLD_TEXT_BIN.read_bytes()
    old_tva = int(meta["text_va"], 16)

    new_data = Path(args.exe).read_bytes()
    img_base, sections = gen.parse_pe(new_data)
    tsec = sections[0]
    new_text = new_data[tsec["raw_off"]:tsec["raw_off"] + tsec["raw_size"]]
    new_tva = img_base + tsec["rva"]

    old_export = json.loads(OLD_SYMS.read_text())
    bounds = sorted((int(f["addr"], 16), int(f["addr"], 16) + int(f["size"]))
                    for f in old_export)
    starts = [b[0] for b in bounds]

    remap_cache: dict[int, int | None] = {}

    def remap_func(old_addr: int) -> int | None:
        if old_addr in remap_cache:
            return remap_cache[old_addr]
        off = old_addr - old_tva
        result = None
        for plen in PROLOGUE_TRY:
            pat, _ = gen.make_pattern(old_text[off:off + plen + 16], old_addr, plen)
            if pat is None:
                continue
            rx = _rx(pat)
            oh = [m.start() for m in rx.finditer(old_text)]
            nh = [m.start() for m in rx.finditer(new_text)]
            if off in oh and nh and len(oh) == len(nh):
                result = new_tva + nh[oh.index(off)]
                break
        remap_cache[old_addr] = result
        return result

    def containing(site_va: int) -> int | None:
        i = bisect.bisect_right(starts, site_va) - 1
        if i < 0:
            return None
        s, e = bounds[i]
        return s if site_va < e else None

    # Targets = unverified function symbols still holding a pre-patch addr.
    doc = json.loads(SYMBOLS_JSON.read_text())
    targets = {}
    for s in doc["symbols"]:
        if s.get("status") != "unverified":
            continue
        raw = s.get("raw") or (s.get("anchor") or {}).get("raw")
        if raw:
            targets.setdefault(int(raw.split("_", 1)[1], 16), []).append(s["name"])

    resolved: dict[str, int] = {}
    for old_addr in sorted(targets):
        names = targets[old_addr]
        votes: Counter[int] = Counter()
        n_sites = n_callers = 0
        for site in find_call_sites(old_text, old_addr - old_tva):
            n_sites += 1
            site_va = old_tva + site
            g_old = containing(site_va)
            if g_old is None or g_old == old_addr:
                continue
            g_new = remap_func(g_old)
            if g_new is None:
                continue
            n_callers += 1
            foff = site_va - g_old
            ctx = old_text[site - CTX:site]  # bytes right before the e8
            g_new_off = g_new - new_tva
            lo = max(0, g_new_off + foff - SITE_WINDOW)
            hi = min(len(new_text) - 5, g_new_off + foff + SITE_WINDOW)
            probe = lo
            while True:
                j = new_text.find(ctx + b"\xe8", probe, hi + CTX + 1)
                if j < 0:
                    break
                e8 = j + CTX
                rel = struct.unpack_from("<i", new_text, e8 + 1)[0]
                votes[new_tva + e8 + 5 + rel] += 1
                probe = j + 1
        label = "/".join(names)
        if votes:
            best, n = votes.most_common(1)[0]
            runner = votes.most_common(2)[1][1] if len(votes) > 1 else 0
            ok = n >= 2 and n > runner
            print(f"  {'OK  ' if ok else 'WEAK'} {label}: 0x{old_addr:x} -> "
                  f"0x{best:x}  ({n} votes / {n_callers} callers / "
                  f"{n_sites} sites, runner {runner})", file=sys.stderr)
            if ok:
                for nm in names:
                    resolved[nm] = best
        else:
            print(f"  MISS {label}: {n_sites} call sites, {n_callers} "
                  f"remappable callers, no vote", file=sys.stderr)

    print(f"\nrecovered {len(resolved)}/"
          f"{sum(len(v) for v in targets.values())} symbols", file=sys.stderr)

    if args.write:
        args.write.write_text(json.dumps(
            {k: f"0x{v:x}" for k, v in resolved.items()}, indent=1))

    if args.update_symbols and resolved:
        for s in doc["symbols"]:
            if s["name"] in resolved:
                new = resolved[s["name"]]
                if s.get("raw"):
                    s["raw"] = f"FUN_{new:x}"
                elif s.get("anchor"):
                    s["anchor"]["raw"] = f"FUN_{new:x}"
                s["status"] = "ok"
                s["note"] = (s.get("note", "") + " ").lstrip() + \
                    "[2026-07-09: recovered via call-site consensus.]"
        SYMBOLS_JSON.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"updated data/symbols.json ({len(resolved)} symbols -> ok)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
