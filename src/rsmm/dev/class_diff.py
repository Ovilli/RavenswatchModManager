#!/usr/bin/env python3
"""
Per-class byte-diff across cooked instances.

Find every cooked file whose root class matches the given name, extract
its final data section, and report which byte offsets are constant
across instances vs which vary. Constant bytes are framework
(struct markers, field counts, padding); variable bytes are actual
values + string content + GUIDs.

For uniform-size classes this immediately reveals the field layout. For
variable-size classes the report buckets instances by size first so each
bucket can be analyzed in isolation.

Usage:
    tools/class_diff.py <RootClassName> [--game-dir /path] [--max N]
    tools/class_diff.py <RootClassName> --list-sizes
    tools/class_diff.py <RootClassName> --body-size 80
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path

from rsmm.engine.paths import DEFAULT_GAME_DIR as DEFAULT_GAME

MARK_BEGIN = bytes.fromhex("1111bbaa")
MARK_END   = bytes.fromhex("2222bbaa")


def parse_root_and_body(path: Path) -> tuple[str | None, bytes]:
    try:
        d = path.read_bytes()
    except OSError:
        return None, b""
    if len(d) < 32:
        return None, b""
    pos = 8
    try:
        if d[pos:pos + 4] == MARK_BEGIN:
            pos += 4
        else:
            slen = struct.unpack_from("<I", d, pos)[0]
            pos += 4 + slen + 4 + 1
            if d[pos:pos + 4] != MARK_BEGIN:
                return None, b""
            pos += 4
        cc = struct.unpack_from("<I", d, pos)[0]
        pos += 4
        if cc == 0 or cc > 200:
            return None, b""
        nl = struct.unpack_from("<I", d, pos)[0]
        pos += 4
        if nl == 0 or nl > 200 or pos + nl > len(d):
            return None, b""
        root = d[pos:pos + nl].decode("ascii", errors="replace")
        lb = d.rfind(MARK_BEGIN)
        le = d.rfind(MARK_END)
        if lb == -1 or le <= lb:
            return root, b""
        return root, d[lb + 4:le]
    except Exception:
        return None, b""


def diff_report(samples: list[bytes], max_print: int = 6) -> None:
    if not samples:
        print("  no samples")
        return
    L = len(samples[0])
    if not all(len(s) == L for s in samples):
        # variable-size: group by size
        by_size: dict[int, list[bytes]] = defaultdict(list)
        for s in samples:
            by_size[len(s)].append(s)
        print(f"  variable-size: {len(by_size)} buckets")
        for sz, group in sorted(by_size.items()):
            print(f"\n  [size={sz}  n={len(group)}]")
            diff_report(group[:max_print + 1], max_print)
        return

    # uniform-size: build per-byte alphabet
    print(f"  uniform-size n={len(samples)} bytes={L}")
    alphabet: list[set[int]] = [set() for _ in range(L)]
    for s in samples:
        for i, b in enumerate(s):
            alphabet[i].add(b)

    # render: dot=constant, X=varies, hex=value
    constants = [next(iter(a)) if len(a) == 1 else None for a in alphabet]
    print("  layout (.=const,?=varies):")
    line = []
    for i in range(L):
        if i and i % 16 == 0:
            print("    " + " ".join(line))
            line = []
        if constants[i] is not None:
            line.append(f"{constants[i]:02x}")
        else:
            line.append("??")
    if line:
        print("    " + " ".join(line))

    var_offsets = [i for i, c in enumerate(constants) if c is None]
    print(f"  varying offsets: {len(var_offsets)} / {L}")
    if var_offsets:
        # show first/last runs of varying offsets
        runs = []
        cur_start = var_offsets[0]
        prev = var_offsets[0]
        for v in var_offsets[1:]:
            if v == prev + 1:
                prev = v
                continue
            runs.append((cur_start, prev))
            cur_start = v
            prev = v
        runs.append((cur_start, prev))
        for s, e in runs[:10]:
            n = e - s + 1
            # show first sample's bytes at that run
            vals = [samples[k][s:e + 1].hex() for k in range(min(4, len(samples)))]
            print(f"    [{s:#04x}..{e:#04x}] len={n}  samples: " + " | ".join(vals))


def size_distribution(samples: list[bytes]) -> dict[int, int]:
    dist: dict[int, int] = defaultdict(int)
    for s in samples:
        dist[len(s)] += 1
    return dict(sorted(dist.items()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("classname")
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--max", type=int, default=200,
                    help="cap samples examined (default 200)")
    ap.add_argument("--list-sizes", action="store_true",
                    help="print body-size distribution and exit")
    ap.add_argument("--body-size", type=int, default=None,
                    help="analyze only samples whose body payload length matches this size")
    args = ap.parse_args()

    cooking = args.game_dir / "DarkTalesResources" / "_Cooking"
    records: list[tuple[Path, bytes]] = []
    for p in cooking.rglob("*.yqz"):
        root, body = parse_root_and_body(p)
        if root != args.classname:
            continue
        if not body:
            continue
        records.append((p, body))
        if len(records) >= args.max:
            break

    samples = [b for _, b in records]
    paths = [p for p, _ in records]

    print(f"class: {args.classname}")
    print(f"found: {len(samples)} samples")
    if not samples:
        print("  no matching samples")
        return 0

    dist = size_distribution(samples)
    if args.list_sizes:
        print("sizes:")
        for sz, count in dist.items():
            print(f"  size={sz:<6d} count={count}")
        return 0

    if args.body_size is not None:
        filtered = [(p, b) for p, b in records if len(b) == args.body_size]
        samples = [b for _, b in filtered]
        paths = [p for p, _ in filtered]
        print(f"filtered size={args.body_size}: {len(samples)} samples")
        if not samples:
            print("  no samples in this bucket")
            return 0

    if samples:
        sample_path = paths[0]
        print(f"first: {sample_path.relative_to(cooking)}")
        print(f"size buckets: {', '.join(f'{k}:{v}' for k, v in dist.items())}")
    diff_report(samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
