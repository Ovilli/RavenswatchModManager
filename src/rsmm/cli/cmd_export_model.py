"""`rsmm export-model` — any of the game's 3D models as a textured glTF.

    rsmm export-model Barrel_Cloth                  # -> Barrel_Cloth.glb in the cwd
    rsmm export-model "Wolf*" -o art/               # every match, into art/
    rsmm export-model --list DarkHills              # what there is (3001 models)
    rsmm export-model --all -o export/              # all of them, mirroring the game's tree
    rsmm export-model --all --filter "3D/Mechas/*" -o mechas/

`export-character` stays the tool for a hero: it assembles the body, weapons,
skins and every clip the game's entities say belong together. This one takes a
single geometry — a tree, a chest, an enemy, an NPC, a boss arena — and writes
it the same way: per-submesh PBR materials (albedo, MRA, normal) embedded as
PNGs, and for a rigged model its skeleton plus every clip in its folder that
fits it. Blender: set the scene to 60 fps before importing animated models (see
`export-character`).

A model's materials are found by its albedo: each submesh names the texture it
wears, and the `.mat` painting that texture is looked for in the model's own
folder, then its area (`3D/Scenery/DarkHills`), then anywhere.
"""

from __future__ import annotations

import argparse
import fnmatch
import functools
import sys
from pathlib import Path

_GEO = ".Geometry.gen"


def models(paths: list[str]) -> list[str]:
    """Every cooked geometry, as its decoded path."""
    return [p for p in paths if p.endswith(_GEO) and "/Animations/" not in p]


def stem(rel: str) -> str:
    """``3D/Scenery/DarkHills/Barrel_Cloth.fbx.Geometry.gen`` -> ``Barrel_Cloth``."""
    return rel.rsplit("/", 1)[-1].split(".fbx", 1)[0].split(".", 1)[0]


def match(pattern: str, geos: list[str]) -> list[str]:
    """Models whose name or path matches ``pattern`` (a glob, case-insensitive).
    An exact name wins over a glob hit, so ``Chest`` is the chest, not every
    ``*Chest*`` model."""
    pat = pattern.lower().replace("\\", "/")
    exact = [g for g in geos if stem(g).lower() == pat]
    if exact:
        return exact
    return [g for g in geos if fnmatch.fnmatch(stem(g).lower(), pat)
            or fnmatch.fnmatch(g.lower(), pat)]


def _area(rel: str) -> str:
    return "/".join(rel.split("/")[:3]) + "/"


@functools.cache
def _albedo_index(prefix: str, paths: tuple[str, ...]) -> dict[str, str]:
    """albedo ref (lower-case) -> the ``.mat`` under ``prefix`` that paints it,
    the shortest name winning (``M_Foo`` over ``M_Foo_LowRes``)."""
    from rsmm.engine import character_export as CE
    mats = sorted((p[3:].removesuffix(".Material.gen").replace("/", "\\") for p in paths
                   if p.startswith(prefix) and p.endswith(".Material.gen")), key=len)
    out: dict[str, str] = {}
    for mat in mats:
        alb = CE.material_slots(mat, scope=None).get("ALB")
        if alb:
            out.setdefault(alb.lower(), mat)
    return out


def materials(geo: bytes, rel: str, paths: tuple[str, ...]) -> list[dict]:
    """Full slot set for each submesh of ``geo``: its albedo's material, looked
    for near the model first; the bare albedo when no material is found."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked
    out = []
    folder = rel.rsplit("/", 1)[0] + "/"
    for ref in CE.submesh_albedo_refs(cooked.parse(geo)):
        mat = None
        if ref:
            for prefix in (folder, _area(rel), "3D/"):
                mat = _albedo_index(prefix, paths).get(ref.lower())
                if mat:
                    break
        out.append(CE.material_slots(mat, scope=None) if mat
                   else ({"ALB": ref} if ref else {}))
    return out


def _rig_folder(rel: str) -> str:
    """Where a rigged model's clips live: its character folder
    (``3D/Characters/Enemies/Wolf/``), else its own folder."""
    parts = rel.split("/")
    if len(parts) > 4 and parts[1] == "Characters":
        return "/".join(parts[:4]) + "/"
    return rel.rsplit("/", 1)[0] + "/"


def clips_for(rel: str, bones: set[str], paths: list[str], pattern: str):
    """``({clip name: bytes}, {clip name: target})`` — every clip in the
    model's folder whose tracks all name its bones (a pet's or a prop's clips
    sharing the folder are skipped)."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus
    from rsmm.engine.cooked_schemas import animation as A
    clips, targets = {}, {}
    folder = _rig_folder(rel)
    for p in paths:
        if not (p.startswith(folder) and p.endswith(".Animation.gen")):
            continue
        name = CE.clip_name(p)
        if not pattern or not fnmatch.fnmatch(name, pattern):
            continue
        raw = corpus.read(p)
        if raw is None:
            continue
        an = A.parse_payload(b"".join(s.payload for s in cooked.parse(raw).sections))
        if {t.name for t in an.tracks} <= bones:
            clips[name], targets[name] = raw, CE.clip_target(p)
    return clips, targets


def export_one(rel: str, paths: list[str], *, clip_glob: str = "*",
               textures: bool = True) -> tuple[bytes, str]:
    """``(glb bytes, one-line summary)`` for the model at decoded path ``rel``."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus
    geo = corpus.read(rel)
    if geo is None:
        raise CE.CharacterExportError("not readable (no game install or mirror)")
    bones = {b["name"] for b in CE.read_skeleton(cooked.parse(geo))}
    clips, targets = clips_for(rel, bones, paths, clip_glob) if bones else ({}, {})
    mats = materials(geo, rel, tuple(paths)) if textures else None
    glb = CE.export(geo, clips, name=stem(rel), clip_targets=targets,
                    textures=textures, materials=mats)
    rig = f"{len(bones)} bones, {len(clips)} clips" if bones else "static"
    return glb, f"{rig}, {len(glb) // 1024} KB"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm export-model",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("model", nargs="?",
                    help="model name or glob (Barrel_Cloth, 'Wolf*', '3D/Mechas/*')")
    ap.add_argument("-o", "--output", type=Path,
                    help="output .glb for one model, else a directory (default: cwd)")
    ap.add_argument("--list", nargs="?", const="", metavar="FILTER",
                    help="list models, optionally only those whose path contains FILTER")
    ap.add_argument("--all", action="store_true",
                    help="export every model into -o, mirroring the game's folders")
    ap.add_argument("--filter", default="*",
                    help="with --all: glob over the decoded path (default every model)")
    ap.add_argument("--clips", default="*",
                    help="glob over clip names for rigged models (default all; '' for none)")
    ap.add_argument("--no-textures", action="store_true",
                    help="geometry only: much faster, no embedded PNGs")
    args = ap.parse_args(argv)

    from rsmm.cli.cmd_export_character import _asset_paths
    from rsmm.engine import character_export as CE

    paths = _asset_paths()
    geos = models(paths)
    if args.list is not None:
        f = args.list.lower()
        for g in geos:
            if f in g.lower():
                print(g)
        return 0

    if args.all:
        targets = [g for g in geos if fnmatch.fnmatch(g.lower(), args.filter.lower())]
        out_dir = args.output or Path(".")
    elif args.model:
        targets = match(args.model, geos)
        if not targets:
            print(f"no model matches {args.model!r} (try --list)", file=sys.stderr)
            return 1
        out_dir = args.output if args.output and (len(targets) > 1 or args.output.is_dir()
                                                  or not args.output.suffix) else None
    else:
        ap.print_help()
        return 2

    failed = 0
    for i, rel in enumerate(targets, 1):
        if out_dir is None:                       # one model, to a file
            dest = args.output or Path(f"{stem(rel)}.glb")
        elif args.all:                            # mirror the game's tree
            dest = out_dir / (rel.removeprefix("3D/").split(".fbx", 1)[0] + ".glb")
        else:
            dest = out_dir / f"{stem(rel)}.glb"
        try:
            glb, summary = export_one(rel, paths, clip_glob=args.clips,
                                      textures=not args.no_textures)
        except (CE.CharacterExportError, ValueError, OSError) as e:
            failed += 1
            print(f"[{i}/{len(targets)}] {rel}: skipped — {e}", file=sys.stderr)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(glb)
        print(f"[{i}/{len(targets)}] {dest}: {summary}")
    if len(targets) > 1:
        print(f"{len(targets) - failed} exported, {failed} skipped")
    return 1 if failed == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
