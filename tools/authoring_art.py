"""Primitives shared by the POI art authoring tools.

Every one of these tools builds a faceted mesh out of flat-normal quads and
draws a 48px minimap icon by rasterising polygons, and these three routines
were copied verbatim between them. This repo has paid for duplicated helpers
more than once — the five drifted `readable()` copies behind `mem_safe.h`, the
nine hand-rolled hook installers behind `hook_util.h`. The stakes here are
lower, since authoring output is committed and reviewed rather than injected
into a running game, but the failure is the same shape: one copy grows a fix
and the other does not.

`make_shrine_assets.py` is the consumer in the tree today. Import from here
rather than copying when you add another.

Nothing at runtime imports this. It is tooling.
"""

from __future__ import annotations

import math

Vec3 = tuple[float, float, float]
UvRect = tuple[float, float, float, float]


def face(verts: list[Vec3], norms: list[Vec3], uvs: list[tuple[float, float]],
         tris: list[int], quad: list[Vec3], uv_rect: UvRect) -> None:
    """Append one quad as two triangles with a flat face normal.

    Vertices are duplicated per face rather than shared. These are faceted stone
    shapes; sharing vertices averages the normals across the join and the hard
    edges the silhouette depends on go soft.
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
    tris.extend([base, base + 1, base + 2, base, base + 2, base + 3])


def tri(verts: list[Vec3], norms: list[Vec3], uvs: list[tuple[float, float]],
        tris: list[int], triangle: list[Vec3], uv_rect: UvRect) -> None:
    """Append one triangle with a flat face normal.

    Cap fans and cone faces need this. Passing ``[a, b, apex, apex]`` to `face`
    looks harmless — it splits into (0,1,2) and (0,2,3) — but the second
    triangle is ``(a, apex, apex)``: zero area, and its normal comes out
    ``(0,0,0)`` because the edge ``d - a`` is the zero vector. Every vanilla
    scenery mesh has exactly zero degenerate triangles and unit-length normals
    throughout; the shrine shipped 48 and 192 of them before this existed.
    """
    a, b, c = triangle
    u0, v0, u1, v1 = uv_rect
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (e1[1] * e2[2] - e1[2] * e2[1],
         e1[2] * e2[0] - e1[0] * e2[2],
         e1[0] * e2[1] - e1[1] * e2[0])
    ln = math.sqrt(sum(x * x for x in n))
    if ln < 1e-12:
        return  # genuinely degenerate input: drop it rather than ship a NaN
    n = (n[0] / ln, n[1] / ln, n[2] / ln)
    base = len(verts)
    verts.extend([a, b, c])
    norms.extend([n] * 3)
    uvs.extend([(u0, v1), (u1, v1), (u1, v0)])
    tris.extend([base, base + 1, base + 2])


def in_poly(px: float, py: float, pts: list[tuple[float, float]]) -> bool:
    """Even-odd point-in-polygon, for rasterising an icon by supersampling."""
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
