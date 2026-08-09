#!/usr/bin/env python3
"""
Inject semantic-named pattern entries for every data/symbols.json function
symbol into data/function_patterns.json, then restamp the meta file.

Why: the pattern DB is republished between app releases (rolling
``pattern-db`` GitHub release, consumed by ``rsmm update-data``), while the
loader DLL bakes pattern *names* at build time (``Sym::X_Pattern``). Names
derived from addresses (``FUN_<addr>``) change on every game patch, which
would strand every shipped DLL. So the DB carries stable SEMANTIC entries
(``NamedEvent_Dispatch``, ``Foo.parent`` for anchor parents) that this
script regenerates from the current exe after each corpus regen — plus
optional legacy ``FUN_<oldaddr>`` aliases so DLLs shipped before the
semantic switch (<= 0.4.6) keep resolving.

Run AFTER scripts/gen_function_patterns.py (which rewrites the DB wholesale)
and after data/symbols.json raw refs have been updated for the new build:

  python scripts/gen_function_patterns.py
  python scripts/sync_symbol_patterns.py [--legacy-map remap.json]
  scripts/publish_pattern_db.sh
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_function_patterns as gen  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data/function_patterns.json"
META_PATH = REPO / "data/function_patterns.meta.json"
PROLOGUE_TRY = (32, 48, 64, 96, 128)


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


def build_entry(name: str, addr: int, text: bytes, text_va: int) -> dict | None:
    """Pattern entry for the function at *addr*, grown until unique (or
    ranked by match_index when duplicates persist)."""
    off = addr - text_va
    if not (0 <= off < len(text)):
        return None
    for plen in PROLOGUE_TRY:
        prologue = text[off:off + plen + 16]
        pat, used = gen.make_pattern(prologue, addr, plen)
        if pat is None:
            continue
        hits = [m.start() for m in pattern_to_regex(pat).finditer(text)]
        if off not in hits:
            continue
        if len(hits) == 1:
            return {"name": name, "addr": f"0x{addr:x}", "size": 0,
                    "pattern": pat, "used_bytes": used, "match_index": 0}
        if plen == PROLOGUE_TRY[-1]:
            return {"name": name, "addr": f"0x{addr:x}", "size": 0,
                    "pattern": pat, "used_bytes": used,
                    "match_index": hits.index(off)}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=gen.DEFAULT_EXE)
    ap.add_argument("--legacy-map", type=Path,
                    help="remap_symbols.py output; adds FUN_<oldaddr> aliases "
                         "so pre-semantic (<=0.4.6) loader DLLs keep resolving")
    args = ap.parse_args()

    # Import here so `--help` works without the package installed.
    from rsmm.engine.symbols import load_symbol_map

    data = Path(args.exe).read_bytes()
    img_base, sections = gen.parse_pe(data)
    text_sec = sections[0]
    text = data[text_sec["raw_off"]:text_sec["raw_off"] + text_sec["raw_size"]]
    text_va = img_base + text_sec["rva"]

    smap = load_symbol_map()
    wanted: dict[str, int] = {}  # entry name -> function addr (current build)
    stale: set[str] = set()      # semantic entries that must NOT survive
    for s in smap.symbols:
        pn = s.pattern_name
        if pn is None:
            continue
        # Skip symbols not re-confirmed against the current build — their
        # raw/anchor still points at a pre-patch address, so a pattern built
        # there is meaningless. status=ok means the address is current.
        if s.status != "ok":
            # ...and REMOVE any entry a previous run left behind. Skipping the
            # write is not enough: demoting a symbol used to leave its old
            # pattern in the DB, so the loader kept resolving it and hooking
            # whatever the stale bytes matched. Downgrading status was purely
            # cosmetic — this is what makes it fail CLOSED.
            stale.add(pn)
            continue
        parent_raw = s.raw or s.anchor["raw"]
        wanted[pn] = int(parent_raw.split("_", 1)[1], 16)

    if args.legacy_map:
        legacy = json.loads(args.legacy_map.read_text())
        for old_addr, info in legacy.items():
            wanted[f"FUN_{old_addr[2:]}"] = int(info["new_addr"], 16)

    db = json.loads(DB_PATH.read_text())
    by_name = {e["name"]: i for i, e in enumerate(db)}

    added = updated = failed = 0
    for name, addr in sorted(wanted.items()):
        entry = build_entry(name, addr, text, text_va)
        if entry is None:
            print(f"  FAILED to build pattern: {name} @ 0x{addr:x}", file=sys.stderr)
            failed += 1
            continue
        if name in by_name:
            db[by_name[name]] = entry
            updated += 1
        else:
            by_name[name] = len(db)
            db.append(entry)
            added += 1

    # Prune before writing. `wanted` wins on a name in both (a symbol can be
    # re-promoted in the same run that another is demoted).
    pruned = 0
    doomed = stale - set(wanted)
    if doomed:
        db = [e for e in db if e["name"] not in doomed]
        pruned = len(doomed)

    DB_PATH.write_text(json.dumps(db))
    print(f"symbol entries: {added} added, {updated} updated, {failed} failed, "
          f"{pruned} pruned (non-ok) (db now {len(db)} entries)", file=sys.stderr)

    meta = {
        "schema": 1,
        "generated": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "game_exe_sha256": hashlib.sha256(data).hexdigest(),
        "game_exe_size": len(data),
        "pattern_count": len(db),
        "patterns_sha256": hashlib.sha256(DB_PATH.read_bytes()).hexdigest(),
    }
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"restamped {META_PATH.name}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
