"""`rsmm import-character` — turn a character .glb edited in Blender into a mod.

    rsmm import-character piper_edit.glb --mod my-piper
    rsmm import-character piper_edit.glb --mod my-piper --skin Combat --force

The inverse of `rsmm export-character`. It writes `mods/<id>/` holding ONLY what
changed against the shipped assets:

* each animation whose motion now differs from the shipped clip of the same name
  (sampled poses, `--threshold` degrees, default 1; a Blender round trip of an
  untouched clip measures up to 0.5) becomes a `kind = "animation"` block;
* the body, when its vertices no longer match the shipped body, becomes a
  `kind = "mesh"` block with `skin = "gltf"` and `submeshes = "map"`.

The .glb is copied into the mod's `art/` folder, so the mod is self-contained.
`rsmm apply` cooks it.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Share of the shipped body's vertices (on a 2 mm grid) that must be missing from
# the edited file before the body counts as edited. A Blender round trip loses
# ~0.2% to grid-boundary rounding; a different body loses ~20%.
BODY_CHANGED = 0.02


def _vertex_keys(glb: bytes) -> set[tuple[int, int, int]]:
    from rsmm.engine import geometry_cook as GC
    subs, skins = GC._glb_parse(glb)
    return {tuple(round(c * 500) for c in p)
            for s, k in zip(subs, skins, strict=True) if k for p in s.positions}


def changed_clips(glb: bytes, paths: list[str], threshold: float) -> list[tuple[str, str, float]]:
    """(clip, target, degrees) for every animation in `glb` that moved off its shipped clip."""
    from rsmm.engine import anim_cook as AC
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus

    shipped = {CE.clip_name(p): p for p in paths
               if p.startswith("3D/Characters/") and p.endswith(".Animation.gen")}
    doc, _ = AC._read_glb(glb)
    out = []
    for anim in doc.get("animations") or []:
        name = anim.get("name")
        rel = shipped.get(name)
        if rel is None:
            print(f"  {name}: no shipped clip of that name, skipped")
            continue
        tpl = b"".join(s.payload for s in cooked.parse(corpus.read(rel)).sections)
        try:
            cooked_clip, _notes = AC.cook(glb, tpl, name=name)
        except AC.AnimCookError as e:
            print(f"  {name}: {e}", file=sys.stderr)
            continue
        rot, move = AC.pose_difference(tpl, cooked_clip)
        if rot > threshold or move > 0.005:
            out.append((name, CE.clip_target(rel), rot))
    return out


def body_changed(glb: bytes, body_ref: str) -> bool:
    from rsmm.engine import character_export as CE
    from rsmm.engine import corpus
    raw = corpus.read("3D/" + body_ref.replace("\\", "/") + ".Geometry.gen")
    if raw is None:
        return False
    ref = _vertex_keys(CE.export(raw, name="body"))
    return len(ref - _vertex_keys(glb)) > BODY_CHANGED * len(ref)


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm import-character",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("glb", type=Path, help="the edited character .glb")
    ap.add_argument("--mod", required=True, help="mod id to write (mods/<id>/)")
    ap.add_argument("--hero", help="hero whose body to compare (default: taken from the clips)")
    ap.add_argument("--skin", help="the skin the file was exported with (--skin of export)")
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="degrees of change that count as an edit (default 1)")
    ap.add_argument("--no-mesh", action="store_true", help="never include the body")
    ap.add_argument("--force", action="store_true", help="overwrite an existing mods/<id>/")
    args = ap.parse_args(argv)

    from rsmm.cli.cmd_export_character import _asset_paths, resolve_setup
    from rsmm.engine.paths import MODS_DIR

    glb = args.glb.read_bytes()
    paths = _asset_paths()
    clips = changed_clips(glb, paths, args.threshold)

    hero = args.hero
    if hero is None:
        heroes = {t.split("\\")[2] for _n, t, _r in clips if t.startswith("Characters\\Heroes\\")}
        hero = heroes.pop() if len(heroes) == 1 else None
    body = None
    if not args.no_mesh:
        if hero is None:
            print("  body: pass --hero to compare it (no changed clip names the hero)")
        else:
            ref = resolve_setup(hero, args.skin, paths).get("body")
            if ref and body_changed(glb, ref):
                body = ref

    if not clips and not body:
        print("nothing changed against the shipped assets; no mod written")
        return 0
    mod = Path(MODS_DIR) / args.mod
    if mod.exists() and not args.force:
        print(f"{mod} exists; pass --force to overwrite it", file=sys.stderr)
        return 1
    (mod / "art").mkdir(parents=True, exist_ok=True)
    art = f"art/{args.glb.name}"
    shutil.copyfile(args.glb, mod / art)

    lines = ["[mod]", f"id          = {_toml_str(args.mod)}",
             f"name        = {_toml_str(args.mod)}", 'version     = "0.1.0"',
             f"description = {_toml_str(f'Character edits imported from {args.glb.name}.')}",
             'author      = "you"', "enabled     = true", 'sdk_version = ">=3.0,<4"',
             'multiplayer_scope = "cosmetic"']
    for name, target, rot in clips:
        lines += ["", f"# moved up to {rot:.1f} degrees from the shipped clip",
                  "[[content]]", 'kind   = "animation"', f"id     = {_toml_str(name.lower())}",
                  f"target = {_toml_str(target)}", f"source = {_toml_str(art)}",
                  f"clip   = {_toml_str(name)}"]
    if body:
        lines += ["", "[[content]]", 'kind      = "mesh"', 'id        = "body"',
                  f"target    = {_toml_str(body)}", f"model     = {_toml_str(art)}",
                  'transform = { skin = "gltf", submeshes = "map" }']
    (mod / "manifest.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{mod}: {len(clips)} changed clip(s){' + the body' if body else ''}")
    for name, _t, rot in clips:
        print(f"  {name}: up to {rot:.1f} deg")
    print("next: rsmm restore --all && rsmm apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
