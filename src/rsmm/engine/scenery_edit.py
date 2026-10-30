"""Edit the objects a chapter places by itself: move, sink, and add scenery.

A chapter draws two kinds of objects. Tiles are generated per run (see
:mod:`tile_editor`), but most of the small things on the map, the rocks,
trees, bushes and ruins, are placed by the chapter's own SCENERY LEVELS
(Dark Hills: ``Map_Dark_Hills_Scenery_NorthEast`` 3898 objects and
``_SouthWest`` 3019). Each of those objects exists once, at a fixed spot, so
editing it changes that map and nothing else.

What an edit can do, and why each is safe:

* **move** rewrites the object's transform where it stands
  (:func:`level_placements.set_transforms`): same bytes count, nothing renumbered;
* **remove** SINKS the object 1000 m under the map with the same rewrite. It
  stops showing and stops blocking. Removing it from the level outright would
  change the object table (ids are positions), which is not proven yet;
* **add** appends a placement (:func:`level_placements.add_placement`, proven
  for tiles) of an entity the chapter ALREADY places somewhere. The chapter's
  resource cache is a superset of everything it places, so such an entity is
  fully preloaded and the cache needs no edit; an entity the chapter does not
  place could leave a null in the preload and take the whole level down.

Every edit is anchored on the object's entity and its shipped position, like a
``tilegen`` slot, so a game patch that renumbers a level fails the edit
instead of moving some other object.
"""

from __future__ import annotations

import base64
import math
import re
from array import array

from . import corpus
from . import level_placements as LP

SINK = 1000.0          # how far a removed object goes under the map
_ANCHOR_TOL = 0.05     # metres: an anchor within this of the shipped position matches


#: Folders whose entities are set dressing, by the second path component
#: (``DarkHills\\SceneryObjects_DarkHills\\Rock.entity.ot``).
_SCENERY_FOLDER = re.compile(r"^(SceneryObjects|Objects|Compositions)_")


class SceneryEditError(ValueError):
    pass


def _me():
    from . import map_editor as ME
    return ME


def levels(chapter) -> list[str]:
    """The chapter's scenery levels that place anything, by decoded path."""
    out = []
    for dec in _me().scenery_levels(chapter):
        raw = corpus.read(dec)
        if raw and LP.objects(raw):
            out.append(dec)
    return out


def _b64(a: array) -> str:
    import sys
    if sys.byteorder != "little":
        a = array(a.typecode, a)
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode("ascii")


def scenery_json(chapter) -> dict:
    """The chapter's scenery as selectable objects, drawn as instanced parts.

    ``objects``: one row per placement, as parallel base64 arrays: ``level``
    (index into ``levels``), ``id`` (its object id in that level), ``entity``
    (index into ``entities``) and ``xf`` (10 floats: pos, quat x y z w, scale).
    ``parts`` / ``matrices`` are what :func:`map_scene.to_json` returns, and
    ``owners[i]`` names, per instance of part ``i``, the object it belongs to.
    """
    from . import map_scene as MS

    lv = levels(chapter)
    entities: dict[str, int] = {}
    o_level, o_id, o_ent, o_xf = array("H"), array("I"), array("I"), array("f")
    order: dict = {}
    mats: list[array] = []
    owners: list[array] = []
    for li, dec in enumerate(lv):
        for oid, pl in LP.objects(corpus.read(dec)):
            oi = len(o_id)
            o_level.append(li)
            o_id.append(oid)
            o_ent.append(entities.setdefault(pl.ref, len(entities)))
            o_xf.extend((*pl.pos, *pl.quat, *pl.scale))
            m = MS.trs(pl.pos, pl.quat, pl.scale)
            for part, local in MS.entity_parts(pl.ref):
                pi = order.get(part)
                if pi is None:
                    pi = order[part] = len(mats)
                    mats.append(array("f"))
                    owners.append(array("I"))
                mats[pi].extend(m if local is MS.IDENTITY else MS.mul(m, local))
                owners[pi].append(oi)
    return {
        "levels": lv,
        "entities": list(entities),
        "objects": {"count": len(o_id), "level": _b64(o_level), "id": _b64(o_id),
                    "entity": _b64(o_ent), "xf": _b64(o_xf)},
        "parts": [{"mesh": p.mesh, "texture": p.texture, "swap_rb": p.swap_rb,
                   "color": p.color, "decal": p.decal} for p in order],
        "matrices": [_b64(m) for m in mats],
        "owners": [_b64(o) for o in owners],
    }


def _mapdef_cache(chapter) -> bytes | None:
    from ..sdk.kinds import poi
    from . import map_pool as MP
    from . import rsc_cache as RC

    want = chapter.key.replace("_", "").lower()
    stem = next((s for c, s in poi.CHAPTERS.items() if c.replace("_", "").lower() == want), None)
    if stem is None:
        return None
    return corpus.read(RC.cache_path_for(f"Definitions/Maps/{stem}{MP.GEN_SUFFIX}"))


def chapter_props(chapter) -> list[dict]:
    """What may be ADDED to this chapter: entities it already places (so its
    cache preloads them), that some shipped level stands on its own."""
    from ..sdk.kinds import poi

    cache = _mapdef_cache(chapter)
    if cache is None:
        raise SceneryEditError(f"{chapter.key}: no resource cache to check additions against")
    text = cache.decode("latin-1")
    cached = {line.split("|")[1] for line in text.splitlines()
              if line.startswith("EntitySettings|") and line.count("|") >= 2}
    out = []
    for e in sorted(poi._placeable_entities() & cached, key=str.lower):
        parts = e.split("\\")
        out.append({"entity": e, "name": parts[-1].removesuffix(".entity.ot"),
                    "group": parts[0] if len(parts) > 1 else "",
                    # Set dressing vs things that DO something (spawners, FX,
                    # chests, NPCs, UI): the editor offers the first by default.
                    "scenery": len(parts) > 2 and bool(_SCENERY_FOLDER.match(parts[1]))})
    return out


# --------------------------------------------------------------------------
# applying edits
# --------------------------------------------------------------------------

def _vec(v, n: int, what: str) -> tuple[float, ...]:
    def num(x) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(num(x) for x in v):
        raise SceneryEditError(f"{what}: expected {n} numbers")
    return tuple(float(x) for x in v)


def _yaw_quat(deg: float) -> tuple[float, float, float, float]:
    h = math.radians(deg) / 2.0
    return (0.0, math.sin(h), 0.0, math.cos(h))


def apply(chapter, level: str, edits: dict) -> tuple[bytes, list[str]]:
    """``(new level bytes, what changed)`` for one scenery level.

    ``edits``: ``moves = {id: {entity, at, pos, quat | yaw, scale}}``,
    ``removes = {id: {entity, at}}``, ``adds = [{entity, pos, yaw, scale}]``.
    """
    if level not in levels(chapter):
        raise SceneryEditError(f"{level} is not one of {chapter.key}'s scenery levels")
    raw = corpus.read(level)
    shipped = dict(LP.objects(raw))
    changes: dict[int, tuple] = {}
    notes: list[str] = []

    def anchored(key, spec, what) -> tuple[int, LP.Placement]:
        try:
            oid = int(key)
        except (TypeError, ValueError):
            raise SceneryEditError(f"{what} {key!r}: not an object id") from None
        pl = shipped.get(oid)
        if pl is None:
            raise SceneryEditError(f"{what} {oid}: the level has no such object")
        if not isinstance(spec, dict) or spec.get("entity") != pl.ref:
            raise SceneryEditError(
                f"{what} {oid}: the level now stands {pl.ref.rsplit(chr(92), 1)[-1]} there, "
                f"not {str((spec or {}).get('entity', '?')).rsplit(chr(92), 1)[-1]} "
                "(the game changed this level since the edit was made)")
        at = _vec(spec.get("at"), 3, f"{what} {oid} at")
        if math.dist(at, pl.pos) > _ANCHOR_TOL:
            raise SceneryEditError(f"{what} {oid}: the object is no longer where the edit "
                                   "found it (the game changed this level)")
        return oid, pl

    for key, spec in (edits.get("moves") or {}).items():
        oid, pl = anchored(key, spec, "move")
        pos = _vec(spec.get("pos", pl.pos), 3, f"move {oid} pos")
        quat = (_vec(spec["quat"], 4, f"move {oid} quat") if "quat" in spec
                else _yaw_quat(float(spec["yaw"])) if "yaw" in spec else pl.quat)
        scale = spec.get("scale", pl.scale)
        scale = ((float(scale),) * 3 if isinstance(scale, (int, float))
                 else _vec(scale, 3, f"move {oid} scale"))
        changes[oid] = (pos, quat, scale)
        notes.append(f"move {pl.ref.rsplit(chr(92), 1)[-1]} ({oid})")
    for key, spec in (edits.get("removes") or {}).items():
        oid, pl = anchored(key, spec, "remove")
        if oid in changes:
            raise SceneryEditError(f"object {oid} is both moved and removed")
        changes[oid] = ((pl.pos[0], pl.pos[1] - SINK, pl.pos[2]), pl.quat, pl.scale)
        notes.append(f"remove {pl.ref.rsplit(chr(92), 1)[-1]} ({oid})")
    out = LP.set_transforms(raw, changes) if changes else raw

    adds = edits.get("adds") or []
    if adds:
        allowed = {p["entity"] for p in chapter_props(chapter)}
        for i, a in enumerate(adds):
            if not isinstance(a, dict) or a.get("entity") not in allowed:
                raise SceneryEditError(
                    f"add {i + 1}: {str((a or {}).get('entity'))!r} is not an entity "
                    f"{chapter.key} already places, so its cache may not preload it")
            pos = _vec(a.get("pos"), 3, f"add {i + 1} pos")
            scale = float(a.get("scale", 1.0))
            if not 0.05 <= scale <= 20:
                raise SceneryEditError(f"add {i + 1}: scale {scale} is outside 0.05..20")
            out = LP.add_placement(out, a["entity"], pos=pos,
                                   quat=_yaw_quat(float(a.get("yaw", 0.0))),
                                   scale=(scale,) * 3)
            notes.append(f"add {a['entity'].rsplit(chr(92), 1)[-1]}")
    if out == raw:
        raise SceneryEditError("nothing to change")
    return out, notes


