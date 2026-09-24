"""Export a character as ONE rigged glTF: armature + skinned mesh + animations.

What Blender / Maya need to author against a Ravenswatch character, and the
input the return paths already accept:

* the **skeleton** — ``oCSkeleton`` / ``oCBone`` embedded in the character's
  ``oCGeometry``. Each bone: name (twice), three row-major 4×4 matrices (row
  vectors, translation in elements 12-14 — the same memory layout as a glTF
  column-major matrix) = inverse bind, world bind, local bind; then the parent
  index (``-1`` = root) and a flag byte. Verified: ``local × parentWorld ==
  world`` for every bone of Piper (100) and Beowulf (113);
* the **skinned mesh** — submeshes from the geometry's meshbuffers, weights
  from its ``oCSkinning8VertexLayer`` re-indexed through each meshbuffer's
  bone-name palette (:func:`geometry_cook._gather_source`);
* **animations** — every clip given, as glTF animations on the joints. Clip
  keys are local transforms in the same space as the local bind (all 100 of
  Piper's clip bones exist in her skeleton).

Coming back: a mesh edited in Blender cooks with ``kind="mesh"`` +
``transform.skin="gltf"`` (weights bound by bone NAME), and a clip cooks with
``kind="animation"`` (keys matched by bone NAME, see :mod:`anim_cook`). The
joint names are the game's bone names, so neither needs remapping.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import PurePosixPath

from . import cooked
from . import geometry_cook as GC
from .cooked_schemas import animation as A
from .cooked_schemas import geometry as _geo

_MB = b"\x11\x11\xbb\xaa"


class CharacterExportError(ValueError):
    pass


# --------------------------------------------------------------------------
# skeleton
# --------------------------------------------------------------------------

def read_skeleton(cf: cooked.CookedFile) -> list[dict]:
    """``[{name, parent, inverse_bind, world_bind, local_bind}]`` in file order."""
    names = [c.name for c in cf.classes]
    if "oCBone" not in names:
        return []
    tag = _MB + struct.pack("<I", names.index("oCBone"))
    out: list[dict] = []
    for sec in cf.sections:
        p = sec.payload
        o = p.find(tag)
        while o >= 0:
            q = o + 8
            n = struct.unpack_from("<I", p, q)[0]
            name = p[q + 4:q + 4 + n].decode("utf-8")
            q += 4 + n
            q += 4 + struct.unpack_from("<I", p, q)[0]          # second name copy
            mats = [list(struct.unpack_from("<16f", p, q + 64 * i)) for i in range(3)]
            q += 192
            parent = struct.unpack_from("<i", p, q)[0]
            out.append({"name": name, "parent": parent, "inverse_bind": mats[0],
                        "world_bind": mats[1], "local_bind": mats[2]})
            o = p.find(tag, q)
    for b in out:
        if not -1 <= b["parent"] < len(out):
            raise CharacterExportError(f"bone {b['name']}: parent {b['parent']} out of range")
    return out


def decompose(m: list[float]):
    """Row-major, row-vector 4×4 -> glTF (translation, rotation xyzw, scale)."""
    t = [m[12], m[13], m[14]]
    s = [math.sqrt(m[r * 4] ** 2 + m[r * 4 + 1] ** 2 + m[r * 4 + 2] ** 2) or 1.0
         for r in range(3)]
    # Column-vector rotation matrix: R[i][j] = m[j*4 + i] / s[j].
    r = [[m[j * 4 + i] / s[j] for j in range(3)] for i in range(3)]
    tr = r[0][0] + r[1][1] + r[2][2]
    if tr > 0:
        k = math.sqrt(tr + 1.0) * 2
        q = [(r[2][1] - r[1][2]) / k, (r[0][2] - r[2][0]) / k, (r[1][0] - r[0][1]) / k, 0.25 * k]
    else:
        i = max(range(3), key=lambda a: r[a][a])
        j, h = (i + 1) % 3, (i + 2) % 3
        k = math.sqrt(1.0 + r[i][i] - r[j][j] - r[h][h]) * 2
        q = [0.0, 0.0, 0.0, 0.0]
        q[i], q[j], q[h] = 0.25 * k, (r[j][i] + r[i][j]) / k, (r[h][i] + r[i][h]) / k
        q[3] = (r[h][j] - r[j][h]) / k
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return t, [c / n for c in q], s


# --------------------------------------------------------------------------
# textures
# --------------------------------------------------------------------------

def submesh_albedo_refs(cf: cooked.CookedFile) -> list[str | None]:
    """The ``u_diffuse`` texture each submesh's material names, in submesh order.

    Every meshbuffer's material section carries ``u_diffuse`` followed by the
    texture reference (``Characters\\Heroes\\Piper\\Textures\\T_Piper_ALB.tga``).
    """
    from . import entity_strings as ES
    texts = [t for _sec, _off, t in ES.list_strings(cooked.emit(cf))]
    out: list[str | None] = []
    for i, t in enumerate(texts):
        if t == "u_diffuse":    # followed by the resource root ("3D") and the path
            out.append(next((x for x in texts[i + 1:i + 4]
                             if x.lower().endswith((".tga", ".png", ".dds"))), None))
    return out


def texture_png(ref: str | None, mode: str = "color") -> bytes | None:
    """PNG of the texture ``ref`` names, or None when unreadable/undecodable.

    ``mode="orm"`` converts the game's MRA map (R metal, G roughness, B AO) to
    glTF's occlusion/roughness/metallic order (R AO, G roughness, B metal) by
    swapping R and B. Normal maps (BC5, two channels) come back from the
    decoder with Z already reconstructed.
    """
    if not ref:
        return None
    from . import corpus, dds, image
    from .cooked_schemas import texture as T
    # Normal maps cook as `.Texture.nrm`; everything else as `.Texture.dxt`.
    base = "3D/" + ref.replace("\\", "/")
    raw = corpus.read(base + ".Texture.dxt") or corpus.read(base + ".Texture.nrm")
    if raw is None:
        return None
    try:
        tcf = cooked.parse(raw)
        schema = T._decode_payload(tcf.sections[-1].payload)
        w, h, rgba = image.decode_dds_to_rgba(dds.read(T.schema_to_dds(schema)))
    except (NotImplementedError, ValueError, struct.error):
        return None
    if mode == "orm":
        px = bytearray(rgba)
        px[0::4], px[2::4] = rgba[2::4], rgba[0::4]
        rgba = bytes(px)
    return image.encode_png(w, h, rgba)


def albedo_png(ref: str | None) -> bytes | None:
    return texture_png(ref, "color")


def material_slots(mat_ref: str | None) -> dict[str, str]:
    """``{"ALB"|"MRA"|"NRM": texture ref}`` from a ``.mat.ot`` (``u_ALB`` ...)."""
    if not mat_ref:
        return {}
    from . import corpus
    from . import entity_strings as ES
    raw = corpus.read("3D/" + mat_ref.replace("\\", "/") + ".Material.gen")
    if raw is None:
        return {}
    texts = [t for _sec, _off, t in ES.list_strings(raw)]
    out: dict[str, str] = {}
    for i, t in enumerate(texts):
        if t in ("u_ALB", "u_MRA", "u_NRM"):
            ref = next((x for x in texts[i + 1:i + 4]
                        if x.lower().endswith((".tga", ".png", ".dds"))), None)
            if ref and "Characters" in ref:
                out[t[2:]] = ref
    return out


# --------------------------------------------------------------------------
# glTF assembly
# --------------------------------------------------------------------------

class _Buf:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.views: list[dict] = []
        self.accs: list[dict] = []

    def add(self, fmt: str, flat: list, count: int, typ: str, ctype: int,
            target: int | None = None, minmax: bool = False) -> int:
        self.bin.extend(b"\0" * (-len(self.bin) % 4))
        data = struct.pack(f"<{len(flat)}{fmt}", *flat)
        view: dict = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            view["target"] = target
        self.bin.extend(data)
        self.views.append(view)
        acc: dict = {"bufferView": len(self.views) - 1, "componentType": ctype,
                     "count": count, "type": typ}
        if minmax:
            w = {"SCALAR": 1, "VEC3": 3}[typ]
            acc["min"] = [min(flat[i::w]) for i in range(w)]
            acc["max"] = [max(flat[i::w]) for i in range(w)]
        self.accs.append(acc)
        return len(self.accs) - 1


def export(geometry_cooked: bytes, clips: dict[str, bytes] | None = None, *,
           name: str = "character", clip_targets: dict[str, str] | None = None,
           textures: bool = True, materials: list[dict] | None = None,
           attachments: list[dict] | None = None,
           extra_skinned: list[dict] | None = None) -> bytes:
    """Build the rigged .glb.

    ``clips`` maps clip name -> cooked oCAnimation file bytes. ``materials``
    gives each body submesh its full slot set (``{"ALB", "MRA", "NRM"}`` texture
    refs, from :func:`material_slots`); without it each submesh wears the albedo
    its own geometry names. ``attachments`` are rigid meshes carried by a bone —
    ``[{"name", "bone", "geometry": cooked bytes, "slots": {...}}]`` — exported
    as a child of that bone's joint, the way the game parents a weapon.
    ``extra_skinned`` are more meshes bound to the same rig (a skin's cloak or
    hat): ``[{"name", "geometry": cooked bytes, "slots": [per-submesh slots]}]``.
    """
    cf = cooked.parse(geometry_cooked)
    bones = read_skeleton(cf)
    if not bones:
        raise CharacterExportError("geometry has no skeleton (not a skinned character mesh)")
    index = {b["name"]: i for i, b in enumerate(bones)}
    buf = _Buf()

    # Joints: one node per bone, local bind as TRS (animated nodes must be TRS).
    nodes: list[dict] = []
    for b in bones:
        t, q, s = decompose(b["local_bind"])
        nodes.append({"name": b["name"], "translation": t, "rotation": q, "scale": s})
    roots = []
    for i, b in enumerate(bones):
        if b["parent"] < 0:
            roots.append(i)
        else:
            nodes[b["parent"]].setdefault("children", []).append(i)
    ibm = buf.add("f", [v for b in bones for v in b["inverse_bind"]], len(bones), "MAT4", 5126)
    skin = {"name": f"{name}_skin", "joints": list(range(len(bones))),
            "inverseBindMatrices": ibm, "skeleton": roots[0]}

    prim_slots: list[dict] = []

    def skinned_prims(gcf, what):
        target = next((si for si, sec in enumerate(gcf.sections)
                       if GC._find_records(sec.payload)), None)
        if target is None:
            raise CharacterExportError(f"{what}: geometry has no meshbuffers")
        subs = _geo._parse_meshbuffers(gcf.sections[target].payload)
        src = GC._gather_source(gcf, target, subs)
        if not src or not src.get("palette") or "skinning#0" not in src["records"]:
            raise CharacterExportError(f"{what}: could not read the mesh's bone weights")
        palette = src["palette"]
        missing = sorted(set(palette) - set(index))
        if missing:
            raise CharacterExportError(
                f"{what}: weights name bones the skeleton lacks: {missing[:6]}")
        return _skinned(subs, src["records"]["skinning#0"], [index[n] for n in palette])

    def _skinned(subs, recs, joint_of):
        prims, off = [], 0
        for sm in subs:
            c = len(sm.positions)
            if not c:
                continue
            joints, weights = [], []
            for rec in recs[off:off + c]:
                idx, w = GC._decode_skin(rec)
                tot = sum(w) or 1.0
                joints.extend(joint_of[i] if wt > 0 else 0 for i, wt in zip(idx, w, strict=True))
                weights.extend(wt / tot for wt in w)
            off += c
            attrs = {"POSITION": buf.add("f", [v for p in sm.positions for v in p], c, "VEC3",
                                         5126, 34962, minmax=True),
                     "JOINTS_0": buf.add("H", joints, c, "VEC4", 5123, 34962),
                     "WEIGHTS_0": buf.add("f", weights, c, "VEC4", 5126, 34962)}
            if sm.normals:
                attrs["NORMAL"] = buf.add("f", [v for n in sm.normals for v in n], c, "VEC3",
                                          5126, 34962)
            if sm.uvs:
                attrs["TEXCOORD_0"] = buf.add("f", [v for u in sm.uvs for v in u], c, "VEC2",
                                              5126, 34962)
            # One material per submesh: Blender merges primitives that share a
            # material into one on export, which loses the submesh split that
            # `kind="mesh"` + `transform.submeshes="map"` needs to come back.
            prim = {"attributes": attrs, "mode": 4, "material": len(prim_slots) + len(prims)}
            if sm.indices:
                prim["indices"] = buf.add("I", list(sm.indices), len(sm.indices), "SCALAR",
                                          5125, 34963)
            prims.append(prim)
        return prims

    prims = skinned_prims(cf, name)
    nodes.append({"name": f"{name}_mesh", "mesh": 0, "skin": 0})
    mesh_node = len(nodes) - 1
    meshes = [{"name": f"{name}_mesh", "primitives": prims}]

    # Per-primitive slot sets, body first then each attachment's submeshes.
    refs = submesh_albedo_refs(cf) if textures else []
    for i in range(len(prims)):
        if materials and i < len(materials) and materials[i]:
            prim_slots.append(materials[i])
        else:
            prim_slots.append({"ALB": refs[i]} if i < len(refs) and refs[i] else {})

    # More meshes on the same rig (a skin's cloak, hat), sharing the skin.
    for extra in extra_skinned or []:
        ecf = cooked.parse(extra["geometry"])
        eprims = skinned_prims(ecf, extra.get("name", "extra"))
        erefs = submesh_albedo_refs(ecf) if textures else []
        slots = extra.get("slots") or []
        for k in range(len(eprims)):
            prim_slots.append(slots[k] if k < len(slots) and slots[k] else
                              ({"ALB": erefs[k]} if k < len(erefs) and erefs[k] else {}))
        meshes.append({"name": extra.get("name", "extra"), "primitives": eprims})
        nodes.append({"name": extra.get("name", "extra"), "mesh": len(meshes) - 1, "skin": 0})
        roots.append(len(nodes) - 1)

    # Rigid attachments (weapons, props) under their bone's joint.
    for att in attachments or []:
        bone = index.get(att.get("bone", ""))
        if bone is None:
            continue
        acf = cooked.parse(att["geometry"])
        at = next((si for si, sec in enumerate(acf.sections)
                   if GC._find_records(sec.payload)), None)
        if at is None:
            continue
        aprims = []
        arefs = submesh_albedo_refs(acf) if textures else []
        for k, sm in enumerate(_geo._parse_meshbuffers(acf.sections[at].payload)):
            c = len(sm.positions)
            if not c:
                continue
            attrs = {"POSITION": buf.add("f", [v for q in sm.positions for v in q], c, "VEC3",
                                         5126, 34962, minmax=True)}
            if sm.normals:
                attrs["NORMAL"] = buf.add("f", [v for n in sm.normals for v in n], c,
                                          "VEC3", 5126, 34962)
            if sm.uvs:
                attrs["TEXCOORD_0"] = buf.add("f", [v for u in sm.uvs for v in u], c,
                                              "VEC2", 5126, 34962)
            prim = {"attributes": attrs, "mode": 4, "material": len(prim_slots)}
            if sm.indices:
                prim["indices"] = buf.add("I", list(sm.indices), len(sm.indices), "SCALAR",
                                          5125, 34963)
            aprims.append(prim)
            prim_slots.append(att.get("slots") or
                              ({"ALB": arefs[k]} if k < len(arefs) and arefs[k] else {}))
        if aprims:
            meshes.append({"name": att.get("name", "attachment"), "primitives": aprims})
            nodes.append({"name": att.get("name", "attachment"), "mesh": len(meshes) - 1})
            nodes[bone].setdefault("children", []).append(len(nodes) - 1)

    # Animations on the joints.
    animations = []
    for clip_name, clip_bytes in sorted((clips or {}).items()):
        acf = cooked.parse(clip_bytes)
        an = A.parse_payload(b"".join(s.payload for s in acf.sections))
        samplers, channels = [], []
        for tr in an.tracks:
            node = index.get(tr.name)
            if node is None:
                continue
            for path, times, vals, dec, typ in (
                    ("translation", tr.t_times, tr.t_values, A._decode_trans_scale, "VEC3"),
                    ("rotation", tr.r_times, tr.r_values, A._decode_quat, "VEC4"),
                    ("scale", tr.s_times, tr.s_values, A._decode_trans_scale, "VEC3")):
                if not times:
                    continue
                secs = A._decode_times(times, tr.duration)
                decoded = [dec(v) for v in vals]
                if path == "rotation":
                    decoded = A.continuous_quats(decoded)
                inp = buf.add("f", secs, len(secs), "SCALAR", 5126, minmax=True)
                out = buf.add("f", [c for v in decoded for c in v], len(vals), typ, 5126)
                samplers.append({"input": inp, "output": out, "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1,
                                 "target": {"node": node, "path": path}})
        animations.append({"name": clip_name, "samplers": samplers, "channels": channels,
                           "extras": {"rsmm": {"duration": an.duration}}})

    # Materials: one per primitive (Blender keeps the split), full PBR set.
    gl_materials, images, gl_textures, tex_cache = [], [], [], {}

    def tex(ref, mode):
        if not textures or not ref:
            return None
        key = (ref, mode)
        if key not in tex_cache:
            png = texture_png(ref, mode)
            tex_cache[key] = None
            if png:
                buf.bin.extend(b"\0" * (-len(buf.bin) % 4))
                buf.views.append({"buffer": 0, "byteOffset": len(buf.bin),
                                  "byteLength": len(png)})
                buf.bin.extend(png)
                images.append({"name": ref.rsplit("\\", 1)[-1] + ("" if mode == "color"
                                                                   else f" ({mode})"),
                               "bufferView": len(buf.views) - 1, "mimeType": "image/png"})
                gl_textures.append({"source": len(images) - 1, "sampler": 0})
                tex_cache[key] = len(gl_textures) - 1
        return tex_cache[key]

    for i, slots in enumerate(prim_slots):
        pbr: dict = {"baseColorFactor": [0.8, 0.8, 0.8, 1.0], "metallicFactor": 0.0,
                     "roughnessFactor": 1.0}
        mat: dict = {"name": f"{name}_submesh_{i}", "doubleSided": True,
                     "pbrMetallicRoughness": pbr}
        alb = tex(slots.get("ALB"), "color")
        if alb is not None:
            pbr["baseColorTexture"] = {"index": alb}
            pbr["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
        orm = tex(slots.get("MRA"), "orm")
        if orm is not None:
            pbr["metallicRoughnessTexture"] = {"index": orm}
            pbr["metallicFactor"] = 1.0
            mat["occlusionTexture"] = {"index": orm}
        nrm = tex(slots.get("NRM"), "normal")
        if nrm is not None:
            mat["normalTexture"] = {"index": nrm}
        gl_materials.append(mat)

    doc = {
        "asset": {"version": "2.0", "generator": "rsmm character export"},
        "extras": {"rsmm": {"kind": "character", "clip_targets": clip_targets or {}}},
        "scene": 0, "scenes": [{"nodes": roots + [mesh_node]}],
        "nodes": nodes, "skins": [skin],
        "meshes": meshes,
        "materials": gl_materials,
        "buffers": [{"byteLength": 0}], "bufferViews": buf.views, "accessors": buf.accs,
    }
    if images:
        doc["images"], doc["textures"] = images, gl_textures
        doc["samplers"] = [{"wrapS": 10497, "wrapT": 10497,
                            "magFilter": 9729, "minFilter": 9987}]
    if animations:
        doc["animations"] = animations
    binb = bytes(buf.bin) + b"\0" * (-len(buf.bin) % 4)
    doc["buffers"][0]["byteLength"] = len(binb)
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(binb)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A)
            + js + struct.pack("<II", len(binb), 0x004E4942) + binb)


def clip_name(rel: str) -> str:
    """``3D/.../Piper_Dash_Default.fbx.Animation.gen`` -> ``Piper_Dash_Default``."""
    return PurePosixPath(rel).name.split(".fbx", 1)[0]


def clip_target(rel: str) -> str:
    """The ``kind="animation"`` target for a cooked clip path."""
    return rel.removeprefix("3D/").removesuffix(".Animation.gen").replace("/", "\\")
