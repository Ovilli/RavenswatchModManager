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
    ``pool``     (table, optional) ``{ add = [...], remove = [...] }`` — tiles
                                  the clone may draw, edited on the CLONE's own
                                  pool (the base map is untouched). A tile is
                                  ``"<Name>"`` (looked up in the base's biome
                                  first) or ``"<Biome>/<Name>"``, e.g.
                                  ``"Avalon/6x6_Fountain_01"``. An added tile
                                  brings its whole resource cache along; every
                                  recipe kind with a count must keep at least
                                  one pool tile carrying its flag.
    ``place``    (table, optional) hand-placed tiles: ``{ "<slot>" =
                                  "<Biome>/<Tile>" }``. ``<slot>`` is a shipped
                                  slot id or ``new<N>``, the N-th entry of
                                  ``tilegen.add_slots``. The tile lands on
                                  exactly that slot in every run (see
                                  `_place_tiles`).
    ``terrain``  (array, optional) brush strokes painted onto the clone's own
                                  terrain: ``[{ op = "raise", x, z, radius,
                                  amount, falloff, layer }]`` — see
                                  `rsmm.engine.terrain.apply_strokes`. Mesh,
                                  collision and navmesh follow at load.
    ``tilegen``  (table, optional) the clone's generation recipe, same
                                  vocabulary as the ``tilegen`` kind (``kinds``,
                                  ``quotas``, ``slots``, ``fill``) but applied
                                  to the clone's own tile-generation level, so
                                  the base chapter keeps its vanilla recipe.

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
tilegen level with that backref repointed (``_clone_levels``). PROVEN IN GAME
2026-09-24: with runestone-shrine in the vanilla Dark Hills pool, the clone
chapter generated 140 tiles and none of them the shrine (was 6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ...engine import corpus
from ...engine import enemy_pools as EP
from ...engine import map_cook as MC
from ...engine import map_editor as ME
from ...engine import map_pool as MP
from ...engine import prop_cook as PC
from ...engine import rsc_cache as RC
from ...engine import terrain as TR
from ...engine import tile_cook as TC
from ...engine import tilegen as TG
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


_TILES = "Definitions/Tiles"
_TILE_SUFFIX = ".tiledef.ot.DtTileDefinition.gen"


def _tile_rel(pool_path: str) -> str:
    """``Tiles\\Avalon\\X.tiledef.ot`` -> its decoded cooked path."""
    stem = pool_path.replace("\\", "/").removesuffix(".tiledef.ot")
    return f"Definitions/{stem}{_TILE_SUFFIX}"


def _resolve_tile(map_id: str, name, biome: str) -> str:
    """A mod's tile name -> the pool path. Names repeat across biomes
    (``3x3_Crystal_01`` ships three times), so a bare name means the base's
    biome first and anywhere else only when that is unambiguous."""
    if not isinstance(name, str) or not name:
        raise ContentError(f"map {map_id}: pool tiles are names, got {name!r}")
    if "/" in name:
        where, stem = name.split("/", 1)
        cands = [f"{_TILES}/{where}/{stem}{_TILE_SUFFIX}"]
    else:
        cands = [f"{_TILES}/{biome}/{name}{_TILE_SUFFIX}"]
        if not corpus.exists(cands[0]):
            cands = [r for r in corpus.rels(f"{_TILES}/", _TILE_SUFFIX)
                     if r.rsplit("/", 1)[-1] == f"{name}{_TILE_SUFFIX}"]
    cands = [c for c in cands if corpus.exists(c)]
    if len(cands) != 1:
        raise ContentError(
            f"map {map_id}: pool tile {name!r} "
            + ("is not a shipped tile" if not cands else
               "ships in several biomes; write it as <Biome>/<Name>"))
    rel = cands[0][len(_TILES) + 1:-len(_TILE_SUFFIX)]
    return "Tiles\\" + rel.replace("/", "\\") + ".tiledef.ot"


def _tile_flags(pool_path: str) -> list[str]:
    data = corpus.read(_tile_rel(pool_path))
    try:
        return list(TC.read(data).kinds) if data else []
    except (TC.TileCookError, ValueError):
        return []


def _edit_pool(map_id: str, pool: list[str], edit, biome: str,
               recipe: TG.TileGen | None, placed_flags: set[str] = frozenset()
               ) -> tuple[list[str], list[str], list[str]]:
    """``(new pool, added, removed)``. Fails closed when the edit would leave a
    kind the recipe still counts with no tile to place: the kind pass loops
    until its count is met, and nobody has seen what it does with nothing."""
    if not isinstance(edit, dict) or set(edit) - {"add", "remove"}:
        raise ContentError(f"map {map_id}: 'pool' is {{ add = [...], remove = [...] }}")
    lists = {}
    for key in ("add", "remove"):
        v = edit.get(key, [])
        if not isinstance(v, list):
            raise ContentError(f"map {map_id}: pool.{key} must be a list of tile names")
        lists[key] = [_resolve_tile(map_id, n, biome) for n in v]
    removed = lists["remove"]
    missing = [p for p in removed if p not in pool]
    if missing:
        raise ContentError(f"map {map_id}: cannot remove {', '.join(missing)}: "
                           f"not in the base map's pool")
    added = [p for p in dict.fromkeys(lists["add"]) if p not in pool]
    if not added and not removed:
        raise ContentError(f"map {map_id}: the pool edit changes nothing")
    new = [p for p in pool if p not in removed] + added
    if not new:
        raise ContentError(f"map {map_id}: the pool would be empty")
    if recipe is not None and removed:
        have = {f for p in new for f in _tile_flags(p)} | placed_flags
        bare = [k.name for k in recipe.kinds.values() if k.count and k.name not in have]
        if bare:
            raise ContentError(f"map {map_id}: after the removals no pool tile carries "
                               f"{', '.join(sorted(bare))}, which the recipe still places")
    return new, added, removed


@dataclass
class _Placed:
    src_rel: str      # the shipped tiledef it copies
    rel: str          # the copy's decoded cooked path
    pool_path: str    # the copy's pool entry
    flag: str         # the flag only the copy carries


def _place_tiles(map_id: str, recipe: TG.TileGen, place, before: set[int],
                 biome: str) -> list[_Placed]:
    """Pin each placed tile to one slot, by data alone.

    The generator never places a NAMED tile; it places a kind, and a kind
    matches pool tiles by flag. So each placement gets a flag no shipped tile
    carries, on a copy of the tile (its own flags kept, so quotas and other
    tiles' constraints still count it), and a kind of its own: count 1,
    allowed by that slot's mask and forced on in every scenario (compatibility
    1), allowed nowhere else. Every other kind and every footprint group's fill
    EXCLUDES the flag, so neither the kind pass nor the fill pass can put the
    copy anywhere else.
    """
    if not isinstance(place, dict) or not place:
        raise ContentError(f"map {map_id}: 'place' is {{ \"<slot>\" = \"<Biome>/<Tile>\" }}")
    new_ids = sorted(set(recipe.slots) - before)
    groups = {i: n for n, sid in zip(recipe.size_names, recipe.spawner.size_ids, strict=True)
              for i in recipe.sizes[sid].slots}
    out: list[_Placed] = []
    taken: set[int] = set()
    for n, (ref, tile) in enumerate(place.items(), 1):
        ref = str(ref)
        if ref.startswith("new") and ref[3:].isdigit() and int(ref[3:]) < len(new_ids):
            sid = new_ids[int(ref[3:])]
        elif ref.isdigit() and int(ref) in recipe.slots and int(ref) in before:
            sid = int(ref)
        else:
            raise ContentError(f"map {map_id}: place: no slot {ref!r} (a shipped id, or "
                               f"new0..new{max(len(new_ids) - 1, 0)} for added slots)")
        if sid in taken:
            raise ContentError(f"map {map_id}: place: slot {ref} is placed twice")
        taken.add(sid)
        if sid not in groups:
            raise ContentError(f"map {map_id}: place: slot {ref} is a whole-map slot")
        pool_path = _resolve_tile(map_id, tile, biome)
        src_rel = _tile_rel(pool_path)
        td = TC.read(corpus.read(src_rel))
        if f"{td.width}x{td.height}" != groups[sid]:
            raise ContentError(f"map {map_id}: place: {tile} is {td.width}x{td.height}, "
                               f"slot {ref} is a {groups[sid]} slot")
        flag = f"RSMM_{map_id}_P{n}"
        TG.add_kind(recipe, flag, count=1, footprints={groups[sid]: True})
        k = len(recipe.kind_names) - 1
        s = recipe.slots[sid]
        s.kinds = [0] * k + [1]
        s.compat = [[2] * k + [1] for _ in s.compat]
        for kid in recipe.spawner.kind_ids[:-1]:
            recipe.kinds[kid].filter.excluded.append(flag)
        for gid in recipe.spawner.size_ids:
            recipe.sizes[gid].filter.excluded.append(flag)
        where, stem = pool_path.split("\\")[1], pool_path.split("\\")[2].removesuffix(".tiledef.ot")
        name = f"{map_id}_P{n}_{stem}"
        out.append(_Placed(src_rel=src_rel, rel=f"{_TILES}/{where}/{name}{_TILE_SUFFIX}",
                           pool_path=f"Tiles\\{where}\\{name}.tiledef.ot", flag=flag))
    # Placed kinds come after every shipped one, so the shipped kinds still
    # place in their own order and the pinned slots are simply theirs.
    return out


def _copy_cache(src_cache: bytes, p: _Placed) -> set[str]:
    """A placed copy's cache: the original's closure, its own line instead of
    the original's (which is not in the pool and needs no preload)."""
    return (set(RC.parse(src_cache)) - {RC.entry_for(p.src_rel)}) | {RC.entry_for(p.rel)}


def _paint(map_id: str, tg: bytes, root: bytes, recipe: TG.TileGen, strokes,
           folder: str, swaps: dict[str, str]) -> dict:
    """Lay `strokes` on the base terrain; re-seat the recipe's slots on it.

    Adds the terrain and scenery clones to `swaps` and returns their bytes."""
    if not isinstance(strokes, list) or not strokes:
        raise ContentError(f"map {map_id}: 'terrain' is a list of brush strokes")
    terrain_refs = [r for r in PC._refs_doc("oCGameStream", tg)[1]["asset_refs"]
                    if r.endswith("_Terrain.level.ot")]
    scenery_refs = [r for r in PC._refs_doc("oCGameStream", root)[1]["asset_refs"]
                    if r.endswith("_Scenery.level.ot")]
    if len(terrain_refs) != 1 or len(scenery_refs) != 1:
        raise ContentError(f"map {map_id}: expected one terrain and one scenery level, "
                           f"found {terrain_refs} and {scenery_refs}")
    terrain_ref, scenery_ref = terrain_refs[0], scenery_refs[0]
    scenery = _read(PC.level_cooked_path(scenery_ref), "the base map's scenery level")
    if terrain_ref not in PC._refs_doc("oCGameStream", scenery)[1]["asset_refs"]:
        raise ContentError(f"map {map_id}: {scenery_ref} does not name {terrain_ref}; "
                           f"the clone's layout assumption no longer holds")
    raw = _read(PC.level_cooked_path(terrain_ref), "the base map's terrain level")
    names = {st.get("layer", TR.HEIGHT) for st in strokes if isinstance(st, dict)} | {TR.HEIGHT}
    try:
        t = TR.read(raw, names)
        TR.apply_strokes(t, strokes)
        painted = TR.write(raw, t)
    except TR.TerrainError as e:
        raise ContentError(f"map {map_id}: {e}") from e
    for s in recipe.slots.values():
        if s.kinds:
            y = t.height_at(s.pos[0], s.pos[2])
            if abs(y - s.pos[1]) > 0.01:
                s.pos = (s.pos[0], y, s.pos[2])
    for old, tag in ((terrain_ref, "Terrain"), (scenery_ref, "Scenery")):
        swaps[old] = f"{folder}\\Map_{map_id}_{tag}.level.ot"
        if corpus.exists(PC.level_cooked_path(swaps[old])):
            raise ContentError(f"map {map_id}: the clone's level {swaps[old]} collides "
                               f"with a shipped level; pick another id.")
    return {"refs": (terrain_ref, scenery_ref), "terrain": painted, "scenery": scenery}


def _clone_levels(map_id: str, base_stem: str, root_ref: str, out_dir: Path,
                  written: list[Path], edits: dict | None = None, place=None,
                  biome: str = "", strokes=None,
                  ) -> tuple[dict[str, str], TG.TileGen | None, list[_Placed]]:
    """Give the clone its own root + tile-generation levels.

    Returns the ``{old: new}`` refs and the clone's recipe, with ``edits`` (the
    ``tilegen`` kind's vocabulary) applied to it.

    Generation does not follow the mapdef that started the chapter: the
    ``oCDtEntityCpntTileSpawnerSettings`` in ``<Map>_TileGeneration.level``
    names its mapdef by path, and that is where the pool is read. Measured
    2026-09-19: a clone reusing the base's levels still placed the base pool.
    So the tilegen level is cloned with that backref pointed at the clone, and
    the root level is cloned to list the new tilegen level as its sub-level.
    Every other sub-level (terrain, scenery, navmesh) is shared unchanged —
    unless ``strokes`` paint the terrain. Then the terrain level is cloned with
    the strokes laid on, and so is the scenery level, which names the terrain
    too: left alone it would load the vanilla terrain beside the clone's. The
    navmesh is not cloned; the game rebuilds all of it at load from the live
    collision (`rsmm.engine.terrain`). Every slot is re-seated on the painted
    ground, since a slot's recorded height IS the ground under it.

    A map with no tile-generation level (Baba Yaga) has no pool to own; its
    levels are reused as before.
    """
    root = _read(PC.level_cooked_path(root_ref), "the base map's root level")
    _h, doc = PC._refs_doc("oCGameStream", root)
    tilegen = [r for r in doc["asset_refs"] if r.endswith("_TileGeneration.level.ot")]
    if not tilegen:
        if edits or place or strokes:
            raise ContentError(f"map {map_id}: the base is not tile-generated, "
                               f"so there is no recipe or terrain to edit")
        return {}, None, []
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
    recipe = TG.read(tg)
    before = set(recipe.slots)
    placed: list[_Placed] = []
    try:
        if edits and not ME.apply_edits(recipe, edits):
            raise ContentError(f"map {map_id}: every tilegen edit already "
                               f"matches the base recipe")
        if place is not None:
            placed = _place_tiles(map_id, recipe, place, before, biome)
        painted = _paint(map_id, tg, root, recipe, strokes, folder, swaps) if strokes else {}
        if edits or placed or painted:
            tg = TG.write(tg, recipe)
    except (ME.MapEditError, TG.TileGenError) as e:
        raise ContentError(f"map {map_id}: tilegen: {e}") from e
    tg_swaps = {base_mapdef: MC.mapdef_asset_path(map_id)}
    root_swaps = {tg_ref: swaps[tg_ref]}
    out = {}
    if painted:
        terrain_ref, scenery_ref = painted["refs"]
        tg_swaps[terrain_ref] = swaps[terrain_ref]
        root_swaps[scenery_ref] = swaps[scenery_ref]
        out[terrain_ref] = PC.clone_tile_level(painted["terrain"], terrain_ref,
                                               swaps[terrain_ref], {})
        out[scenery_ref] = PC.clone_tile_level(painted["scenery"], scenery_ref,
                                               swaps[scenery_ref],
                                               {terrain_ref: swaps[terrain_ref]})
    out[tg_ref] = PC.clone_tile_level(tg, tg_ref, swaps[tg_ref], tg_swaps)
    out[root_ref] = PC.clone_tile_level(root, root_ref, swaps[root_ref], root_swaps)
    for old, blob in out.items():
        dest = out_dir / Path(*PC.level_cooked_path(swaps[old]).split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    return swaps, recipe, placed


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
    edits = defn.fields.get("tilegen")
    if edits is not None and not isinstance(edits, dict):
        raise ContentError(f"map {defn.id}: 'tilegen' must be a table.")

    written: list[Path] = []

    # 1. The clone, on levels of its own so it generates from its own pool.
    base_rel = f"{_MAPS}/{base_stem}{MC.MAP_GEN_SUFFIX}"
    base_bytes = _read(base_rel, f"base map {base!r}")
    root_ref = MC.read_mapdef(base_bytes)["level_ref"][1]
    levels, recipe, placed = _clone_levels(defn.id, base_stem, root_ref, out_dir, written,
                                           edits, defn.fields.get("place"), base,
                                           defn.fields.get("terrain"))
    clone = MC.clone_mapdef(base_bytes, tribe=tribe, level=levels.get(root_ref))
    added: list[str] = []
    removed: list[str] = []
    if "pool" in defn.fields:
        pool = MP.read_pool(clone)
        if pool is None or recipe is None:
            raise ContentError(f"map {defn.id}: {base} is not tile-generated, "
                               f"so it has no pool to edit")
        new_pool, added, removed = _edit_pool(defn.id, pool, defn.fields["pool"],
                                              base, recipe, {p.flag for p in placed})
        clone = MP.set_pool(clone, new_pool)
    if placed:
        clone = MP.add_to_pool(clone, [p.pool_path for p in placed])
        for p in placed:
            # The copy keeps the original's bytes but for one more flag, so its
            # cache is the original's plus its own line.
            td = TC.read(corpus.read(p.src_rel))
            td.kinds = [*td.kinds, p.flag]
            dest = out_dir / Path(*p.rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(TC.write(td))
            written.append(dest)
            src_cache = corpus.read(RC.cache_path_for(p.src_rel))
            if src_cache is None:
                raise ContentError(f"map {defn.id}: placed tile {p.src_rel} ships no "
                                   f"resource cache, so it could never be placed")
            cache_lines = sorted(_copy_cache(src_cache, p))
            cdest = out_dir / Path(*RC.cache_path_for(p.rel).split("/"))
            cdest.write_bytes(RC.render(cache_lines))
            written.append(cdest)
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
    # The map cache lists its pool's tiledefs one for one: a pooled tile with
    # no line is never loaded, so never placed. An added tile's own cache
    # carries that line plus everything the tile reaches.
    for p in removed:
        lines.discard(RC.entry_for(_tile_rel(p)))
    for p in placed:
        lines |= _copy_cache(corpus.read(RC.cache_path_for(p.src_rel)), p)
    for p in added:
        tile_cache = corpus.read(RC.cache_path_for(_tile_rel(p)))
        if tile_cache is None:
            raise ContentError(f"map {defn.id}: pool tile {p} ships no resource "
                               f"cache, so it could never be placed")
        lines |= set(RC.parse(tile_cache))
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
