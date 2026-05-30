"""Assemble one Blender-loadable GLB per hero from already-uncooked outputs.

`rsmm uncook` emits each cooked file in isolation: the mesh GLB
(`<Hero>_GEO.fbx.glb`) carries geometry + a flat grey `rsmm_default`
material, the albedo lives beside it as `Textures/T_<Hero>_ALB.png`, and
every animation clip is its own GLB under `Animations/` holding the bone
hierarchy (nodes) + keyframe channels but no mesh.

This module stitches them back together with a *surgical* glTF merge: the
existing chunks are reused verbatim and only the cross-references are
re-based, so no accessor is ever re-decoded. Two transforms:

- `embed_base_color` — point every material's `baseColorTexture` at the
  ALB png so the mesh stops rendering grey.
- `merge_animations` — append each animation clip's nodes / accessors /
  bufferViews / animations into the base document, re-basing all indices,
  and parent the clip's root nodes into the scene so the skeleton shows up.

Skin *deform* (per-vertex JOINTS_0/WEIGHTS_0) is intentionally NOT produced
here: those weights live in the cooked `.Geometry` side-channels which the
geometry decoder currently drops, so the unified GLB ships an un-skinned
mesh plus an animated skeleton a modder can weight-paint in Blender.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942


# --- GLB container read / write -----------------------------------------

def read_glb(data: bytes) -> tuple[dict, bytes]:
    """Split a .glb blob into (json_document, bin_chunk)."""
    magic, version, _total = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC:
        raise ValueError("not a glb (bad magic)")
    if version != 2:
        raise ValueError(f"unsupported glb version {version}")
    off = 12
    gltf: dict | None = None
    binary = b""
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        body = data[off:off + clen]
        off += clen
        if ctype == _CHUNK_JSON:
            gltf = json.loads(body)
        elif ctype == _CHUNK_BIN:
            binary = body
    if gltf is None:
        raise ValueError("glb has no JSON chunk")
    return gltf, binary


def write_glb(gltf: dict, binary: bytes,
              generator: str = "rsmm unify") -> bytes:
    gltf = dict(gltf)
    gltf.setdefault("asset", {})
    gltf["asset"] = {**gltf["asset"], "version": "2.0", "generator": generator}

    bin_pad = (-len(binary)) % 4
    bin_payload = binary + b"\0" * bin_pad

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (-len(json_bytes)) % 4
    json_bytes += b" " * json_pad

    total = 12 + 8 + len(json_bytes) + (8 + len(bin_payload) if bin_payload else 0)
    out = bytearray()
    out += struct.pack("<III", _GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(json_bytes), _CHUNK_JSON)
    out += json_bytes
    if bin_payload:
        out += struct.pack("<II", len(bin_payload), _CHUNK_BIN)
        out += bin_payload
    return bytes(out)


# --- Base-colour texture embedding --------------------------------------

def embed_base_color(gltf: dict, binary: bytearray, png_bytes: bytes) -> bytes:
    """Embed `png_bytes` as the baseColorTexture of every material.

    Mutates `gltf` in place; returns the (possibly grown) binary buffer.
    The png is appended to the bin chunk with a fresh bufferView so the
    single-buffer layout is preserved.
    """
    binary = bytearray(binary)
    pad = (-len(binary)) % 4
    binary += b"\0" * pad
    offset = len(binary)
    binary += png_bytes

    views = gltf.setdefault("bufferViews", [])
    view_idx = len(views)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(png_bytes)})

    images = gltf.setdefault("images", [])
    image_idx = len(images)
    images.append({"bufferView": view_idx, "mimeType": "image/png"})

    samplers = gltf.setdefault("samplers", [])
    sampler_idx = len(samplers)
    samplers.append({"magFilter": 9729, "minFilter": 9729,
                     "wrapS": 10497, "wrapT": 10497})

    textures = gltf.setdefault("textures", [])
    texture_idx = len(textures)
    textures.append({"sampler": sampler_idx, "source": image_idx})

    materials = gltf.setdefault("materials", [])
    if not materials:
        materials.append({"name": "rsmm_unified", "doubleSided": True})
    for mat in materials:
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        pbr["baseColorTexture"] = {"index": texture_idx, "texCoord": 0}
        # The albedo already carries the colour; neutralise any grey factor.
        pbr["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]

    return bytes(binary)


# --- Animation merge -----------------------------------------------------

def _remap_node(node: dict, n_off: int, m_off: int, s_off: int) -> dict:
    out = dict(node)
    if "children" in out:
        out["children"] = [c + n_off for c in out["children"]]
    if "mesh" in out:
        out["mesh"] = out["mesh"] + m_off
    if "skin" in out:
        out["skin"] = out["skin"] + s_off
    return out


def _rig_signature(clip: dict) -> list[tuple]:
    """(name, children-tuple) per node — identity of a clip's bone tree."""
    return [(n.get("name", ""), tuple(n.get("children", [])))
            for n in clip.get("nodes", [])]


def merge_animations(base: dict, base_bin: bytes,
                     clips: list[tuple[str, dict, bytes]]) -> tuple[dict, bytes]:
    """Fold each `(name, gltf, bin)` clip into `base`.

    Ravenswatch ships every clip for a hero on the *same* bone hierarchy,
    so the skeleton is imported once (from the first clip) and every later
    clip whose rig matches is retargeted onto those shared node indices —
    Blender then sees one armature with N actions instead of N overlapping
    armatures. A clip with a divergent rig falls back to getting its own
    skeleton appended.

    Cross-references (bufferView->buffer, accessor->bufferView,
    node->{children,mesh,skin}, skin->{joints,ibm,skeleton}, animation
    channel->node, sampler->accessor) are re-based onto the growing base.
    """
    base = json.loads(json.dumps(base))  # deep copy, don't clobber caller
    binary = bytearray(base_bin)

    b_views = base.setdefault("bufferViews", [])
    b_acc = base.setdefault("accessors", [])
    b_nodes = base.setdefault("nodes", [])
    b_meshes = base.setdefault("meshes", [])
    b_skins = base.setdefault("skins", [])
    b_anims = base.setdefault("animations", [])
    scenes = base.setdefault("scenes", [{"nodes": list(range(len(b_nodes)))}])
    scene0 = scenes[base.get("scene", 0)]
    scene0.setdefault("nodes", [])

    # signature(tuple) -> node index base of an already-imported skeleton.
    # A hero may ship several distinct rigs (alternate forms); each is
    # imported once and every matching clip retargets onto it.
    rigs: dict[tuple, int] = {}

    for name, clip, clip_bin in clips:
        v_off = len(b_views)
        a_off = len(b_acc)
        m_off = len(b_meshes)
        s_off = len(b_skins)

        # Append clip bin, 4-byte aligned; record where it landed.
        pad = (-len(binary)) % 4
        binary += b"\0" * pad
        bin_base = len(binary)
        binary += clip_bin

        for v in clip.get("bufferViews", []):
            nv = dict(v)
            nv["buffer"] = 0
            nv["byteOffset"] = nv.get("byteOffset", 0) + bin_base
            b_views.append(nv)

        for a in clip.get("accessors", []):
            na = dict(a)
            if "bufferView" in na:
                na["bufferView"] = na["bufferView"] + v_off
            b_acc.append(na)

        sig = tuple(_rig_signature(clip))
        if sig in rigs:
            # Reuse the already-imported skeleton: channels target it directly.
            n_off = rigs[sig]
        else:
            # New rig — append its nodes once and remember where it landed.
            n_off = len(b_nodes)
            clip_nodes = clip.get("nodes", [])
            roots = set(range(len(clip_nodes)))
            for node in clip_nodes:
                for c in node.get("children", []):
                    roots.discard(c)
                b_nodes.append(_remap_node(node, n_off, m_off, s_off))
            for mesh in clip.get("meshes", []):
                b_meshes.append(mesh)
            for skin in clip.get("skins", []):
                ns = dict(skin)
                ns["joints"] = [j + n_off for j in ns.get("joints", [])]
                if "inverseBindMatrices" in ns:
                    ns["inverseBindMatrices"] = ns["inverseBindMatrices"] + a_off
                if "skeleton" in ns:
                    ns["skeleton"] = ns["skeleton"] + n_off
                b_skins.append(ns)
            for r in sorted(roots):
                scene0["nodes"].append(r + n_off)
            rigs[sig] = n_off

        for anim in clip.get("animations", []):
            samplers = []
            for s in anim.get("samplers", []):
                ns = dict(s)
                ns["input"] = ns["input"] + a_off
                ns["output"] = ns["output"] + a_off
                samplers.append(ns)
            channels = []
            for c in anim.get("channels", []):
                nc = dict(c)
                tgt = dict(nc["target"])
                if "node" in tgt:
                    tgt["node"] = tgt["node"] + n_off
                nc["target"] = tgt
                channels.append(nc)
            b_anims.append({
                "name": anim.get("name", name),
                "samplers": samplers,
                "channels": channels,
            })

    base["buffers"] = [{"byteLength": len(binary) + ((-len(binary)) % 4)}]
    return base, bytes(binary)


# --- Hero orchestration --------------------------------------------------

def _find_albedo(hero_dir: Path) -> Path | None:
    tex = hero_dir / "Textures"
    if not tex.is_dir():
        return None
    # Prefer full-res ALB over *_LowRes; root textures over skin-variant subdirs.
    albs = sorted(tex.glob("*ALB*.png")) or sorted(tex.rglob("*ALB*.png"))
    albs.sort(key=lambda p: ("LowRes" in p.name, len(p.parts), len(p.name)))
    return albs[0] if albs else None


def _pick_base_mesh(hero_dir: Path) -> Path:
    """Choose the main-body mesh GLB among a hero's variant GEOs.

    Heroes ship several `*_GEO.fbx.glb` (alt forms, props, weapons). Prefer
    `<Hero>_GEO.fbx.glb`; else the shortest hero-prefixed name (props and
    skins have longer suffixes); else the shortest GEO overall.
    """
    geos = sorted(hero_dir.glob("*_GEO.fbx.glb"))
    if not geos:
        raise FileNotFoundError(f"no *_GEO.fbx.glb in {hero_dir}")
    name = hero_dir.name
    exact = hero_dir / f"{name}_GEO.fbx.glb"
    if exact in geos:
        return exact
    prefixed = [g for g in geos if g.name.startswith(name)]
    pool = prefixed or geos
    return min(pool, key=lambda g: len(g.name))


def _animation_clips(hero_dir: Path) -> list[Path]:
    """All animation GLBs, under `Animations/` or `Animation/` (recursive)."""
    for sub in ("Animations", "Animation"):
        d = hero_dir / sub
        if d.is_dir():
            return sorted(d.rglob("*.glb"))
    return []


def unify_hero(hero_dir: Path, out: Path | None = None,
               include_animations: bool = True) -> Path:
    """Build `<Hero>_unified.glb`: base mesh + albedo + merged animations."""
    hero_dir = Path(hero_dir)
    base_path = _pick_base_mesh(hero_dir)
    gltf, binary = read_glb(base_path.read_bytes())

    alb = _find_albedo(hero_dir)
    if alb is not None:
        binary = bytearray(embed_base_color(gltf, bytearray(binary),
                                            alb.read_bytes()))

    if include_animations:
        clips: list[tuple[str, dict, bytes]] = []
        for clip_path in _animation_clips(hero_dir):
            cj, cb = read_glb(clip_path.read_bytes())
            clips.append((clip_path.stem, cj, cb))
        if clips:
            gltf, binary = merge_animations(gltf, bytes(binary), clips)

    if out is None:
        out = hero_dir / f"{base_path.name.split('_GEO')[0]}_unified.glb"
    out = Path(out)
    out.write_bytes(write_glb(gltf, bytes(binary)))
    return out
