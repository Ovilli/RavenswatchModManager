"""Cook a custom mesh into a Ravenswatch oCGeometry by vertex/index swap.

Building a cooked mesh from scratch would mean reproducing the engine's
whole multi-section oCGeometry layout (skeleton, skinning vertex layers,
material refs, vertex quantization). Instead we take an *existing* cooked
mesh as a template and overwrite only its oCMeshBuffer vertex/index blobs
with the new geometry — every other byte (class table, skeleton, AABB,
markers, section framing) is preserved, so the result is a structurally
valid cooked file the engine recognises.

The default-buffer vertex stride is 48 bytes:
    position(12) + normal(12) + uv0(8) + tangent(12) + handedness(4)
Only position / normal / uv0 are authored; the trailing 16 bytes are
zero-filled (the corpus stores tangents there but the engine tolerates a
zero tangent for an un-tangent-space-lit mesh).

CAVEAT — skinned templates: the skinning vertex layers stay sized to the
*original* vertex count, so a swap into a skinned slot may render in bind
pose / without deformation until those layers are resized too. Good enough
to validate that a custom mesh loads; full skin re-bind is future work.
"""

from __future__ import annotations

import logging
import math
import struct

from .cooked_schemas import geometry as _geo
from .cooked_schemas.base import NotReversedError

_log = logging.getLogger(__name__)

#: swap_geometry refuses meshes above this vertex count — confirmed in-game
#: that a 243k-vert mesh crashes a 1.2k-vert weapon slot at load. 65535 is the
#: 16-bit-index boundary and a defensible ceiling; overridable per-cook via the
#: RSMM_GEO_VERTEX_CAP env var if a higher count is verified to load.
_VERTEX_HARD_CAP = 65535

# Bump whenever the cook output for the same inputs changes, so the apply-
# time cache (keyed by source + template) invalidates stale cooked files.
#   1 -> initial meshbuffer vertex/index swap
#   2 -> also resize per-vertex skin/binormal/tangent layers (anti-glitch)
#   3 -> align to template space + nearest-neighbour bone-weight transfer
#   4 -> proper-rotation align (no reflection) + transform normals
#   5 -> rigid Euler rotation (auto-upright or explicit rotate_deg), no shear
#   6 -> k-nearest inverse-distance weight blend (smooth, no torn fragments)
#   7 -> normal-aware blend bias (fixes face/hat front-back bleed)
#   8 -> bake glTF node TRS into positions (props placed by node transform)
#   9 -> fit rigid/non-skinned templates too (weapons were dumped raw, ~100x);
#        + explicit `scale` transform multiplier
#  10 -> bone-name palettes: transferred weights are re-indexed against a
#        merged palette written back into the record (they used to carry
#        another submesh's indices); AABB found at unaligned offsets;
#        centroid centring for skinned templates; `submeshes="map"`;
#        `skin="gltf"` + `bones` / `drop_bones`
ENCODER_VERSION = 10

_VERTEX_STRIDE = 48
_TRIMESH_VER = struct.pack("<I", 7)

_COMPONENT_VEC = {"VEC3": (3, "<3f"), "VEC2": (2, "<2f")}


# --- glTF accessor decode (only what a mesh primitive needs) ------------

def _accessor_floats(gltf: dict, binary: bytes, idx: int, kind: str
                     ) -> list[tuple]:
    acc = gltf["accessors"][idx]
    assert acc["type"] == kind, f"accessor {idx} is {acc['type']}, want {kind}"
    n_comp, fmt = _COMPONENT_VEC[kind]
    view = gltf["bufferViews"][acc["bufferView"]]
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or (n_comp * 4)
    out = []
    for k in range(acc["count"]):
        out.append(struct.unpack_from(fmt, binary, base + k * stride))
    return out


def _accessor_indices(gltf: dict, binary: bytes, idx: int) -> list[int]:
    acc = gltf["accessors"][idx]
    view = gltf["bufferViews"][acc["bufferView"]]
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    ct = acc["componentType"]
    fmt, size = {5121: ("<B", 1), 5123: ("<H", 2), 5125: ("<I", 4)}[ct]
    stride = view.get("byteStride") or size
    return [struct.unpack_from(fmt, binary, base + k * stride)[0]
            for k in range(acc["count"])]


def _mat_identity() -> list[float]:
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _mat_mul(a: list[float], b: list[float]) -> list[float]:
    """Column-major 4x4 multiply (glTF convention): result = a * b."""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return out


def _node_local_matrix(node: dict) -> list[float]:
    """A node's local transform: explicit `matrix`, else T * R * S."""
    if "matrix" in node:
        return [float(x) for x in node["matrix"]]
    t = node.get("translation", [0.0, 0.0, 0.0])
    r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])  # quaternion x,y,z,w
    s = node.get("scale", [1.0, 1.0, 1.0])
    x, y, z, w = (float(v) for v in r)
    # Rotation matrix from quaternion (column-major).
    rot = [
        1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
        2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
        2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
        0, 0, 0, 1,
    ]
    sm = [s[0], 0, 0, 0, 0, s[1], 0, 0, 0, 0, s[2], 0, 0, 0, 0, 1]
    rs = _mat_mul(rot, sm)
    rs[12], rs[13], rs[14] = float(t[0]), float(t[1]), float(t[2])
    return rs


def _mat_apply_point(m: list[float], p) -> tuple[float, float, float]:
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def _mat_apply_normal(m: list[float], n) -> tuple[float, float, float]:
    # Rotate by the upper-left 3x3, then renormalize. Exact for rotation +
    # uniform scale; the small per-axis scale diff a modeller leaves on a prop is
    # absorbed by the renormalize, and the downstream fit recomputes normals.
    x, y, z = n
    rx = m[0] * x + m[4] * y + m[8] * z
    ry = m[1] * x + m[5] * y + m[9] * z
    rz = m[2] * x + m[6] * y + m[10] * z
    length = (rx * rx + ry * ry + rz * rz) ** 0.5 or 1.0
    return (rx / length, ry / length, rz / length)


def _accessor_vec4(gltf: dict, binary: bytes, idx: int) -> list[tuple]:
    """A VEC4 accessor as four numbers per element.

    Covers both shapes a skinned glTF uses: `JOINTS_0` is an unsigned integer
    VEC4 (u8 or u16), `WEIGHTS_0` a float VEC4 or a normalized integer one.
    Normalized integers are scaled to 0..1 here so the caller sees weights
    regardless of how the exporter packed them.
    """
    acc = gltf["accessors"][idx]
    assert acc["type"] == "VEC4", f"accessor {idx} is {acc['type']}, want VEC4"
    ct = acc["componentType"]
    fmt, size, denom = {
        5121: ("<4B", 4, 255.0),
        5123: ("<4H", 8, 65535.0),
        5125: ("<4I", 16, 4294967295.0),
        5126: ("<4f", 16, None),
    }[ct]
    view = gltf["bufferViews"][acc["bufferView"]]
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or size
    out = []
    for k in range(acc["count"]):
        v = struct.unpack_from(fmt, binary, base + k * stride)
        if denom is not None and acc.get("normalized"):
            v = tuple(c / denom for c in v)
        out.append(v)
    return out


#: Per-vertex bone influences taken from a glTF skin: `(bone name, weight)`
#: pairs, already filtered to non-zero weights.
Influences = list[list[tuple[str, float]]]


def glb_to_submeshes(glb_bytes: bytes) -> list[_geo.SubMesh]:
    """Decode every triangle primitive in a .glb into SubMesh records.

    Node transforms (translation/rotation/scale, including parent chains) are
    baked into the vertex positions, so a prop placed via its node — e.g. a
    cube parented onto the head with its own offset+scale — lands where the
    modeller put it instead of at the raw-accessor origin.
    """
    return _glb_parse(glb_bytes)[0]


def glb_skin_influences(glb_bytes: bytes) -> list[Influences | None]:
    """Per-submesh bone influences from the .glb's own skin, or None entries.

    This is the data a hand-rigged mesh carries and the cooker used to throw
    away: `skins[].joints` gives node indices, the node's `name` gives the
    bone name, and `JOINTS_0` indexes into that joints array. Reading it is
    what lets a mesh built in Blender be bound by NAME to the game skeleton
    instead of having weights guessed from the nearest original vertices.

    Note that an `rsmm uncook` .glb reports no skin at all — the cooked
    weights ride in `extras.rsmm.cooked_b64`, not in glTF skinning — so this
    returns None entries for one. Re-rigging in Blender is what produces a
    real skin.
    """
    return _glb_parse(glb_bytes)[1]


def _glb_parse(glb_bytes: bytes) -> tuple[list[_geo.SubMesh],
                                          list[Influences | None]]:
    from .unify import read_glb

    gltf, binary = read_glb(glb_bytes)
    nodes = gltf.get("nodes", [])

    # Resolve each node's world matrix by walking down from the scene roots.
    world: dict[int, list[float]] = {}
    child_of: set[int] = set()
    for n in nodes:
        for c in n.get("children", []):
            child_of.add(c)
    scenes = gltf.get("scenes", [])
    si = gltf.get("scene", 0)
    if scenes and 0 <= si < len(scenes):
        roots = list(scenes[si].get("nodes", []))
    else:
        roots = [i for i in range(len(nodes)) if i not in child_of]

    stack = [(ri, _mat_identity()) for ri in roots]
    while stack:
        ni, parent = stack.pop()
        if ni < 0 or ni >= len(nodes) or ni in world:
            continue
        m = _mat_mul(parent, _node_local_matrix(nodes[ni]))
        world[ni] = m
        for c in nodes[ni].get("children", []):
            stack.append((c, m))

    out: list[_geo.SubMesh] = []
    skins: list[Influences | None] = []
    # Iterate nodes (not meshes) so each instance carries its own transform.
    for ni, node in enumerate(nodes):
        mi = node.get("mesh")
        if mi is None:
            continue
        m = world.get(ni, _mat_identity())
        joint_names = _skin_joint_names(gltf, nodes, node.get("skin"))
        for prim in gltf["meshes"][mi].get("primitives", []):
            attrs = prim.get("attributes", {})
            # Require NORMAL: a renderable surface has it, while helper nodes
            # (e.g. the `aabb` bounding-box that `rsmm uncook` emits) are
            # POSITION-only and must NOT be merged as geometry.
            if ("POSITION" not in attrs or "NORMAL" not in attrs
                    or "indices" not in prim):
                continue
            positions = _accessor_floats(gltf, binary, attrs["POSITION"], "VEC3")
            normals = _accessor_floats(gltf, binary, attrs["NORMAL"], "VEC3")
            uvs = (_accessor_floats(gltf, binary, attrs["TEXCOORD_0"], "VEC2")
                   if "TEXCOORD_0" in attrs else [(0.0, 0.0)] * len(positions))
            indices = _accessor_indices(gltf, binary, prim["indices"])
            infl = _prim_influences(gltf, binary, attrs, joint_names)
            # A skinned mesh is posed by its skeleton, not by the node it
            # hangs off: glTF says to ignore the node transform for one, and
            # Blender routinely exports a skinned mesh under a node carrying a
            # stale offset. Baking it would slide the mesh off its own bones.
            if infl is None:
                positions = [_mat_apply_point(m, p) for p in positions]
                normals = [_mat_apply_normal(m, nrm) for nrm in normals]
            out.append(_geo.SubMesh(positions=positions, normals=normals,
                                    uvs=uvs, indices=indices))
            skins.append(infl)
    return out, skins


def _skin_joint_names(gltf: dict, nodes: list, skin_idx) -> list[str] | None:
    """Bone name per joint slot of `skin_idx`, or None if there is no skin."""
    if skin_idx is None:
        return None
    try:
        joints = gltf["skins"][skin_idx]["joints"]
    except (KeyError, IndexError, TypeError):
        return None
    out: list[str] = []
    for ji in joints:
        node = nodes[ji] if 0 <= ji < len(nodes) else {}
        out.append(str(node.get("name") or f"joint{ji}"))
    return out


def _prim_influences(gltf: dict, binary: bytes, attrs: dict,
                     joint_names: list[str] | None) -> Influences | None:
    """`(bone name, weight)` per vertex for one primitive, or None."""
    if not joint_names or "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
        return None
    joints = _accessor_vec4(gltf, binary, attrs["JOINTS_0"])
    weights = _accessor_vec4(gltf, binary, attrs["WEIGHTS_0"])
    out: Influences = []
    for jv, wv in zip(joints, weights, strict=True):
        per: list[tuple[str, float]] = []
        for j, w in zip(jv, wv, strict=True):
            j = int(j)
            if w > 0.0 and 0 <= j < len(joint_names):
                per.append((joint_names[j], float(w)))
        out.append(per)
    return out


# --- oCMeshBuffer record encode -----------------------------------------

def _encode_record(sm: _geo.SubMesh, flag: int) -> bytes:
    """Encode one meshbuffer's mutable region (from the vertex_count field
    through the end of the vertex blob)."""
    vcount = len(sm.positions)
    indices = sm.indices
    out = bytearray()
    out += struct.pack("<I", vcount)                       # informational count
    out += struct.pack("<II", len(indices), len(indices) * 4)  # index oCTVector
    out += struct.pack(f"<{len(indices)}I", *indices)
    out += bytes([flag])
    out += struct.pack("<II", vcount, vcount * _VERTEX_STRIDE)
    for k in range(vcount):
        px, py, pz = sm.positions[k]
        nx, ny, nz = sm.normals[k] if k < len(sm.normals) else (0.0, 0.0, 1.0)
        u, v = sm.uvs[k] if k < len(sm.uvs) else (0.0, 0.0)
        out += struct.pack("<8f", px, py, pz, nx, ny, nz, u, v)
        out += b"\x00" * 16  # tangent(12) + handedness(4)
    return bytes(out)


_DEGENERATE = _geo.SubMesh(positions=[(0.0, 0.0, 0.0)],
                           normals=[(0.0, 0.0, 1.0)], uvs=[(0.0, 0.0)],
                           indices=[])


def _find_records(main: bytes) -> list[tuple[int, int, int]]:
    """Return (mutable_start, end, flag) for each default-buffer meshbuffer."""
    recs: list[tuple[int, int, int]] = []
    n = len(main)
    i = 0
    while True:
        j = main.find(_TRIMESH_VER, i)
        if j == -1:
            break
        i = j + 4
        pos = j - 5
        if pos < 0:
            continue
        try:
            if main[pos + 4] not in (0, 1) or main[pos + 9] != 0:
                continue
            p = pos + 10
            mut_start = p
            p += 4
            _ielem, ibytes = struct.unpack_from("<II", main, p)
            p += 8
            if ibytes % 4 or p + ibytes > n:
                continue
            p += ibytes
            flag = main[p]
            p += 1
            vcount, vbytes = struct.unpack_from("<II", main, p)
            p += 8
            if vcount == 0 or vbytes // vcount != _VERTEX_STRIDE or p + vbytes > n:
                continue
            recs.append((mut_start, p + vbytes, flag))
            i = p + vbytes
        except (struct.error, IndexError):
            continue
    return recs


# --- bone-name palette (one per meshbuffer) -----------------------------
#
# THE thing to know about skinning here: the `u8` bone indices in a submesh's
# `oCSkinning8VertexLayer` do NOT index the file's oCSkeleton. They index a
# palette of bone NAMES carried by that submesh's own meshbuffer, immediately
# after its vertex blob:
#
#     u32 count; count x { u32 len; bytes name }
#
# The engine resolves palette entry -> bone by name. So the same index means
# different bones in different submeshes: measured on the shipped Beowulf,
# index 6 is `DEF.PHY.Hair` in submesh 0 (palette of 13) and `DEF.Cup.R` in
# submesh 1 (palette of 63). Corpus check over the shipped geometries: every
# submesh's maximum referenced index is exactly `len(palette) - 1`.
#
# That is what made a skinned character graft produce garbage. `_gather_source`
# pools the template's per-vertex skinning records across ALL its submeshes
# into one list, and the swap writes the transferred result into record 0 —
# which kept record 0's 13-entry palette while carrying indices up to 62 from
# submesh 1. Silently out of range, and only on a multi-submesh (i.e. any
# character) template, which is why every prop and weapon swap shipped fine.
#
# The fix is small because both sides are the SAME skeleton: decode each source
# record through the palette of the submesh it came from, re-index against one
# merged palette, and write that palette back into the records that receive
# transferred geometry.

#: A palette index is a u8, so this many distinct bones is the hard ceiling.
_PALETTE_MAX = 256


def _parse_palette(main: bytes, off: int) -> tuple[list[str], int] | None:
    """Bone-name palette at `off` (just past a vertex blob) + its end offset.

    Returns None if the bytes there are not a plausible palette, so a template
    whose layout we have not seen degrades to "leave it alone" rather than
    corrupting the record.
    """
    try:
        count = struct.unpack_from("<I", main, off)[0]
    except struct.error:
        return None
    if not 0 < count < _PALETTE_MAX:
        return None
    names: list[str] = []
    p = off + 4
    for _ in range(count):
        try:
            ln = struct.unpack_from("<I", main, p)[0]
        except struct.error:
            return None
        if not 0 < ln < 128 or p + 4 + ln > len(main):
            return None
        raw = main[p + 4:p + 4 + ln]
        if not all(32 <= c < 127 for c in raw):
            return None
        names.append(raw.decode("ascii"))
        p += 4 + ln
    return names, p


def _encode_palette(names: list[str]) -> bytes:
    out = bytearray(struct.pack("<I", len(names)))
    for n in names:
        b = n.encode("ascii")
        out += struct.pack("<I", len(b)) + b
    return bytes(out)


def _record_palettes(main: bytes) -> list[list[str]] | None:
    """Every meshbuffer's palette, in record order — or None if any is absent.

    All-or-nothing on purpose: a partial read would re-index some records and
    not others, which is worse than not re-indexing at all.
    """
    out: list[list[str]] = []
    for _mut, end, _flag in _find_records(main):
        got = _parse_palette(main, end)
        if got is None:
            return None
        out.append(got[0])
    return out or None


def _swap_section(main: bytes, placed: list[_geo.SubMesh | None],
                  palette: list[str] | None = None) -> bytes:
    """Rewrite a section's meshbuffer blobs with the custom geometry.

    `placed[i]` is the mesh for template record `i`; None degenerates that
    record (a single vertex) so the old mesh doesn't show through. When
    `palette` is given, each record that actually receives geometry also gets
    its bone-name palette replaced — the transferred weights are indexed
    against that merged palette, not against the one the record shipped with.
    A degenerated record keeps its original palette, because its layers keep
    replicating the template's own vertex-0 record.
    """
    recs = _find_records(main)
    if not recs:
        raise ValueError("template section has no default-buffer meshbuffer")
    out = bytearray()
    cursor = 0
    for ri, (mut_start, end, flag) in enumerate(recs):
        sm = placed[ri] if ri < len(placed) else None
        out += main[cursor:mut_start]
        out += _encode_record(sm if sm is not None else _DEGENERATE, flag)
        cursor = end
        if sm is not None and palette is not None:
            got = _parse_palette(main, end)
            if got is not None:
                out += _encode_palette(palette)
                cursor = got[1]
    out += main[cursor:]
    return bytes(out)


# --- per-vertex side layers (binormal / tangent / skinning) -------------
#
# Each submesh ships parallel per-vertex layers sized to ITS vertex count:
#   ver=9  comp=0  "binormal"/"tangent"  -> one 12 B/vertex vec3 block
#   ver=11 comp=0  "skinning"            -> two 20 B/vertex blocks
#   ver=12 comp=0  "skinning"            -> two 20 B/vertex blocks
# The engine reads these by the meshbuffer's vertex count, so after a swap
# they MUST be resized to the new count or every vertex gets garbage bone
# weights and the mesh explodes. We rebuild each block by replicating the
# template's vertex-0 record — a uniform, valid binding (whole submesh
# rigidly follows one bone: no deformation, but no glitch).
#
# ver=12 was MISSING here, and that is what broke every character swap. The
# shipped hero meshes carry `oCSkinning8VertexLayer` at version 12, so
# `_layer_vertex_count` returned None for it, the rewrite loop skipped it as
# "not a per-vertex layer", and the swapped mesh kept the TEMPLATE's bone data
# — 3034 vertices' worth of weights addressed by a 15107-vertex mesh. Static
# checks all passed and the model looked correct until the skeleton moved, at
# which point it was shredded. Two 20-byte blocks = 8 bones per vertex; the
# first block is bones 1-4, the second 5-8, which is why anything written to
# both blocks double-weights the vertex.

_LAYER_VERS = (9, 11, 12)


def _layer_vertex_count(payload: bytes) -> int | None:
    """If `payload` is a per-vertex side layer, return its vertex count."""
    try:
        ver = struct.unpack_from("<I", payload, 0)[0]
        if ver not in _LAYER_VERS:
            return None
        nl = struct.unpack_from("<I", payload, 4)[0]
        if nl > 64 or 8 + nl + 1 > len(payload):
            return None
        pos = 8 + nl
        if payload[pos] != 0:  # comp_mode must be uncompressed
            return None
        pos += 1
        count, bc = struct.unpack_from("<II", payload, pos)
        if count == 0 or bc % count or pos + 8 + bc > len(payload):
            return None
        return count
    except (struct.error, IndexError):
        return None


def _merge(submeshes: list[_geo.SubMesh]) -> _geo.SubMesh:
    positions: list = []
    normals: list = []
    uvs: list = []
    indices: list[int] = []
    for sm in submeshes:
        base = len(positions)
        positions += sm.positions
        normals += sm.normals
        uvs += sm.uvs
        indices += [base + i for i in sm.indices]
    return _geo.SubMesh(positions=positions, normals=normals, uvs=uvs,
                        indices=indices)


def sanitize(mesh: _geo.SubMesh) -> tuple[_geo.SubMesh, dict[str, int]]:
    """Drop degenerate triangles and repair unusable normals.

    Every shipped scenery mesh measured has **zero** zero-area triangles and
    unit-length normals throughout. A mesh that breaks either invariant is not
    merely ugly: a zero-area triangle has no face normal, and a zero-length
    vertex normal makes `normalize(n)` a division by zero, so the tangent basis
    the cooked container carries per vertex comes out NaN. That is authored
    data the engine has no defined behaviour for.

    It is easy to produce by accident — emitting a triangle-fan segment as the
    quad ``[a, b, c, a]`` yields exactly this, one dead triangle and four dead
    normals per cap face, and that is what the first custom prop this SDK ever
    built shipped (48 of 172 triangles, 192 of 344 normals).

    Repairs rather than refuses: exporters legitimately emit the odd sliver, and
    a mod should not fail to build over one. Returns the cleaned mesh and a
    count of what was fixed so callers can report it.
    """
    fixed = {"degenerate_tris": 0, "bad_normals": 0}
    pos = mesh.positions
    tris = [mesh.indices[i:i + 3] for i in range(0, len(mesh.indices) - 2, 3)]

    def area2(t):
        a, b, c = pos[t[0]], pos[t[1]], pos[t[2]]
        e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (e1[1] * e2[2] - e1[2] * e2[1],
             e1[2] * e2[0] - e1[0] * e2[2],
             e1[0] * e2[1] - e1[1] * e2[0])
        return n, math.sqrt(sum(x * x for x in n))

    keep, face_n = [], {}
    for t in tris:
        if len(set(t)) < 3:
            fixed["degenerate_tris"] += 1
            continue
        n, ln = area2(t)
        if ln < 1e-12:
            fixed["degenerate_tris"] += 1
            continue
        keep.append(t)
        unit = (n[0] / ln, n[1] / ln, n[2] / ln)
        for v in t:
            face_n.setdefault(v, unit)

    normals = list(mesh.normals)
    for i, n in enumerate(normals):
        ln = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if ln > 1e-6 and abs(ln - 1.0) < 1e-3:
            continue
        fixed["bad_normals"] += 1
        # Prefer a face normal from a surviving triangle; else renormalize;
        # else point up, which is wrong but finite.
        normals[i] = face_n.get(i) or (
            (n[0] / ln, n[1] / ln, n[2] / ln) if ln > 1e-12 else (0.0, 1.0, 0.0))

    out = _geo.SubMesh(positions=pos, normals=normals, uvs=mesh.uvs,
                       indices=[i for t in keep for i in t])
    return out, fixed


# --- alignment + weight transfer ----------------------------------------

def _extents(pos: list) -> tuple[list[float], list[float], list[float]]:
    mn = [min(p[i] for p in pos) for i in range(3)]
    mx = [max(p[i] for p in pos) for i in range(3)]
    return mn, mx, [mx[i] - mn[i] for i in range(3)]


def _rot_matrix(euler_deg: tuple[float, float, float]) -> list[list[float]]:
    """Rotation matrix for extrinsic X->Y->Z Euler angles (degrees)."""
    rx, ry, rz = (math.radians(a) for a in euler_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rxm = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    rym = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rzm = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
                for i in range(3)]

    return mul(rzm, mul(rym, rxm))


def _apply_m(m: list[list[float]], v) -> tuple[float, float, float]:
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


#: How tall Y must be, relative to the longest axis, to be believed as up.
#: A T-posed character is WIDER than it is tall (arms out), so "longest axis
#: wins" lays it on its side — which is exactly what happened to a character
#: swap: extents X/Y/Z = 2.5/1.72/0.67 guessed a 90 deg roll. A genuinely
#: Z-up model has Y as its shallow depth axis and sits far below this ratio
#: (~0.3), so the two cases stay cleanly separated.
_UPRIGHT_Y_RATIO = 0.6


def _auto_upright_euler(custom: list) -> tuple[float, float, float]:
    """Best-effort guess: rotate the tallest mesh axis to the game up-axis (Y).

    A pure rigid rotation, so it never distorts — only the *direction* may be
    wrong (upside down / facing away), which the modeller corrects with an
    explicit `rotate_deg`.
    """
    _mn, _mx, ext = _extents(custom)
    up = ext.index(max(ext))
    # Believe an already-plausible Y before believing the longest axis.
    if ext[1] >= _UPRIGHT_Y_RATIO * max(ext):
        return (0.0, 0.0, 0.0)
    if up == 1:          # already Y-up
        return (0.0, 0.0, 0.0)
    if up == 2:          # Z-up -> bring Z to Y
        return (-90.0, 0.0, 0.0)
    return (0.0, 0.0, 90.0)  # X-up -> bring X to Y


def _centre_of(pts: list, use_centroid: bool) -> list[float]:
    """Horizontal centre to align on: bounding-box mid, or the centroid.

    The bbox mid is what "line these two up" normally means, and it is what
    props are tuned against — but it is dominated by the single most distant
    vertex, and on a character that vertex belongs to an accessory. Measured
    on Beowulf: his geometry includes the back-mounted wyrm (submesh 2), a
    flat fan sprawling to z = -2.544 while contributing almost nothing in Y.
    The combined bbox centre is z = -0.782; the centroid is z = -0.016, which
    is where his body actually is. Fitting to the bbox therefore parked a
    replacement body 0.85 units BEHIND the hero — "the model stands behind the
    character and the character sticks out of it" — and no weight work could
    fix it, because the mesh was in the wrong place before skinning began.

    Centroid centring is used for skinned templates only. A skinned graft
    lives or dies on overlapping the source point cloud (weights are copied
    from the nearest source vertices), and the centroid maximises that
    overlap; props keep the bbox behaviour their sightings were tuned on.
    """
    if not use_centroid:
        mn, mx, _e = _extents(pts)
        return [(mn[i] + mx[i]) / 2 for i in range(3)]
    return [sum(p[i] for p in pts) / len(pts) for i in range(3)]


def _fit_transform(custom: list, template: list,
                   euler_deg: tuple[float, float, float],
                   scale_mult: float = 1.0, fit: str = "height",
                   centroid: bool = False):
    """Rigid rotate by `euler_deg`, then size into the template's space and
    recenter (feet + horizontal centre). A rigid rotation + one uniform scale
    can never shear/distort the mesh. `scale_mult` multiplies the result.

    `fit` chooses what "size into" means:

    ``"height"``
        Match the template's tallest extent. Right when the custom mesh stands
        in for the same *kind* of thing — a sword for a sword.
    ``"none"``
        Keep the mesh's own dimensions. Right when the donor is a mounting
        point rather than a size reference, which is the usual case for a
        structure: a 2.9-unit obelisk taking over a 1.4-unit ruin slab is
        squashed to 47% by height-fitting and comes out looking like the slab
        it replaced — it renders perfectly and reads as "nothing happened".

    Returns (apply_pos, apply_nrm)."""
    m = _rot_matrix(euler_deg)
    rotated = [_apply_m(m, p) for p in custom]
    rmn, _rmx, re = _extents(rotated)
    tmn, _tmx, te = _extents(template)
    # Up is Y, always — not "whichever template axis is longest". The engine is
    # Y-up and props stand on y=0 (the blood fountain base spans y 0.00..2.46),
    # so the longest-axis guess only coincides with up for things taller than
    # they are wide. A prop that is wider than tall breaks it: the ruin slab is
    # 0.99 x 0.30 x 0.51, so the guess picked X, anchored the custom mesh along
    # the ground plane and centred it vertically instead of standing it up.
    up = 1
    if fit == "none":
        scale = scale_mult
    elif fit == "height":
        # BOTH extents need the guard. `re[up]` (the custom mesh) was checked
        # and `te[up]` (the template) was not — but a donor that is planar in Y
        # gives te[up] == 0 and hence scale == 0, collapsing the swapped mesh to
        # a single point. That cooks, applies and renders nothing, which is
        # indistinguishable from "the override never reached the game" and is
        # the single most expensive failure to diagnose in this pipeline. A
        # template with no height cannot express a height fit, so fall back to
        # the mesh's own dimensions and say so.
        if not te[up] or not re[up]:
            _log.warning(
                "geometry: template has no usable height (extent %.4f); "
                "fit='height' would scale the mesh to nothing — keeping the "
                "mesh's own size instead (equivalent to fit='none')", te[up])
            scale = scale_mult
        else:
            scale = (te[up] / re[up]) * scale_mult
    else:
        raise ValueError(f"transform.fit must be 'height' or 'none', got {fit!r}")
    # Align the two centres on the horizontal axes; the up axis still anchors
    # feet-to-feet on the minimum, so a model stands on the ground either way.
    tc = _centre_of(template, centroid)
    cc = _centre_of(rotated, centroid)
    off = [tc[i] - (cc[i] - rmn[i]) * scale for i in range(3)]

    def apply_pos(p):
        q = _apply_m(m, p)
        return tuple((q[i] - rmn[i]) * scale
                     + (tmn[i] if i == up else off[i])
                     for i in range(3))

    def apply_nrm(n):
        q = _apply_m(m, n)
        length = (q[0] ** 2 + q[1] ** 2 + q[2] ** 2) ** 0.5 or 1.0
        return (q[0] / length, q[1] / length, q[2] / length)

    return apply_pos, apply_nrm


def _layer_name(payload: bytes) -> str:
    nl = struct.unpack_from("<I", payload, 4)[0]
    return payload[8:8 + nl].decode("utf-8", "replace")


def _layer_blocks(payload: bytes) -> tuple[bytes, list[tuple[int, list[bytes]]]]:
    """Split a per-vertex layer into (header, [(stride, per-vertex records)])."""
    pos = 8 + struct.unpack_from("<I", payload, 4)[0] + 1
    header = payload[:pos]
    blocks: list[tuple[int, list[bytes]]] = []
    n = len(payload)
    while pos < n:
        count, bc = struct.unpack_from("<II", payload, pos)
        pos += 8
        stride = bc // count
        recs = [payload[pos + i * stride:pos + (i + 1) * stride] for i in range(count)]
        pos += bc
        blocks.append((stride, recs))
    return header, blocks


def _assemble_layer(header: bytes, blocks: list[tuple[int, list[bytes]]]) -> bytes:
    out = bytearray(header)
    for stride, recs in blocks:
        out += struct.pack("<II", len(recs), stride * len(recs))
        out += b"".join(recs)
    return bytes(out)


#: Point count at or below which :meth:`_Grid.k_nearest` scans every point
#: instead of walking cells. Shipped prop templates are far below it (the
#: tombstone has 52 points, the blood fountain base 400-odd), so this is the
#: path prop cooking actually takes.
_GRID_BRUTE_FORCE_MAX = 4096


class _Grid:
    """Uniform spatial hash for approximate nearest-neighbour over points."""

    def __init__(self, pts: list) -> None:
        self.pts = pts
        _mn, _mx, ext = _extents(pts) if pts else ([0] * 3, [0] * 3, [1] * 3)
        self.cell = max(max(ext) / 32.0, 1e-4)
        self.mn = _mn
        self.grid: dict[tuple[int, int, int], list[int]] = {}
        for i, p in enumerate(pts):
            self.grid.setdefault(self._key(p), []).append(i)
        # Bounds of the OCCUPIED cells. The expanding search stops once its
        # radius covers these, which is what keeps a query point that lands
        # outside the grid from expanding forever (see k_nearest).
        keys = self.grid.keys()
        self.kmin = tuple(min(kk[a] for kk in keys) for a in range(3)) if keys \
            else (0, 0, 0)
        self.kmax = tuple(max(kk[a] for kk in keys) for a in range(3)) if keys \
            else (0, 0, 0)

    def _key(self, p) -> tuple[int, int, int]:
        return tuple(int((p[a] - self.mn[a]) // self.cell) for a in range(3))

    @staticmethod
    def _shell(r: int):
        """Cell offsets at Chebyshev distance exactly `r` — the new cells only.

        Iterating the full cube each round re-visits everything already seen,
        which turns an expanding search into O(r^3) repeated work per step and
        was the dominant cost of the whole geometry cook.
        """
        if r == 0:
            yield (0, 0, 0)
            return
        span = range(-r, r + 1)
        for dx in span:
            ax = dx in (-r, r)
            for dy in span:
                zs = span if (ax or dy in (-r, r)) else (-r, r)
                for dz in zs:
                    yield (dx, dy, dz)

    def k_nearest(self, p, k: int) -> list[tuple[int, float]]:
        """Return up to `k` (index, squared-distance) pairs nearest to `p`.

        The grid is built over the TEMPLATE's points but queried with the
        CUSTOM mesh's, and those two need not overlap at all — a 2.9-unit
        obelisk against a 1.4-unit slab puts most query points well outside the
        occupied cells. The original loop answered that by rescanning an
        ever-larger cube from scratch, up to radius 64, for every single
        vertex: roughly 1e7 dict lookups each, and `rsmm apply` took over ten
        minutes with one model in the tree. Two bounds fix it — visit each cell
        once (`_shell`), and stop once the radius has swept past the occupied
        cells instead of grinding to the hardcoded 64.
        """
        if not self.grid:
            return []
        # Small templates: scan them. The grid exists to avoid an O(N*M) sweep
        # over a big mesh, and below this size that sweep is cheaper than the
        # cell walk it replaces — the shipped tombstone template has 52 points,
        # against which the expanding search was doing millions of empty-cell
        # lookups per query. Exact, and it removes the pathological case
        # entirely rather than bounding it.
        if len(self.pts) <= _GRID_BRUTE_FORCE_MAX:
            found = sorted(
                (((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2), i)
                for i, q in enumerate(self.pts))
            return [(i, d) for d, i in found[:k]]

        # Start from the nearest cell that actually holds points. An
        # out-of-bounds query would otherwise have to expand all the way back
        # to the occupied region one ring at a time, and the custom mesh is
        # routinely far outside the template's extent (a 2.9-unit obelisk
        # against a 1.4-unit slab, at a cell size derived from the slab).
        raw = self._key(p)
        key = tuple(min(max(raw[a], self.kmin[a]), self.kmax[a]) for a in range(3))
        # Beyond this radius every occupied cell has already been visited, so
        # another ring cannot add a candidate.
        max_r = max(max(abs(key[a] - self.kmin[a]), abs(key[a] - self.kmax[a]))
                    for a in range(3))
        found: list[tuple[float, int]] = []
        radius = 0
        # Expand until we have >= k candidates, then one extra ring so the
        # true k-nearest aren't missed at a cell boundary.
        extra = 1
        while radius <= max_r:
            for dx, dy, dz in self._shell(radius):
                for i in self.grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                    q = self.pts[i]
                    d = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                         + (p[2] - q[2]) ** 2)
                    found.append((d, i))
            if len(found) >= k:
                if extra <= 0:
                    break
                extra -= 1
            radius += 1
        found.sort()
        return [(i, d) for d, i in found[:k]]


def swap_geometry(template_cooked: bytes, glb_bytes: bytes,
                  transform: dict | None = None) -> bytes:
    """Return a cooked oCGeometry: `template_cooked` with its mesh replaced
    by the geometry in `glb_bytes`, retargeted onto the original skeleton.

    `transform` controls how the custom mesh is oriented + sized into the
    template's space (see `_fit_transform`):
      - None            -> auto-upright guess (tallest axis -> up)
      - {"rotate_deg": [x, y, z]}  -> explicit rigid rotation (degrees)
      - {"scale": s}    -> multiply the fitted scale by `s`
      - {"fit": "none"} -> keep the mesh's OWN size instead of matching the
                           template's height (see `_fit_transform`); what a
                           structure usually wants, since its donor is a
                           mounting point, not a size reference
      - {"fit": "rig"}  -> place the mesh exactly where it was authored: no
                           scale, no recentre, no auto-upright. Right when the
                           mesh was rigged against the game's own skeleton,
                           where any fit would slide it off its bones. The
                           default for `skin="gltf"`.
      - {"skin": ...}   -> how bone weights are produced; see below
      - {"submeshes": "map"} -> lay the .glb's submeshes 1:1 onto the
                           template's instead of merging them all into the
                           first, preserving its material split
      - {"bones": {src: dst}} -> rename bones on the way in (`skin="gltf"`)
      - {"drop_bones": [...]} -> delete geometry driven by those bones
    Recentering is always automatic; scale stays uniform (never distorts).
    """
    from . import cooked

    transform = dict(transform or {})
    submeshes, skins = _glb_parse(glb_bytes)
    if not submeshes:
        raise ValueError("glb has no indexed triangle mesh to cook")

    sub_mode = str(transform.get("submeshes", "merge"))
    if sub_mode not in ("merge", "map"):
        raise ValueError(f"transform.submeshes must be 'merge' or 'map', "
                         f"got {sub_mode!r}")
    skin_mode = str(transform.get("skin", "transfer"))
    if skin_mode not in ("transfer", "rigid", "gltf"):
        raise ValueError(f"transform.skin must be 'transfer', 'rigid' or "
                         f"'gltf', got {skin_mode!r}")
    aliases = {str(k): str(v) for k, v in (transform.get("bones") or {}).items()}
    drop_bones = {str(b) for b in (transform.get("drop_bones") or [])}

    if skin_mode == "gltf" and not any(s for s in skins):
        raise NotReversedError(
            "oCGeometry",
            "transform.skin='gltf' needs bone weights in the .glb, and this "
            "one carries no skin (no JOINTS_0/WEIGHTS_0). An `rsmm uncook` "
            "mesh reports none by design — its weights are in "
            "extras.rsmm.cooked_b64, not in glTF skinning. Rig the mesh to "
            "the game's skeleton in Blender and export with the armature, or "
            "use skin='transfer'.")
    if drop_bones:
        if skin_mode != "gltf":
            raise ValueError(
                "transform.drop_bones needs transform.skin='gltf': it selects "
                "geometry by the bone driving it, and only a .glb with its own "
                "skin says which bone that is")
        submeshes, skins, dropped = _drop_bone_geometry(
            submeshes, skins, drop_bones, aliases)
        _log.info("drop_bones removed %d vertices driven by %s",
                  dropped, ", ".join(sorted(drop_bones)))
        if not any(s.indices for s in submeshes):
            raise ValueError("transform.drop_bones removed the entire mesh")

    cf = cooked.parse(template_cooked)
    target = next((si for si, sec in enumerate(cf.sections)
                   if _find_records(sec.payload)), None)
    if target is None:
        raise ValueError("template has no oCMeshBuffer section")

    old_subs = _geo._parse_meshbuffers(cf.sections[target].payload)
    old_counts = [len(s.positions) for s in old_subs]
    # Captured before the swap: the stored AABB equals these bounds, which is
    # how _rewrite_aabb finds the field without trusting a tail offset.
    old_positions = [p for s in old_subs for p in s.positions]

    # Gather the template's skinned vertices (position + per-vertex side-layer
    # records) so the custom mesh can borrow real bone weights by proximity.
    # Skinning records come back re-indexed against one merged bone palette.
    src = _gather_source(cf, target, old_subs)
    palette = src.get("palette") if src else None

    if skin_mode == "gltf" and palette is None:
        raise NotReversedError(
            "oCGeometry",
            "transform.skin='gltf' needs the template's bone-name palettes, "
            "and this template's could not be read — so a joint name from the "
            ".glb has nothing to bind to")

    # Lay the custom submeshes onto the template's records. `merge` (the
    # default, and what every shipped swap was cooked with) collapses them all
    # into record 0. `map` places them 1:1, which is what keeps a multi-
    # material template's split alive: the template hands one material to each
    # record via its entity, so everything merged into record 0 draws with one
    # material and the donor's other atlas can never appear.
    donors = list(submeshes) if sub_mode == "map" else [_merge(submeshes)]
    dskins = (list(skins) if sub_mode == "map"
              else [_merge_influences(submeshes, skins)])
    placed: list[_geo.SubMesh | None] = [None] * len(old_counts)
    pskins: list[Influences | None] = [None] * len(old_counts)
    for i, (donor, dskin) in enumerate(zip(donors, dskins, strict=True)):
        slot = min(i, len(old_counts) - 1)
        if placed[slot] is None:
            placed[slot], pskins[slot] = donor, dskin
        else:
            # More donor submeshes than the template has records: the surplus
            # piles onto the last one rather than being silently dropped.
            pskins[slot] = _merge_influences([placed[slot], donor],
                                             [pskins[slot], dskin])
            placed[slot] = _merge([placed[slot], donor])

    for ri, sm in enumerate(placed):
        if sm is None:
            continue
        clean, repaired = sanitize(sm)
        placed[ri] = clean
        if any(repaired.values()):
            _log.warning(
                "custom mesh needed repair before cooking: %d degenerate "
                "triangle(s) dropped, %d unusable normal(s) rebuilt. Every "
                "shipped mesh has neither; a zero-length normal makes the "
                "per-vertex tangent basis NaN. Fix this in the source .glb.",
                repaired["degenerate_tris"], repaired["bad_normals"])

    # Vertex-budget guard. CONFIRMED in-game: a 243k-vert mesh swapped onto a
    # 1.2k-vert weapon slot crashes on launch; the vanilla gun (1.2k) is fine.
    # Cooked indices are 32-bit, so the cap is a renderer/GPU buffer limit, not
    # an index limit. The observed crash sits between 1.2k and 243k; 65535 (the
    # 16-bit boundary most engine paths still assume somewhere) is the
    # defensible ceiling, and ~60k verts already looks near-identical to a 250k
    # film source. Refuse above it so apply_mods skips the asset rather than
    # installing a crasher. Decimate the source toward — not far below — this
    # cap; you can go FAR higher than the vanilla count. Override (at your own
    # risk, having tested a higher count in-game) via RSMM_GEO_VERTEX_CAP.
    cap = int(__import__("os").environ.get("RSMM_GEO_VERTEX_CAP", _VERTEX_HARD_CAP))
    custom_vtx = sum(len(s.positions) for s in placed if s is not None)
    tpl_vtx = sum(old_counts) or 1
    if custom_vtx > cap:
        raise NotReversedError(
            "oCGeometry",
            f"custom mesh has {custom_vtx:,} vertices; the safe ceiling for a "
            f"swapped slot is {cap:,} (vanilla here is {tpl_vtx:,}, but you can "
            f"go far higher than that — ~{cap:,} looks near-identical to a 250k "
            f"source). Decimate in Blender toward ~{cap:,} verts. A heavier mesh "
            f"crashes the game at load. Raise RSMM_GEO_VERTEX_CAP only if you "
            f"have tested a higher count in-game on this slot.",
        )

    # Fit target: the template's skinned vertices when present, else the
    # template's own mesh-buffer positions. Either way the custom mesh MUST
    # be fit into the template's space — a rigid (non-skinned) template like
    # a weapon still needs it, or the raw GLB (commonly authored in metres,
    # ~100x the cooked cm scale) renders enormous.
    fit_target = (src["positions"] if src is not None and src["positions"]
                  else [p for s in old_subs for p in s.positions])
    # A mesh rigged to the game's own skeleton is ALREADY in the right space;
    # fitting it would slide it off its bones, so that path defaults to "rig".
    fit = str(transform.get("fit", "rig" if skin_mode == "gltf" else "height"))

    if fit_target and fit != "rig":
        if "rotate_deg" in transform:
            euler = tuple(float(a) for a in transform["rotate_deg"])
        else:
            euler = _auto_upright_euler(
                [p for s in placed if s is not None for p in s.positions])
        scale_mult = float(transform.get("scale", 1.0))
        apply_pos, apply_nrm = _fit_transform(
            [p for s in placed if s is not None for p in s.positions],
            fit_target, euler, scale_mult, fit,
            centroid=src is not None and bool(src["positions"]))
        placed = [None if s is None else _geo.SubMesh(
            positions=[apply_pos(p) for p in s.positions],
            normals=[apply_nrm(n) for n in s.normals],
            uvs=s.uvs, indices=s.indices) for s in placed]
    elif "rotate_deg" in transform:
        # `fit="rig"` still honours an explicit rotation: it is the one part of
        # the transform that says "the export axes are wrong", not "move it".
        m = _rot_matrix(tuple(float(a) for a in transform["rotate_deg"]))
        placed = [None if s is None else _geo.SubMesh(
            positions=[_apply_m(m, p) for p in s.positions],
            normals=[_apply_m(m, n) for n in s.normals],
            uvs=s.uvs, indices=s.indices) for s in placed]

    # Per-record bone weights.
    rigid_rec = _rigid_skin(src) if skin_mode == "rigid" else None
    knn: list[list | None] = [None] * len(placed)
    blended: list[list[bytes] | None] = [None] * len(placed)
    missing: dict[str, int] = {}
    for ri, sm in enumerate(placed):
        if sm is None:
            continue
        n = len(sm.positions)
        if skin_mode == "rigid":
            # Bind the WHOLE model to one bone: it follows the character but
            # never deforms. Per-vertex transfer assumes the custom mesh
            # occupies roughly the same space as the one it replaces, and for a
            # character it does not — a replacement body has its limbs
            # somewhere else entirely, so each vertex ends up weighted to
            # whatever bone happened to be nearest and the model is torn apart
            # the moment the skeleton animates.
            blended[ri] = [rigid_rec] * n if rigid_rec else None
        elif skin_mode == "gltf":
            blended[ri] = _gltf_skin_records(pskins[ri], n, palette, aliases,
                                             missing)
        elif src is not None and src["positions"]:
            knn[ri] = _build_transfer(sm.positions, src)
            gap = bind_pose_gap(knn[ri], src)
            if gap is not None and gap > _BIND_POSE_GAP:
                _log.warning(
                    "custom mesh does not overlap the original's bind pose "
                    "(median gap %.0f%% of the model's size). Bone weights are "
                    "copied from the NEAREST original vertices, so a limb "
                    "sitting where the original has nothing gets weighted to "
                    "the wrong bone and the model tears apart as soon as it "
                    "animates. Pose your mesh over the original in Blender "
                    "before exporting, or pass skin='rigid' to bind the whole "
                    "model to one bone (it follows the character but never "
                    "bends).", gap * 100)
            blended[ri] = _blend_skin_records(sm.normals, knn[ri], src)
    if missing:
        _log.warning(
            "skin='gltf': %d bone name(s) in the .glb are not on the "
            "template's skeleton and were ignored: %s. Rename them in Blender "
            "or map them with transform.bones.",
            len(missing),
            ", ".join(f"{n} ({c} verts)" for n, c in sorted(missing.items())))

    if palette is not None:
        _check_palette(blended, palette)

    cf.sections[target] = cooked.Section(
        payload=_swap_section(cf.sections[target].payload, placed, palette))

    # Which template record each per-vertex side layer belongs to, by the
    # vertex count it was sized for.
    rec_of_count: dict[int, int] = {}
    for ri, c in enumerate(old_counts):
        rec_of_count.setdefault(c, ri)

    for si, sec in enumerate(cf.sections):
        if si == target:
            continue
        vc = _layer_vertex_count(sec.payload)
        if vc is None or vc not in rec_of_count:
            continue
        ri = rec_of_count[vc]
        sm = placed[ri]
        cf.sections[si] = cooked.Section(payload=_rebuild_layer(
            sec.payload, len(sm.positions) if sm is not None else 1,
            knn[ri] if sm is not None else None,
            src, blended[ri] if sm is not None else None))

    new_positions = [p for s in placed if s is not None for p in s.positions]
    _rewrite_aabb(cf, _bbox6(old_positions), _bbox6(new_positions))
    return cooked.emit(cf)


def _merge_influences(subs: list, skins: list) -> Influences | None:
    """Concatenate per-submesh influences the way `_merge` concatenates verts.

    A submesh with no skin still has to occupy its vertices' slots, or every
    influence after it addresses the wrong vertex.
    """
    if not any(s for s in skins):
        return None
    out: Influences = []
    for sub, sk in zip(subs, skins, strict=True):
        out.extend(sk if sk is not None else [[] for _ in sub.positions])
    return out


def _drop_bone_geometry(subs: list, skins: list, drop: set[str],
                        aliases: dict[str, str]) -> tuple[list, list, int]:
    """Remove triangles whose vertices are mostly driven by `drop` bones.

    The use case is a donor body carrying a prop that has to become a separate
    object — the hog captain's anchor-and-chain is 1340 vertices on bones the
    hero's skeleton does not have, so it ends up stretched between the world
    origin and his wrist. Dropping by bone is the only handle on it: the chain
    is not a separate submesh, just a region of one.

    Majority rule per vertex (>0.5 of its weight on a dropped bone), then a
    triangle goes if any of its vertices does — trimming the boundary rather
    than leaving a fringe of half-bound triangles behind.
    """
    out_subs, out_skins, removed = [], [], 0
    for sub, sk in zip(subs, skins, strict=True):
        if sk is None:
            out_subs.append(sub)
            out_skins.append(sk)
            continue
        doomed = set()
        for vi, infl in enumerate(sk):
            total = sum(w for _n, w in infl) or 1.0
            bad = sum(w for n, w in infl if aliases.get(n, n) in drop)
            if bad / total > 0.5:
                doomed.add(vi)
        tris = [sub.indices[i:i + 3] for i in range(0, len(sub.indices) - 2, 3)]
        keep = [t for t in tris if not (set(t) & doomed)]
        if len(keep) == len(tris):
            out_subs.append(sub)
            out_skins.append(sk)
            continue
        used = sorted({i for t in keep for i in t})
        remap = {old: new for new, old in enumerate(used)}
        removed += len(sub.positions) - len(used)
        out_subs.append(_geo.SubMesh(
            positions=[sub.positions[i] for i in used],
            normals=[sub.normals[i] for i in used],
            uvs=[sub.uvs[i] for i in used],
            indices=[remap[i] for t in keep for i in t]))
        out_skins.append([sk[i] for i in used])
    return out_subs, out_skins, removed


def _gltf_skin_records(infl: Influences | None, count: int,
                       palette: list[str], aliases: dict[str, str],
                       missing: dict[str, int]) -> list[bytes] | None:
    """One cooked skinning record per vertex, bound BY NAME to `palette`.

    This is the path that makes a hand-rigged mesh possible at all: the
    modeller's own weights are used, so nothing is guessed from proximity and
    a body in a different pose is no longer a problem. Unresolvable names are
    counted in `missing` for one collected warning; a vertex left with no
    influence at all is fatal, because it would render pinned to bone 0.
    """
    if infl is None:
        return None
    index = {n: i for i, n in enumerate(palette)}
    out: list[bytes] = []
    orphans = 0
    for vi in range(count):
        acc: dict[int, float] = {}
        for name, w in (infl[vi] if vi < len(infl) else []):
            resolved = aliases.get(name, name)
            slot = index.get(resolved)
            if slot is None:
                missing[name] = missing.get(name, 0) + 1
                continue
            acc[slot] = acc.get(slot, 0.0) + w
        if not acc:
            orphans += 1
            out.append(_encode_skin((0, 0, 0, 0), (1.0, 0.0, 0.0, 0.0)))
            continue
        top = sorted(acc.items(), key=lambda kv: kv[1], reverse=True)[:4]
        total = sum(w for _b, w in top) or 1.0
        idx = [b for b, _w in top]
        weights = [w / total for _b, w in top]
        while len(idx) < 4:
            idx.append(0)
            weights.append(0.0)
        out.append(_encode_skin(idx, weights))
    if orphans:
        raise NotReversedError(
            "oCGeometry",
            f"skin='gltf': {orphans} of {count} vertices have no weight on any "
            f"bone the template knows, so they would all be pinned to one "
            f"bone. Rig against the game's skeleton (bone names must match) "
            f"or map the names with transform.bones.")
    return out


def _check_palette(blended: list[list[bytes] | None], palette: list[str]) -> None:
    """Fail if any produced weight addresses past the palette it ships with.

    The bug this exists to stop was silent: indices pooled from a 63-entry
    palette written into a record carrying 13 names. Nothing downstream
    noticed, and the corpus says the game never ships such a file.
    """
    for recs in blended:
        for rec in recs or ():
            idx, weights = _decode_skin(rec)
            for b, wt in zip(idx, weights, strict=True):
                if wt > 0.0 and b >= len(palette):
                    raise NotReversedError(
                        "oCGeometry",
                        f"bone index {b} addresses past the {len(palette)}-entry "
                        f"bone palette being written; this is the cooker's bug, "
                        f"not the mod's")


def _bbox6(pos: list) -> tuple[float, ...] | None:
    """``(xMin, yMin, zMin, xMax, yMax, zMax)`` over `pos`, or None if empty."""
    if not pos:
        return None
    return (min(p[0] for p in pos), min(p[1] for p in pos), min(p[2] for p in pos),
            max(p[0] for p in pos), max(p[1] for p in pos), max(p[2] for p in pos))


def _rewrite_aabb(cf, old_bb, new_bb) -> None:
    """Move the file's bounding box onto the mesh that is now in it.

    A cooked oCGeometry stores one 6-float AABB, and the swap did not touch it
    — so every custom mesh shipped with its DONOR's bounds. The engine culls
    and sorts against that box, so a mesh larger than its donor is clipped away
    wherever the box is off-screen, and the mod looks like it never applied.

    That is what hid the shrine: `Carpet_4x4` is a floor rug whose box is
    0.02..0.12 units tall, and the obelisk swapped into it stands 2.91 — the
    geometry was correct, cooked, applied and listed in the resource cache, and
    still invisible. It also explains why the very first sighting worked: that
    donor was a lantern post, tall enough to contain the obelisk.

    Located by VALUE rather than by offset: the stored box equals the
    template's own mesh bounds, so we search for those six floats instead of
    trusting a tail layout (`_parse_main_body` reads this field four bytes
    late, which is a separate defect and not one worth depending on here).
    Not finding it is not fatal — the mesh still swaps, it just keeps the old
    bounds — so this warns rather than raises.

    The scan steps ONE byte, not four. A type-A cooked container header is 27
    bytes (it carries a `u8 type_tag`), so nothing inside a section payload is
    4-aligned: Beowulf's box sits at offset 672530 (2 mod 4) and the hog
    captain's at 516245 and 543955 (1 and 3 mod 4). A 4-aligned scan found
    none of them, so every skinned character swap logged "template AABB not
    found" and shipped the donor's bounds.

    Every match is rewritten, not just the first. The buffer box and the file
    box are the same six floats whenever the template's bounds coincide, and
    the hog proves a template can genuinely store two — stopping at the first
    leaves the other stale. Six consecutive floats matching to 1e-3 by
    coincidence is not a practical risk.
    """
    if not old_bb or not new_bb:
        return
    packed_new = struct.pack("<6f", *new_bb)
    hits = 0
    for si in range(len(cf.sections)):
        payload = cf.sections[si].payload
        off = 0
        while off <= len(payload) - 24:
            got = struct.unpack_from("<6f", payload, off)
            if all(abs(a - b) <= 1e-3 for a, b in zip(got, old_bb, strict=True)):
                cf.sections[si] = _sec_replace(cf.sections[si], off, packed_new)
                payload = cf.sections[si].payload
                hits += 1
                off += 24
                continue
            off += 1
    if not hits:
        _log.warning(
            "template AABB not found (mesh bounds %s); the swapped mesh keeps "
            "the template's bounding box and may be culled if it is larger",
            old_bb)


def _sec_replace(sec, off: int, blob: bytes):
    from . import cooked

    buf = bytearray(sec.payload)
    buf[off:off + len(blob)] = blob
    return cooked.Section(payload=bytes(buf))


def _gather_source(cf, target: int, old_subs: list) -> dict | None:
    """Collect template skinned verts: positions + side-layer records, keyed
    by layer name, concatenated across every submesh (shared skeleton).

    Skinning records are RE-INDEXED as they are gathered: each submesh's
    `u8` bone indices address that submesh's own name palette, so pooling
    them raw mixes three unrelated index spaces (see the palette notes above).
    Every record here comes back indexed against `["palette"]`, one space for
    the whole template, which is also what gets written into the swapped
    record. Falls back to the raw records (and `palette=None`) when the
    template's palettes cannot be read, which leaves behaviour unchanged for
    a layout we have not seen.
    """
    by_count: dict[int, dict[str, bytes]] = {}
    for si, sec in enumerate(cf.sections):
        if si == target:
            continue
        vc = _layer_vertex_count(sec.payload)
        if vc is None:
            continue
        by_count.setdefault(vc, {})[_layer_name(sec.payload)] = sec.payload

    palettes = _record_palettes(cf.sections[target].payload)
    if palettes is not None and len(palettes) != len(old_subs):
        palettes = None
    merged: list[str] = []
    seen: dict[str, int] = {}
    if palettes is not None:
        for pal in palettes:
            for n in pal:
                if n not in seen:
                    seen[n] = len(merged)
                    merged.append(n)
        if len(merged) > _PALETTE_MAX:
            # A u8 cannot address it. Never observed (Beowulf, the widest
            # shipped rig here, merges to ~100), but fail loudly rather than
            # wrap around silently if a future asset gets there.
            raise NotReversedError(
                "oCGeometry",
                f"template's merged bone palette has {len(merged)} entries; "
                f"a skinning index is a u8, so {_PALETTE_MAX} is the ceiling",
            )

    positions: list = []
    normals: list = []
    records: dict[str, list[bytes]] = {}
    for k, sub in enumerate(old_subs):
        c = len(sub.positions)
        layers = by_count.get(c)
        if not layers:
            return None
        positions.extend(sub.positions)
        normals.extend(sub.normals)
        for name, payload in layers.items():
            _hdr, blocks = _layer_blocks(payload)
            # Concatenate each block's records side by side per vertex.
            for bi, (_stride, recs) in enumerate(blocks):
                if name == "skinning" and palettes is not None:
                    pal = palettes[k]
                    recs = [_reindex_skin(r, pal, seen) for r in recs]
                records.setdefault(f"{name}#{bi}", []).extend(recs)
    if not positions:
        return None
    return {"positions": positions, "normals": normals, "records": records,
            "palette": merged if palettes is not None else None}


def _reindex_skin(rec: bytes, pal: list[str], into: dict[str, int]) -> bytes:
    """Re-address one skinning record from `pal` to the merged palette `into`.

    A zero-weight slot keeps index 0 rather than being resolved: the engine
    ignores it, and the shipped records already park unused slots there.
    """
    idx, weights = _decode_skin(rec)
    out = []
    for b, wt in zip(idx, weights, strict=True):
        if wt <= 0.0 or b >= len(pal):
            out.append(0)
        else:
            out.append(into[pal[b]])
    return _encode_skin(out, weights)


# One skinning record = 4 bone indices (u8) + 4 weights (f32), summing to 1.
_SKIN_K = 6  # source vertices blended per custom vertex


def _decode_skin(rec: bytes) -> tuple[tuple[int, ...], tuple[float, ...]]:
    return struct.unpack_from("<4B", rec, 0), struct.unpack_from("<4f", rec, 4)


def _encode_skin(idx, weights) -> bytes:
    return (struct.pack("<4B", *(int(i) & 0xFF for i in idx))
            + struct.pack("<4f", *weights))


def _blend_skin(records: list[bytes], sq_dists: list[float],
                mults: list[float] | None = None) -> bytes:
    """Blend several skinning records into one, weighting each source by
    `mult / (dist + eps)`.

    Copying a single nearest neighbour gives noisy per-vertex bindings that
    tear the mesh in motion; blending the k nearest smooths the weights so
    adjacent vertices move together. `mults` (e.g. surface-normal agreement)
    lets a custom vertex prefer source verts on the same side of the body,
    so a face vertex doesn't borrow back-of-head bones.
    """
    if mults is None:
        mults = [1.0] * len(records)
    acc: dict[int, float] = {}
    for rec, d, m in zip(records, sq_dists, mults, strict=True):
        idx, weights = _decode_skin(rec)
        iw = m / (d + 1e-9)
        for b, wt in zip(idx, weights, strict=True):
            if wt > 0.0:
                acc[b] = acc.get(b, 0.0) + wt * iw
    if not acc:
        return records[0]
    top = sorted(acc.items(), key=lambda kv: kv[1], reverse=True)[:4]
    total = sum(w for _, w in top) or 1.0
    idx = [b for b, _ in top]
    weights = [w / total for _, w in top]
    while len(idx) < 4:
        idx.append(0)
        weights.append(0.0)
    return _encode_skin(idx, weights)


def _blend_skin_records(cust_normals: list, knn: list, src: dict
                        ) -> list[bytes] | None:
    """Precompute one blended skinning record per custom vertex, biasing the
    blend toward source verts whose normal agrees with the custom vertex's
    (reduces front/back bleed on faces, hats, etc.)."""
    srec = src["records"].get("skinning#0")
    snorm = src.get("normals")
    if srec is None:
        return None
    out: list[bytes] = []
    for j, nb in enumerate(knn):
        if not nb:
            out.append(srec[0])
            continue
        recs = [srec[i] for i, _ in nb]
        dists = [d for _, d in nb]
        if snorm:
            cn = cust_normals[j]
            mults = []
            for i, _ in nb:
                sn = snorm[i]
                dot = cn[0] * sn[0] + cn[1] * sn[1] + cn[2] * sn[2]
                # Floor keeps a vertex bound even if all neighbours disagree.
                mults.append(0.1 + 0.9 * max(0.0, dot))
        else:
            mults = None
        out.append(_blend_skin(recs, dists, mults))
    return out


def _rigid_skin(src: dict | None) -> bytes | None:
    """One skinning record, repeated for every vertex — a rigid bind.

    Which bone matters. The obvious choice, the template's vertex 0, is
    whatever the exporter happened to write first and is routinely a hand, a
    hair strand or a weapon attachment — binding a whole body to it makes the
    model orbit that limb. Instead take the record of the template vertex
    nearest the template's own centre, which on a humanoid is reliably a spine
    or pelvis bone: the model then follows the character's overall motion and
    ignores the limbs.

    The trade is explicit: no deformation at all. Arms and legs will not bend.
    That is the point — a rigid model that slides around intact is usable,
    where a mis-transferred one is shredded on the first animation frame.
    """
    if not src or not src["positions"]:
        return None
    skin_key = next((k for k in src["records"] if k.startswith("skinning#")), None)
    if skin_key is None:
        return None
    recs = src["records"][skin_key]
    pos = src["positions"]
    if not recs or len(recs) < len(pos):
        return None
    cx = sum(p[0] for p in pos) / len(pos)
    cy = sum(p[1] for p in pos) / len(pos)
    cz = sum(p[2] for p in pos) / len(pos)
    best = min(range(len(pos)),
               key=lambda i: ((pos[i][0] - cx) ** 2 + (pos[i][1] - cy) ** 2
                              + (pos[i][2] - cz) ** 2))
    # Collapse to the single strongest bone of that vertex, weight 1.0: a
    # blended record would still spread the model across several bones.
    idx, w = _decode_skin(recs[best])
    dominant = idx[max(range(4), key=lambda j: w[j])]
    return _encode_skin((dominant, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))


def _build_transfer(custom_pos: list, src: dict) -> list[list[tuple[int, float]]]:
    grid = _Grid(src["positions"])
    return [grid.k_nearest(p, _SKIN_K) for p in custom_pos]


#: Median gap (as a fraction of the template's bounding-box diagonal) past
#: which a skinned swap is assumed to be authored in the wrong pose. A mesh
#: modelled over the original sits ON its surface, so the typical nearest
#: source vertex is a couple of percent of the diagonal away; a donor standing
#: in its own pose puts whole limbs where the template has nothing, and the
#: figure jumps well past this. Deliberately loose: it must not cry wolf on a
#: legitimately chunkier silhouette.
_BIND_POSE_GAP = 0.08


def bind_pose_gap(knn: list[list[tuple[int, float]]], src: dict) -> float | None:
    """Median distance from a custom vertex to its nearest template vertex, as a
    fraction of the template's bounding-box diagonal.

    The number that says whether a skinned swap will animate or tear: weights
    are copied POSITIONALLY, so a mesh that does not occupy the same space as
    the one it replaces gets every vertex weighted to whatever bone happened to
    be nearest. Returns None when there is nothing to measure.
    """
    pts = src.get("positions") or []
    if not pts or not knn:
        return None
    lo = [min(p[a] for p in pts) for a in range(3)]
    hi = [max(p[a] for p in pts) for a in range(3)]
    diag = math.sqrt(sum((hi[a] - lo[a]) ** 2 for a in range(3)))
    if diag <= 0:
        return None
    nearest = sorted(math.sqrt(n[0][1]) for n in knn if n)
    if not nearest:
        return None
    mid = len(nearest) // 2
    median = (nearest[mid] if len(nearest) % 2
              else (nearest[mid - 1] + nearest[mid]) / 2)
    return median / diag


def _rebuild_layer(payload: bytes, count: int,
                   knn: list[list[tuple[int, float]]] | None,
                   src: dict | None, blended_skin: list[bytes] | None) -> bytes:
    """Rebuild one per-vertex side layer for whatever now occupies its record.

    The `skinning` layer takes `blended_skin` when there is one — the
    normal-aware proximity blend, the rigid single-bone record, or the .glb's
    own weights, all of which arrive here already indexed against the palette
    being written. Geometric layers (binormal/tangent) copy the single nearest
    source vertex, which is enough for shading. With no correspondence to
    transfer along (a degenerated record, or a layer the template has no
    source for) the template's own vertex-0 record is replicated, which is a
    uniform, valid binding rather than garbage.

    Every block of the skinning layer gets the SAME record, because that is
    the invariant the shipped meshes hold: measured on Aladdin, each of the
    two 20-byte blocks independently sums to weight 1.0 per vertex. So the
    blocks are not one 8-bone set to be split across (that would make vanilla
    vertices total 2.0); zeroing the second would invent a rule the data
    contradicts.
    """
    name = _layer_name(payload)
    header, blocks = _layer_blocks(payload)
    new_blocks: list[tuple[int, list[bytes]]] = []
    for bi, (stride, recs) in enumerate(blocks):
        if name == "skinning" and blended_skin is not None:
            new_blocks.append((stride, list(blended_skin)))
            continue
        srcrecs = src["records"].get(f"{name}#{bi}") if src else None
        if srcrecs is None or knn is None:
            new_blocks.append((stride, [recs[0]] * count))
        else:
            new_blocks.append(
                (stride, [srcrecs[nb[0][0]] if nb else srcrecs[0] for nb in knn]))
    return _assemble_layer(header, new_blocks)


def geometry_matches_cooked(glb_bytes: bytes, cooked_bytes: bytes) -> bool:
    """True if `glb_bytes`' renderable geometry equals the mesh in
    `cooked_bytes` (i.e. an `rsmm uncook` GLB that was NOT edited).

    Used to tell an untouched round-trip (-> passthrough the original bytes)
    from an edited reference mesh (-> swap the new geometry into it).
    """
    from . import cooked

    glb_pos = [p for sm in glb_to_submeshes(glb_bytes) for p in sm.positions]
    cf = cooked.parse(cooked_bytes)
    ck_pos = [p for s in cf.sections
              for r in _geo._parse_meshbuffers(s.payload) for p in r.positions]
    if len(glb_pos) != len(ck_pos):
        return False
    for a, b in zip(sorted(glb_pos), sorted(ck_pos), strict=True):
        if abs(a[0] - b[0]) > 1e-5 or abs(a[1] - b[1]) > 1e-5 \
                or abs(a[2] - b[2]) > 1e-5:
            return False
    return True


def template_from_uncooked_glb(uncooked_glb: bytes) -> bytes:
    """Pull the embedded original cooked bytes out of an `rsmm uncook` GLB."""
    from .unify import read_glb

    gltf, _ = read_glb(uncooked_glb)
    rsmm = (gltf.get("extras") or {}).get("rsmm") or {}
    blob = rsmm.get("cooked_b64")
    if not blob:
        raise ValueError("glb carries no rsmm.cooked_b64 template")
    import base64
    return base64.b64decode(blob)
