"""Map (biome) content builder: clone a shipped mapdef and point a chapter at it.

A map clone is a REMIX of a shipped chapter: it keeps the base's terrain and
tile-generation level, so today it plays like its base (see the proof note
below for why). It cannot author a new terrain (that stays the hard wall, see
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
vanilla pool still appeared). Changing what a clone places needs the clone to
carry its own tilegen level with that backref repointed; not built yet.
"""
from __future__ import annotations

import re
from pathlib import Path

from ...engine import enemy_pools as EP
from ...engine import map_cook as MC
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

    # 1. The clone. Same bytes as the base unless the tribe is repointed.
    base_rel = f"{_MAPS}/{base_stem}{MC.MAP_GEN_SUFFIX}"
    clone = MC.clone_mapdef(_read(base_rel, f"base map {base!r}"), tribe=tribe)
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
