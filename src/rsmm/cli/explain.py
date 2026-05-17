"""
rsmm explain <id> — show the patch plan a mod would emit.

Prints the manifest metadata + expanded list of [[patch]] blocks and
raw `assets/` files. Useful for verifying composite recipes and for
understanding conflict surface before `rsmm apply`.
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

from rsmm.engine.paths import MODS_DIR
from rsmm.cli.merge import _toml_load


def explain_one(entry: Path) -> int:
    mf = entry / "manifest.toml"
    if not mf.exists():
        print(f"no manifest: {entry}", file=sys.stderr)
        return 1
    t = _toml_load(mf)
    m = t.get("mod", {})
    print(f"# {entry.name}")
    for k in ("id", "name", "version", "author", "enabled",
              "load_order", "multiplayer_scope",
              "requires", "conflicts", "replaces"):
        if k in m:
            print(f"  {k:20s} {m[k]}")

    patches = t.get("patch", []) or []
    print(f"\n  [{len(patches)} patch block(s)]")
    for i, p in enumerate(patches, 1):
        kind = p.get("kind", "?")
        kv = "  ".join(f"{k}={v}" for k, v in p.items() if k != "kind")
        print(f"    {i:3d}. {kind:10s} {kv}")

    assets = entry / "assets"
    if assets.is_dir():
        raw = list(assets.rglob("*"))
        raw = [f for f in raw if f.is_file()]
        print(f"\n  [{len(raw)} raw asset file(s)]")
        for f in raw:
            rel = f.relative_to(assets).as_posix()
            size = f.stat().st_size
            print(f"    {size:>10d}  {rel}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Show a mod's full patch plan")
    ap.add_argument("mod_id")
    args = ap.parse_args()
    p = MODS_DIR / args.mod_id
    if not p.is_dir():
        print(f"no such mod: {args.mod_id}", file=sys.stderr)
        return 1
    return explain_one(p)


if __name__ == "__main__":
    sys.exit(main())
