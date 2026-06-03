#!/usr/bin/env python3
"""`rsmm talents` — discover + edit hero talent ("Skill") values.

Talents are internally "Skills". Their effect magnitudes are f32s in the hero's
cooked entity files under
``EntitySettings/Heroes/Hero_<Hero>/*.entity.ot.EntitySettingsResource.gen``.
This surfaces every editable value so a mod can patch it (the patch is
length-preserving, shipped as a plain entity override). See
:mod:`rsmm.engine.talent_values`.

  rsmm talents                       # list heroes that have skill values
  rsmm talents Juliet                # every editable talent value for Juliet
  rsmm talents Juliet --grep range   # filter by label
  rsmm talents Juliet --spawner      # also show runtime Spawner slots (0.0)
  rsmm talents Juliet --file Hero_Juliet_Skill_Power_Cone_Damage
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.engine.paths import DATA_DIR
from rsmm.engine.talent_values import list_talent_values

_HEROES_DIR = DATA_DIR / "uncooked" / "EntitySettings" / "Heroes"
_GEN_GLOB = "*.entity.ot.EntitySettingsResource.gen"


def _hero_dirs() -> list[Path]:
    if not _HEROES_DIR.is_dir():
        return []
    return sorted(d for d in _HEROES_DIR.glob("Hero_*") if d.is_dir())


def _resolve_hero(name: str) -> Path | None:
    low = name.lower()
    for d in _hero_dirs():
        stem = d.name[len("Hero_"):]
        if stem.lower() == low or d.name.lower() == low:
            return d
    return None


def _cmd_list_heroes() -> int:
    print("heroes with discoverable talent values:")
    for d in _hero_dirs():
        stem = d.name[len("Hero_"):]
        n = 0
        for p in d.glob(_GEN_GLOB):
            n += len(list_talent_values(p.read_bytes()))
        if n:
            print(f"  {stem:<14} {n:>4} value(s)   (rsmm talents {stem})")
    return 0


def _cmd_hero(args) -> int:
    d = _resolve_hero(args.hero)
    if d is None:
        print(f"no such hero {args.hero!r} (try: rsmm talents)", file=sys.stderr)
        return 1
    grep = args.grep.lower() if args.grep else None
    any_rows = False
    for p in sorted(d.glob(_GEN_GLOB)):
        if args.file and args.file.lower() not in p.name.lower():
            continue
        vals = list_talent_values(p.read_bytes(), include_spawner=args.spawner)
        rows = [v for v in vals if grep is None or grep in v.label.lower()]
        if not rows:
            continue
        any_rows = True
        decoded = p.name.split(".entity.ot.", 1)[0]
        print(f"\n# {decoded}")
        print(f"  (decoded asset: EntitySettings\\Heroes\\{d.name}\\{p.name})")
        for v in rows:
            if v.is_spawner:
                tag = "  [spawner/runtime, no-op]"
            elif v.is_int:
                tag = "  [int]"
            else:
                tag = ""
            if v.is_overridden:
                tag += "  [shadowed/no-op]"
            shown = int(v.value) if v.is_int else v.value
            print(f"   {shown:>12}  {v.label}{tag}")
    if not any_rows:
        print(f"(no talent values matched for {args.hero})")
        return 0
    print(
        "\nedit: ship a copy of the entity .gen above as a mod asset override,\n"
        "patched via talent_values.set_talent_value(cooked, label, new, expect=old)\n"
        "(int32 or f32 per node kind, length-preserving; no re-cook)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm talents",
                                 description="discover + edit hero talent values")
    ap.add_argument("hero", nargs="?", help="hero name, e.g. Juliet")
    ap.add_argument("--grep", help="filter labels (substring, case-insensitive)")
    ap.add_argument("--file", help="only scan entity files matching this substring")
    ap.add_argument("--spawner", action="store_true",
                    help="also show runtime Spawner slots (always 0.0, no-op to edit)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if not args.hero:
        return _cmd_list_heroes()
    return _cmd_hero(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
