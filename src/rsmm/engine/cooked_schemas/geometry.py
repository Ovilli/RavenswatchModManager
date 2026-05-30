"""oCGeometry (v1.2) — container + bone-vector + side-channel decode.

Full decompile of `FUN_14064b0c0` (oCGeometry::Serialize),
`FUN_14065a7c0` (bone-vector reader), `FUN_1404ddd80`
(oCVec3VertexLayer::Serialize). Encode is intentionally *raw-payload
round-trip only*: the cooker-side quantization paths
(`FUN_1404c3440` 20B/vertex, `FUN_1404c3dc0` 18B/vertex) remain
unreversed, so re-cooking arbitrary glTF would lose byte stability.

Round-trip strategy
-------------------
`decode()` produces a viewer-loadable `.glb`:
- One TRIANGLES mesh per submesh with real POSITION / NORMAL /
  TEXCOORD_0 + index buffer, decoded from each oCMeshBuffer's
  default-buffer uncompressed stream (Stage 5c.i + 5b wired together by
  `_parse_meshbuffers`). This is the actual Blender-loadable mesh.
- One node per bone (4x4 transforms preserved as `node.matrix`)
- The side-channel vec3 layers (binormal / tangent) are NOT plotted as
  geometry when real submeshes exist — as unit vectors they render as a
  bogus "ball of dots". They are only emitted as a fallback POINTS
  preview for the rare files that carry no decodable submesh.
- AABB exposed as `extras.rsmm.aabb`
- `extras.rsmm.raw_payload_b64` carries the original section bytes
  concatenated so `encode()` can reproduce them byte-stably.

`encode()` extracts `raw_payload_b64` and returns those bytes. Any
glTF without that marker is refused — round-tripping arbitrary mesh
edits requires the cooker quantization pipelines.

Section layout (variant-B cooked container)
-------------------------------------------

```
sec[0]: aux header — 12 B
  u32 side_channel_count
  u32 version_a (always 7 in v1.2 corpus)
  u32 version_b (always 7 in v1.2 corpus)

sec[1..side_channel_count]: vertex-layer sections
  u32 schema_version (= 7)
  lstring layer_name        ("binormal", "tangent", "uv2", "tangentSign", ...)
  u8 comp_mode              (= 0 = uncompressed)
  u32 vertex_count
  u32 byte_count            (= vertex_count * stride)
  byte_count bytes          (vec3 f32 array — stride 12, OR vec2 f32
                            for "uv*", OR float for "*Sign")

sec[N]: main oCGeometry body
  u32 oIResource prelude    (= 0)
  u32 bone_count
  bone_count * {
    16 × f32 matrix         (64 B, row-major)
    lstring name_a
    lstring name_b
  }
  u32 submesh_count
  u8  has_skeleton          (per RE_NOTES correction)
  submesh_count × SubObject<oCMesh>
  if has_skeleton: SubObject<oCSkeleton>
  6 × f32 AABB              (xMin yMin zMin xMax yMax zMax)
  (v >= 2) trailing struct  (u32(0x01010000), u32(0x01010000), u8(1))
```
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field

from . import register
from .base import SchemaHandler

UID = 0x16b8
CURRENT_VERSION = (1, 2)

MARK_BEGIN = b"\x11\x11\xbb\xaa"
MARK_END = b"\x22\x22\xbb\xaa"


# Layer-name -> (stride_bytes, glTF-attribute-name).
# Side-channel sections in v1.2 corpus are always vec3 f32 streams
# (12 B/vertex) regardless of layer name — the engine sizes the
# blob from the FUN_1404ddd80 `count*0xc` line. UV layers use a
# different vertex-layer class which is not emitted as a top-level
# section in this corpus, so we don't decode them here.
_KNOWN_LAYERS = {
    "binormal": (12, "_BINORMAL"),
    "tangent": (12, "TANGENT"),  # glTF spec uses VEC4 for TANGENT; preview is vec3
    "tangentSign": (12, "_TANGENT_SIGN"),
    "uv2": (12, "TEXCOORD_1"),
}


@dataclass
class VertexLayer:
    """One side-channel vertex layer extracted from its own top-level section."""
    name: str
    vertex_count: int
    data: bytes                        # vertex_count * 12 bytes (vec3 f32)


@dataclass
class Bone:
    """One entry in the bone/instance vector."""
    matrix: tuple[float, ...]          # 16 floats (4x4 row-major)
    name_a: str
    name_b: str


@dataclass
class SubMesh:
    """Real triangle geometry pulled from an oCMeshBuffer default-buffer.

    Positions / normals / uvs are parallel arrays of length `vertex_count`;
    `indices` is a flat triangle-list (length = 3 * triangle_count).
    """
    positions: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    uvs: list[tuple[float, float]]
    indices: list[int]


@dataclass
class Geometry:
    """Parsed oCGeometry container — preserves all bytes for round-trip."""
    raw_payload: bytes                 # full concatenated section bytes
    bones: list[Bone] = field(default_factory=list)
    submesh_count: int = 0
    has_skeleton: bool = False
    aabb: tuple[float, float, float, float, float, float] = (0,) * 6
    layers: list[VertexLayer] = field(default_factory=list)
    submeshes: list[SubMesh] = field(default_factory=list)


def _read_lstring(buf: bytes, pos: int) -> tuple[str, int]:
    n = struct.unpack_from("<I", buf, pos)[0]
    s = buf[pos + 4:pos + 4 + n].decode("utf-8", errors="replace")
    return s, pos + 4 + n


def _parse_layer(payload: bytes) -> VertexLayer | None:
    """Parse a top-level side-channel section into a VertexLayer.

    Returns None if the payload doesn't look like a v7 uncompressed
    vec3 layer (which is the only top-level layer variant the corpus
    emits).
    """
    if len(payload) < 13:
        return None
    try:
        ver = struct.unpack_from("<I", payload, 0)[0]
        if ver != 7:
            return None
        name, pos = _read_lstring(payload, 4)
        comp_mode = payload[pos]
        pos += 1
        if comp_mode != 0:
            return None
        count, byte_count = struct.unpack_from("<II", payload, pos)
        pos += 8
        if byte_count != count * 12:
            return None
        if pos + byte_count != len(payload):
            return None
        return VertexLayer(name=name, vertex_count=count, data=payload[pos:pos + byte_count])
    except (struct.error, IndexError):
        return None


_TRAILING_STRUCT = struct.pack("<IIB", 0x01010000, 0x01010000, 1)
_AABB_BYTES = 24
_TAIL_BYTES = _AABB_BYTES + len(_TRAILING_STRUCT)


def _parse_main_body(payload: bytes) -> tuple[list[Bone], int, bool, tuple, int]:
    """Parse the main oCGeometry body section.

    Returns (bones, submesh_count, has_skeleton, aabb, consumed_through_aabb).
    Submesh sub-object bodies are not walked via BEGIN/END markers
    (float vertex data triggers false matches on big meshes) — instead
    we deterministically compute the AABB position by subtracting the
    known fixed-size tail from the end of the section payload.
    """
    pos = 0
    if len(payload) < 9 + _TAIL_BYTES:
        raise ValueError(f"oCGeometry body too small ({len(payload)} B)")
    res_prelude = struct.unpack_from("<I", payload, pos)[0]
    pos += 4
    bone_count = struct.unpack_from("<I", payload, pos)[0]
    pos += 4
    if bone_count > 100_000:
        raise ValueError(f"implausible bone_count {bone_count}")

    bones: list[Bone] = []
    for _ in range(bone_count):
        if pos + 64 > len(payload):
            raise ValueError("truncated at bone matrix")
        matrix = struct.unpack_from("<16f", payload, pos)
        pos += 64
        name_a, pos = _read_lstring(payload, pos)
        name_b, pos = _read_lstring(payload, pos)
        bones.append(Bone(matrix=matrix, name_a=name_a, name_b=name_b))

    submesh_count = struct.unpack_from("<I", payload, pos)[0]
    pos += 4
    has_skeleton = bool(payload[pos])
    pos += 1

    # AABB lives `_TAIL_BYTES` from the end of the payload (trailing v>=2
    # struct comes after). Submesh + optional skeleton sub-objects fill
    # everything between `pos` and the AABB start.
    aabb_off = len(payload) - _TAIL_BYTES
    if aabb_off < pos:
        raise ValueError("truncated at AABB (no room between header and tail)")
    aabb = struct.unpack_from("<6f", payload, aabb_off)

    # Sanity-check trailing struct matches the corpus invariant.
    trailing = payload[aabb_off + _AABB_BYTES:]
    if trailing != _TRAILING_STRUCT:
        # Soft warning: still round-trippable via raw_payload, just flag.
        pass

    return bones, submesh_count, has_skeleton, aabb, len(payload)


def _skip_subobject(buf: bytes, pos: int) -> int:
    """Advance past one BEGIN..END bracketed sub-object. Stride-4 scan."""
    assert buf[pos:pos + 4] == MARK_BEGIN
    pos += 4
    depth = 1
    n = len(buf)
    while pos + 4 <= n:
        tag = buf[pos:pos + 4]
        if tag == MARK_BEGIN:
            depth += 1
            pos += 4
            continue
        if tag == MARK_END:
            depth -= 1
            pos += 4
            if depth == 0:
                return pos
            continue
        pos += 1
    raise ValueError("unterminated sub-object")


# oCMeshBuffer default-buffer / uncompressed vertex stride (Stage 5c.i, SOLVED).
# 48 B = position(12) + normal(12) + uv0(8) + tangent(12) + handedness(4).
_VERTEX_STRIDE = 48
# Signature scanned to locate each submesh's inner oSTriangleMesh record:
# `FUN_1404cb570` writes its schema version (currently 7) right after the
# oCMeshBuffer res-prelude (u32) + unique_flag (u8). Across the full shipped
# corpus every default-buffer mesh is unique_flag==0 / comp_mode==0, so the
# uncompressed path is the only one we decode here.
_TRIMESH_VER = struct.pack("<I", 7)


def _parse_meshbuffers(main: bytes) -> list[SubMesh]:
    """Extract real triangle geometry from every oCMeshBuffer in the main body.

    Walks the section scanning for the `FUN_1404cb570` ver==7 signature, then
    parses each record structurally (index oCTVector blob, then the uncompressed
    48-byte-stride vertex blob). Because every blob length is read from its own
    on-disk size prefix, the parser consumes exactly the right span and never
    has to depth-scan BEGIN/END markers through the float vertex data (where
    false `0xAABBxxxx` matches would otherwise derail it).

    Only the default-buffer (`unique_flag==0`) uncompressed (`comp_mode==0`)
    path is handled — the only one present in the shipped corpus. Quantized
    paths (`FUN_1404c3440` / `FUN_1404c3dc0`) are skipped silently.
    """
    out: list[SubMesh] = []
    n = len(main)
    i = 0
    while True:
        j = main.find(_TRIMESH_VER, i)
        if j == -1:
            break
        i = j + 4
        pos = j - 5  # res(u32) + unique_flag(u8) precede the ver field
        if pos < 0:
            continue
        try:
            unique_flag = main[pos + 4]
            comp_mode = main[pos + 9]
        except IndexError:
            continue
        if unique_flag not in (0, 1) or comp_mode != 0:
            continue
        p = pos + 10
        try:
            # u32 vertex_count (informational; the vertex blob carries its own)
            p += 4
            # Index oCTVector blob: u32 elem_count, u32 byte_size, then bytes.
            _ielem, ibytes = struct.unpack_from("<II", main, p)
            p += 8
            if ibytes % 4 or ibytes > n or p + ibytes > n:
                continue
            n_idx = ibytes // 4
            indices = list(struct.unpack_from(f"<{n_idx}I", main, p))
            p += ibytes
            # Vertex sub-record: u8 flag, u32 count, u32 byte_size, then bytes.
            p += 1  # flag
            vcount, vbytes = struct.unpack_from("<II", main, p)
            p += 8
            if vcount == 0 or vbytes % vcount or vbytes // vcount != _VERTEX_STRIDE:
                continue
            if p + vbytes > n:
                continue
            if indices and max(indices) >= vcount:
                continue
            positions: list[tuple[float, float, float]] = []
            normals: list[tuple[float, float, float]] = []
            uvs: list[tuple[float, float]] = []
            for k in range(vcount):
                o = p + k * _VERTEX_STRIDE
                positions.append(struct.unpack_from("<3f", main, o))
                normals.append(struct.unpack_from("<3f", main, o + 12))
                uvs.append(struct.unpack_from("<2f", main, o + 24))
            out.append(SubMesh(positions=positions, normals=normals,
                               uvs=uvs, indices=indices))
            i = p + vbytes
        except (struct.error, IndexError):
            continue
    return out


def parse_payload(raw_payload: bytes, section_lengths: list[int]) -> Geometry:
    """Parse the concatenated section bytes.

    Caller supplies `section_lengths` because the cooked container has
    already split the bytes — we re-walk the boundaries here to find
    the aux header + side-channel sections + main body.
    """
    g = Geometry(raw_payload=raw_payload)
    if not section_lengths:
        return g

    # Slice by section boundaries.
    sections: list[bytes] = []
    offset = 0
    for sl in section_lengths:
        sections.append(raw_payload[offset:offset + sl])
        offset += sl

    # The shipped corpus has two patterns:
    #   A) 2 sections: [oIResource (4 B), main body] — tiny meshes with no
    #      side channels.
    #   B) 4+ sections: [aux header, layer*, main body] — full meshes.
    if len(sections) <= 2:
        main = sections[-1]
        bones, submesh_count, has_skel, aabb, _ = _parse_main_body(main)
        g.bones = bones
        g.submesh_count = submesh_count
        g.has_skeleton = has_skel
        g.aabb = aabb
        g.submeshes = _parse_meshbuffers(main)
        return g

    # Pattern B: aux header at [0], layers in [1..n-2], main body at [n-1].
    for sec in sections[1:-1]:
        layer = _parse_layer(sec)
        if layer is not None:
            g.layers.append(layer)

    main = sections[-1]
    bones, submesh_count, has_skel, aabb, _ = _parse_main_body(main)
    g.bones = bones
    g.submesh_count = submesh_count
    g.has_skeleton = has_skel
    g.aabb = aabb
    g.submeshes = _parse_meshbuffers(main)
    return g


def _build_glb_preview(g: Geometry) -> bytes:
    """Emit a viewer-loadable .glb with bone nodes + side-channel layers."""
    bin_buf = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []
    scene_roots: list[int] = []

    def push_view(data: bytes, target: int | None = None) -> int:
        pad = (-len(bin_buf)) % 4
        bin_buf.extend(b"\0" * pad)
        offset = len(bin_buf)
        bin_buf.extend(data)
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    def push_vec3(values: list[tuple[float, float, float]]) -> int:
        flat = [c for v in values for c in v]
        data = struct.pack(f"<{len(flat)}f", *flat)
        view = push_view(data, 34962)  # ARRAY_BUFFER
        accessor: dict = {
            "bufferView": view, "componentType": 5126,
            "count": len(values), "type": "VEC3",
        }
        if values:
            accessor["min"] = [min(p[i] for p in values) for i in range(3)]
            accessor["max"] = [max(p[i] for p in values) for i in range(3)]
        accessors.append(accessor)
        return len(accessors) - 1

    def push_vec2(values: list[tuple[float, float]]) -> int:
        flat = [c for v in values for c in v]
        data = struct.pack(f"<{len(flat)}f", *flat)
        view = push_view(data, 34962)  # ARRAY_BUFFER
        accessors.append({
            "bufferView": view, "componentType": 5126,
            "count": len(values), "type": "VEC2",
        })
        return len(accessors) - 1

    def push_indices(values: list[int]) -> int:
        max_i = max(values) if values else 0
        if max_i < 65535:
            data = struct.pack(f"<{len(values)}H", *values)
            ctype = 5123  # UNSIGNED_SHORT
        else:
            data = struct.pack(f"<{len(values)}I", *values)
            ctype = 5125  # UNSIGNED_INT
        view = push_view(data, 34963)  # ELEMENT_ARRAY_BUFFER
        accessors.append({
            "bufferView": view, "componentType": ctype,
            "count": len(values), "type": "SCALAR",
        })
        return len(accessors) - 1

    # Real triangle geometry decoded from each oCMeshBuffer. This is the
    # actual viewable/editable mesh — POSITION + NORMAL + TEXCOORD_0 + indices.
    materials: list[dict] = []
    if g.submeshes:
        materials.append({
            "name": "rsmm_default",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.8, 0.8, 0.8, 1.0],
                "metallicFactor": 0.0, "roughnessFactor": 1.0,
            },
            "doubleSided": True,
        })
    for si, sm in enumerate(g.submeshes):
        if not sm.positions:
            continue
        attrs = {"POSITION": push_vec3(sm.positions)}
        if sm.normals:
            attrs["NORMAL"] = push_vec3(sm.normals)
        if sm.uvs:
            attrs["TEXCOORD_0"] = push_vec2(sm.uvs)
        prim: dict = {"attributes": attrs, "mode": 4}  # TRIANGLES
        if sm.indices:
            prim["indices"] = push_indices(sm.indices)
        if materials:
            prim["material"] = 0
        meshes.append({"name": f"submesh_{si}", "primitives": [prim]})
        nodes.append({"name": f"submesh_{si}", "mesh": len(meshes) - 1})
        scene_roots.append(len(nodes) - 1)

    # AABB → wireframe box mesh as a visual scene marker.
    if any(g.aabb):
        x0, y0, z0, x1, y1, z1 = g.aabb
        if all(abs(c) < 1e30 for c in g.aabb):
            corners = [
                (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
            ]
            pos_acc = push_vec3(corners)
            # 12 edges -> 24 indices.
            edges = [0,1,1,2,2,3,3,0, 4,5,5,6,6,7,7,4, 0,4,1,5,2,6,3,7]
            idx_data = struct.pack(f"<{len(edges)}H", *edges)
            idx_view = push_view(idx_data, 34963)  # ELEMENT_ARRAY_BUFFER
            accessors.append({
                "bufferView": idx_view, "componentType": 5123,
                "count": len(edges), "type": "SCALAR",
            })
            idx_acc = len(accessors) - 1
            meshes.append({
                "name": "aabb",
                "primitives": [{
                    "attributes": {"POSITION": pos_acc},
                    "indices": idx_acc,
                    "mode": 1,  # LINES
                }],
            })
            nodes.append({"name": "AABB", "mesh": len(meshes) - 1})
            scene_roots.append(len(nodes) - 1)

    # Bone nodes (transform-only).
    for b in g.bones:
        nodes.append({"name": b.name_a or "bone", "matrix": list(b.matrix)})
        scene_roots.append(len(nodes) - 1)

    # Side-channel layers → one preview mesh per layer, exposing the vec3
    # data as POSITION for visual inspection. Not anatomically correct
    # (a binormal stream is not a position stream) — they are unit vectors,
    # so plotted as points they form a "ball of dots". Only emitted as a
    # last-resort preview when no real submesh geometry was decoded;
    # otherwise they would clutter the actual mesh with a bogus point cloud.
    for layer in (g.layers if not g.submeshes else []):
        n = layer.vertex_count
        if n == 0:
            continue
        floats = struct.unpack_from(f"<{n*3}f", layer.data, 0)
        verts = [(floats[i*3], floats[i*3+1], floats[i*3+2]) for i in range(n)]
        pos_acc = push_vec3(verts)
        meshes.append({
            "name": f"layer_{layer.name}",
            "primitives": [{
                "attributes": {"POSITION": pos_acc},
                "mode": 0,  # POINTS — explicit "this is preview, not a mesh"
            }],
        })
        nodes.append({"name": f"layer_{layer.name}", "mesh": len(meshes) - 1})
        scene_roots.append(len(nodes) - 1)

    extras = {
        "rsmm": {
            "schema_version": 1,
            "class": "oCGeometry",
            "uid": UID,
            "cooked_version": list(CURRENT_VERSION),
            "raw_payload_b64": base64.b64encode(g.raw_payload).decode("ascii"),
            "decoded": {
                "bone_count": len(g.bones),
                "submesh_count": g.submesh_count,
                "has_skeleton": g.has_skeleton,
                "aabb": list(g.aabb),
                "layers": [
                    {"name": l.name, "vertex_count": l.vertex_count}
                    for l in g.layers
                ],
                "submeshes": [
                    {"vertex_count": len(sm.positions),
                     "triangle_count": len(sm.indices) // 3}
                    for sm in g.submeshes
                ],
            },
        },
    }

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "rsmm oCGeometry extractor"},
        "extras": extras,
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": meshes,
        "nodes": nodes,
        "scenes": [{"nodes": scene_roots or list(range(len(nodes)))}],
        "scene": 0,
    }
    if materials:
        gltf["materials"] = materials

    bin_pad = (-len(bin_buf)) % 4
    bin_payload = bytes(bin_buf) + b"\0" * bin_pad
    if bin_payload:
        gltf["buffers"] = [{"byteLength": len(bin_payload)}]

    for k in ("bufferViews", "accessors", "meshes", "nodes", "buffers"):
        if k in gltf and not gltf[k]:
            del gltf[k]

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (-len(json_bytes)) % 4
    json_bytes += b" " * json_pad

    total = 12 + 8 + len(json_bytes) + (8 + len(bin_payload) if bin_payload else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)
    out += json_bytes
    if bin_payload:
        out += struct.pack("<II", len(bin_payload), 0x004E4942)
        out += bin_payload
    return bytes(out)


def _extract_raw_payload_from_glb(glb_bytes: bytes) -> bytes:
    """Pull `extras.rsmm.raw_payload_b64` out of a .glb produced by
    `_build_glb_preview`. Refuses glb authored from anything else —
    re-cooking arbitrary glTF requires the encoder quantization paths
    (`FUN_1404c3440` / `FUN_1404c3dc0`), which are not yet reversed.
    """
    if len(glb_bytes) < 20 or glb_bytes[:4] != b"glTF":
        raise ValueError("not a glTF binary container (missing 'glTF' magic)")
    version = struct.unpack_from("<I", glb_bytes, 4)[0]
    if version != 2:
        raise ValueError(f"glTF version {version} not supported (need 2)")

    pos = 12
    chunk_len = struct.unpack_from("<I", glb_bytes, pos)[0]
    chunk_type = glb_bytes[pos + 4:pos + 8]
    if chunk_type != b"JSON":
        raise ValueError(f"first chunk is not JSON, got {chunk_type!r}")
    json_bytes = glb_bytes[pos + 8:pos + 8 + chunk_len]
    try:
        doc = json.loads(json_bytes.rstrip(b" "))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid glTF JSON: {e}") from e

    extras = doc.get("extras") or {}
    rsmm = extras.get("rsmm") or {}
    blob_b64 = rsmm.get("raw_payload_b64")
    if not blob_b64:
        raise ValueError(
            "glb has no rsmm.raw_payload_b64 — cooked mesh re-encode from "
            "arbitrary glTF is blocked on the cooker quantization paths "
            "(FUN_1404c3440 / FUN_1404c3dc0) not yet being reversed. "
            "Re-extract via `rsmm uncook` to embed the original cooked bytes."
        )
    return base64.b64decode(blob_b64)


def decode_cooked_to_glb(cooked_bytes: bytes) -> bytes:
    """Take a full cooked-file byte string and emit a viewer-loadable
    .glb that round-trips back to the same cooked bytes.

    Stashes the original cooked container (not just the section
    payloads) in `extras.rsmm.cooked_b64` so `encode_container` can
    return the original bytes directly — bypassing the multi-section
    class-table rebuild that an mesh authoring pipeline would otherwise
    need to handle (and which is blocked on the cooker quantization
    paths).
    """
    from .. import cooked

    cf = cooked.parse(cooked_bytes)
    raw = b"".join(s.payload for s in cf.sections)
    sec_lens = [len(s.payload) for s in cf.sections]
    g = parse_payload(raw, sec_lens)
    return _build_glb_preview_with_cooked(g, cooked_bytes)


def _build_glb_preview_with_cooked(g: Geometry, cooked_bytes: bytes) -> bytes:
    """Inject the full cooked-file bytes into the GLB extras before emit."""
    glb = _build_glb_preview(g)

    # Patch the JSON chunk to add `extras.rsmm.cooked_b64`. Cheapest way
    # is to re-decode the JSON, mutate, and re-emit. The bin chunk and
    # global byte offsets are unaffected so we only need to rewrite the
    # header total length + JSON chunk length.
    import json as _json
    json_len = struct.unpack_from("<I", glb, 12)[0]
    json_off = 20
    bin_block = glb[json_off + json_len:]
    doc = _json.loads(glb[json_off:json_off + json_len].rstrip(b" "))
    doc.setdefault("extras", {}).setdefault("rsmm", {})["cooked_b64"] = \
        base64.b64encode(cooked_bytes).decode("ascii")
    new_json = _json.dumps(doc, separators=(",", ":")).encode("utf-8")
    pad = (-len(new_json)) % 4
    new_json += b" " * pad

    total = 12 + 8 + len(new_json) + len(bin_block)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(new_json), 0x4E4F534A)
    out += new_json
    out += bin_block
    return bytes(out)


def _extract_cooked_from_glb(glb_bytes: bytes) -> bytes:
    """Pull the full cooked container bytes back out of a .glb.

    Falls back to raising a helpful error if the marker is missing —
    same policy as `_extract_raw_payload_from_glb`.
    """
    if len(glb_bytes) < 20 or glb_bytes[:4] != b"glTF":
        raise ValueError("not a glTF binary container")
    json_len = struct.unpack_from("<I", glb_bytes, 12)[0]
    doc = json.loads(glb_bytes[20:20 + json_len].rstrip(b" "))
    rsmm = (doc.get("extras") or {}).get("rsmm") or {}
    blob = rsmm.get("cooked_b64")
    if not blob:
        raise ValueError(
            "glb has no rsmm.cooked_b64 — cooked mesh re-encode from "
            "arbitrary glTF is blocked on the cooker quantization paths "
            "(FUN_1404c3440 / FUN_1404c3dc0) not yet being reversed. "
            "Re-extract via `rsmm uncook` to embed the original cooked "
            "bytes."
        )
    return base64.b64decode(blob)


class GeometryHandler(SchemaHandler):
    """oCGeometry handler. Section-payload-level decode is partial: full
    structure parsed, but per-submesh vertex extraction defers to the
    embedded raw payload for round-trip.

    The handler supports two flavours:
      - `decode(payload)`         section-payload-level (used by the
                                  generic dispatcher)
      - `decode_cooked(bytes)`    full cooked-file level (used by the
                                  CLI `rsmm uncook` so encode_container
                                  can later return the original bytes
                                  exactly)
    """

    def __init__(self) -> None:
        super().__init__(
            class_name="oCGeometry",
            source_ext="glb",
            decoded=True,
            encoded=True,
        )

    def decode(self, payload: bytes) -> bytes:
        # Section-payload entry point — we don't know the section
        # boundaries from the blob alone, so produce a raw-payload-only
        # GLB. Callers that want full structure + cooked-bytes round-
        # trip should use `decode_cooked`.
        g = Geometry(raw_payload=payload)
        return _build_glb_preview(g)

    def decode_cooked(self, cooked_bytes: bytes) -> bytes:
        return decode_cooked_to_glb(cooked_bytes)

    def encode(self, source: bytes) -> bytes:
        return _extract_raw_payload_from_glb(source)

    def encode_container(self, source: bytes) -> bytes:
        return _extract_cooked_from_glb(source)


register(GeometryHandler())
