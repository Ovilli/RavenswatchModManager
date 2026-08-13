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
ENCODER_VERSION = 9

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


def glb_to_submeshes(glb_bytes: bytes) -> list[_geo.SubMesh]:
    """Decode every triangle primitive in a .glb into SubMesh records.

    Node transforms (translation/rotation/scale, including parent chains) are
    baked into the vertex positions, so a prop placed via its node — e.g. a
    cube parented onto the head with its own offset+scale — lands where the
    modeller put it instead of at the raw-accessor origin.
    """
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
    # Iterate nodes (not meshes) so each instance carries its own transform.
    for ni, node in enumerate(nodes):
        mi = node.get("mesh")
        if mi is None:
            continue
        m = world.get(ni, _mat_identity())
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
            positions = [_mat_apply_point(m, p) for p in positions]
            normals = [_mat_apply_normal(m, nrm) for nrm in normals]
            out.append(_geo.SubMesh(positions=positions, normals=normals,
                                    uvs=uvs, indices=indices))
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


def _swap_section(main: bytes, merged: _geo.SubMesh) -> bytes:
    """Rewrite a section's meshbuffer blobs with the `merged` custom mesh.

    The first record gets the combined custom geometry; any extra template
    records are degenerated (empty) so the old mesh doesn't show through.
    """
    recs = _find_records(main)
    if not recs:
        raise ValueError("template section has no default-buffer meshbuffer")
    out = bytearray()
    cursor = 0
    for ri, (mut_start, end, flag) in enumerate(recs):
        out += main[cursor:mut_start]
        out += _encode_record(merged if ri == 0 else _DEGENERATE, flag)
        cursor = end
    out += main[cursor:]
    return bytes(out)


# --- per-vertex side layers (binormal / tangent / skinning) -------------
#
# Each submesh ships parallel per-vertex layers sized to ITS vertex count:
#   ver=9  comp=0  "binormal"/"tangent"  -> one 12 B/vertex vec3 block
#   ver=11 comp=0  "skinning"            -> two 20 B/vertex blocks
# The engine reads these by the meshbuffer's vertex count, so after a swap
# they MUST be resized to the new count or every vertex gets garbage bone
# weights and the mesh explodes. We rebuild each block by replicating the
# template's vertex-0 record — a uniform, valid binding (whole submesh
# rigidly follows one bone: no deformation, but no glitch).

_LAYER_VERS = (9, 11)


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


def _rewrite_layer(payload: bytes, new_count: int) -> bytes:
    """Resize a per-vertex layer to `new_count`, replicating vertex 0."""
    pos = 8 + struct.unpack_from("<I", payload, 4)[0] + 1  # past ver+name+comp
    out = bytearray(payload[:pos])
    n = len(payload)
    while pos < n:
        count, bc = struct.unpack_from("<II", payload, pos)
        pos += 8
        stride = bc // count
        template = payload[pos:pos + stride]  # vertex-0 record
        pos += bc
        out += struct.pack("<II", new_count, stride * new_count)
        out += template * new_count
    return bytes(out)


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


def _auto_upright_euler(custom: list) -> tuple[float, float, float]:
    """Best-effort guess: rotate the tallest mesh axis to the game up-axis (Y).

    A pure rigid rotation, so it never distorts — only the *direction* may be
    wrong (upside down / facing away), which the modeller corrects with an
    explicit `rotate_deg`.
    """
    _mn, _mx, ext = _extents(custom)
    up = ext.index(max(ext))
    if up == 1:          # already Y-up
        return (0.0, 0.0, 0.0)
    if up == 2:          # Z-up -> bring Z to Y
        return (-90.0, 0.0, 0.0)
    return (0.0, 0.0, 90.0)  # X-up -> bring X to Y


def _fit_transform(custom: list, template: list,
                   euler_deg: tuple[float, float, float],
                   scale_mult: float = 1.0, fit: str = "height"):
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
    tmn, tmx, te = _extents(template)
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
        scale = (te[up] / re[up] if re[up] else 1.0) * scale_mult
    else:
        raise ValueError(f"transform.fit must be 'height' or 'none', got {fit!r}")
    tc = [(tmn[i] + tmx[i]) / 2 for i in range(3)]

    def apply_pos(p):
        q = _apply_m(m, p)
        return tuple((q[i] - rmn[i]) * scale
                     + (tmn[i] if i == up else tc[i] - re[i] * scale * 0.5)
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
    Recentering is always automatic; scale stays uniform (never distorts).
    """
    from . import cooked

    submeshes = glb_to_submeshes(glb_bytes)
    if not submeshes:
        raise ValueError("glb has no indexed triangle mesh to cook")
    merged = _merge(submeshes)
    merged, repaired = sanitize(merged)
    if any(repaired.values()):
        _log.warning(
            "custom mesh needed repair before cooking: %d degenerate triangle(s) "
            "dropped, %d unusable normal(s) rebuilt. Every shipped mesh has "
            "neither; a zero-length normal makes the per-vertex tangent basis "
            "NaN. Fix this in the source .glb.",
            repaired["degenerate_tris"], repaired["bad_normals"])

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
    custom_vtx = len(merged.positions)
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

    # Gather the template's skinned vertices (position + per-vertex side-layer
    # records) so the custom mesh can borrow real bone weights by proximity.
    src = _gather_source(cf, target, old_subs)

    # Fit target: the template's skinned vertices when present, else the
    # template's own mesh-buffer positions. Either way the custom mesh MUST
    # be fit into the template's space — a rigid (non-skinned) template like
    # a weapon still needs it, or the raw GLB (commonly authored in metres,
    # ~100x the cooked cm scale) renders enormous.
    fit_target = (src["positions"] if src is not None and src["positions"]
                  else [p for s in old_subs for p in s.positions])

    if fit_target:
        if transform and "rotate_deg" in transform:
            euler = tuple(float(a) for a in transform["rotate_deg"])
        else:
            euler = _auto_upright_euler(merged.positions)
        scale_mult = float(transform["scale"]) if transform and "scale" in transform else 1.0
        fit = str(transform.get("fit", "height")) if transform else "height"
        apply_pos, apply_nrm = _fit_transform(
            merged.positions, fit_target, euler, scale_mult, fit)
        merged = _geo.SubMesh(
            positions=[apply_pos(p) for p in merged.positions],
            normals=[apply_nrm(n) for n in merged.normals],
            uvs=merged.uvs, indices=merged.indices)

    if src is not None and src["positions"]:
        nn = _build_transfer(merged.positions, src)
        blended_skin = _blend_skin_records(merged.normals, nn, src)
    else:
        nn = None
        blended_skin = None

    cf.sections[target] = cooked.Section(
        payload=_swap_section(cf.sections[target].payload, merged))

    new_counts = [len(merged.positions), *([1] * (len(old_counts) - 1))]
    count_map: dict[int, int] = {}
    for old, new in zip(old_counts, new_counts, strict=True):
        count_map.setdefault(old, new)
    main_count = old_counts[0] if old_counts else None

    for si, sec in enumerate(cf.sections):
        if si == target:
            continue
        vc = _layer_vertex_count(sec.payload)
        if vc is None or vc not in count_map:
            continue
        if nn is not None and vc == main_count:
            # The swapped submesh's layers get transferred per-vertex records.
            cf.sections[si] = cooked.Section(
                payload=_transfer_layer(sec.payload, nn, src, blended_skin))
        else:
            cf.sections[si] = cooked.Section(
                payload=_rewrite_layer(sec.payload, count_map[vc]))

    _rewrite_aabb(cf, _bbox6(old_positions), _bbox6(merged.positions))
    return cooked.emit(cf)


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
    """
    if not old_bb or not new_bb:
        return
    packed_new = struct.pack("<6f", *new_bb)
    for si, sec in enumerate(cf.sections):
        payload = sec.payload
        for off in range(0, len(payload) - 24 + 1, 4):
            got = struct.unpack_from("<6f", payload, off)
            if all(abs(a - b) <= 1e-3 for a, b in zip(got, old_bb, strict=True)):
                cf.sections[si] = _sec_replace(sec, off, packed_new)
                return
    _log.warning(
        "template AABB not found (mesh bounds %s); the swapped mesh keeps the "
        "template's bounding box and may be culled if it is larger", old_bb)


def _sec_replace(sec, off: int, blob: bytes):
    from . import cooked

    buf = bytearray(sec.payload)
    buf[off:off + len(blob)] = blob
    return cooked.Section(payload=bytes(buf))


def _gather_source(cf, target: int, old_subs: list) -> dict | None:
    """Collect template skinned verts: positions + side-layer records, keyed
    by layer name, concatenated across every submesh (shared skeleton)."""
    by_count: dict[int, dict[str, bytes]] = {}
    for si, sec in enumerate(cf.sections):
        if si == target:
            continue
        vc = _layer_vertex_count(sec.payload)
        if vc is None:
            continue
        by_count.setdefault(vc, {})[_layer_name(sec.payload)] = sec.payload

    positions: list = []
    normals: list = []
    records: dict[str, list[bytes]] = {}
    for sub in old_subs:
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
                records.setdefault(f"{name}#{bi}", []).extend(recs)
    if not positions:
        return None
    return {"positions": positions, "normals": normals, "records": records}


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


def _build_transfer(custom_pos: list, src: dict) -> list[list[tuple[int, float]]]:
    grid = _Grid(src["positions"])
    return [grid.k_nearest(p, _SKIN_K) for p in custom_pos]


def _transfer_layer(payload: bytes, knn: list[list[tuple[int, float]]],
                    src: dict, blended_skin: list[bytes] | None) -> bytes:
    """Rebuild a layer for the swapped mesh from its source neighbours.

    The `skinning` layer uses the precomputed normal-aware blend
    (`blended_skin`); geometric layers (binormal/tangent) copy the single
    nearest source vertex, which is enough for shading.
    """
    name = _layer_name(payload)
    header, blocks = _layer_blocks(payload)
    new_blocks: list[tuple[int, list[bytes]]] = []
    for bi, (stride, _recs) in enumerate(blocks):
        srcrecs = src["records"].get(f"{name}#{bi}")
        if srcrecs is None:
            new_blocks.append((stride, [_recs[0]] * len(knn)))
        elif name == "skinning" and blended_skin is not None:
            new_blocks.append((stride, list(blended_skin)))
        else:
            recs = [srcrecs[nb[0][0]] if nb else srcrecs[0] for nb in knn]
            new_blocks.append((stride, recs))
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
