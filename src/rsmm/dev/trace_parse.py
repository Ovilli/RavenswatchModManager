#!/usr/bin/env python3
"""Extract DarkTalesResources file accesses from a Wine +file debug log.

Usage:
    tools/trace_parse.py [/path/to/steam-<appid>.log]

Reads the Proton/Wine debug log produced when the game is launched with
PROTON_LOG=1 WINEDEBUG=+file and reports unique paths under
DarkTalesResources that the game/engine opened (or attempted to open).
Useful for answering:

  * Does the engine probe uncooked .ot paths anywhere outside _Cooking/?
  * What's the lookup order: text source first, cooked .gen first, or
    only-cooked?
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_LOG = os.environ.get(
    "RSMM_TRACE_LOG",
    str(Path.home() / ".var/app/com.valvesoftware.Steam/steam-2071280.log"),
)

PATH_RE = re.compile(r'[A-Z]:\\\\[^"\s\)\]]*?DarkTalesResources[^"\s\)\]]*', re.IGNORECASE)
# Wine prints both Windows-style (C:\...) and unix-style (/home/...) paths
# depending on the call. Catch both.
UNIX_RE = re.compile(r'/[^\s"\)\]]*DarkTalesResources/[^\s"\)\]]*')


def main():
    log = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG)
    if not log.exists():
        print(f"log not found: {log}", file=sys.stderr)
        sys.exit(1)

    hits: Counter[str] = Counter()
    cooked = 0
    uncooked = 0
    with log.open("r", encoding="latin-1", errors="replace") as f:
        for line in f:
            for rx in (PATH_RE, UNIX_RE):
                for m in rx.findall(line):
                    p = m.replace("\\\\", "\\")
                    hits[p] += 1
                    if "_Cooking" in p:
                        cooked += 1
                    else:
                        uncooked += 1

    print(f"# unique DarkTalesResources paths: {len(hits)}")
    print(f"# total accesses — cooked tree: {cooked}, outside _Cooking: {uncooked}")
    print()
    print("# Top 40 most-accessed:")
    for p, n in hits.most_common(40):
        print(f"{n:6d}  {p}")

    print()
    print("# Sample uncooked accesses (outside _Cooking, first 40):")
    shown = 0
    for p in hits:
        if "_Cooking" not in p:
            print(f"  {p}")
            shown += 1
            if shown >= 40:
                break


if __name__ == "__main__":
    main()
