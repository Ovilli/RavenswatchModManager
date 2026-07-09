#!/usr/bin/env python3
"""
Recover functions by build-INDEPENDENT anchors: a unique string literal the
function references, or a unique 32-bit constant it embeds (class hash / UID).
Neither depends on any prior address, so this survives arbitrary build skew
(unlike prologue- or call-site scans that need a matching old .text).

Per target we resolve an anchor to a NEW .text reference site, then map that
site to its containing function via the new Ghidra export's function bounds.
If every anchor for a target lands in the same function, that's the match.

  string anchor:  find the string's VA in the new build (data section scan),
                  then find the rip-relative `lea/mov` in .text that loads it.
  hash anchor:    find the 4-byte little-endian immediate directly in .text.

Config lives in ANCHORS below (semantic knowledge from the symbol notes).

Usage:
  scripts/recover_by_anchor.py [--exe NEW.exe] [--update-symbols]
"""

from __future__ import annotations

import argparse
import bisect
import json
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_function_patterns as gen  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NEW_SYMS = REPO / "docs/_re/out_new/symbols.json"
SYMBOLS_JSON = REPO / "data/symbols.json"

# name -> {"strings": [...], "hashes": [ints]} — anchors drawn from the symbol
# notes. A target matches iff a single function contains ALL its anchors.
ANCHORS: dict[str, dict] = {
    "GameModifierDef_RegisterAssetLoader": {"strings": ["*.gamemodifierdef.ot"]},
    "RewardDef_RegisterAssetLoader":       {"strings": ["*.rewarddef.ot"]},
    "NamedEvent_GiveMagicalObject_Ctor":   {"strings": ["GIVE_MAGICAL_OBJECT"]},
    "HeroDef_LoadSkinEntity":              {"strings": ["Level load - LoadAndGetPlayedHeroEntity"]},
    "InitialLoading_LoadAllDefinitions":   {"strings": ["InitialLoading - Load all definitions"]},
    "Serializer_ReadPolyPtrVector":        {"strings": ["Vector.Length", "Vector[%d]"]},
    "Definition_DeserializeBase":          {"hashes": [0x1768CE8E]},
    "RewardDef_Deserialize":               {"hashes": [0x176F164E]},
    "RewardType_Serialize":                {"hashes": [0x176F4FDC]},
    "CustomFlagFilter_Serialize":          {"hashes": [0x15A9D9BF]},
    "EnemyDefinition_ctor":                {"hashes": [0x176DEBB7]},
}


def load_new():
    new_data = Path(gen.DEFAULT_EXE).read_bytes()
    img, sections = gen.parse_pe(new_data)
    return new_data, img, sections


def section_bytes(data, sec):
    return data[sec["raw_off"]:sec["raw_off"] + sec["raw_size"]], sec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--update-symbols", action="store_true")
    args = ap.parse_args()

    new_data = Path(args.exe).read_bytes()
    img, sections = gen.parse_pe(new_data)
    text_sec = sections[0]
    text = new_data[text_sec["raw_off"]:text_sec["raw_off"] + text_sec["raw_size"]]
    text_va = img + text_sec["rva"]

    # function bounds from the fresh Ghidra export of the new build
    export = json.loads(NEW_SYMS.read_text())
    bounds = sorted((int(f["addr"], 16), int(f["addr"], 16) + int(f["size"]))
                    for f in export)
    starts = [b[0] for b in bounds]

    def containing(va: int) -> int | None:
        i = bisect.bisect_right(starts, va) - 1
        if i < 0:
            return None
        s, e = bounds[i]
        return s if va < e else None

    def string_va(s: str) -> list[int]:
        """VAs where the NUL-terminated ascii string lives (any section)."""
        needle = s.encode() + b"\x00"
        out = []
        for sec in sections:
            blob = new_data[sec["raw_off"]:sec["raw_off"] + sec["raw_size"]]
            base = img + sec["rva"]
            start = 0
            while True:
                i = blob.find(needle, start)
                if i < 0:
                    break
                # must be string start (preceded by NUL or section start)
                if i == 0 or blob[i - 1] == 0:
                    out.append(base + i)
                start = i + 1
        return out

    def sites_referencing_va(target_va: int) -> list[int]:
        """.text offsets with a rip-relative disp32 pointing at target_va."""
        sites = []
        for off in range(len(text) - 4):
            disp = struct.unpack_from("<i", text, off)[0]
            if text_va + off + 4 + disp == target_va:
                sites.append(off)
        return sites

    def sites_with_imm32(value: int) -> list[int]:
        needle = struct.pack("<I", value & 0xFFFFFFFF)
        sites, start = [], 0
        while True:
            i = text.find(needle, start)
            if i < 0:
                break
            sites.append(i)
            start = i + 1
        return sites

    doc = json.loads(SYMBOLS_JSON.read_text())
    resolved: dict[str, int] = {}

    for name, spec in ANCHORS.items():
        func_votes: Counter[int] = Counter()
        detail = []
        for s in spec.get("strings", []):
            svas = string_va(s)
            hit_funcs = set()
            for sva in svas:
                for off in sites_referencing_va(sva):
                    f = containing(text_va + off)
                    if f is not None:
                        hit_funcs.add(f)
            detail.append(f'"{s}"->{len(svas)}va/{len(hit_funcs)}fn')
            for f in hit_funcs:
                func_votes[f] += 1
        for h in spec.get("hashes", []):
            hit_funcs = set()
            for off in sites_with_imm32(h):
                f = containing(text_va + off)
                if f is not None:
                    hit_funcs.add(f)
            detail.append(f"0x{h:x}->{len(hit_funcs)}fn")
            for f in hit_funcs:
                func_votes[f] += 1

        n_anchors = len(spec.get("strings", [])) + len(spec.get("hashes", []))
        if func_votes:
            best, n = func_votes.most_common(1)[0]
            runner = func_votes.most_common(2)[1][1] if len(func_votes) > 1 else 0
            # require the function to satisfy all anchors and be unambiguous
            ok = n == n_anchors and n > runner
            print(f"  {'OK  ' if ok else 'WEAK'} {name}: -> 0x{best:x}  "
                  f"({n}/{n_anchors} anchors, runner {runner}) [{'; '.join(detail)}]",
                  file=sys.stderr)
            if ok:
                resolved[name] = best
        else:
            print(f"  MISS {name}: no anchor hits [{'; '.join(detail)}]",
                  file=sys.stderr)

    print(f"\nrecovered {len(resolved)}/{len(ANCHORS)}", file=sys.stderr)

    if args.update_symbols and resolved:
        for s in doc["symbols"]:
            if s["name"] in resolved:
                new = resolved[s["name"]]
                if s.get("anchor"):
                    s["anchor"]["raw"] = f"FUN_{new:x}"
                else:
                    s["raw"] = f"FUN_{new:x}"
                s["status"] = "ok"
                s["note"] = (s.get("note", "") + " ").lstrip() + \
                    "[2026-07-09: recovered via string/hash anchor.]"
        SYMBOLS_JSON.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"updated data/symbols.json ({len(resolved)} -> ok)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
