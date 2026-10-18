"""The 3D tile editor: a shipped tile's objects one by one, and the mod that
adds objects to it.

A chapter map is generated from tiles, so an object stands inside a TILE and
appears wherever that tile spawns. This reads a tile's level as separate
objects (entity + transform each), so the page can draw, select and outline
them, and writes what the author adds as a ``poi`` def in ``replace_base``
mode with ``places``: the path proven in game, which edits the shipped level
in place and extends the tile's and chapters' resource caches for whatever it
stands there. Objects the game ships are shown, not edited (moving or removing
them is not built yet).

Every save is proven by running the real ``poi`` emit before anything is
written, so the editor can only produce a mod ``rsmm apply`` will accept.
"""

from __future__ import annotations

import math
import re
import tempfile
import tomllib
from pathlib import Path

from . import corpus
from . import level_placements as LP
from . import map_pool as MP

#: First line of every manifest this editor writes; it reopens only those.
TILE_MARK = "# Made by the rsmm 3D tile editor."
_TILE_RE = re.compile(r"^Tiles\\([A-Za-z0-9_]+)\\([A-Za-z0-9_.-]+)\.tiledef\.ot$")
_ENTITY_RE = re.compile(r"^[A-Za-z0-9_ .\\-]+\.entity\.ot$")
#: A place's numbers stay inside what a tile can hold: tiles are at most
#: 40x40 units, and a prop scaled past this is no longer the prop.
_POS_LIMIT = 200.0
_SCALE_RANGE = (0.05, 20.0)


class TileEditError(ValueError):
    pass


def _poi():
    from ..sdk.kinds import poi
    return poi


def base_of(tile: str) -> str:
    """``Tiles\\Dark_Hills\\X.tiledef.ot`` -> ``Dark_Hills/X`` (a poi ``base``)."""
    m = _TILE_RE.match(tile or "")
    if not m:
        raise TileEditError(f"{tile!r} is not a tile path (Tiles\\<Biome>\\<Name>.tiledef.ot)")
    return f"{m[1]}/{m[2]}"


def chapters_of(tile: str) -> list[str]:
    """The chapters whose pool draws ``tile``: their caches must list what it
    stands, so the edit extends each of them."""
    poi = _poi()
    out = []
    for chapter, stem in sorted(poi.CHAPTERS.items()):
        gen = corpus.read(f"{poi._MAPS_DIR}/{stem}{MP.GEN_SUFFIX}")
        if gen is not None and tile in (MP.read_pool(gen) or []):
            out.append(chapter)
    return out


def _level(tile: str) -> tuple[str, bytes]:
    from . import prop_cook as PC

    poi = _poi()
    base = base_of(tile)
    if not poi._tile_path(base).is_file():
        raise TileEditError(f"{tile} is not a shipped tile")
    try:
        ref = poi._level_ref_of(poi._prefab_ref_of(base, "editor"), "editor")
    except Exception as e:  # the SDK's own reason, shown as it is
        raise TileEditError(str(e)) from e
    raw = corpus.read(PC.level_cooked_path(ref))
    if raw is None:
        raise TileEditError(f"{tile}: its level {ref} is not readable")
    return ref, raw


def _name(ref: str) -> str:
    return ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")


def objects_json(tile: str) -> dict:
    """Every object the tile's level stands, in the level's own space (the
    space ``places`` positions are written in)."""
    ref, raw = _level(tile)
    try:
        placements = LP.decode(raw)
    except LP.LevelPlacementError as e:
        raise TileEditError(f"{tile}: its level cannot be read object by object ({e})") from e
    return {
        "tile": tile, "base": base_of(tile), "level": ref, "chapters": chapters_of(tile),
        "objects": [{"entity": p.ref, "name": _name(p.ref), "pos": list(p.pos),
                     "quat": list(p.quat), "scale": list(p.scale)} for p in placements],
    }


def entity_json(ref: str) -> dict:
    """What one entity draws, in its own space (the page instances it at each
    object's transform)."""
    from . import map_scene as MS

    if not _ENTITY_RE.match(ref or ""):
        raise TileEditError(f"{ref!r} is not an entity reference")
    return MS.to_json(list(MS.entity_parts(ref)))


def props_json() -> list[dict]:
    """What may be added: every entity some shipped level stands on its own,
    the same rule ``places`` is validated against."""
    return [{"entity": e, "name": _name(e),
             "group": e.split("\\", 1)[0] if "\\" in e else ""}
            for e in sorted(_poi()._placeable_entities(), key=str.lower)]


# --------------------------------------------------------------------------
# saving
# --------------------------------------------------------------------------

def _num(v, what: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise TileEditError(f"{what}: expected a number")
    if not lo <= v <= hi:
        raise TileEditError(f"{what}: {v} is outside {lo}..{hi}")
    return float(v)


def clean_places(places) -> list[dict]:
    """Check what the page sent: ``[{entity, pos: [x, y, z], yaw, scale}]``."""
    if not isinstance(places, list) or not places:
        raise TileEditError("add at least one object")
    if len(places) > 256:
        raise TileEditError("at most 256 added objects per tile")
    out = []
    for i, p in enumerate(places):
        if not isinstance(p, dict):
            raise TileEditError(f"object {i + 1}: expected an object")
        ent = p.get("entity")
        if not isinstance(ent, str) or not _ENTITY_RE.match(ent):
            raise TileEditError(f"object {i + 1}: not an entity reference")
        pos = p.get("pos")
        if not isinstance(pos, list) or len(pos) != 3:
            raise TileEditError(f"object {i + 1}: pos needs three numbers")
        out.append({
            "entity": ent,
            "pos": [round(_num(v, f"object {i + 1} pos", -_POS_LIMIT, _POS_LIMIT), 4) for v in pos],
            "yaw": round(_num(p.get("yaw", 0.0), f"object {i + 1} yaw", -360.0, 360.0), 3),
            "scale": round(_num(p.get("scale", 1.0), f"object {i + 1} scale", *_SCALE_RANGE), 4),
        })
    return out


def _fields(tile: str, places: list[dict]) -> dict:
    chapters = chapters_of(tile)
    if not chapters:
        raise TileEditError(f"{tile} is not drawn by any chapter this editor can extend "
                            f"({', '.join(sorted(_poi().CHAPTERS))})")
    return {"base": base_of(tile), "chapters": chapters, "replace_base": True,
            "places": places}


def check(tile: str, places) -> list[str]:
    """Run the real poi emit on these places; the files it would write."""
    from ..sdk.content import ContentDef, ContentError

    places = clean_places(places)
    fields = _fields(tile, places)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            files = _poi().emit("editor", ContentDef(kind="poi", id=poi_id(tile),
                                                     fields=fields), Path(tmp))
        except (ContentError, ValueError) as e:
            raise TileEditError(str(e)) from e
        return sorted(f.relative_to(tmp).as_posix() for f in files)


def poi_id(tile: str) -> str:
    """The poi folder name for a tile: its file name, lower-cased."""
    return re.sub(r"[^a-z0-9_]", "_", base_of(tile).split("/", 1)[1].lower())


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def poi_toml(tile: str, places) -> str:
    places = clean_places(places)
    f = _fields(tile, places)
    lines = [
        "# Objects added to a shipped tile by the rsmm 3D tile editor.",
        "# replace_base edits the tile in place: what is added here stands in",
        "# EVERY spawn of this tile. `rsmm restore` puts the tile back.",
        f"base         = {_q(f['base'])}",
        "chapters     = [" + ", ".join(_q(c) for c in f["chapters"]) + "]",
        "replace_base = true",
        "",
    ]
    for p in places:
        lines += ["[[places]]", f"entity = {_q(p['entity'])}",
                  "pos    = [" + ", ".join(f"{v:g}" for v in p["pos"]) + "]",
                  f"yaw    = {p['yaw']:g}", f"scale  = {p['scale']:g}", ""]
    return "\n".join(lines)


def manifest_toml(mod_id: str, name: str, tiles: list[str]) -> str:
    title = name or mod_id
    names = ", ".join(t.rsplit("\\", 1)[-1].removesuffix(".tiledef.ot") for t in tiles)
    return "\n".join([
        TILE_MARK,
        "[mod]",
        f"id          = {_q(mod_id)}",
        f"name        = {_q(title)}",
        'version     = "1.0.0"',
        'author      = "rsmm tile editor"',
        f"description = {_q('Objects added to ' + names)}",
        'sdk_version = ">=3.0,<4"',
        "enabled     = false",
        'tags        = ["world", "map", "decoration"]',
        "# The tile is part of the seeded map: every player needs the same version.",
        'multiplayer_scope = "deterministic-shared"',
        "",
    ])


def read_places(text: str) -> tuple[str, list[dict]]:
    """``(tile, places)`` back from a poi.toml this editor wrote."""
    data = tomllib.loads(text)
    base = data.get("base", "")
    if "/" not in base or not data.get("replace_base"):
        raise TileEditError("not a tile-editor poi.toml")
    biome, stem = base.split("/", 1)
    tile = f"Tiles\\{biome}\\{stem}.tiledef.ot"
    return tile, clean_places(data.get("places") or [])
