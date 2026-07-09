#!/usr/bin/env python3
"""
Re-locate ``va``-status data symbols (globals + vftables) after a game update.

Two strategies:

* ``--vftables OLD.jsonl NEW.jsonl`` — vftables are recovered by Ghidra from
  RTTI, whose mangled class names are stable across builds. Join old addr ->
  RTTI symbol name -> new addr.

* data-ref consensus (default, for ``g_*`` globals) — find every
  RIP-relative reference to the global's OLD address inside functions we
  already remapped (scripts/remap_symbols.py). For each site, look in the
  NEW build's version of that function, around the same function-relative
  offset, for the same instruction encoding (opcode bytes minus the 4-byte
  displacement) and decode the displacement found there. Sites vote; the
  majority target wins. Requires docs/_re/out/text_section.{bin,json}
  (old build) — see dump_text_section.py.

Usage:
  scripts/rewire_va_globals.py --remap remap.json [--vftables old.jsonl new.jsonl]
      [--update-symbols]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_function_patterns as gen  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OLD_TEXT_BIN = REPO / "docs/_re/out/text_section.bin"
OLD_TEXT_META = REPO / "docs/_re/out/text_section.json"
SYMBOLS_JSON = REPO / "data/symbols.json"

SITE_WINDOW = 96      # how far the site may drift inside the function
MIN_OPCODE_CTX = 3    # opcode bytes preceding the displacement to match on


def find_ref_sites(old_text: bytes, old_text_va: int, target: int) -> list[int]:
    """Offsets in old .text whose int32 reads as a RIP-relative disp to target."""
    sites = []
    # disp32 sits at the end of the instruction: next_ip = va(site)+4 (+imm for
    # some encodings — those simply won't verify in the consensus pass).
    want = target - old_text_va
    for off in range(0, len(old_text) - 4):
        disp = struct.unpack_from("<i", old_text, off)[0]
        if off + 4 + disp == want:
            sites.append(off)
    return sites


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--remap", type=Path, required=True,
                    help="remap_symbols.py --write output")
    ap.add_argument("--vftables", nargs=2, type=Path, metavar=("OLD", "NEW"),
                    help="old + new ExportVftables.java jsonl dumps")
    ap.add_argument("--update-symbols", action="store_true")
    args = ap.parse_args()

    doc = json.loads(SYMBOLS_JSON.read_text())
    va_syms = [s for s in doc["symbols"]
               if s.get("va") and not s.get("raw") and not s.get("anchor")]

    resolved: dict[str, int] = {}

    # --- strategy 1: RTTI vftable name join -------------------------------
    if args.vftables:
        old_by_addr = {}
        for line in args.vftables[0].read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                old_by_addr[int(e["addr"], 16)] = e["sym"]
        new_by_sym = {}
        for line in args.vftables[1].read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                new_by_sym[e["sym"]] = int(e["addr"], 16)
        for s in va_syms:
            old_va = int(s["va"], 16)
            sym_name = old_by_addr.get(old_va)
            if sym_name and sym_name in new_by_sym:
                resolved[s["name"]] = new_by_sym[sym_name]
                print(f"  vftable {s['name']}: 0x{old_va:x} -> "
                      f"0x{new_by_sym[sym_name]:x}  ({sym_name})", file=sys.stderr)

    # --- strategy 2: data-ref consensus -----------------------------------
    meta = json.loads(OLD_TEXT_META.read_text())
    old_text = OLD_TEXT_BIN.read_bytes()
    old_text_va = int(meta["text_va"], 16)

    new_data = Path(args.exe).read_bytes()
    img_base, sections = gen.parse_pe(new_data)
    tsec = sections[0]
    new_text = new_data[tsec["raw_off"]:tsec["raw_off"] + tsec["raw_size"]]
    new_text_va = img_base + tsec["rva"]

    remap = {int(o, 16): int(v["new_addr"], 16)
             for o, v in json.loads(args.remap.read_text()).items()}

    # Function boundaries of the OLD build (Ghidra export made before the
    # patch) — lets us locate any reference site's containing function, then
    # remap that function on demand by pattern scan (cached).
    old_export = json.loads((REPO / "docs/_re/out/symbols.json").read_text())
    old_bounds = sorted((int(f["addr"], 16), int(f["addr"], 16) + int(f["size"]))
                        for f in old_export)
    old_starts = [b[0] for b in old_bounds]

    import bisect
    import re as _re

    def containing_func(site_va: int) -> int | None:
        i = bisect.bisect_right(old_starts, site_va) - 1
        if i < 0:
            return None
        start, end = old_bounds[i]
        return start if site_va < end else None

    PROLOGUE_TRY = (32, 48, 64, 96, 128)

    def _rx(pat: str) -> _re.Pattern[bytes]:
        parts = []
        for t in pat.split():
            if t == "??":
                parts.append(b".")
            else:
                b = int(t, 16)
                parts.append(_re.escape(bytes([b])))
        return _re.compile(b"".join(parts), _re.DOTALL)

    def remap_func(old_addr: int) -> int | None:
        """old function VA -> new function VA (pattern scan, cached)."""
        if old_addr in remap:
            return remap[old_addr]
        off = old_addr - old_text_va
        for plen in PROLOGUE_TRY:
            pat, _ = gen.make_pattern(old_text[off:off + plen + 16], old_addr, plen)
            if pat is None:
                continue
            rx = _rx(pat)
            old_hits = [m.start() for m in rx.finditer(old_text)]
            new_hits = [m.start() for m in rx.finditer(new_text)]
            if off in old_hits and new_hits and len(old_hits) == len(new_hits):
                remap[old_addr] = new_text_va + new_hits[old_hits.index(off)]
                return remap[old_addr]
        remap[old_addr] = None  # cache the failure
        return None

    for s in va_syms:
        if s["name"] in resolved:
            continue
        old_va = int(s["va"], 16)
        votes: Counter[int] = Counter()
        for site in find_ref_sites(old_text, old_text_va, old_va):
            site_va = old_text_va + site
            f_old = containing_func(site_va)
            if f_old is None:
                continue
            f_new = remap_func(f_old)
            if f_new is None:
                continue
            func_off = site_va - f_old
            ctx = old_text[site - MIN_OPCODE_CTX:site]
            f_new_off = f_new - new_text_va
            lo = max(0, f_new_off + func_off - SITE_WINDOW)
            hi = min(len(new_text) - 4, f_new_off + func_off + SITE_WINDOW)
            probe = lo
            while True:
                probe = new_text.find(ctx, probe, hi + MIN_OPCODE_CTX)
                if probe < 0:
                    break
                dloc = probe + MIN_OPCODE_CTX
                disp = struct.unpack_from("<i", new_text, dloc)[0]
                votes[new_text_va + dloc + 4 + disp] += 1
                probe += 1
        if votes:
            best, n = votes.most_common(1)[0]
            runner = votes.most_common(2)[1][1] if len(votes) > 1 else 0
            ok = n >= 2 and n > runner
            print(f"  {'OK  ' if ok else 'WEAK'} {s['name']}: 0x{old_va:x} -> "
                  f"0x{best:x}  ({n} votes, runner-up {runner})", file=sys.stderr)
            if ok:
                resolved[s["name"]] = best
        else:
            print(f"  MISS {s['name']}: no reference sites survived", file=sys.stderr)

    print(f"resolved {len(resolved)}/{len(va_syms)} va symbols", file=sys.stderr)

    if args.update_symbols and resolved:
        for s in doc["symbols"]:
            if s["name"] in resolved:
                s["va"] = f"0x{resolved[s['name']]:x}"
        SYMBOLS_JSON.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"updated data/symbols.json ({len(resolved)} va fields)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
