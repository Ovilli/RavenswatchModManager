#!/usr/bin/env python3
"""
Build data/cooked_classes.json — full taxonomy of every cooked-container class
in the shipped game, with per-class samples for downstream schema work.

Scans every cooked-container extension under DarkTalesResources/_Cooking/:
  .yqz (.gen)  — generic cooked (entity, mesh, material, anim, vfx, defs)
  .tpi (.dxt)  — textures (oCTexture)
  .zux (.nrm)  — normal maps (oCTexture, by convention)

Both container variants are supported:
  Type A: u32 hdr_size, u32 flags, length-prefixed "Cooked", u32 extra,
          u8 tag, then 0xAABB1111 marker.
  Type B: u32 hdr_size, u32 flags, then 0xAABB1111 marker (no "Cooked" string).

For each file the class registry is parsed (every class name + uid + version
+ parent_id). The root class is whichever appears first. Aggregated output is
keyed by class name and records:
  uid_seen          uids observed (typically one, but new schema versions
                    occasionally rebrand uids)
  parents_seen      parent class names observed
  versions_seen     (vmaj, vmin) tuples observed
  containers        ext -> count of files whose root is this class
  size_min/max      body-section size range across files
  samples           up to 5 representative file paths (smallest first)

Usage:
    python -m rsmm.dev.cooked_manifest [--game-dir PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

MARK_BEGIN = bytes.fromhex("1111bbaa")
MARK_END = bytes.fromhex("2222bbaa")

# Cooked-container suffixes on disk (encoded form). Decoded:
#   .yqz -> .gen, .tpi -> .dxt, .zux -> .nrm
COOKED_EXTS = (".yqz", ".tpi", ".zux")

DEFAULT_GAME = Path.home() / (
    ".var/app/com.valvesoftware.Steam/.local/share/Steam/"
    "steamapps/common/Ravenswatch"
)


class ParseError(Exception):
    pass


def parse_classes(data: bytes) -> tuple[list[tuple[str, int, int, int, int]], int, int]:
    """Return (classes, body_begin_off, body_end_off).

    classes is a list of (name, class_id, vmaj, vmin, parent_id) in file order.
    body_begin_off/body_end_off bracket the final data section payload (between
    the last BEGIN and the final END markers).
    """
    if len(data) < 32:
        raise ParseError("too short")
    pos = 8  # hdr_size, flags
    if data[pos:pos + 4] == MARK_BEGIN:
        pos += 4  # Type B
    else:
        slen = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if slen > 32 or pos + slen > len(data):
            raise ParseError("bad cooked-string length")
        # Type A: "Cooked" then u32 extra, u8 tag, BEGIN
        pos += slen + 4 + 1
        if data[pos:pos + 4] != MARK_BEGIN:
            raise ParseError("missing BEGIN after Cooked header")
        pos += 4
    class_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if class_count == 0 or class_count > 200:
        raise ParseError(f"implausible class_count={class_count}")
    classes: list[tuple[str, int, int, int, int]] = []
    for _ in range(class_count):
        nlen = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if nlen == 0 or nlen > 200 or pos + nlen > len(data):
            raise ParseError("bad class name length")
        name = data[pos:pos + nlen].decode("ascii", errors="replace")
        pos += nlen
        if pos + 16 > len(data):
            raise ParseError("truncated class entry")
        class_id, vmaj, vmin, parent_id = struct.unpack_from("<IIII", data, pos)
        pos += 16
        classes.append((name, class_id, vmaj, vmin, parent_id))
    if data[pos:pos + 4] != MARK_END:
        raise ParseError("missing END after class table")
    last_begin = data.rfind(MARK_BEGIN)
    last_end = data.rfind(MARK_END)
    if last_begin == -1 or last_end <= last_begin:
        raise ParseError("no terminal section")
    return classes, last_begin + 4, last_end


def iter_cooked_files(cooking: Path) -> Iterable[Path]:
    for ext in COOKED_EXTS:
        yield from cooking.rglob(f"*{ext}")


def build_manifest(cooking: Path, progress_every: int = 2000) -> dict:
    aggregates: dict[str, dict] = defaultdict(lambda: {
        "uids_seen": set(),
        "parents_seen": set(),
        "versions_seen": set(),
        "containers": defaultdict(int),
        "size_min": None,
        "size_max": None,
        "samples": [],
    })
    parents_by_uid: dict[int, str] = {}
    parse_failures: list[tuple[str, str]] = []

    files = list(iter_cooked_files(cooking))
    print(f"scanning {len(files)} cooked files...", file=sys.stderr)
    for i, p in enumerate(files):
        if i and i % progress_every == 0:
            print(f"  {i}/{len(files)}", file=sys.stderr)
        try:
            data = p.read_bytes()
            classes, b0, b1 = parse_classes(data)
        except (OSError, ParseError) as e:
            parse_failures.append((str(p), str(e)))
            continue
        for name, uid, _vmaj, _vmin, _parent in classes:
            parents_by_uid.setdefault(uid, name)
        root_name, root_uid, root_vmaj, root_vmin, root_parent = classes[0]
        body_size = b1 - b0
        agg = aggregates[root_name]
        agg["uids_seen"].add(root_uid)
        if root_parent:
            parent_name = parents_by_uid.get(root_parent, f"<uid:{root_parent:#x}>")
            agg["parents_seen"].add(parent_name)
        agg["versions_seen"].add((root_vmaj, root_vmin))
        agg["containers"][p.suffix] += 1
        agg["size_min"] = body_size if agg["size_min"] is None else min(agg["size_min"], body_size)
        agg["size_max"] = body_size if agg["size_max"] is None else max(agg["size_max"], body_size)
        rel = p.relative_to(cooking).as_posix()
        agg["samples"].append((body_size, rel))

    out: dict[str, dict] = {}
    for name, agg in aggregates.items():
        agg["samples"].sort()
        samples = [s for _, s in agg["samples"][:5]]
        out[name] = {
            "count": sum(agg["containers"].values()),
            "uids_seen": sorted(f"{u:#010x}" for u in agg["uids_seen"]),
            "parents_seen": sorted(agg["parents_seen"]),
            "versions_seen": sorted([list(v) for v in agg["versions_seen"]]),
            "containers": dict(agg["containers"]),
            "size_min": agg["size_min"],
            "size_max": agg["size_max"],
            "samples": samples,
        }
    return {
        "_meta": {
            "total_files_scanned": len(files),
            "parse_failures": len(parse_failures),
            "cooking_root": str(cooking),
        },
        "classes": dict(sorted(out.items(), key=lambda kv: -kv[1]["count"])),
        "_failures_sample": parse_failures[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "cooked_classes.json",
    )
    args = ap.parse_args()

    cooking = args.game_dir / "DarkTalesResources" / "_Cooking"
    if not cooking.is_dir():
        print(f"_Cooking not found: {cooking}", file=sys.stderr)
        return 1

    manifest = build_manifest(cooking)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2))
    print(f"wrote {args.out} ({len(manifest['classes'])} classes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
