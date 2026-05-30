"""Minimal glTF 2.0 binary (.glb) writer.

Pure format encoder — no Ravenswatch schema knowledge. The oCGeometry /
oCMesh decoder calls into this module with parsed vertex/index arrays plus
optional bone hierarchy and emits a self-contained `.glb` file readable by
Blender, Maya, three.js, glTF Viewer, etc.

GLB layout (https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#binary-gltf-layout):

  u32 magic           = 0x46546C67  ("glTF")
  u32 version         = 2
  u32 length          = total file length
  --- JSON chunk ---
  u32 chunkLength
  u32 chunkType       = 0x4E4F534A  ("JSON")
  bytes utf8_json_padded_to_4
  --- BIN chunk (optional) ---
  u32 chunkLength
  u32 chunkType       = 0x004E4942  ("BIN\0")
  bytes binary_payload_padded_to_4

Single-buffer design: all vertex/index data lives in one BIN chunk; JSON
references it by byteOffset / byteLength. Enough for one mesh with multiple
primitives + skin. Multi-buffer GLB is not implemented (overkill for the
mod authoring path).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Literal

# Component types (https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#accessor-data-types)
COMPONENT_BYTE = 5120
COMPONENT_UBYTE = 5121
COMPONENT_SHORT = 5122
COMPONENT_USHORT = 5123
COMPONENT_UINT = 5125
COMPONENT_FLOAT = 5126

# Accessor types
TYPE_SCALAR = "SCALAR"
TYPE_VEC2 = "VEC2"
TYPE_VEC3 = "VEC3"
TYPE_VEC4 = "VEC4"
TYPE_MAT4 = "MAT4"

# Buffer view targets
TARGET_ARRAY_BUFFER = 34962        # vertex attributes
TARGET_ELEMENT_ARRAY = 34963       # indices

# Primitive topologies
TOPO_TRIANGLES = 4


@dataclass
class Primitive:
    """One drawcall within a mesh. Holds accessor indices, not raw data."""
    attributes: dict[str, int]                     # e.g. {"POSITION": 0, "NORMAL": 1}
    indices: int | None = None                     # accessor index for indices
    material: int | None = None                    # material index
    mode: int = TOPO_TRIANGLES


@dataclass
class Mesh:
    name: str
    primitives: list[Primitive]


@dataclass
class Node:
    """Scene-graph node. Either a mesh ref or a transform-only joint."""
    name: str
    mesh: int | None = None
    skin: int | None = None
    children: list[int] = field(default_factory=list)
    translation: tuple[float, float, float] | None = None
    rotation: tuple[float, float, float, float] | None = None  # quaternion x,y,z,w
    scale: tuple[float, float, float] | None = None
    matrix: list[float] | None = None              # 4x4 column-major


@dataclass
class Skin:
    name: str
    joints: list[int]                              # node indices
    inverse_bind_matrices: int                     # accessor index (Nx mat4)


class GlbBuilder:
    """Accumulator. Add accessors via add_*; call build_glb() when done."""

    def __init__(self) -> None:
        self._bin = bytearray()
        self._buffer_views: list[dict] = []
        self._accessors: list[dict] = []
        self._meshes: list[Mesh] = []
        self._nodes: list[Node] = []
        self._skins: list[Skin] = []
        self._materials: list[dict] = []
        self._images: list[dict] = []
        self._samplers: list[dict] = []
        self._textures: list[dict] = []
        self._scene_roots: list[int] = []

    # --- Binary payload helpers -----------------------------------------

    def _push_aligned(self, data: bytes, alignment: int = 4) -> int:
        pad = (-len(self._bin)) % alignment
        self._bin += b"\0" * pad
        offset = len(self._bin)
        self._bin += data
        return offset

    def _add_buffer_view(self, data: bytes, target: int | None,
                         byte_stride: int | None = None) -> int:
        offset = self._push_aligned(data)
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        if byte_stride is not None:
            view["byteStride"] = byte_stride
        idx = len(self._buffer_views)
        self._buffer_views.append(view)
        return idx

    # --- Accessor builders ----------------------------------------------

    def add_positions(self, positions: list[tuple[float, float, float]]) -> int:
        data = b"".join(struct.pack("<fff", *p) for p in positions)
        view = self._add_buffer_view(data, TARGET_ARRAY_BUFFER, 12)
        if positions:
            mins = [min(p[i] for p in positions) for i in range(3)]
            maxs = [max(p[i] for p in positions) for i in range(3)]
        else:
            mins = [0.0, 0.0, 0.0]
            maxs = [0.0, 0.0, 0.0]
        self._accessors.append({
            "bufferView": view,
            "componentType": COMPONENT_FLOAT,
            "count": len(positions),
            "type": TYPE_VEC3,
            "min": mins,
            "max": maxs,
        })
        return len(self._accessors) - 1

    def add_vec3(self, values: list[tuple[float, float, float]],
                 normalized: bool = False) -> int:
        data = b"".join(struct.pack("<fff", *v) for v in values)
        view = self._add_buffer_view(data, TARGET_ARRAY_BUFFER, 12)
        self._accessors.append({
            "bufferView": view,
            "componentType": COMPONENT_FLOAT,
            "count": len(values),
            "type": TYPE_VEC3,
            **({"normalized": True} if normalized else {}),
        })
        return len(self._accessors) - 1

    def add_vec2(self, values: list[tuple[float, float]]) -> int:
        data = b"".join(struct.pack("<ff", *v) for v in values)
        view = self._add_buffer_view(data, TARGET_ARRAY_BUFFER, 8)
        self._accessors.append({
            "bufferView": view,
            "componentType": COMPONENT_FLOAT,
            "count": len(values),
            "type": TYPE_VEC2,
        })
        return len(self._accessors) - 1

    def add_indices(self, indices: list[int]) -> int:
        # Choose u16 vs u32 based on max index.
        max_i = max(indices) if indices else 0
        if max_i < 65535:
            data = struct.pack(f"<{len(indices)}H", *indices)
            ctype = COMPONENT_USHORT
        else:
            data = struct.pack(f"<{len(indices)}I", *indices)
            ctype = COMPONENT_UINT
        view = self._add_buffer_view(data, TARGET_ELEMENT_ARRAY)
        self._accessors.append({
            "bufferView": view,
            "componentType": ctype,
            "count": len(indices),
            "type": TYPE_SCALAR,
        })
        return len(self._accessors) - 1

    def add_mat4_array(self, matrices: list[list[float]]) -> int:
        """Each matrix is 16 floats column-major."""
        data = b"".join(struct.pack("<16f", *m) for m in matrices)
        view = self._add_buffer_view(data, None)
        self._accessors.append({
            "bufferView": view,
            "componentType": COMPONENT_FLOAT,
            "count": len(matrices),
            "type": TYPE_MAT4,
        })
        return len(self._accessors) - 1

    # --- Scene structure -------------------------------------------------

    def add_mesh(self, mesh: Mesh) -> int:
        self._meshes.append(mesh)
        return len(self._meshes) - 1

    def add_node(self, node: Node, is_root: bool = False) -> int:
        self._nodes.append(node)
        idx = len(self._nodes) - 1
        if is_root:
            self._scene_roots.append(idx)
        return idx

    def add_skin(self, skin: Skin) -> int:
        self._skins.append(skin)
        return len(self._skins) - 1

    def add_texture_png(self, png_bytes: bytes) -> int:
        """Embed a PNG as a glTF texture; returns the texture index.

        Image bytes go in the BIN chunk via a bufferView (no external file);
        a default linear-wrap sampler is reused across all textures.
        """
        view = self._add_buffer_view(png_bytes, None)
        img_idx = len(self._images)
        self._images.append({"bufferView": view, "mimeType": "image/png"})
        if not self._samplers:
            # 10497 = REPEAT wrap; 9729 = LINEAR filter.
            self._samplers.append({"wrapS": 10497, "wrapT": 10497,
                                   "magFilter": 9729, "minFilter": 9729})
        tex_idx = len(self._textures)
        self._textures.append({"source": img_idx, "sampler": 0})
        return tex_idx

    def add_material(self, name: str,
                     base_color: tuple[float, float, float, float] = (1, 1, 1, 1),
                     base_color_texture: int | None = None,
                     double_sided: bool = False) -> int:
        pbr: dict = {
            "baseColorFactor": list(base_color),
            "metallicFactor": 0.0,
            "roughnessFactor": 1.0,
        }
        if base_color_texture is not None:
            pbr["baseColorTexture"] = {"index": base_color_texture}
        mat: dict = {"name": name, "pbrMetallicRoughness": pbr}
        if double_sided:
            mat["doubleSided"] = True
        self._materials.append(mat)
        return len(self._materials) - 1

    # --- Final emit ------------------------------------------------------

    def build_glb(self, copyright_str: str = "rsmm cooked extractor") -> bytes:
        # Pad bin chunk to 4-byte boundary.
        bin_pad = (-len(self._bin)) % 4
        bin_payload = bytes(self._bin) + b"\0" * bin_pad

        gltf: dict = {
            "asset": {"version": "2.0", "generator": copyright_str},
            "buffers": [{"byteLength": len(bin_payload)}] if bin_payload else [],
            "bufferViews": self._buffer_views,
            "accessors": self._accessors,
            "meshes": [
                {
                    "name": m.name,
                    "primitives": [
                        _primitive_to_dict(p) for p in m.primitives
                    ],
                }
                for m in self._meshes
            ],
            "nodes": [_node_to_dict(n) for n in self._nodes],
            "scenes": [{"nodes": self._scene_roots or list(range(len(self._nodes)))}],
            "scene": 0,
        }
        if self._skins:
            gltf["skins"] = [
                {
                    "name": s.name,
                    "joints": s.joints,
                    "inverseBindMatrices": s.inverse_bind_matrices,
                }
                for s in self._skins
            ]
        if self._materials:
            gltf["materials"] = self._materials
        if self._images:
            gltf["images"] = self._images
        if self._samplers:
            gltf["samplers"] = self._samplers
        if self._textures:
            gltf["textures"] = self._textures

        # Drop empty top-level arrays for cleanliness.
        for k in ("buffers", "bufferViews", "accessors", "meshes", "nodes",
                  "skins", "materials", "images", "samplers", "textures"):
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


def _node_to_dict(n: Node) -> dict:
    out: dict = {"name": n.name}
    if n.mesh is not None:
        out["mesh"] = n.mesh
    if n.skin is not None:
        out["skin"] = n.skin
    if n.children:
        out["children"] = n.children
    if n.matrix is not None:
        out["matrix"] = n.matrix
    else:
        if n.translation is not None:
            out["translation"] = list(n.translation)
        if n.rotation is not None:
            out["rotation"] = list(n.rotation)
        if n.scale is not None:
            out["scale"] = list(n.scale)
    return out


def _primitive_to_dict(p: Primitive) -> dict:
    out: dict = {"attributes": p.attributes, "mode": p.mode}
    if p.indices is not None:
        out["indices"] = p.indices
    if p.material is not None:
        out["material"] = p.material
    return out
