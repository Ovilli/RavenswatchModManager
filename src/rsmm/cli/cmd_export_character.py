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


def _entity_strings(rel: str) -> list[str]:
    from rsmm.engine import corpus
    from rsmm.engine import entity_strings as ES
    raw = corpus.read(rel)
    return [t for _s, _o, t in ES.list_strings(raw)] if raw else []


def _graphic_objects(rel: str) -> list[tuple[str, str | None, str]]:
    """``(object name, bone or None, mesh ref)`` for every 3D graphic object."""
    import struct as _st

    from rsmm.engine import cooked, corpus
    from rsmm.engine import entity_strings as ES
    raw = corpus.read(rel)
    if raw is None:
        return []
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    by_sec: dict[int, list[str]] = {}
    for sec, _o, t in ES.list_strings(raw):
        by_sec.setdefault(sec, []).append(t)
    out = []
    for i, sec in enumerate(cf.sections):
        if len(sec.payload) < 4:
            continue
        ci = _st.unpack_from("<I", sec.payload, 0)[0]
        if ci >= len(names) or names[ci] != "oCEntityCpnt3dGraphicObjectSettings":
            continue
        ss = by_sec.get(i, [])
        mesh = next((x for x in ss if x.lower().endswith(".fbx") and "Heroes" in x), None)
        label = next((x for x in ss if not x.startswith("[")), None)
        if mesh and label:
            out.append((label, next((x for x in ss if x.startswith("DEF.")), None), mesh))
    return out


def _material_values(strings: list[str]) -> dict[str, str]:
    """``{object name: .mat.ot ref}`` from ``[Value] ...\\<Obj> Material Value`` pairs."""
    out = {}
    for i, t in enumerate(strings):
        if t.startswith("[Value]") and t.endswith(" Material Value"):
            ref = next((x for x in strings[i + 1:i + 6] if x.endswith(".mat.ot")), None)
            if ref:
                out[t.rsplit("\\", 1)[-1][:-len(" Material Value")]] = ref
    return out


def _mesh_groups(strings: list[str], hero: str) -> list[tuple[str, list[str]]]:
    """Inline mesh overrides in a skin entity: ``(mesh ref, [its .mat.ot refs])``."""
    groups: list[tuple[str, list[str]]] = []
    for t in strings:
        if t.lower().endswith(".fbx") and f"Heroes\\{hero}\\" in t:
            groups.append((t, []))
        elif t.startswith("["):
            if groups and groups[-1][0]:
                groups.append(("", []))           # a label ends the run
        elif t.endswith(".mat.ot") and t.startswith("Characters") and groups and groups[-1][0]:
            groups[-1][1].append(t)
    seen, out = set(), []
    for g in groups:
        if g[0] and g[0] not in seen:
            seen.add(g[0])
            out.append(g)
    return out


def _is_skin(strings: list[str], hero: str, default_keys: set[str]) -> bool:
    """A skin restyles THIS character: it sets every material slot the default
    look sets, or swaps in a ``<Hero>_..._GEO`` body. A pet (``PiperRat_...``)
    or an FX entity is a different object and is neither."""
    if default_keys and set(_material_values(strings)) >= default_keys:
        return True
    return any(t.lower().endswith("_geo.fbx") and f"Heroes\\{hero}\\" in t
               and t.rsplit("\\", 1)[-1].lower().startswith(hero.lower() + "_")
               for t in strings)


def _vertex_count(geo: bytes) -> int:
    from rsmm.engine import cooked
    from rsmm.engine import geometry_cook as GC
    from rsmm.engine.cooked_schemas import geometry as _geo
    cf = cooked.parse(geo)
    t = next((i for i, sec in enumerate(cf.sections) if GC._find_records(sec.payload)), None)
    return sum(len(sm.positions) for sm in _geo._parse_meshbuffers(cf.sections[t].payload)) \
        if t is not None else 0


def resolve_setup(hero: str, skin: str | None, paths: list[str]) -> dict:
    """What the game's entities say the hero is made of, for the default look or a skin."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus

    ents = [p for p in paths if p.startswith("EntitySettings/Heroes/")
            and p.endswith(".entity.ot.EntitySettingsResource.gen")]
    default = next((p for p in ents if p.endswith("_Default.entity.ot.EntitySettingsResource.gen")
                    and any(f"Heroes\\{hero}\\" in t for t in _entity_strings(p))), None)
    if default is None:
        return {}
    folder = default.rsplit("/", 1)[0] + "/"
    stem = default[len(folder):].split("_Default.")[0]            # Hero_Piper
    base = [folder + f"{stem}{suf}.entity.ot.EntitySettingsResource.gen" for suf in ("", "_FX")]
    objs = [o for p in base for o in _graphic_objects(p)]
    mats = _material_values(_entity_strings(default))
    # Inline mesh -> material pairs (the gun, the flask); the default look wins.
    mesh_mats = {m: g for p in base + [default]
                 for m, g in _mesh_groups(_entity_strings(p), hero) if g}
    setup = {"body": next((m for n, b, m in objs if n == "Character Mesh"), None),
             "attachments": {n: {"bone": b, "mesh": m} for n, b, m in objs
                             if b and n != "Character Mesh"},
             "extra": [], "body_mats": None, "mesh_mats": mesh_mats, "skins": sorted(
                 p[len(folder) + len(stem) + 1:].split(".entity")[0] for p in ents
                 if p.startswith(folder + stem + "_") and "_Default." not in p
                 and "_FX." not in p and _is_skin(_entity_strings(p), hero, set(mats)))}
    if skin:
        skin_rel = next((p for p in ents if p.startswith(folder)
                         and p[len(folder):].lower().endswith(f"_{skin.lower()}.entity.ot"
                                                              ".entitysettingsresource.gen")),
                        None)
        if skin_rel is None:
            raise SystemExit(f"no skin {skin!r} for {hero}; have: {', '.join(setup['skins'])}")
        ss = _entity_strings(skin_rel)
        mats.update(_material_values(ss))
        skinned = []
        base_raw = corpus.read("3D/" + setup["body"].replace("\\", "/") + ".Geometry.gen") \
            if setup["body"] else None
        base_bones = {b["name"] for b in CE.read_skeleton(cooked.parse(base_raw))} \
            if base_raw else set()
        for mesh, gmats in _mesh_groups(ss, hero):
            raw = corpus.read("3D/" + mesh.replace("\\", "/") + ".Geometry.gen")
            if raw is None:
                continue
            skel = {b["name"] for b in CE.read_skeleton(cooked.parse(raw))}
            if skel:
                skinned.append((mesh, gmats, (len(skel & base_bones), _vertex_count(raw))))
            else:
                # A rigid override replaces the attachment it resembles (the flute).
                def key(ref: str) -> str:            # Piper_Flute(.fbx|_Combat_GEO) -> Flute
                    parts = ref.rsplit("\\", 1)[-1].removesuffix(".fbx").split("_")
                    return parts[1] if len(parts) > 1 else parts[0]
                for a in setup["attachments"].values():
                    if key(a["mesh"]) == key(mesh):
                        a["mesh"], a["mat"] = mesh, gmats[0] if gmats else None
        # The body is the skinned mesh on the default body's skeleton (not RED's wolf
        # form), the biggest one on it (Geppetto's beard comes first).
        body = max((m for m in skinned if "_GEO" in m[0]), key=lambda m: m[2], default=None)
        if body and setup["body"]:
            setup["body"], setup["body_mats"] = body[0], body[1]
        setup["extra"] = [{"mesh": m, "mats": g} for m, g, _n in skinned
                          if body is None or m != body[0]]
    setup["mats"] = mats
    return setup


def materials_by_albedo(hero: str, paths: list[str], named: list[str]) -> dict[str, str]:
    """albedo texture ref (lower-case) -> the hero's ``.mat`` that paints it.

    A geometry names only each submesh's albedo, and the entity's material keys
    are free text ("Chatacter Mesh Beowulf", "Character Mesh Acc"), so matching
    a submesh to its material goes through the albedo. Materials the entity
    names win, then the shortest name (``M_Beowulf`` over ``M_Beowulf_LowRes``).
    """
    from rsmm.engine import character_export as CE
    folder = f"{_HEROES}{hero}/"
    found = [p[3:].removesuffix(".Material.gen").replace("/", "\\") for p in paths
             if p.startswith(folder) and p.endswith(".Material.gen")]
    out: dict[str, str] = {}
    for mat in [m for m in named if m] + sorted(found, key=len):
        alb = CE.material_slots(mat).get("ALB")
        if alb:
            out.setdefault(alb.lower(), mat)
    return out


def _name_tokens(ref: str) -> set[str]:
    import re
    stem = ref.rsplit("\\", 1)[-1].split(".")[0]
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", stem)
    return {w.lower() for w in words} - {"m", "geo", "skin", "mat", "fbx"}


def material_by_name(mesh: str, candidates: list[str], hero: str) -> str | None:
    """The candidate ``.mat`` whose name, minus the hero's, is made only of words
    in ``mesh``'s name, the most such words winning (``Merlin_Staff_Crystal_GEO`` ->
    ``M_Merlin_Staff_Crystal``, RED's ``Wolf_WolfCult_Skin_GEO`` ->
    ``M_Red_Wolf_WolfCult``; not ``M_PiperCombatFlute`` for the Combat cloak).
    For a piece the skin names no material for; None when no candidate fits."""
    # ponytail: name matching, not the engine's own link; that link is an entity
    # key ("Weapon In Right Hand Mesh") the skin's inline mesh group never names.
    have, common = _name_tokens(mesh), _name_tokens(hero)
    fits = [(len(t), m) for m in candidates if (t := _name_tokens(m) - common) and t <= have]
    return max(fits, key=lambda f: (f[0], -len(f[1])))[1] if fits else None


def submesh_materials(geo: bytes, by_albedo: dict[str, str],
                      fallback: list[str]) -> list[str | None]:
    """The ``.mat`` for each submesh of ``geo``: its albedo's material, else the
    entity's pairing for that submesh (``fallback``, last one repeated)."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked
    from rsmm.engine import geometry_cook as GC
    from rsmm.engine.cooked_schemas import geometry as _geo
    cf = cooked.parse(geo)
    refs = CE.submesh_albedo_refs(cf)
    t = next((i for i, sec in enumerate(cf.sections) if GC._find_records(sec.payload)), None)
    n = max(len(refs), sum(1 for sm in _geo._parse_meshbuffers(cf.sections[t].payload)
                           if sm.positions) if t is not None else 1)
    out = []
    for i in range(n):
        ref = refs[i].lower() if i < len(refs) and refs[i] else ""
        out.append(by_albedo.get(ref) or (fallback[min(i, len(fallback) - 1)]
                                          if fallback else None))
    return out


def _list_values(hero: str) -> int:
    """Every labelled number in the hero's entity family, for `values = {...}`."""
    from rsmm.engine import corpus
    from rsmm.engine import hero_cook as H

    def norm(x: str) -> str:
        return x.replace("_", "").lower()
    folders = sorted({r.split("/")[2] for r in corpus.rels("EntitySettings/Heroes/Hero_")})
    folder = next((f for f in folders if norm(f) == "hero" + norm(hero)), None) \
        or next((f for f in folders if norm(hero) in norm(f)), None)
    if folder is None:
        print(f"no entity folder for {hero!r}", file=sys.stderr)
        return 1
    files = {r.rsplit("/", 1)[-1][:-len(H.ENTITY_SUFFIX)]: corpus.read(r)
             for r in corpus.rels(f"EntitySettings/Heroes/{folder}/", H.ENTITY_SUFFIX)
             if r.rsplit("/", 1)[-1].startswith(folder)}
    for label, where in sorted(H.list_values(files).items()):
        vals = sorted({v for _f, v, _i in where})
        kind = "int" if where[0][2] else "number"
        shown = ", ".join(f"{v:g}" for v in vals)
        print(f"{label:60} {kind:6} {shown:14} in {', '.join(sorted({f for f, _v, _i in where}))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm export-character",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("hero", nargs="?", help="hero folder, e.g. Piper, Beowulf, Wukong")
    ap.add_argument("-o", "--output", type=Path, help="output .glb (default <hero>.glb)")
    ap.add_argument("--mesh", help="geometry name to use instead of the largest rig")
    ap.add_argument("--clips", default="*",
                    help="glob over clip names (default all; '' for none)")
    ap.add_argument("--skin", help="export a skin's look (materials, body, weapon)")
    ap.add_argument("--list", action="store_true", help="list exportable heroes")
    ap.add_argument("--list-skins", action="store_true", help="list the hero's skins")
    ap.add_argument("--list-values", action="store_true",
                    help="list the numbers a custom hero based on this one can set "
                         "(hero kind `values`)")
    args = ap.parse_args(argv)

    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus
    from rsmm.engine import geometry_cook as GC
    from rsmm.engine.cooked_schemas import animation as A

    paths = _asset_paths()
    if args.list or not args.hero:
        print("\n".join(heroes(paths)))
        return 0 if args.list else 2
    if args.list_values:
        return _list_values(args.hero)
    setup = {} if args.mesh else resolve_setup(args.hero, args.skin, paths)
    if args.list_skins:
        print("\n".join(setup.get("skins") or []))
        return 0

    def geo_of(ref: str | None) -> bytes | None:
        return corpus.read("3D/" + ref.replace("\\", "/") + ".Geometry.gen") if ref else None

    geo = geo_of(setup.get("body"))
    if geo is not None and CE.read_skeleton(cooked.parse(geo)):
        geo_rel, n_bones = setup["body"], len(CE.read_skeleton(cooked.parse(geo)))
    else:
        if args.skin:
            print(f"could not resolve {args.hero} skin {args.skin!r}", file=sys.stderr)
            return 1
        found = pick_geometry(args.hero, paths, args.mesh)
        if found is None:
            print(f"no skinned geometry for {args.hero!r} (try --list, or the game install "
                  f"is not reachable)", file=sys.stderr)
            return 1
        geo_rel, n_bones, geo, _ = found
        setup = {}
    bones = {b["name"] for b in CE.read_skeleton(cooked.parse(geo))}

    # Materials: the skin's per-submesh list, else each submesh's by its albedo.
    mats = setup.get("mats") or {}
    by_alb = materials_by_albedo(args.hero, paths, list(mats.values()))
    mesh_mats = setup.get("mesh_mats") or {}
    body_mats = setup.get("body_mats") or submesh_materials(
        geo, by_alb, mesh_mats.get(geo_rel) or [m for m in [mats.get("Character Mesh")] if m])
    materials = [CE.material_slots(m) for m in body_mats] or None
    attachments = []
    for name, a in (setup.get("attachments") or {}).items():
        g = geo_of(a["mesh"])
        if g is None:
            continue
        named = mats.get(name) or mats.get(name.removesuffix(" Mesh"))
        amats = ([a["mat"]] if a.get("mat") else mesh_mats.get(a["mesh"])) \
            or submesh_materials(g, by_alb, [named] if named else [])
        attachments.append({"name": name, "bone": a["bone"], "geometry": g,
                            "slots": [CE.material_slots(m) for m in amats]})
    def piece_mats(e: dict, g: bytes) -> list[str | None]:
        # Never the body's own material: a piece wearing it names that albedo itself,
        # and the Combat cloak (an FX score shader) would otherwise get the body texture.
        pool = [m for m in list(mats.values()) + list(by_alb.values())
                if m not in body_mats and m != mats.get("Character Mesh")]
        by_name = material_by_name(e["mesh"], pool, args.hero)
        return e["mats"] or submesh_materials(g, by_alb, [by_name] if by_name else [])

    extra, own_rig = [], []
    for e in setup.get("extra") or []:
        g = geo_of(e["mesh"])
        if g is None:
            continue
        ecf = cooked.parse(g)
        t = next((i for i, sec in enumerate(ecf.sections) if GC._find_records(sec.payload)),
                 None)
        pal = GC._record_palettes(ecf.sections[t].payload) if t is not None else None
        label = e["mesh"].rsplit("\\", 1)[-1].removesuffix(".fbx")
        if pal is None or not {n for pl in pal for n in pl} <= bones:
            if CE.read_skeleton(ecf):       # e.g. a cloak on its own small skeleton
                        own_rig.append({"name": label, "geometry": g,
                                "slots": [CE.material_slots(m) for m in piece_mats(e, g)]})
            continue
        extra.append({"name": label, "geometry": g,
                      "slots": [CE.material_slots(m) for m in piece_mats(e, g)]})

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

    glb = CE.export(geo, clips, name=args.hero, clip_targets=targets, materials=materials,
                    attachments=attachments, extra_skinned=extra, own_rig=own_rig)
    out = args.output or Path(f"{args.hero}{'_' + args.skin if args.skin else ''}.glb")
    out.write_bytes(glb)
    print(f"{out}: {Path(geo_rel).name.split('.fbx')[0]} ({n_bones} bones), "
          f"{len(attachments)} attachment(s), {len(extra) + len(own_rig)} extra mesh(es), "
          f"{len(clips)} clips ({skipped} skipped: other rigs), {len(glb) // 1024} KB")
    for piece in own_rig:
        print(f"  {piece['name']}: its own skeleton, exported as a separate armature at "
              f"its origin (the game does not say where it hangs; place it in Blender)")
    for name in sorted(targets):
        print(f"  {name:48} target = {targets[name]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
