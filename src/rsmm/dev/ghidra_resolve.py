#!/usr/bin/env python3
"""
Resolve vtable + Serialize() addresses for every cooked class via PE RTTI scan.

Inputs:
  Ravenswatch.exe (path) + data/cooked_classes.json (Stage 1 manifest).

Algorithm (MSVC x64 RTTI):
  1. For each class name "X" in the manifest, build mangled RTTI name
     ".?AVX@@" (or with namespace prefix — these are flat single-class
     names in this binary, so V suffix works).
  2. Find that ASCIIZ in the image. The byte 16 bytes earlier is the
     start of the TypeDescriptor struct (pVtable + spare + name).
  3. Scan image for any 4-byte little-endian RVA equal to the TypeDescriptor
     RVA; each hit is the +0x0c field of a CompleteObjectLocator.
  4. Validate: COL is at hit - 0x0c; read u32 pSelf at +0x14 → must equal
     COL's own RVA.
  5. Scan image for any 8-byte little-endian VA equal to the COL VA; each
     hit is the vtable[-1] slot. vtable[0] is at hit + 8.
  6. Read vtable[3] = Serialize() address per ravensmith convention
     (confirmed against oCMaterial decompilation).

Output: data/cooked_class_map.json
  { class_name: { uid, vtable_va, serialize_va, col_va, td_va, mangled } }

Failure modes (logged but non-fatal):
  - Mangled RTTI name not found (class may be nested or namespaced).
  - Multiple vtables found (multi-inheritance) — all reported, first wins.

Usage:
  pip install pefile  # required dep, dev-only
  python -m rsmm.dev.ghidra_resolve --exe PATH [--manifest data/cooked_classes.json]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import pefile


def candidate_mangles(name: str) -> list[str]:
    """MSVC RTTI mangling: '.?AV' = class, '.?AU' = struct. Game data classes
    live in oe::dt namespace (mangled inside-out: @dt@oe@@)."""
    return [
        f".?AV{name}@@",
        f".?AV{name}@dt@oe@@",
        f".?AU{name}@@",
        f".?AU{name}@dt@oe@@",
    ]


def file_off_to_rva(pe: pefile.PE, off: int) -> int | None:
    for s in pe.sections:
        start = s.PointerToRawData
        end = start + s.SizeOfRawData
        if start <= off < end:
            return s.VirtualAddress + (off - start)
    return None


def find_all(buf: bytes, needle: bytes) -> list[int]:
    hits = []
    i = 0
    while True:
        j = buf.find(needle, i)
        if j < 0:
            return hits
        hits.append(j)
        i = j + 1


def resolve_class(pe: pefile.PE, raw: bytes, ib: int, class_name: str) -> dict | None:
    mangled = None
    name_hits: list[int] = []
    for candidate in candidate_mangles(class_name):
        hits = find_all(raw, candidate.encode("ascii") + b"\x00")
        if hits:
            mangled = candidate
            name_hits = hits
            break
    if not name_hits or mangled is None:
        return None
    # Pick first hit; ambiguous duplicates are rare for top-level class names.
    name_off = name_hits[0]
    name_rva = file_off_to_rva(pe, name_off)
    if name_rva is None:
        return None
    # TypeDescriptor starts 16 bytes earlier (pVtable + hash).
    td_rva = name_rva - 0x10
    td_va = td_rva + ib

    # Find COLs that point to this TypeDescriptor.
    td_needle = struct.pack("<I", td_rva)
    cols = []
    for hit in find_all(raw, td_needle):
        ref_rva = file_off_to_rva(pe, hit)
        if ref_rva is None:
            continue
        col_rva = ref_rva - 0xC
        try:
            body = pe.get_data(col_rva, 0x18)
        except Exception:
            continue
        sig, this_off, cd_off, ptd, pcd, pself = struct.unpack("<IIIIII", body)
        if pself == col_rva and ptd == td_rva:
            cols.append((col_rva, this_off))
    if not cols:
        return None

    # For each COL, find vtable references.
    vtables = []
    for col_rva, this_off in cols:
        col_va = col_rva + ib
        for hit in find_all(raw, struct.pack("<Q", col_va)):
            ptr_rva = file_off_to_rva(pe, hit)
            if ptr_rva is None:
                continue
            vtable_va = (ptr_rva + ib) + 8
            try:
                vt_slots = struct.unpack("<8Q", pe.get_data(ptr_rva + 8, 64))
            except Exception:
                continue
            vtables.append({
                "col_va": f"{col_va:#x}",
                "this_offset": this_off,
                "vtable_va": f"{vtable_va:#x}",
                "vt_slots": [f"{s:#x}" for s in vt_slots],
                "serialize_va": f"{vt_slots[3]:#x}",
            })

    return {
        "td_va": f"{td_va:#x}",
        "mangled": mangled,
        "vtables": vtables,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--exe",
        type=Path,
        default=Path.home() / (
            ".var/app/com.valvesoftware.Steam/.local/share/Steam/"
            "steamapps/common/Ravenswatch/Ravenswatch.exe"
        ),
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "cooked_classes.json",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "cooked_class_map.json",
    )
    args = ap.parse_args()

    if not args.exe.exists():
        print(f"exe not found: {args.exe}", file=sys.stderr)
        return 1
    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text())
    pe = pefile.PE(str(args.exe), fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    raw = args.exe.read_bytes()

    out: dict[str, dict] = {}
    misses: list[str] = []
    for class_name, info in manifest["classes"].items():
        res = resolve_class(pe, raw, ib, class_name)
        if res is None:
            misses.append(class_name)
            continue
        out[class_name] = {
            "uid": info["uids_seen"][0],
            "versions_seen": info["versions_seen"],
            "td_va": res["td_va"],
            "mangled": res["mangled"],
            "vtables": res["vtables"],
        }
        primary = res["vtables"][0] if res["vtables"] else None
        if primary:
            print(
                f"{class_name:40s}  vt={primary['vtable_va']}  "
                f"serialize={primary['serialize_va']}  "
                f"vtables_total={len(res['vtables'])}"
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "_meta": {
            "exe": str(args.exe),
            "image_base": f"{ib:#x}",
            "resolved": len(out),
            "missed": misses,
        },
        "classes": out,
    }, indent=2))
    print(f"\nwrote {args.out}  resolved={len(out)}  missed={len(misses)}", file=sys.stderr)
    if misses:
        print(f"missed: {misses}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
