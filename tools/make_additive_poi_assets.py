#!/usr/bin/env python3
"""Author the custom art for `mods/additive-poi-test`'s `custom_clone` layer.

An *authoring tool*, the stand-in for opening Blender — run it once, commit what
it writes, and the mod ships those. Nothing at runtime calls it (mods ship data,
not code; see CLAUDE.md). Re-run it only to change the art.

It writes SOURCE art into the POI folder, not cooked assets:

    mods/additive-poi-test/pois/custom_clone/model.glb   the mesh
    mods/additive-poi-test/pois/custom_clone/icon.png    the minimap icon

The `poi` kind picks both up by filename — `MODEL_NAMES` and `ICON_NAMES` — and
cooks them at apply time, grafting the mesh onto `prop.entity_base`'s own
geometry as the template. So there is nothing to pre-cook here, unlike
`tools/make_shrine_assets.py`, which has to graft at authoring time because it
ships finished `.Geometry.gen` bytes.

Why this exists at all
----------------------
`custom_clone` shipped a `model.glb` that was a **byte-identical copy** of the
runestone shrine's obelisk (md5 946c25c9…, both 11200 B). That is fine until
both mods are installed, and then it defeats the one thing this test mod is for:
knowing WHICH mod put a thing on the map. Its own note says the earlier layers
failed because the tile was "INDISTINGUISHABLE"; wearing another mod's mesh is
the same mistake one level down. So the shape here is deliberately nothing like
a tapered obelisk — a stack of square slabs, each rotated a further 22 degrees,
under a floating beacon. Steppy and twisted reads at a distance and from above,
which is where a minimap POI is judged from.

The icon was a shipped name (`Map_Icons_3Pigs_Resources_Stone.png`) for a reason
the manifest records: mixing a new `Ui` name into the experiment would have made
the result unreadable while the loading question was open. It is not open any
more — a mod-introduced entity resolves (2026-09-11) and the level-stream writer
that broke every additive run is fixed (2026-09-12) — so the icon is this mod's
own now, and `runestone-shrine` has proven the `Ui` path separately.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rsmm.engine import gltf  # noqa: E402
from rsmm.engine import image as IMG  # noqa: E402
from rsmm.engine.paths import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import authoring_art as art  # noqa: E402

Vec3 = tuple[float, float, float]


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #

def _face(verts, norms, uvs, quad, uv_rect) -> None:
    art.face(verts, norms, uvs, _face.tris, quad, uv_rect)


def _tri(verts, norms, uvs, triangle, uv_rect) -> None:
    art.tri(verts, norms, uvs, _face.tris, triangle, uv_rect)


def _slab(verts, norms, uvs, y0: float, y1: float, half: float,
          yaw_deg: float, uv_rect) -> None:
    """A square slab from y0 to y1, `half` across, rotated `yaw_deg` about Y.

    Rotating the whole box — both rings at the same phase — rather than twisting
    it between the two rings. A twist shears the side faces and the stack reads
    as one melted column; equal phases keep each slab a crisp box and put the
    step where it belongs, at the join.
    """
    a = math.radians(yaw_deg)
    ca, sa = math.cos(a), math.sin(a)

    def corner(sx: float, sz: float, y: float) -> Vec3:
        x, z = sx * half, sz * half
        return (x * ca - z * sa, y, x * sa + z * ca)

    lo = [corner(-1, -1, y0), corner(1, -1, y0), corner(1, 1, y0), corner(-1, 1, y0)]
    hi = [corner(-1, -1, y1), corner(1, -1, y1), corner(1, 1, y1), corner(-1, 1, y1)]
    u0, v0, u1, v1 = uv_rect
    for i in range(4):
        j = (i + 1) % 4
        su0 = u0 + (u1 - u0) * (i / 4)
        su1 = u0 + (u1 - u0) * ((i + 1) / 4)
        _face(verts, norms, uvs, [lo[i], lo[j], hi[j], hi[i]], (su0, v0, su1, v1))
    _face(verts, norms, uvs, [hi[0], hi[1], hi[2], hi[3]], uv_rect)
    _face(verts, norms, uvs, [lo[3], lo[2], lo[1], lo[0]], uv_rect)


def _bipyramid(verts, norms, uvs, cy: float, half_h: float, r: float,
               sides: int, uv_rect) -> None:
    """A floating faceted beacon: two cones base to base."""
    ring = [(r * math.cos(2 * math.pi * i / sides), cy,
             r * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    top = (0.0, cy + half_h, 0.0)
    bot = (0.0, cy - half_h, 0.0)
    u0, v0, u1, v1 = uv_rect
    for i in range(sides):
        j = (i + 1) % sides
        su0 = u0 + (u1 - u0) * (i / sides)
        su1 = u0 + (u1 - u0) * ((i + 1) / sides)
        # Triangles, not quads with a repeated apex — see `_tri`.
        _tri(verts, norms, uvs, [ring[i], ring[j], top], (su0, v0, su1, v1))
        _tri(verts, norms, uvs, [ring[j], ring[i], bot], (su0, v0, su1, v1))


def build_totem_glb() -> bytes:
    """A stack of rotated slabs under a floating beacon.

    2.51 units tall with the feet on y=0, which is what `fit = "none"` ships
    unchanged. That puts it a little under the blood fountain it stands in for
    (0.00..2.46 plus its own plinth) — tall enough to be the thing you look at
    in a 6x6 clearing, short enough not to poke through what the tile pools
    around it.
    """
    verts: list[Vec3] = []
    norms: list[Vec3] = []
    uvs: list[tuple[float, float]] = []
    _face.tris = []

    UV_STONE = (0.02, 0.02, 0.98, 0.46)
    UV_BEACON = (0.02, 0.52, 0.98, 0.98)

    # THREE slabs, not four. Four steps in 1.9 units is a 0.4-unit riser, which
    # is below what reads as a step at the distance a POI is first seen from —
    # and the icon that has to depict the same object has 48 pixels to do it in,
    # where four bars merge into a plain pyramid. Three is the most that reads
    # in both places, and the shape has to survive being a 48px glyph.
    #
    # 25 degrees of rotation per slab, not 45: at 45 the corners land on the
    # edges below and the stack is a plain square column again from half the
    # compass.
    steps = [(0.00, 0.42, 1.00), (0.42, 1.10, 0.74), (1.10, 1.72, 0.48)]
    for i, (y0, y1, half) in enumerate(steps):
        _slab(verts, norms, uvs, y0, y1, half, 25.0 * i, UV_STONE)

    # The beacon floats clear of the top slab. The gap is the shape's whole
    # idea, so it has to survive being seen from above on a minimap.
    _bipyramid(verts, norms, uvs, cy=2.15, half_h=0.36, r=0.26,
               sides=6, uv_rect=UV_BEACON)

    b = gltf.GlbBuilder()
    pi = b.add_positions(verts)
    ni = b.add_vec3(norms)
    ui = b.add_vec2(uvs)
    ii = b.add_indices(_face.tris)
    mesh = b.add_mesh(gltf.Mesh(name="RSMM_AdditiveTotem", primitives=[
        gltf.Primitive(attributes={"POSITION": pi, "NORMAL": ni,
                                   "TEXCOORD_0": ui}, indices=ii)]))
    b.add_node(gltf.Node(name="RSMM_AdditiveTotem", mesh=mesh), is_root=True)
    return b.build_glb()


# --------------------------------------------------------------------------- #
# Minimap icon
# --------------------------------------------------------------------------- #

#: 48x48, which is what 42 of the 60 shipped minimap icons are. Transparent
#: ground, a thick dark outline around a flat saturated fill, a rim light along
#: the top-left. Matching the house style matters more than the drawing — an
#: icon in a different idiom reads as a bug rather than as content.
ICON_SIZE = 48
_OUTLINE_PX = 2

#: AMBER on cool grey, deliberately not the shrine's cyan-on-warm-grey. Both
#: mods can be installed at once and the minimap is where you tell them apart.
#: The low end stays well clear of the outline's value. At (66,68,80) the base
#: bar and the 2px near-black ring around it were within a shade of each other,
#: so the bottom third of the icon read as one dark mass and the seam between
#: the last two slabs disappeared into it.
_STONE_HI = (158, 160, 172)
_STONE_LO = (92, 96, 112)
_BEACON_HI = (255, 226, 138)
_BEACON_LO = (232, 140, 28)
_OUTLINE = (16, 14, 20)


def build_icon(size: int = ICON_SIZE) -> bytes:
    """Draw the totem: four stepped bars under a floating diamond.

    Two passes — rasterise a material id per pixel, supersampled so the steps
    are not jagged, then grow the finished mask outward for the outline. Growing
    the whole mask is what gives the even, fully-enclosing border the shipped
    icons have; stroking each bar on its own leaves seams where they meet.
    """
    S = size / 48.0
    SS = 3

    # The gap under the beacon has to survive the outline pass: the ring grows
    # `r` outward from both sides, so anything under 2*r closes up. At r=2 that
    # needs more than 4px of clear space, and 6 leaves margin at 48px.
    beacon = [(24 * S, 2 * S), (31 * S, 9 * S), (24 * S, 16 * S), (17 * S, 9 * S)]
    # Three bars, matching the mesh's three slabs, with a 4px jog per side at
    # each join. Smaller jogs and the outline pass fills them in and the stack
    # comes out a smooth pyramid — which is what four narrower bars did.
    # Bottom edge stops at 45 so the outline's own 2px ring stays on canvas;
    # at 46 it was clipped and the base read as cut off rather than resting.
    bars = [
        [(18 * S, 22 * S), (30 * S, 22 * S), (30 * S, 30 * S), (18 * S, 30 * S)],
        [(14 * S, 30 * S), (34 * S, 30 * S), (34 * S, 37 * S), (14 * S, 37 * S)],
        [(9 * S, 37 * S), (39 * S, 37 * S), (39 * S, 45 * S), (9 * S, 45 * S)],
    ]

    # 0 empty, 1 stone, 2 beacon
    mat = [[0] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            hits = {1: 0, 2: 0}
            for sy in range(SS):
                for sx in range(SS):
                    fx, fy = x + (sx + 0.5) / SS, y + (sy + 0.5) / SS
                    if art.in_poly(fx, fy, beacon):
                        hits[2] += 1
                    elif any(art.in_poly(fx, fy, bar) for bar in bars):
                        hits[1] += 1
            if hits[2] * 2 >= SS * SS:
                mat[y][x] = 2
            elif (hits[1] + hits[2]) * 2 >= SS * SS:
                mat[y][x] = 1

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

    # The step lines: a filled pixel whose neighbour above is empty OR whose
    # row is a bar boundary. Drawing them dark is what separates four bars that
    # would otherwise merge into one silhouette once the fill is flat.
    seam_rows = {int(v * S) for v in (30, 31, 37, 38)}

    # Rim light along the top-left edge — what gives the shipped icons their
    # raised look. A pixel is rim if it is filled and its up or left neighbour
    # is not.
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
                t = (y / S - 2) / 14.0
                hi, lo = _BEACON_HI, _BEACON_LO
            else:
                t = (y / S - 22) / 23.0
                hi, lo = _STONE_HI, _STONE_LO
            t = max(0.0, min(1.0, t))
            col = tuple(int(hi[c] + (lo[c] - hi[c]) * t) for c in range(3))
            if m == 1 and y in seam_rows:
                col = tuple(int(c * 0.55) for c in col)
            elif rim[y][x]:
                col = tuple(min(255, int(c * 1.30 + 26)) for c in col)
            out[i:i + 4] = bytes((*col, 255))
    return bytes(out)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mod", default="additive-poi-test",
                    help="mod directory under mods/ to write source art into")
    ap.add_argument("--into", default="pois/custom_clone",
                    help="POI folder under the mod")
    ap.add_argument("--icon-size", type=int, default=ICON_SIZE)
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    out = REPO_ROOT / "mods" / args.mod / args.into
    if not out.is_dir():
        print(f"no such POI folder: {out}", file=sys.stderr)
        return 1

    glb = build_totem_glb()
    (out / "model.glb").write_bytes(glb)
    print(f"  model.glb   {len(_face.tris) // 3} tris, {len(glb)} B")

    png = IMG.encode_png(args.icon_size, args.icon_size, build_icon(args.icon_size))
    (out / "icon.png").write_bytes(png)
    print(f"  icon.png    {args.icon_size}x{args.icon_size}, {len(png)} B")

    print(f"\nwrote source art into {out.relative_to(REPO_ROOT)}")
    print("`rsmm apply` cooks both — the mesh against prop.entity_base's own "
          "geometry, the icon into the tiledef's icon slot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
