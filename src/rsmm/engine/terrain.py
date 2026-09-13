"""Read a chapter's painted terrain: the height field and the level-design masks.

Every tile-generated chapter ships a `Map_<Name>_Terrain.level` beside its
generation recipe. Its object graph holds one `oCTerrainGo` and a set of named
**painted input layers** the terrain generators sample — `Base Height`,
`LD Path`, `LD Block`, `Base Water Height`, a vertex-colour layer and so on.
Each painted layer is a square grid::

    u32 classIndex, u32 len, name, <per-layer header of varying size>,
    u32 width, u32 height, u32 byteCount, byteCount bytes of cells

Float layers store little-endian float32 cells, the colour layer RGBA8, and
in every shipped layer ``byteCount == width * height * 4`` and the grid runs to
the exact end of the payload. The walk finds the grid header by those relations
rather than by offset (the header before it varies per layer), and refuses a
layer where they do not pick out exactly one position.

`oCTerrainGo` carries the terrain's world box (``-256,-50,-256 .. 256,50,256``
in all three chapters). Height cells are normalised: world
``y = box_min.y + cell * (box_max.y - box_min.y)``; row ``r`` runs along world Z
and column ``c`` along world X, both from the box minimum.

That mapping is proven against independent data, not assumed: sampling the
height field under every tile slot of every chapter's generation recipe
reproduces the slot's own recorded Y with a mean error of 0.00 m, and every
flipped or swapped orientation misses by metres (`tests/test_terrain.py`).

The painted base is what the level designers authored. Tiles placed at run time
blend their own heights on top (`Tiles Heights`), so the base shows the land
the generator places onto, not the finished run.

Read-only, and nothing here is shipped: the editor reads these files from the
user's own install (or a local `data/uncooked` mirror) each time.
"""

from __future__ import annotations

import array
import math
import struct
import sys
from dataclasses import dataclass, field

from . import level_placements as LP

TERRAIN_GO = "oCTerrainGo"
FLOAT_LAYER = "oCTerrainPaintedFloatInputLayer"
COLOR_LAYER = "oCTerrainPaintedColorInputLayer"
HEIGHT = "Base Height"
_MAX_GRID = 4096
_BOX_LIMIT = 1.0e5


class TerrainError(ValueError):
    """A terrain level this reader cannot vouch for."""


@dataclass
class Layer:
    name: str
    size: int                 # cells per side
    kind: str                 # "float" or "rgba"
    cells: array.array | bytes

    def at(self, u: float, v: float) -> float:
        """Nearest cell at normalised (u along X, v along Z), both in 0..1."""
        n = self.size
        c = min(n - 1, max(0, int(u * n)))
        r = min(n - 1, max(0, int(v * n)))
        return self.cells[r * n + c]


@dataclass
class Terrain:
    box_min: tuple[float, float, float]
    box_max: tuple[float, float, float]
    layers: dict[str, Layer] = field(default_factory=dict)

    def uv(self, x: float, z: float) -> tuple[float, float]:
        return ((x - self.box_min[0]) / (self.box_max[0] - self.box_min[0]),
                (z - self.box_min[2]) / (self.box_max[2] - self.box_min[2]))

    def height_at(self, x: float, z: float) -> float:
        h = self.layers.get(HEIGHT)
        if h is None:
            raise TerrainError(f"terrain has no {HEIGHT!r} layer")
        u, v = self.uv(x, z)
        return self.box_min[1] + h.at(u, v) * (self.box_max[1] - self.box_min[1])


def _class_names(g) -> list[str]:
    ct = g.blocks[g.ot - 1][2]
    (n,) = struct.unpack_from("<I", ct, 0)
    o, out = 4, []
    for _ in range(n):
        (ln,) = struct.unpack_from("<I", ct, o)
        out.append(ct[o + 4:o + 4 + ln].decode("latin-1"))
        o += 4 + ln + 16
    return out


def _grid_offset(p: bytes, start: int) -> int:
    """The one offset where ``w, h, n`` frame a square grid ending at the payload end."""
    hits = []
    for off in range(start, len(p) - 12):
        w, h, nb = struct.unpack_from("<III", p, off)
        if 0 < w <= _MAX_GRID and w == h and nb == w * h * 4 and off + 12 + nb == len(p):
            hits.append(off)
    if len(hits) != 1:
        raise TerrainError(f"painted layer grid header is ambiguous ({len(hits)} candidates)")
    return hits[0]


def _box(p: bytes) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The world box: six floats, min < max on every axis, square in X/Z."""
    hits = []
    for off in range(0, len(p) - 23):
        v = struct.unpack_from("<6f", p, off)
        if not all(math.isfinite(x) and abs(x) <= _BOX_LIMIT for x in v):
            continue
        lo, hi = v[:3], v[3:]
        if all(a < b for a, b in zip(lo, hi, strict=True)) and hi[0] - lo[0] >= 16 \
                and abs((hi[0] - lo[0]) - (hi[2] - lo[2])) < 1e-3:
            hits.append((lo, hi))
    if len(hits) != 1:
        raise TerrainError(f"{TERRAIN_GO}: world box is ambiguous ({len(hits)} candidates)")
    return hits[0]


def read(level_bytes: bytes, names: set[str] | None = None) -> Terrain:
    """Decode the terrain box and painted layers (all, or only `names`)."""
    _cf, _sec, inner = LP._inner(level_bytes)
    g = LP._graph(inner)
    classes = _class_names(g)
    box = None
    layers: dict[str, Layer] = {}
    for _b, _e, p in g.objects:
        (ci,) = struct.unpack_from("<I", p, 0)
        cn = classes[ci] if ci < len(classes) else ""
        if cn == TERRAIN_GO:
            if box is not None:
                raise TerrainError(f"more than one {TERRAIN_GO}")
            box = _box(p)
        elif cn in (FLOAT_LAYER, COLOR_LAYER):
            (ln,) = struct.unpack_from("<I", p, 4)
            name = p[8:8 + ln].decode("latin-1")
            if names is not None and name not in names:
                continue
            off = _grid_offset(p, 8 + ln)
            size, _h, nb = struct.unpack_from("<III", p, off)
            body = p[off + 12:off + 12 + nb]
            if cn == FLOAT_LAYER:
                cells = array.array("f")
                cells.frombytes(body)
                if sys.byteorder != "little":
                    cells.byteswap()
                layers[name] = Layer(name, size, "float", cells)
            else:
                layers[name] = Layer(name, size, "rgba", bytes(body))
    if box is None:
        raise TerrainError(f"no {TERRAIN_GO} in this level")
    return Terrain(box_min=box[0], box_max=box[1], layers=layers)


def resample(layer: Layer, n: int) -> list[float]:
    """`layer` as an ``n`` x ``n`` grid of floats, cell-centre sampled."""
    if layer.kind != "float":
        raise TerrainError(f"{layer.name} is not a float layer")
    src, s = layer.cells, layer.size
    out = []
    for r in range(n):
        row = min(s - 1, int((r + 0.5) * s / n)) * s
        for c in range(n):
            out.append(src[row + min(s - 1, int((c + 0.5) * s / n))])
    return out
