"""rsmm unify — assemble one Blender-loadable GLB per hero.

After `rsmm uncook` has produced a hero's source tree (mesh GLB +
`Textures/*ALB*.png` + `Animations/*.glb`), this stitches them into a
single `<Hero>_unified.glb` carrying:

- the mesh with its albedo wired as the baseColorTexture (no more grey),
- the bone hierarchy imported once, and
- every animation clip retargeted onto that one skeleton (N actions).

Per-vertex skin weights are NOT recovered here (they live in the cooked
`.Geometry` side-channels the geometry decoder drops), so the mesh ships
un-skinned beside an animated skeleton a modder can weight-paint in
Blender. Re-cook of edits is out of scope for this command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.engine import unify


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm unify",
        description="Combine an uncooked hero's mesh, albedo and animations "
                    "into one GLB.",
    )
    ap.add_argument("hero_dir", type=Path,
                    help="uncooked hero directory (contains *_GEO.fbx.glb)")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output .glb (default: <hero_dir>/<Hero>_unified.glb)")
    ap.add_argument("--no-animations", action="store_true",
                    help="skip animation merge; emit mesh + albedo only")
    args = ap.parse_args()

    if not args.hero_dir.is_dir():
        print(f"not a directory: {args.hero_dir}", file=sys.stderr)
        return 1

    try:
        out = unify.unify_hero(
            args.hero_dir,
            out=args.output,
            include_animations=not args.no_animations,
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
