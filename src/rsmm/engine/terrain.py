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

Nothing here is shipped: the editor reads these files from the user's own
install (or a local `data/uncooked` mirror) each time, and a mod carries
brush STROKES (`apply_strokes`) that `write` lays onto the vanilla grid at
apply time, never the grid itself.

Why painting the grid is enough (static RE, 2026-10-17, build b9c3): the
shipped level holds no ground geometry. Of Dark Hills' 26.7 MB, 25.7 MB are
painted layers; its 7168 `oCTerrainMeshTile` and 2048 `oCPhysicTerrainTile`
objects average 29 bytes, descriptors for the `Terrain Mesh Generator` and
`Physic Terrain Generator` that build render mesh and collision from the
layers at load ("Level load - Rebuild terrain"). The navmesh IS baked
(`Map_<X>_NavMeshes.level`, Detour tiles), but "Level load - Rebuild navmesh"
in `LevelLoad_Orchestrator` marks every tile of every navmesh dirty over the
navmesh's own full bounds (0x14086b310) and rebuilds them (0x14086b750) with
`oCDtDetourMeshTileTriangleBuilder` (slot 1, 0x1402a3f00), which rasterizes
the scene's live physics world. So height, collision and walkability all
follow the painted height. Unproven in game until a playtest says so.
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
    for off in range(len(p) - 23):
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


# --------------------------------------------------------------------------
# writing: brush strokes onto the vanilla grid
# --------------------------------------------------------------------------

#: Layers whose cells are a normalised height: a stroke's amounts are metres.
METRE_LAYERS = {HEIGHT, "Base Water Height", "Base Water Ocean Height", "Base Flying Height"}
#: Ops on a float layer; ``tint`` is the one op on an RGBA layer.
OPS = ("raise", "lower", "set", "flatten", "smooth", "tint")
FALLOFFS = ("smooth", "linear", "constant")
MAX_RADIUS = 512.0


def _falloff(t: float, kind: str) -> float:
    """Weight at normalised distance `t` (0 centre .. 1 edge)."""
    if kind == "constant":
        return 1.0
    if kind == "linear":
        return 1.0 - t
    return 1.0 - t * t * (3.0 - 2.0 * t)          # smoothstep


def apply_strokes(t: Terrain, strokes: list[dict]) -> list[str]:
    """Apply brush `strokes` to `t`'s float layers in place; describe each.

    A stroke is ``{op, x, z, radius, amount, falloff, layer, color}``: ``op``
    one of `OPS`, centre ``x``/``z`` and ``radius`` in world metres,
    ``amount`` in metres on a height layer (`METRE_LAYERS`) and in raw cell
    units otherwise, ``falloff`` one of `FALLOFFS`, ``layer`` defaulting to
    ``Base Height``. ``flatten`` pulls toward ``amount`` (or, without one, the
    value under the centre); ``smooth`` pulls toward the 3x3 neighbourhood
    mean; ``set`` replaces. Every float cell is clamped to 0..1, the range the
    shipped grids use. ``tint`` is the RGBA layers' op (the terrain's vertex
    colour): it blends each cell's RGB toward ``color`` (``"#rrggbb"``) by
    ``amount`` (0..1) times the falloff, leaving alpha alone.
    """
    span = t.box_max[1] - t.box_min[1]
    out = []
    for n, st in enumerate(strokes):
        what = f"terrain[{n}]"
        if not isinstance(st, dict) or set(st) - {"op", "x", "z", "radius", "amount",
                                                 "falloff", "layer", "color"}:
            raise TerrainError(f"{what}: expected {{op, x, z, radius, amount, falloff, "
                               f"layer, color}}")
        op, name = st.get("op"), st.get("layer", HEIGHT)
        fall = st.get("falloff", "smooth")
        if op not in OPS or fall not in FALLOFFS:
            raise TerrainError(f"{what}: op is one of {OPS}, falloff one of {FALLOFFS}")
        layer = t.layers.get(name)
        want = "rgba" if op == "tint" else "float"
        if layer is None or layer.kind != want:
            raise TerrainError(f"{what}: no painted {want} layer {name!r}; have "
                               f"{sorted(k for k, v in t.layers.items() if v.kind == want)}")
        try:
            x, z, radius = float(st["x"]), float(st["z"]), float(st["radius"])
            amount = None if st.get("amount") is None else float(st["amount"])
        except (KeyError, TypeError, ValueError):
            raise TerrainError(f"{what}: x, z and radius are numbers") from None
        if not (0 < radius <= MAX_RADIUS) or not all(map(math.isfinite, (x, z))):
            raise TerrainError(f"{what}: radius must be 0..{MAX_RADIUS} m")
        if amount is None and op not in ("flatten", "smooth"):
            raise TerrainError(f"{what}: {op} needs an amount")
        if op == "tint":
            if not (0.0 < amount <= 1.0):
                raise TerrainError(f"{what}: a tint's amount is its strength, 0..1")
            rgb = _rgb(st.get("color"), what)
        scale = 1.0 / span if name in METRE_LAYERS else 1.0
        if amount is not None and name in METRE_LAYERS and op in ("set", "flatten"):
            target = (amount - t.box_min[1]) / span       # an absolute height
        else:
            target = None if amount is None else amount * scale

        if op == "tint" and not isinstance(layer.cells, bytearray):
            layer.cells = bytearray(layer.cells)
        size, cells = layer.size, layer.cells
        cell_m = (t.box_max[0] - t.box_min[0]) / size
        cu, cv = t.uv(x, z)
        cc, cr = cu * size - 0.5, cv * size - 0.5
        rc = radius / cell_m
        if op == "flatten" and target is None:
            target = layer.at(cu, cv)
        src = array.array("f", cells) if op == "smooth" else cells
        touched = 0
        for r in range(max(0, int(cr - rc)), min(size, int(cr + rc) + 2)):
            for c in range(max(0, int(cc - rc)), min(size, int(cc + rc) + 2)):
                d = math.hypot(c - cc, r - cr) / rc
                if d >= 1.0:
                    continue
                w = _falloff(d, fall)
                i = r * size + c
                if op == "tint":
                    for k in range(3):
                        old = cells[i * 4 + k]
                        cells[i * 4 + k] = round(old + (rgb[k] - old) * w * amount)
                    touched += 1
                    continue
                v = cells[i]
                if op == "raise":
                    v += target * w
                elif op == "lower":
                    v -= target * w
                elif op == "set":
                    v = target if w > 0 else v
                elif op == "flatten":
                    v += (target - v) * w
                else:
                    ring = [src[rr * size + cc2]
                            for rr in range(max(0, r - 1), min(size, r + 2))
                            for cc2 in range(max(0, c - 1), min(size, c + 2))]
                    v += (sum(ring) / len(ring) - v) * w
                cells[i] = min(1.0, max(0.0, v))
                touched += 1
        if not touched:
            raise TerrainError(f"{what}: the brush at ({x:g}, {z:g}) misses the terrain")
        out.append(f"terrain: {op} {name} at ({x:g}, {z:g}) r {radius:g} m"
                   + ("" if amount is None else f" by {amount:g}"))
    return out


def _rgb(color, what: str) -> tuple[int, int, int]:
    if not (isinstance(color, str) and len(color) == 7 and color[0] == "#"):
        raise TerrainError(f"{what}: a tint needs color = \"#rrggbb\"")
    try:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        raise TerrainError(f"{what}: {color!r} is not a #rrggbb colour") from None


def write(level_bytes: bytes, t: Terrain) -> bytes:
    """`level_bytes` with `t`'s layers written back over the shipped cells.

    A grid never changes size, so every payload keeps its length and the
    object graph, ids and section sizes are untouched: only cell bytes move.
    """
    cf, sec, inner = LP._inner(level_bytes)
    g = LP._graph(inner)
    classes = _class_names(g)
    out = bytearray(inner)
    done = set()
    for b, _e, p in g.objects:
        (ci,) = struct.unpack_from("<I", p, 0)
        cn = classes[ci] if ci < len(classes) else ""
        if cn not in (FLOAT_LAYER, COLOR_LAYER):
            continue
        (ln,) = struct.unpack_from("<I", p, 4)
        name = p[8:8 + ln].decode("latin-1")
        layer = t.layers.get(name)
        if layer is None:
            continue
        off = _grid_offset(p, 8 + ln)
        size, _h, nb = struct.unpack_from("<III", p, off)
        if size != layer.size:
            raise TerrainError(f"{name}: grid is {size}, layer is {layer.size}")
        if layer.kind == "rgba":
            body = bytes(layer.cells)
        else:
            cells = array.array("f", layer.cells)
            if sys.byteorder != "little":
                cells.byteswap()
            body = cells.tobytes()
        if len(body) != nb:
            raise TerrainError(f"{name}: {len(body)} bytes of cells for a {nb}-byte grid")
        start = b + 4 + off + 12                      # past MARK_BEGIN and the header
        out[start:start + nb] = body
        done.add(name)
    missing = set(t.layers) - done
    if missing:
        raise TerrainError(f"layers not found in this level: {sorted(missing)}")
    return _emit(cf, sec, bytes(out))


def _emit(cf, sec: bytes, inner: bytes) -> bytes:
    from . import cooked

    new_sec = bytearray(sec[:16]) + inner
    struct.pack_into("<II", new_sec, 8, len(inner), len(inner))
    cf.sections[-1] = cooked.Section(payload=bytes(new_sec))
    return cooked.emit(cf)
