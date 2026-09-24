"""Map (biome) content builder: clone a shipped mapdef and point a chapter at it.

A map clone is a REMIX of a shipped chapter: it keeps the base's terrain,
scenery and navmesh, and gets its own root and tile-generation levels so that
it generates from ITS OWN tile pool (the mapdef's), not the base's.
It cannot author a new terrain (that stays the hard wall, see
docs/_re/kinds/maps-chapters.md).

Fields:
    ``base``     (str, required)  a shipped map: ``Dark_Hills``, ``Storm_Island``,
                                  ``Avalon`` or ``Baba_Yaga``.
    ``tribe``    (str, optional)  repoint the mapdef's ``tribe_ref``, e.g. ``Gnolls``.
                                  The tribe must ship a resource cache; its whole
                                  preload closure is merged into the map's.
                                  ⚠ NO VISIBLE EFFECT observed: a Dark Hills clone
                                  with ``Knights`` played in chapter 1 showed no
                                  knights (2026-09-19). Camp enemies come from
                                  the camp/tile data, not this field.
    ``chapter``  (int, optional)  make chapter object N of ``All_Chapters`` play
                                  this map (0 Dark Hills, 1 Storm Island,
                                  2 Avalon, 3 Baba Yaga). Without it the map is
                                  emitted and registered but nothing plays it.

Emits the clone ``Definitions/Maps/<id>.mapdef.ot...gen`` and its own
``<id>.mapdef.UsedRscCache.ot`` (a mapdef whose name has no cache preloads none
of its tiles, so nothing is placed). With ``chapter``, also overrides
``All_Chapters`` in place (the proven route for game-mode edits) and adds the
clone to its cache. That override is a whole-file replacement, so it conflicts
with a ``game_mode`` edit in another mod: last writer wins.

PROVEN IN GAME 2026-09-19: chapter 0 took the resref branch and resolved to the
clone (a fifth oCDtMapDefinition, not the vanilla pointer), and the run started
in it. ⚠ The TILE POOL still comes from the base: generation follows the reused
tile-generation level's own backref to the ORIGINAL mapdef (a POI added to the
vanilla pool still appeared). So a clone now carries its own
tilegen level with that backref repointed (``_clone_levels``); ⚠ NOT yet
proven in game.
"""
from __future__ import annotations

import re
from pathlib import Path

from ...engine import corpus
from ...engine import enemy_pools as EP
from ...engine import map_cook as MC
from ...engine import prop_cook as PC
from ...engine import rsc_cache as RC
from ..content import ContentDef, ContentError, SchemaNotMined

_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

#: Shipped maps by the name a mod uses, in versiondef (= biome index) order.
BASES: dict[str, str] = {
    "Dark_Hills": "Dark_Hills_LiveOps_Update5",
    "Storm_Island": "Storm_Island_LiveOps_Update5",
    "Avalon": "Avalon_LiveOps_Update5",
    "Baba_Yaga": "Baba_Yaga_Map_Update3",
}

_MAPS = "Definitions/Maps"
_MODE_STEM = "All_Chapters"
_MODE_REL = f"Definitions/GameModes/{_MODE_STEM}{MC.MODE_GEN_SUFFIX}"
_MODE_CLASS = "GameModeDefaultDefinition"


def _read(rel: str, what: str) -> bytes:
    blob = EP.corpus_read(rel)
    if blob is None:
        raise SchemaNotMined(
            f"map: {what} ({rel}) is not in the corpus or the game install.")
    return blob


def _map_line(stem: str) -> str:
    return f"Definitions|Maps\\{stem}.mapdef.ot|{MC.MAP_CLASS}"


def _level_line(ref: str) -> str:
    return f"Ot|{ref}|oCGameStream"


def _clone_levels(map_id: str, base_stem: str, root_ref: str, out_dir: Path,
                  written: list[Path]) -> dict[str, str]:
    """Give the clone its own root + tile-generation levels. ``{old: new}`` refs.

    Generation does not follow the mapdef that started the chapter: the
    ``oCDtEntityCpntTileSpawnerSettings`` in ``<Map>_TileGeneration.level``
    names its mapdef by path, and that is where the pool is read. Measured
    2026-09-19: a clone reusing the base's levels still placed the base pool.
    So the tilegen level is cloned with that backref pointed at the clone, and
    the root level is cloned to list the new tilegen level as its sub-level.
    Every other sub-level (terrain, scenery, navmesh) is shared unchanged.

    A map with no tile-generation level (Baba Yaga) has no pool to own; its
    levels are reused as before.
    """
    root = _read(PC.level_cooked_path(root_ref), "the base map's root level")
    _h, doc = PC._refs_doc("oCGameStream", root)
    tilegen = [r for r in doc["asset_refs"] if r.endswith("_TileGeneration.level.ot")]
    if not tilegen:
        return {}
    if len(tilegen) != 1:
        raise ContentError(f"map {map_id}: base root level lists {len(tilegen)} "
                           f"tile-generation levels; expected one")
    tg_ref = tilegen[0]
    folder = root_ref.rsplit("\\", 1)[0]
    swaps = {root_ref: f"{folder}\\Map_{map_id}.level.ot",
             tg_ref: f"{folder}\\Map_{map_id}_TileGeneration.level.ot"}
    for new in swaps.values():
        if corpus.exists(PC.level_cooked_path(new)):
            raise ContentError(f"map {map_id}: the clone's level {new} collides "
                               f"with a shipped level; pick another id.")

    base_mapdef = MC.mapdef_asset_path(base_stem)
    tg = _read(PC.level_cooked_path(tg_ref), "the base map's tile-generation level")
    if base_mapdef not in PC._refs_doc("oCGameStream", tg)[1]["asset_refs"]:
        raise ContentError(f"map {map_id}: {tg_ref} does not name {base_mapdef}, "
                           f"so there is no pool backref to repoint")
    out = {
        tg_ref: PC.clone_tile_level(tg, tg_ref, swaps[tg_ref],
                                    {base_mapdef: MC.mapdef_asset_path(map_id)}),
        root_ref: PC.clone_tile_level(root, root_ref, swaps[root_ref],
                                      {tg_ref: swaps[tg_ref]}),
    }
    for old, blob in out.items():
        dest = out_dir / Path(*PC.level_cooked_path(swaps[old]).split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    return swaps


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    if not _ID_RE.match(defn.id):
        raise ContentError(
            f"invalid map id {defn.id!r}: letters, digits and underscores, "
            f"starting with a letter (it becomes the mapdef's file name).")
    if defn.id in BASES.values() or defn.id in BASES:
        raise ContentError(f"map {defn.id}: the id collides with a shipped map.")
    base = defn.fields.get("base")
    if base not in BASES:
        raise ContentError(
            f"map {defn.id}: 'base' must be one of {', '.join(BASES)} (got {base!r}).")
    base_stem = BASES[base]

    tribe = defn.fields.get("tribe")
    if tribe is not None and not (isinstance(tribe, str) and _ID_RE.match(tribe)):
        raise ContentError(f"map {defn.id}: 'tribe' must be a tribe name, e.g. \"Gnolls\".")
    chapter = defn.fields.get("chapter")
    if chapter is not None and (not isinstance(chapter, int) or isinstance(chapter, bool)):
        raise ContentError(f"map {defn.id}: 'chapter' must be an integer 0..3.")

    written: list[Path] = []

    # 1. The clone, on levels of its own so it generates from its own pool.
    base_rel = f"{_MAPS}/{base_stem}{MC.MAP_GEN_SUFFIX}"
    base_bytes = _read(base_rel, f"base map {base!r}")
    root_ref = MC.read_mapdef(base_bytes)["level_ref"][1]
    levels = _clone_levels(defn.id, base_stem, root_ref, out_dir, written)
    clone = MC.clone_mapdef(base_bytes, tribe=tribe, level=levels.get(root_ref))
    clone_rel = f"{_MAPS}/{defn.id}{MC.MAP_GEN_SUFFIX}"
    dest = out_dir / Path(*clone_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(clone)
    written.append(dest)

    # 2. Its own resource cache: the base's closure, the base's own line renamed,
    # plus the new tribe's whole closure. A cache that misses something the map
    # reaches is a null slot the level teardown destroys unchecked.
    lines = set(RC.parse(_read(RC.cache_path_for(base_rel), f"{base!r}'s resource cache")))
    lines.discard(_map_line(base_stem))
    lines.add(_map_line(defn.id))
    for old, new in levels.items():
        lines.discard(_level_line(old))
        lines.add(_level_line(new))
    if tribe is not None:
        tribe_rel = f"Definitions/EnemyTribes/{tribe}.enemytribedef.ot.DtEnemyTribeDefinition.gen"
        tribe_cache = EP.corpus_read(RC.cache_path_for(tribe_rel))
        if tribe_cache is None:
            raise ContentError(
                f"map {defn.id}: tribe {tribe!r} has no resource cache (or does not "
                f"exist), so its enemies cannot be preloaded with the map. Pick a "
                f"tribe that ships one, e.g. Gnolls, Wolves or Knights.")
        lines |= set(RC.parse(tribe_cache))
    cache = out_dir / Path(*RC.cache_path_for(clone_rel).split("/"))
    cache.write_bytes(RC.render(sorted(lines)))
    written.append(cache)

    # 3. Point a chapter at it, overriding All_Chapters in place.
    if chapter is not None:
        mode = _read(_MODE_REL, "the All_Chapters game mode")
        try:
            new_mode = MC.set_chapter_map(mode, chapter, defn.id)
        except MC.MapCookError as e:
            raise ContentError(f"map {defn.id}: {e}") from e
        mdest = out_dir / Path(*_MODE_REL.split("/"))
        mdest.parent.mkdir(parents=True, exist_ok=True)
        mdest.write_bytes(new_mode)
        written.append(mdest)
        mode_cache = set(RC.parse(_read(RC.cache_path_for(_MODE_REL),
                                        "All_Chapters' resource cache")))
        mode_cache.add(_map_line(defn.id))
        mcache = out_dir / Path(*RC.cache_path_for(_MODE_REL).split("/"))
        mcache.write_bytes(RC.render(sorted(mode_cache)))
        written.append(mcache)

    return written
