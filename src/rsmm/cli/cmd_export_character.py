"""`rsmm export-character` — a hero as one rigged glTF for Blender / Maya.

    rsmm export-character Piper                   # -> Piper.glb in the cwd
    rsmm export-character Piper -o art/piper.glb --clips "Piper_Dash*"
    rsmm export-character --list

Writes the armature (the game's own bone names, hierarchy and bind pose), the
skinned mesh wearing its albedo textures, and every animation clip whose bones
belong to that skeleton, so it imports in Blender as a posable, animated,
textured character.

Blender: set the scene frame rate to 60 BEFORE importing (Scene > Output >
Frame Rate). Clips are keyed on a 30 fps grid with 60 fps keys where the
animator snapped something (Piper's dash flips her weapon in half a frame);
Blender places keys by scene frame rate, so 24 or 30 fps drops those. At 60,
all 45 Piper clips measured within 0.3 degrees after an import/export round
trip.

Coming back: an edited clip is a `kind = "animation"` block (`source` = the
exported .glb, `clip` = the action name, `target` = the clip's reference, which
this command prints per clip); an edited body is `kind = "mesh"` with
`transform = { skin = "gltf", submeshes = "map" }`.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

_HEROES = "3D/Characters/Heroes/"


def _asset_paths() -> list[str]:
    from rsmm.engine.paths import DATA_DIR
    m = json.loads((DATA_DIR / "asset_map.json").read_text(encoding="utf-8"))
    return sorted({v.replace("\\", "/") for v in m.values() if isinstance(v, str)})


def heroes(paths: list[str]) -> list[str]:
    return sorted({p[len(_HEROES):].split("/", 1)[0] for p in paths
                   if p.startswith(_HEROES) and p.endswith(".Geometry.gen")})


def pick_geometry(hero: str, paths: list[str], mesh: str | None):
    """The hero's main skinned mesh: the geometry with the largest skeleton."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus

    cands = [p for p in paths if p.startswith(f"{_HEROES}{hero}/")
             and p.endswith(".Geometry.gen") and "/Animations/" not in p]
    if mesh:
        cands = [p for p in cands if Path(p).name.split(".fbx")[0].lower() == mesh.lower()]
    best = None
    for p in cands:
        raw = corpus.read(p)
        if raw is None:
            continue
        n = len(CE.read_skeleton(cooked.parse(raw)))
        # Ties (a skin variant shares the rig) go to the plain `<Hero>_GEO` body.
        plain = Path(p).name.lower().startswith(f"{hero.lower()}_geo")
        if n and (best is None or (n, plain) > (best[1], best[3])):
            best = (p, n, raw, plain)
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm export-character",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("hero", nargs="?", help="hero folder, e.g. Piper, Beowulf, Wukong")
    ap.add_argument("-o", "--output", type=Path, help="output .glb (default <hero>.glb)")
    ap.add_argument("--mesh", help="geometry name to use instead of the largest rig")
    ap.add_argument("--clips", default="*",
                    help="glob over clip names (default all; '' for none)")
    ap.add_argument("--list", action="store_true", help="list exportable heroes")
    args = ap.parse_args(argv)

    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus
    from rsmm.engine.cooked_schemas import animation as A

    paths = _asset_paths()
    if args.list or not args.hero:
        print("\n".join(heroes(paths)))
        return 0 if args.list else 2
    found = pick_geometry(args.hero, paths, args.mesh)
    if found is None:
        print(f"no skinned geometry for {args.hero!r} (try --list, or the game install is "
              f"not reachable)", file=sys.stderr)
        return 1
    geo_rel, n_bones, geo, _ = found
    bones = {b["name"] for b in CE.read_skeleton(cooked.parse(geo))}

    clips: dict[str, bytes] = {}
    targets: dict[str, str] = {}
    skipped = 0
    for rel in paths:
        if not (rel.startswith(f"{_HEROES}{args.hero}/") and rel.endswith(".Animation.gen")):
            continue
        name = CE.clip_name(rel)
        if not args.clips or not fnmatch.fnmatch(name, args.clips):
            continue
        raw = corpus.read(rel)
        if raw is None:
            continue
        an = A.parse_payload(b"".join(s.payload for s in cooked.parse(raw).sections))
        if not {t.name for t in an.tracks} <= bones:
            skipped += 1                       # another rig (a pet, a prop)
            continue
        clips[name], targets[name] = raw, CE.clip_target(rel)

    glb = CE.export(geo, clips, name=args.hero, clip_targets=targets)
    out = args.output or Path(f"{args.hero}.glb")
    out.write_bytes(glb)
    print(f"{out}: {Path(geo_rel).name.split('.fbx')[0]} ({n_bones} bones), "
          f"{len(clips)} clips ({skipped} skipped: other rigs), {len(glb) // 1024} KB")
    for name in sorted(targets):
        print(f"  {name:48} target = {targets[name]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
