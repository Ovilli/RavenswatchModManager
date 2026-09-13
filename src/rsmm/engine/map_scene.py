"""What a chapter LOOKS like: placed entities resolved down to meshes and textures.

Read-only, for the map editor's renderer. Nothing here is shipped: every byte is
read from the user's own install (or the dev `data/uncooked` mirror) on request,
and the meshes and textures the page draws are the `data/uncooked` conversions
`scripts/extract_uncooked.py` makes locally (`*.fbx.glb`, `*.png`). Without that
mirror the editor still works; it just draws spots on bare terrain.

**Resource references.** Cooked entities, materials and levels name other
resources as two length-prefixed strings, ``u32 n, root, u32 m, path`` — the same
``<Root>|<Path>`` pair a `*.UsedRscCache.ot` line spells out. The roots that
matter here:

* ``3D``: a mesh (``Scenery\\DarkHills\\Rock_Medium_B.fbx``), then the materials
  it is drawn with (``...\\M_Rocks_Moss_Medium_Small_Atlas.mat.ot``), in order;
* ``EntitySettings``: another entity — a parent it inherits from, a child node
  (grass patches), or one alternative of an "Entity selector to spawn";
* ``Ot``: a composition level (``Prefab``), itself a list of placements.

**What an entity draws**, in the order tried: its own meshes; else the entities
of its prefab level, each at its placement; else its referenced entities — only
the first that draws anything when it is a random selector, all of them
otherwise. Depth-bounded and memoised.

**Known approximations** (visual only; nothing is written back):

* child-node LOCAL transforms inside an entity are not read, so a patch of three
  grass meshes draws them at the patch origin;
* a random selector always shows its first drawable alternative;
* LOD meshes are ignored (``_LOD1``) and one albedo texture per mesh is used;
* a decal (``DecalCube_1x1`` + a decal material) is drawn as its texture on a
  flat quad rather than projected onto what is under it;
* level-design helpers the game never shows are skipped: ``LD_Basic``
  primitives, ``LD_Terrain_Shapes`` (they stamp terrain height) and ``_anim_``
  copies of a mesh;
* ``Dt_Color_<Name>`` materials (the black silhouettes that frame a map) draw
  as their flat colour.

Coordinates stay in engine space (Y up; the page mirrors Z once for WebGL).
"""

from __future__ import annotations

import functools
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from . import level_placements as LP
from .paths import DATA_DIR

MAX_DEPTH = 5
#: Parts one entity may expand to. A composition of compositions can multiply
#: quickly; past this the rest is dropped rather than stalling the page.
MAX_PARTS = 4000
_MAX_ROOT = 32
_MAX_PATH = 300
_SELECTOR = b"Entity selector to spawn"
#: Albedo naming, best first. Anything else is a mask, normal or lookup texture.
_ALBEDO_HINTS = ("_alb", "_albedo", "_basecolor", "_base_color", "_diffuse", "_col", "_color", "_d")
#: Suffixes of the other maps a material samples.
_NOT_ALBEDO = ("_nrm", "_normal", "_mra", "_msk", "_mask", "_emi", "_rough", "_ao")
#: Engine placeholder textures (``Textures\\Black.png``), never an albedo.
_PLACEHOLDERS = ("black", "white", "grey", "gray")
_TPI_SENTINEL = bytes.fromhex("2222bbaa1111bbaa000000002222bbaa1111bbaa00000000")
_FMT_RGBA = 0

Matrix = tuple[float, ...]   # 16 floats, column-major, like glTF / WebGL
IDENTITY: Matrix = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


#: Mesh paths that are editor helpers, invisible in game.
_HELPER_MESHES = ("3D/LD_Basic/",)
_HELPER_ENTITIES = ("ld_terrain_shapes\\",)
_DECAL_MESH = "3D/DecalCube_1x1.fbx.glb"
#: Flat colours of the engine's ``Dt_Color_<Name>`` materials.
_FLAT_COLORS = {"black": "#0b0b0c", "white": "#eeeeee", "grey": "#808080", "gray": "#808080",
                "red": "#b03030", "green": "#3f7f3f", "blue": "#3a5fa0"}


@dataclass(frozen=True)
class Part:
    mesh: str                 # data/uncooked-relative glb path, "/"-separated
    texture: str | None       # data/uncooked-relative png path
    swap_rb: bool             # the png came from an uncompressed (R/B-swapped) texture
    color: str | None = None  # flat colour when the material has no texture
    decal: bool = False       # draw the texture on a flat quad, not the mesh


# --------------------------------------------------------------------------
# asset lookup
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _index() -> tuple[dict[str, str], frozenset[str]]:
    """``"root/path".lower()`` -> decoded key of the cooked file, plus the roots."""
    from .asset_map import decoded_to_encoded

    out: dict[str, str] = {}
    roots: set[str] = set()
    for dec in decoded_to_encoded():
        if not dec.endswith(".gen") or "/" not in dec:
            continue
        stem = dec[:-4]
        cut = stem.rfind(".")
        if cut <= 0:
            continue
        out.setdefault(stem[:cut].lower(), dec)
        roots.add(dec.split("/", 1)[0])
    return out, frozenset(roots)


def _decoded(root: str, path: str) -> str | None:
    return _index()[0].get(f"{root}/{path.replace(chr(92), '/')}".lower())


def _bytes(root: str, path: str) -> bytes | None:
    from .map_editor import _shipped

    dec = _decoded(root, path)
    return _shipped(dec) if dec else None


def resource_refs(data: bytes) -> list[tuple[str, str]]:
    """Every ``(root, path)`` pair in a cooked blob, in stream order."""
    roots = _index()[1]
    out: list[tuple[str, str]] = []
    i, end = 0, len(data) - 8
    while i < end:
        (n,) = struct.unpack_from("<I", data, i)
        if 0 < n <= _MAX_ROOT and i + 8 + n <= len(data):
            root = data[i + 4:i + 4 + n]
            if root.isascii() and root.decode("ascii", "replace") in roots:
                (m,) = struct.unpack_from("<I", data, i + 4 + n)
                j = i + 8 + n
                path = data[j:j + m]
                if 0 < m <= _MAX_PATH and len(path) == m and all(32 <= c < 127 for c in path):
                    out.append((root.decode("ascii"), path.decode("ascii")))
                    i = j + m
                    continue
        i += 1
    return out


def _uncooked(rel: str) -> Path | None:
    p = DATA_DIR / "uncooked" / Path(*rel.split("/"))
    return p if p.is_file() else None


# --------------------------------------------------------------------------
# materials and textures
# --------------------------------------------------------------------------

def _texture_uncompressed(tex_path: str) -> bool:
    """Is the cooked texture stored uncompressed? Its png copy is then R/B-swapped."""
    data = _bytes("3D", tex_path)
    if not data:
        return False
    s = data.find(_TPI_SENTINEL, 0, 4096)
    if s < 0 or s + len(_TPI_SENTINEL) + 16 > len(data):
        return False
    fmt = struct.unpack_from("<I", data, s + len(_TPI_SENTINEL) + 16)[0]
    return fmt == _FMT_RGBA


def material_color(mat_path: str) -> str | None:
    """The flat colour of a ``Dt_Color_<Name>`` material, else None."""
    stem = mat_path.rsplit("\\", 1)[-1].lower().removesuffix(".mat.ot").removesuffix("_skinned")
    if not stem.startswith("dt_color_"):
        return None
    return _FLAT_COLORS.get(stem.removeprefix("dt_color_"))


@functools.lru_cache(maxsize=4096)
def material_albedo(mat_path: str) -> tuple[str | None, bool]:
    """``(png path, swap_rb)`` of a material's albedo texture, when one is on disk."""
    data = _bytes("3D", mat_path)
    if not data:
        return None, False
    texs = [p for r, p in resource_refs(data)
            if r == "3D" and p.lower().endswith((".tga", ".png"))]

    def score(p: str) -> int:
        stem = p.rsplit("\\", 1)[-1].rsplit(".", 1)[0].lower()
        if stem in _PLACEHOLDERS or stem.endswith(_NOT_ALBEDO):
            return 99
        for i, h in enumerate(_ALBEDO_HINTS):
            if stem.endswith(h):
                return i
        return 50

    for p in sorted(texs, key=score):
        if score(p) == 99:
            break
        rel = "3D/" + p.replace("\\", "/").rsplit(".", 1)[0] + ".png"
        if _uncooked(rel):
            return rel, _texture_uncompressed(p)
    return None, False


# --------------------------------------------------------------------------
# transforms
# --------------------------------------------------------------------------

def trs(pos, quat, scale) -> Matrix:
    """Column-major matrix from translation, quaternion (x, y, z, w) and scale."""
    x, y, z, w = quat
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    sx, sy, sz = scale
    return (
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0.0,
        (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0.0,
        (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0.0,
        float(pos[0]), float(pos[1]), float(pos[2]), 1.0,
    )


def mul(a: Matrix, b: Matrix) -> Matrix:
    """``a * b`` for column-major 4x4 matrices."""
    return tuple(
        sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
        for c in range(4) for r in range(4)
    )


# --------------------------------------------------------------------------
# entities
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=8192)
def entity_parts(ref: str, depth: int = 0) -> tuple[tuple[Part, Matrix], ...]:
    """What entity `ref` (an ``EntitySettings`` path) draws, in its own space."""
    if depth > MAX_DEPTH or ref.lower().startswith(_HELPER_ENTITIES):
        return ()
    data = _bytes("EntitySettings", ref)
    if not data:
        return ()
    refs = resource_refs(data)

    own: list[tuple[Part, Matrix]] = []
    meshes = 0
    mesh: str | None = None
    tex: tuple[str | None, bool] = (None, False)
    color: str | None = None

    def flush():
        if not mesh:
            return
        decal = mesh == _DECAL_MESH
        if decal and not tex[0]:
            return                       # a decal with nothing to show
        own.append((Part(mesh, tex[0], tex[1], None if tex[0] else color, decal), IDENTITY))

    for root, path in refs:
        low = path.lower()
        if root == "3D" and low.endswith(".fbx"):
            flush()
            meshes += 1
            rel = "3D/" + path.replace("\\", "/") + ".glb"
            name = low.rsplit("\\", 1)[-1]
            skip = ("_lod" in name or "_anim_" in name or "\\animations\\" in low
                    or rel.startswith(_HELPER_MESHES))
            mesh = rel if not skip and _uncooked(rel) else None
            tex, color = (None, False), None
        elif root == "3D" and low.endswith(".mat.ot") and mesh and tex[0] is None:
            tex = material_albedo(path)
            color = color or material_color(path)
    flush()
    if own or meshes:
        return tuple(own)                # an entity with meshes of its own stops here

    for root, path in refs:
        if root == "Ot" and path.lower().endswith(".level.ot"):
            got = level_parts("Ot", path, depth + 1)
            if got:
                return got

    children = [p for r, p in refs if r == "EntitySettings" and p.lower() != ref.lower()]
    out: list[tuple[Part, Matrix]] = []
    for child in children:
        got = entity_parts(child, depth + 1)
        if not got:
            continue
        if _SELECTOR in data:
            return got
        out.extend(got)
        if len(out) >= MAX_PARTS:
            break
    return tuple(out[:MAX_PARTS])


@functools.lru_cache(maxsize=1024)
def level_parts(root: str, path: str, depth: int = 0) -> tuple[tuple[Part, Matrix], ...]:
    """Every part a level's placements draw, in the level's space."""
    data = _bytes(root, path)
    if not data:
        return ()
    return tuple(placed_parts(data, depth))


def placed_parts(level_bytes: bytes, depth: int = 0) -> list[tuple[Part, Matrix]]:
    try:
        placements = LP.decode(level_bytes)
    except LP.LevelPlacementError:
        return []
    out: list[tuple[Part, Matrix]] = []
    for pl in placements:
        m = trs(pl.pos, pl.quat, pl.scale)
        for part, local in entity_parts(pl.ref, depth):
            out.append((part, m if local is IDENTITY else mul(m, local)))
        if len(out) >= MAX_PARTS * 8:
            break
    return out


# --------------------------------------------------------------------------
# page payload
# --------------------------------------------------------------------------

def to_json(parts: list[tuple[Part, Matrix]]) -> dict:
    """Instances grouped per part: ``{"parts": [...], "matrices": [base64 f32]}``."""
    import array
    import base64
    import sys

    order: dict[Part, int] = {}
    mats: list[array.array] = []
    for part, m in parts:
        i = order.get(part)
        if i is None:
            i = order[part] = len(mats)
            mats.append(array.array("f"))
        mats[i].extend(m)
    if sys.byteorder != "little":
        for a in mats:
            a.byteswap()
    return {
        "parts": [{"mesh": p.mesh, "texture": p.texture, "swap_rb": p.swap_rb,
                   "color": p.color, "decal": p.decal} for p in order],
        "matrices": [base64.b64encode(a.tobytes()).decode("ascii") for a in mats],
        "instances": len(parts),
    }
