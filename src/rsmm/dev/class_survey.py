#!/usr/bin/env python3
"""
Bucket every cooked file in _Cooking/ by its root class and surface
classes that look easy to reverse-engineer.

For each class we report:

  count          number of cooked files whose root class is this
  size_min/max   data-section byte spread
  uniform        True if every file's data section is exactly the same size
                 (strong signal of fixed-layout schema -> easy to RE by diffing)

Output is sorted by `uniform * count` so the highest-leverage candidates
come first. Pipe into `head` to get a starting work list.

Usage:
    tools/class_survey.py [--game-dir /path] [--limit N]
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path

MARK_BEGIN = bytes.fromhex("1111bbaa")
MARK_END   = bytes.fromhex("2222bbaa")

DEFAULT_GAME = Path.home() / (
    ".var/app/com.valvesoftware.Steam/.local/share/Steam/"
    "steamapps/common/Ravenswatch"
)


def parse_root(path: Path) -> tuple[str | None, int]:
    """Return (root_class_name, body_section_size) or (None, 0) on parse fail.

    body_section_size = size of the final data section payload (everything
    between the last BEGIN and the final END), which is where a single-instance
    cooked file holds its actual object data.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None, 0
    if len(data) < 32:
        return None, 0
    pos = 0
    try:
        # header: u32 hdr_size, u32 flags
        pos += 8
        if data[pos:pos + 4] == MARK_BEGIN:
            # Type B (stream): no Cooked string. Class table begins here.
            pos += 4
        else:
            # Type A: length-prefixed "Cooked" + u32 extra + u8 tag + BEGIN
            slen = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + slen + 4 + 1
            if data[pos:pos + 4] != MARK_BEGIN:
                return None, 0
            pos += 4
        class_count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if class_count == 0 or class_count > 200:
            return None, 0
        # first class (root)
        nlen = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if nlen == 0 or nlen > 200 or pos + nlen > len(data):
            return None, 0
        root = data[pos:pos + nlen].decode("ascii", errors="replace")
        pos += nlen
        # skip remaining class table: u32 class_id, u32 vmaj, u32 vmin, u32 parent_id
        pos += 16
        for _ in range(class_count - 1):
            nl = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + nl + 16
            if pos > len(data):
                return None, 0
        if data[pos:pos + 4] != MARK_END:
            return root, 0
        # body size: distance from final BEGIN to final END
        last_begin = data.rfind(MARK_BEGIN)
        last_end = data.rfind(MARK_END)
        if last_begin == -1 or last_end <= last_begin:
            return root, 0
        return root, last_end - last_begin - 4
    except Exception:
        return None, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--limit", type=int, default=60,
                    help="rows to print (default 60)")
    ap.add_argument("--ext", default=".yqz",
                    help="cooked-file suffix to scan (default .yqz)")
    args = ap.parse_args()

    cooking = args.game_dir / "DarkTalesResources" / "_Cooking"
    if not cooking.is_dir():
        print(f"_Cooking not found: {cooking}", file=sys.stderr)
        return 1

    buckets: dict[str, list[int]] = defaultdict(list)
    files = list(cooking.rglob(f"*{args.ext}"))
    print(f"scanning {len(files)} files...", file=sys.stderr)

    for i, p in enumerate(files):
        if i and i % 2000 == 0:
            print(f"  {i}/{len(files)}", file=sys.stderr)
        root, size = parse_root(p)
        if not root:
            continue
        buckets[root].append(size)

    # rank: uniform == 1, then count
    rows = []
    for cls, sizes in buckets.items():
        n = len(sizes)
        mn, mx = min(sizes), max(sizes)
        uniform = (mn == mx)
        rows.append((cls, n, mn, mx, uniform))
    # sort: uniform first (desc), then count (desc)
    rows.sort(key=lambda r: (r[4], r[1]), reverse=True)

    print(f"{'cls':<60s} {'count':>6s}  {'min':>7s}  {'max':>7s}  uniform")
    for cls, n, mn, mx, u in rows[: args.limit]:
        flag = " *" if u else ""
        print(f"{cls:<60s} {n:>6d}  {mn:>7d}  {mx:>7d}{flag}")
    print(f"\n... ({len(rows)} distinct root classes total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
