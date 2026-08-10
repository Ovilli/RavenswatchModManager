#!/usr/bin/env python3
"""Author the custom art for the **Runestone Shrine** POI (`mods/runestone-shrine`).

This is an *authoring tool*, the stand-in for opening Blender and Substance —
run it once, commit the assets it writes, and the mod ships those. It is not
part of the mod and nothing at runtime calls it. (Mods ship data, not code; see
CLAUDE.md.) Re-run it only to change the art.

What it produces, all generated from scratch — no game bytes are copied into
the pixels or the vertices:

    <mod>/assets/3D/Scenery/DarkHills/RSMM_Runestone.fbx.Geometry.gen   custom mesh
    <mod>/assets/3D/Scenery/DarkHills/T_RSMM_Runestone_ALB.tga.Texture.dxt   albedo
    <mod>/assets/3D/Scenery/DarkHills/T_RSMM_Runestone_MRA.tga.Texture.dxt   metal/rough/AO
    <mod>/assets/3D/Scenery/DarkHills/T_RSMM_Runestone_NRM.tga.Texture.dxt   normal

The mesh is a tapered obelisk on a stepped plinth with a floating faceted
crystal above it — built here as explicit triangles, welded per-face so the
hard edges stay hard. The textures are painted procedurally: layered value
noise for the stone, carved vertical rune bands, and a moss gradient that
climbs the base.

Why a cooked `.Geometry.gen` and not a raw `.glb`
-------------------------------------------------
`cook_cache` can cook a `.glb` at apply time, but only when it can find a
*template* — a cooked oCGeometry to graft the new mesh onto — and it looks for
that at the destination path. A brand-new asset has no destination file, so
there is nothing to find. The template is instead embedded in the donor GLBs
that `rsmm uncook` writes, so this tool grafts against one here, at authoring
time, and the mod ships the finished cooked geometry. The donor contributes
*structure only* (vertex layout, material slot count); every position, normal
and UV in the output is generated below.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rsmm.engine import geometry_cook as GC  # noqa: E402
from rsmm.engine import gltf  # noqa: E402
from rsmm.engine import image as IMG  # noqa: E402
from rsmm.engine.cooked_schemas.texture import TextureHandler  # noqa: E402
from rsmm.engine.paths import DATA_DIR, REPO_ROOT  # noqa: E402

#: Uncooked GLB whose embedded cooked bytes are used as the graft template.
#: A small static scenery prop: 1 submesh, 90 verts, no skeleton — the simplest
#: structure in the corpus for a static prop, so nothing unnecessary is carried
#: into the output.
DONOR_GLB = (DATA_DIR / "uncooked" / "3D" / "Scenery" / "DarkHills"
             / "Wall_Ruins_Block_Small_A.fbx.glb")

TEX_SIZE = 256

Vec3 = tuple[float, float, float]


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #

def _face(verts: list[Vec3], norms: list[Vec3], uvs: list[tuple[float, float]],
          quad: list[Vec3], uv_rect: tuple[float, float, float, float]) -> None:
    """Append one quad as two triangles with a flat face normal.

    Vertices are duplicated per face rather than shared: the shrine is faceted
    stone, and sharing them would average the normals into a soft blob.
    """
    a, b, c, d = quad
    u0, v0, u1, v1 = uv_rect
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (d[0] - a[0], d[1] - a[1], d[2] - a[2])
    n = (e1[1] * e2[2] - e1[2] * e2[1],
         e1[2] * e2[0] - e1[0] * e2[2],
         e1[0] * e2[1] - e1[1] * e2[0])
    ln = math.sqrt(sum(x * x for x in n)) or 1.0
    n = (n[0] / ln, n[1] / ln, n[2] / ln)
    base = len(verts)
    verts.extend([a, b, c, d])
    norms.extend([n] * 4)
    uvs.extend([(u0, v1), (u1, v1), (u1, v0), (u0, v0)])
    _face.tris.extend([base, base + 1, base + 2, base, base + 2, base + 3])


def _prism(verts, norms, uvs, sides: int, y0: float, y1: float,
           r0: float, r1: float, uv_rect, twist: float = 0.0,
           cap_top: bool = True, cap_bottom: bool = True) -> None:
    """A closed N-gon prism / frustum from y0 (radius r0) to y1 (radius r1)."""
    def ring(y: float, r: float, phase: float) -> list[Vec3]:
        return [(r * math.cos(2 * math.pi * i / sides + phase), y,
                 r * math.sin(2 * math.pi * i / sides + phase))
                for i in range(sides)]

    lo = ring(y0, r0, 0.0)
    hi = ring(y1, r1, twist)
    u0, v0, u1, v1 = uv_rect
    for i in range(sides):
        j = (i + 1) % sides
        su0 = u0 + (u1 - u0) * (i / sides)
        su1 = u0 + (u1 - u0) * ((i + 1) / sides)
        _face(verts, norms, uvs, [lo[i], lo[j], hi[j], hi[i]], (su0, v0, su1, v1))
    if cap_top:
        for i in range(1, sides - 1):
            _face(verts, norms, uvs, [hi[0], hi[i], hi[i + 1], hi[0]],
                  (u0, v0, u1, v1))
    if cap_bottom:
        for i in range(1, sides - 1):
            _face(verts, norms, uvs, [lo[0], lo[i + 1], lo[i], lo[0]],
                  (u0, v0, u1, v1))


def build_shrine_glb() -> bytes:
    """A stepped plinth, a tapered runed obelisk, and a floating crystal."""
    verts: list[Vec3] = []
    norms: list[Vec3] = []
    uvs: list[tuple[float, float]] = []
    _face.tris = []

    # UV atlas rows: base stone / rune band / crystal.
    UV_STONE = (0.02, 0.02, 0.98, 0.30)
    UV_RUNES = (0.02, 0.34, 0.98, 0.62)
    UV_CRYSTAL = (0.02, 0.68, 0.98, 0.98)

    # Plinth: two square steps.
    _prism(verts, norms, uvs, 4, 0.00, 0.16, 1.05, 0.98, UV_STONE)
    _prism(verts, norms, uvs, 4, 0.16, 0.30, 0.86, 0.80, UV_STONE)

    # Obelisk shaft: hexagonal, tapering, with a slight twist so the silhouette
    # reads as carved rather than extruded.
    _prism(verts, norms, uvs, 6, 0.30, 1.05, 0.62, 0.50, UV_RUNES,
           twist=math.radians(6))
    _prism(verts, norms, uvs, 6, 1.05, 1.85, 0.50, 0.34, UV_RUNES,
           twist=math.radians(10))
    # Pyramidion cap.
    _prism(verts, norms, uvs, 6, 1.85, 2.15, 0.34, 0.06, UV_STONE)

    # Floating crystal: two stacked pyramids (octahedral bipyramid).
    cy, ch, cr = 2.55, 0.34, 0.19
    _prism(verts, norms, uvs, 6, cy - ch, cy, 0.02, cr, UV_CRYSTAL)
    _prism(verts, norms, uvs, 6, cy, cy + ch, cr, 0.02, UV_CRYSTAL)

    b = gltf.GlbBuilder()
    pi = b.add_positions(verts)
    ni = b.add_vec3(norms)
    ui = b.add_vec2(uvs)
    ii = b.add_indices(_face.tris)
    mesh = b.add_mesh(gltf.Mesh(name="RSMM_Runestone", primitives=[
        gltf.Primitive(attributes={"POSITION": pi, "NORMAL": ni,
                                   "TEXCOORD_0": ui}, indices=ii)]))
    b.add_node(gltf.Node(name="RSMM_Runestone", mesh=mesh), is_root=True)
    return b.build_glb()


# --------------------------------------------------------------------------- #
# Textures
# --------------------------------------------------------------------------- #

def _hash01(x: int, y: int, seed: int) -> float:
    """Deterministic value hash -> [0,1). Stable across runs and platforms."""
    h = (x * 374761393 + y * 668265263 + seed * 2654435761) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0xFFFFFF)


def _value_noise(px: float, py: float, freq: int, seed: int) -> float:
    """Smoothed value noise at one point."""
    fx, fy = px * freq, py * freq
    x0, y0 = int(fx), int(fy)
    tx, ty = fx - x0, fy - y0
    # smoothstep so the lattice doesn't show as a grid
    tx = tx * tx * (3 - 2 * tx)
    ty = ty * ty * (3 - 2 * ty)
    c00 = _hash01(x0, y0, seed)
    c10 = _hash01(x0 + 1, y0, seed)
    c01 = _hash01(x0, y0 + 1, seed)
    c11 = _hash01(x0 + 1, y0 + 1, seed)
    return ((c00 * (1 - tx) + c10 * tx) * (1 - ty)
            + (c01 * (1 - tx) + c11 * tx) * ty)


def _fbm(px: float, py: float, seed: int, octaves: int = 5,
         base_freq: int = 24) -> float:
    """Fractal noise. `base_freq` is in cycles across the whole map — it has to
    be high enough that the grain reads at texel scale; the first pass used 4
    and produced smooth colour blobs instead of stone."""
    total, amp, norm, freq = 0.0, 1.0, 0.0, base_freq
    for _ in range(octaves):
        total += _value_noise(px, py, freq, seed) * amp
        norm += amp
        amp *= 0.5
        freq *= 2
    return total / norm


#: Rune glyphs on a 3x5 grid, drawn as lit cells. Invented shapes — angular
#: enough to read as carved at the distance the camera actually sits.
_RUNES = [
    [(1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (0, 1), (2, 1)],          # cross
    [(0, 0), (1, 1), (2, 2), (1, 3), (0, 4), (2, 0), (2, 4)],          # arrow
    [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (1, 2), (2, 1), (2, 3)],  # branch
    [(0, 0), (2, 0), (1, 1), (1, 2), (1, 3), (0, 4), (2, 4)],          # hourglass
    [(0, 0), (1, 0), (2, 0), (1, 1), (1, 2), (1, 3), (0, 4), (2, 4)],  # anchor
    [(0, 1), (0, 2), (0, 3), (2, 1), (2, 2), (2, 3), (1, 0), (1, 4)],  # gate
]


def _rune_mask(u: float, v: float) -> float:
    """1.0 inside a carved rune glyph, 0.0 outside. `v` runs down the band."""
    cols, rows = 6, 4
    cu, cv = u * cols, v * rows
    ci, ri = int(cu) % cols, int(cv) % rows
    gx, gy = cu - int(cu), cv - int(cv)
    # Inset so glyphs don't touch cell edges.
    if not (0.18 < gx < 0.82 and 0.12 < gy < 0.88):
        return 0.0
    glyph = _RUNES[(ci + ri * 2) % len(_RUNES)]
    px = int((gx - 0.18) / 0.64 * 3)
    py = int((gy - 0.12) / 0.76 * 5)
    return 1.0 if (min(px, 2), min(py, 4)) in glyph else 0.0


def _bands(v: float) -> str:
    """Which UV atlas row a texel falls in (matches the geometry's UV rects)."""
    if v < 0.32:
        return "stone"
    if v < 0.64:
        return "runes"
    return "crystal"


def build_textures(size: int = TEX_SIZE) -> dict[str, bytes]:
    """Paint albedo / MRA / normal as tight RGBA8 buffers."""
    alb = bytearray(size * size * 4)
    mra = bytearray(size * size * 4)
    nrm = bytearray(size * size * 4)
    height = [[0.0] * size for _ in range(size)]

    for y in range(size):
        v = y / size
        band = _bands(v)
        for x in range(size):
            u = x / size
            grain = _fbm(u, v, seed=7)
            speck = _fbm(u, v, seed=23, octaves=3, base_freq=64)
            mottle = _fbm(u, v, seed=91, octaves=3, base_freq=6)

            if band == "crystal":
                # Cool translucent quartz: banded, high-value, low grain.
                t = 0.55 + 0.45 * math.sin(u * 18 + mottle * 4)
                facet = 0.85 + 0.15 * grain
                r = int((70 + 60 * t) * facet)
                g = int((150 + 80 * t) * facet)
                bl = int((190 + 60 * t) * facet)
                rough, metal, ao = 0.12, 0.0, 1.0
                h = 0.5 + 0.35 * t
            else:
                # Weathered granite: grey-brown, darker in the crevices. The
                # low-frequency `mottle` gives large tonal patches, `grain` the
                # per-texel roughness, `speck` the mineral flecks.
                base = 0.34 + 0.26 * grain + 0.18 * mottle
                base -= 0.12 * (speck > 0.68)
                r = int(255 * base * 0.86)
                g = int(255 * base * 0.83)
                bl = int(255 * base * 0.78)
                rough = 0.62 + 0.28 * grain
                metal = 0.0
                ao = 0.55 + 0.45 * grain
                h = base

                # Moss creeping up from the FOOT of each band. `_face` gives the
                # bottom ring the larger v, so the base of the shrine is v->1
                # within its band, not v->0 (which is where the first pass put
                # the moss — growing on top of the obelisk).
                local_v = (v / 0.32) if band == "stone" else ((v - 0.32) / 0.32)
                from_foot = 1.0 - local_v
                moss = max(0.0, 1.0 - from_foot * 1.7) * (0.35 + 0.65 * mottle)
                if moss > 0.30:
                    k = min(1.0, (moss - 0.30) * 2.4)
                    r = int(r * (1 - k) + 78 * k)
                    g = int(g * (1 - k) + 104 * k)
                    bl = int(bl * (1 - k) + 52 * k)
                    rough = rough * (1 - k) + 0.92 * k
                    ao *= 1 - 0.25 * k

                if band == "runes":
                    carve = _rune_mask(u, (v - 0.32) / 0.32)
                    if carve > 0:
                        # Carved channel: darker, recessed, with a cyan glow
                        # bleeding out of the cut.
                        r = int(r * 0.30 + 20)
                        g = int(g * 0.30 + 190)
                        bl = int(bl * 0.30 + 210)
                        rough, ao = 0.28, 0.35
                        h = base - 0.34

            i = (y * size + x) * 4
            alb[i:i + 4] = bytes((max(0, min(255, r)), max(0, min(255, g)),
                                  max(0, min(255, bl)), 255))
            mra[i:i + 4] = bytes((int(max(0, min(1, metal)) * 255),
                                  int(max(0, min(1, rough)) * 255),
                                  int(max(0, min(1, ao)) * 255), 255))
            height[y][x] = h

    # Normals from the height field (Sobel, wrapping so the map tiles).
    for y in range(size):
        for x in range(size):
            hl = height[y][(x - 1) % size]
            hr = height[y][(x + 1) % size]
            hu = height[(y - 1) % size][x]
            hd = height[(y + 1) % size][x]
            # Strength: the height field is mostly fine grain, so a gentle
            # slope factor flattens to a featureless blue sheet.
            nx, ny, nz = (hl - hr) * 7.0, (hu - hd) * 7.0, 1.0
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            i = (y * size + x) * 4
            nrm[i:i + 4] = bytes((int((nx / ln * 0.5 + 0.5) * 255),
                                  int((ny / ln * 0.5 + 0.5) * 255),
                                  int((nz / ln * 0.5 + 0.5) * 255), 255))

    return {"ALB": bytes(alb), "MRA": bytes(mra), "NRM": bytes(nrm)}


# --------------------------------------------------------------------------- #
# Minimap icon
# --------------------------------------------------------------------------- #

#: Minimap icons are 48x48 (42 of the 60 shipped ones), transparent, with a
#: thick black outline around a flat saturated fill and a little vertical
#: shading. Matching that matters more than the drawing itself — an icon in a
#: different style reads as a bug, not as content.
ICON_SIZE = 48
_OUTLINE_PX = 2

#: Palette, sampled to sit in the same value range as the shipped icons.
_STONE_HI = (168, 158, 140)
_STONE_LO = (84, 76, 68)
_CRYSTAL_HI = (170, 248, 255)
_CRYSTAL_LO = (24, 150, 205)
_RUNE = (90, 232, 255)
_OUTLINE = (16, 14, 20)


def _in_poly(px: float, py: float, pts: list[tuple[float, float]]) -> bool:
    """Even-odd point-in-polygon."""
    inside = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > py) != (y1 > py):
            xint = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
            if px < xint:
                inside = not inside
    return inside


def build_icon(size: int = ICON_SIZE) -> bytes:
    """Draw the shrine as a minimap icon: obelisk + floating crystal.

    Two-pass: rasterise a material id per pixel (supersampled so the diagonals
    are not jagged), then grow that mask outward to make the outline. Growing a
    finished mask is what gives the even, fully-enclosing border the vanilla
    icons have — stroking each shape separately leaves seams where they meet.
    """
    S = size / 48.0          # design at 48 and scale, so shapes stay in place
    SS = 3                   # supersamples per axis

    # Sized to fill the frame the way the shipped icons do — the first pass was
    # a thin spire with a third of the canvas empty, which reads as small and
    # faint next to a cauldron that spans nearly the full width.
    # The crystal has to read as FLOATING, which is the shape's whole idea, so
    # the gap between it and the obelisk must survive the outline pass — the
    # ring grows `r` outward from both, so anything under 2*r closes up. At
    # r=2 that means >4px of clear space; 6 leaves margin at 48px.
    crystal = [(24 * S, 1 * S), (31 * S, 7 * S), (24 * S, 13 * S), (17 * S, 7 * S)]
    # Pyramidion top rather than a needle point: a sharp tip disappears into
    # the outline at this size.
    obelisk = [(21 * S, 19 * S), (27 * S, 19 * S), (33 * S, 29 * S),
               (34 * S, 40 * S), (14 * S, 40 * S), (15 * S, 29 * S)]
    plinth = [(9 * S, 40 * S), (39 * S, 40 * S), (39 * S, 45 * S), (9 * S, 45 * S)]

    # 0 empty, 1 stone, 2 crystal
    mat = [[0] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            hits = {1: 0, 2: 0}
            for sy in range(SS):
                for sx in range(SS):
                    fx, fy = x + (sx + 0.5) / SS, y + (sy + 0.5) / SS
                    if _in_poly(fx, fy, crystal):
                        hits[2] += 1
                    elif _in_poly(fx, fy, obelisk) or _in_poly(fx, fy, plinth):
                        hits[1] += 1
            if hits[2] * 2 >= SS * SS:
                mat[y][x] = 2
            elif (hits[1] + hits[2]) * 2 >= SS * SS:
                mat[y][x] = 1

    # Grow the filled mask to make the outline ring.
    r = max(1, round(_OUTLINE_PX * S))
    outline = [[False] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            if mat[y][x]:
                continue
            near = False
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy > r * r:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < size and 0 <= nx < size and mat[ny][nx]:
                        near = True
                        break
                if near:
                    break
            outline[y][x] = near

    # Rune band on the shaft — the one detail that says which shrine this is.
    rune_rows = {int(v * S) for v in (31, 32, 36, 37)}

    # Rim light along the top-left edge, which is what gives the shipped icons
    # their raised look. A pixel is rim if it is filled and its up-left
    # neighbour is not.
    rim = [[False] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            if not mat[y][x]:
                continue
            up = mat[y - 1][x] if y else 0
            left = mat[y][x - 1] if x else 0
            if not up or not left:
                rim[y][x] = True

    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            m = mat[y][x]
            if m == 0:
                if outline[y][x]:
                    out[i:i + 4] = bytes((*_OUTLINE, 255))
                continue
            if m == 2:
                t = (y / S - 1) / 12.0
                hi, lo = _CRYSTAL_HI, _CRYSTAL_LO
            else:
                t = (y / S - 19) / 26.0
                hi, lo = _STONE_HI, _STONE_LO
            t = max(0.0, min(1.0, t))
            col = tuple(int(hi[c] + (lo[c] - hi[c]) * t) for c in range(3))
            if m == 1 and y in rune_rows and 17 * S <= x <= 31 * S:
                col = _RUNE
            elif rim[y][x]:
                col = tuple(min(255, int(c * 1.30 + 26)) for c in col)
            out[i:i + 4] = bytes((*col, 255))
    return bytes(out)


# --------------------------------------------------------------------------- #
# Cooking + output
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mod", default="runestone-shrine",
                    help="mod directory under mods/ to write assets into")
    ap.add_argument("--size", type=int, default=TEX_SIZE, help="texture edge in px")
    ap.add_argument("--preview", action="store_true",
                    help="also write the textures as PNGs for eyeballing")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if not DONOR_GLB.is_file():
        print(f"donor template missing: {DONOR_GLB}\n"
              f"run `python scripts/extract_uncooked.py` first", file=sys.stderr)
        return 1

    out = REPO_ROOT / "mods" / args.mod / "assets" / "3D" / "Scenery" / "DarkHills"
    out.mkdir(parents=True, exist_ok=True)

    # --- mesh ---
    glb = build_shrine_glb()
    n_tris = len(_face.tris) // 3
    template = GC.template_from_uncooked_glb(DONOR_GLB.read_bytes())
    cooked_geo = GC.swap_geometry(template, glb)
    (out / "RSMM_Runestone.fbx.Geometry.gen").write_bytes(cooked_geo)
    print(f"  mesh    RSMM_Runestone.fbx.Geometry.gen   "
          f"{n_tris} tris, {len(cooked_geo)} B")

    # --- textures ---
    handler = TextureHandler()
    for suffix, rgba in build_textures(args.size).items():
        png = IMG.encode_png(args.size, args.size, rgba)
        cooked_tex = handler.encode_container(png)
        name = f"T_RSMM_Runestone_{suffix}.tga.Texture.dxt"
        (out / name).write_bytes(cooked_tex)
        print(f"  texture {name:38} {args.size}x{args.size}, {len(cooked_tex)} B")
        if args.preview:
            (out / f"preview_{suffix}.png").write_bytes(png)

    print(f"\nwrote {len(list(out.glob('*')))} file(s) to "
          f"{out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
