#!/usr/bin/env python3
"""Render data/asset_map.csv's decoded paths as data/uncooked_tree.txt.

The tree is the decoded (plaintext) layout of `_Cooking/`, one line per
path, in `tree(1)` style. Rebuild it whenever asset_map.csv changes:

    python scripts/uncooked_tree.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSET_MAP_CSV = REPO / "data" / "asset_map.csv"
OUT = REPO / "data" / "uncooked_tree.txt"


def _tree() -> tuple[dict, int]:
    root: dict = {}
    seen: set[str] = set()
    with ASSET_MAP_CSV.open(encoding="utf-8", newline="") as f:
        rdr = csv.reader(f)
        next(rdr, None)
        for row in rdr:
            if len(row) < 2 or not row[1]:
                continue
            dec = row[1]
            if dec in seen:
                continue
            seen.add(dec)
            node = root
            for part in dec.split("\\"):
                node = node.setdefault(part, {})
    return root, len(seen)


def _render(node: dict, prefix: str, out: list[str]) -> None:
    names = sorted(node, key=lambda n: (not node[n], n.lower()))
    for i, name in enumerate(names):
        last = i == len(names) - 1
        label = name + "/" if node[name] else name
        out.append(f"{prefix}{'└── ' if last else '├── '}{label}")
        if node[name]:
            _render(node[name], prefix + ("    " if last else "│   "), out)


def main() -> int:
    root, count = _tree()
    lines = [
        "# Ravenswatch uncooked asset tree",
        f"# Source: data/asset_map.csv ({count} decoded paths)",
        "# Root in game: <install>/DarkTalesResources/_Cooking/ (cooked, obfuscated)",
        "",
        ".",
    ]
    _render(root, "", lines)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(REPO)}: {count} paths, {len(lines)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
