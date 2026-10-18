"""Editing a chapter's map-generation recipe by NAME.

`rsmm.engine.tilegen` reads and writes the recipe byte-exactly, but it speaks in
object ids and per-index masks. This module is the layer a person edits through:

* `chapters()` finds the tile-generated chapters the game ships;
* `vanilla_level(chapter)` returns the SHIPPED bytes of one recipe;
* `to_json(tg)` flattens a recipe into what the editor draws;
* `apply_edits(tg, edits)` applies an edit document keyed by kind, footprint and
  flag names, and `edits_json_errors` checks one without touching bytes.

The edit document is also what the `tilegen` content kind stores in a mod
manifest, so the editor and `rsmm apply` share one vocabulary::

    {
      "kinds":  {"Camp": {"count": 8, "min_distance": 80.0,
                          "footprints": {"40x40": true, "64x64": false}}},
      "quotas": {"Wishing_Well": 2},
      "slots":  {"42": {"pos": [x, y, z], "allow": {"Camp": true}}}
    }

Names rather than indices, because an index silently means a different kind
the day a patch reorders the list, while a missing name fails loudly. Slots have
no name, so a slot edit carries the position it was made against and is refused
when the slot is no longer there.

Deliberately NOT editable: adding or removing slots or kinds (the object count
is fixed; see `tilegen.write`), and the per-scenario compatibility table.

What that table means, read off the shipped data rather than the engine: per
scenario, per kind, 2 defers to the slot's mask, 1 forces the kind allowed and 0
forbids it. The evidence is Start: in Dark Hills and Storm Island every 40x40
slot has Start OFF in its mask, yet each of the four scenarios carries exactly
one 40x40 slot with Start = 1, a different slot per scenario — which is how the
generator still places one Start per run. The 0s fall on the kinds that must
keep clear of a scenario's start (Teleporter, Camp, Map_Boss, Special). Avalon
ships one scenario and all 2s, and its Start comes from the mask. So a slot's
mask is the default a scenario may override, and eligibility is per scenario.
It is strongly evidenced, not engine-proven, which is why it is shown and not
editable.
"""

from __future__ import annotations

import array
import base64
import functools
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rsmm.engine.paths import BACKUP_SUFFIX

from . import terrain as TR
from . import tilegen as TG
from .paths import DATA_DIR

#: Decoded asset path of every tile-generation recipe, under this prefix.
_PREFIX = "Ot/"
_SUFFIX = "_TileGeneration.level.ot.GameStream.gen"

#: Upper bounds a sane edit stays under. Not engine limits: guard rails that
#: stop a typo (an extra zero) from becoming a recipe that stalls generation.
MAX_COUNT = 500
MAX_DISTANCE = 2000.0
MAX_QUOTA = 500
#: How far a slot may sit from the position its edit was made against.
POS_TOLERANCE = 0.05
#: Bound on an authored slot coordinate; shipped maps sit well inside ±1000 m.
MAX_COORD = 2000.0
MAX_NEW_SLOTS = 500


class MapEditError(ValueError):
    """An edit that does not apply to this recipe."""


@dataclass(frozen=True)
class Chapter:
    """One tile-generated chapter."""

    key: str        # the biome directory, e.g. "DarkHills"
    decoded: str    # decoded asset path of its recipe level

    @property
    def label(self) -> str:
        """The chapter as a player names it: ``Map_Dark_Hills_LiveOps_Update5``
        reads "Dark Hills". Release tags (LiveOps, UpdateN) are dropped."""
        stem = self.decoded.rsplit("/", 1)[-1].removesuffix(_SUFFIX)
        words = stem.removeprefix("Map_").split("_")
        keep = [w for w in words
                if w != "LiveOps" and not (w.startswith("Update") and w[6:].isdigit())]
        return " ".join(keep or words)


def chapters() -> list[Chapter]:
    """Every tile-generation recipe the asset map knows, sorted by key."""
    from .asset_map import decoded_to_encoded

    out = []
    for dec in decoded_to_encoded():
        if dec.startswith(_PREFIX) and dec.endswith(_SUFFIX) and dec.count("/") == 2:
            out.append(Chapter(key=dec.split("/")[1], decoded=dec))
    return sorted(out, key=lambda c: c.key)


def find_chapter(key: str) -> Chapter:
    """Resolve a chapter by biome key (``DarkHills``) or by its full level name."""
    want = key.strip().lower()
    for c in chapters():
        if want in (c.key.lower(), c.decoded.lower(),
                    c.decoded.rsplit("/", 1)[-1].removesuffix(_SUFFIX).lower()):
            return c
    raise MapEditError(
        f"no tile-generated chapter {key!r}; have "
        + ", ".join(c.key for c in chapters()))


def _shipped(decoded: str) -> bytes | None:
    """Shipped bytes of one asset: install backup, install, then data/uncooked."""
    try:
        from .asset_map import decoded_to_encoded
        from .paths import COOKING_SUBDIR, default_game_dir

        enc = decoded_to_encoded().get(decoded)
        if enc:
            p = default_game_dir() / COOKING_SUBDIR / Path(*enc.split("\\"))
            bak = p.with_name(p.name + BACKUP_SUFFIX)
            for cand in (bak, p):
                if cand.is_file():
                    return cand.read_bytes()
    except (OSError, ImportError):
        pass
    mirror = DATA_DIR / "uncooked" / Path(*decoded.split("/"))
    return mirror.read_bytes() if mirror.is_file() else None


def vanilla_level(chapter: Chapter) -> bytes:
    """The SHIPPED recipe bytes for `chapter`.

    Prefers the game install, and within it the `.rsmm.bak` backup when a mod
    has already overridden the file, so an edit is always made against vanilla
    rather than stacked on another mod's output. Falls back to the dev
    checkout's `data/uncooked` mirror. Raises when neither exists.
    """
    data = _shipped(chapter.decoded)
    if data is None:
        raise MapEditError(
            f"{chapter.key}: recipe not found in the game install or in data/uncooked "
            f"({chapter.decoded})")
    return data


def load(chapter: Chapter) -> TG.TileGen:
    return TG.read(vanilla_level(chapter))


# --------------------------------------------------------------------------
# recipe -> editor JSON
# --------------------------------------------------------------------------

def _quota_key(flags: list[str]) -> str:
    return "+".join(flags)


def to_json(tg: TG.TileGen) -> dict:
    """Flatten a recipe into what the editor draws and edits."""
    kind_names = tg.kind_names
    groups = []
    group_of: dict[int, str] = {}
    for sid in tg.spawner.size_ids:
        s = tg.sizes[sid]
        name = f"{s.width}x{s.height}"
        groups.append({"name": name, "flag": s.name, "fill": list(s.filter.required),
                       "slots": list(s.slots)})
        for i in s.slots:
            group_of[i] = name
    whole = tg.spawner.whole_map
    for i in whole.slots:
        group_of[i] = f"{whole.width}x{whole.height}"

    kinds = []
    for kid in tg.spawner.kind_ids:
        k = tg.kinds[kid]
        kinds.append({
            "name": k.name,
            "count": k.count,
            "min_distance": round(k.min_distance, 4),
            "footprints": {g["name"]: bool(v) for g, v in zip(groups, k.footprints, strict=True)},
            "rule": k.rule,
            # The tile flags a kind matches, so the page can pick tiles for it.
            "required": list(k.filter.required),
            "excluded": list(k.filter.excluded),
        })

    slots = []
    for i in sorted(tg.slots):
        s = tg.slots[i]
        slots.append({
            "id": i,
            "pos": [round(v, 4) for v in s.pos],
            "group": group_of.get(i, "?"),
            "whole_map": not s.kinds,
            "allow": {n: bool(v) for n, v in zip(kind_names, s.kinds, strict=False)},
            # Per scenario, only the entries that OVERRIDE the mask: 1 forces
            # the kind allowed, 0 forbids it; 2 (no override) is left out.
            "overrides": [{n: v for n, v in zip(kind_names, row, strict=False) if v != 2}
                          for row in s.compat],
        })

    return {
        "kinds": kinds,
        "groups": groups,
        "whole_map": {"name": f"{whole.width}x{whole.height}", "slots": list(whole.slots)},
        "scenarios": [{"id": sc.id, "label": sc.label} for sc in tg.spawner.scenarios],
        "quotas": [{"key": _quota_key(q.flags), "flags": list(q.flags), "limit": q.limit}
                   for q in tg.spawner.quotas],
        "slots": slots,
        "mapdef": list(tg.spawner.mapdef),
    }


# --------------------------------------------------------------------------
# terrain -> editor JSON
# --------------------------------------------------------------------------

#: Cells per side sent to the page. The painted height is 1024; 256 keeps the
#: payload near 300 KB and the mesh at 65k vertices while slopes stay readable.
TERRAIN_GRID = 256
#: Grids the page may ask for: 512 for the 3D view, where models must sit on the ground.
TERRAIN_GRIDS = (256, 512)
_TERRAIN_SUFFIX = "_Terrain.level.ot.GameStream.gen"
_TERRAIN_LAYERS = {TR.HEIGHT, "LD Path", "LD Block", "Base Water Height"}


def terrain_decoded(chapter: Chapter) -> str | None:
    """Decoded path of the chapter's painted terrain level, when exactly one exists."""
    from .asset_map import decoded_to_encoded

    folder = chapter.decoded.rsplit("/", 1)[0] + "/"
    hits = [d for d in decoded_to_encoded()
            if d.startswith(folder) and d.count("/") == 2 and d.endswith(_TERRAIN_SUFFIX)]
    return hits[0] if len(hits) == 1 else None


def _b64(values: list[float], lo: float, hi: float, bits: int) -> str:
    top = (1 << bits) - 1
    span = (hi - lo) or 1.0
    q = [min(top, max(0, round((v - lo) / span * top))) for v in values]
    arr = array.array("H" if bits == 16 else "B", q)
    if bits == 16 and sys.byteorder != "little":
        arr.byteswap()
    return base64.b64encode(arr.tobytes()).decode("ascii")


@functools.lru_cache(maxsize=4)
def terrain_json(chapter: Chapter, n: int = TERRAIN_GRID) -> dict:
    """The chapter's painted terrain, downsampled for the editor's 3D view.

    Heights are world metres quantised to u16 over ``[y_min, y_max]``; masks are
    u8 over 0..1; water is world metres on the same scale as height. Raises
    `MapEditError` when the terrain is not available locally.
    """
    dec = terrain_decoded(chapter)
    data = _shipped(dec) if dec else None
    if data is None:
        raise MapEditError(f"{chapter.key}: no terrain level in the game install or data/uncooked")
    try:
        tr = TR.read(data, names=_TERRAIN_LAYERS)
    except (TR.TerrainError, TG.TileGenError, ValueError) as e:
        raise MapEditError(f"{chapter.key}: terrain not readable: {e}") from None
    if TR.HEIGHT not in tr.layers:
        raise MapEditError(f"{chapter.key}: terrain has no {TR.HEIGHT!r} layer")
    y0, y1 = tr.box_min[1], tr.box_max[1]
    heights = [y0 + v * (y1 - y0) for v in TR.resample(tr.layers[TR.HEIGHT], n)]
    lo, hi = min(heights), max(heights)
    out = {
        "grid": n,
        "box_min": list(tr.box_min), "box_max": list(tr.box_max),
        "height": {"min": lo, "max": hi, "u16": _b64(heights, lo, hi, 16)},
    }
    for key, name in (("path", "LD Path"), ("block", "LD Block")):
        if name in tr.layers:
            out[key] = _b64(TR.resample(tr.layers[name], n), 0.0, 1.0, 8)
    if "Base Water Height" in tr.layers:
        water = [y0 + v * (y1 - y0) for v in TR.resample(tr.layers["Base Water Height"], n)]
        out["water"] = {"min": lo, "max": hi, "u16": _b64(water, lo, hi, 16)}
    return out


@functools.lru_cache(maxsize=1)
def _terrain_all(chapter: Chapter) -> TR.Terrain:
    """Every painted layer of the chapter's terrain (one chapter kept)."""
    dec = terrain_decoded(chapter)
    data = _shipped(dec) if dec else None
    if data is None:
        raise MapEditError(f"{chapter.key}: no terrain level in the game install or data/uncooked")
    try:
        return TR.read(data)
    except (TR.TerrainError, TG.TileGenError, ValueError) as e:
        raise MapEditError(f"{chapter.key}: terrain not readable: {e}") from None


def terrain_layers_json(chapter: Chapter) -> dict:
    """The chapter's painted layers, for the page's surface brush: name,
    ``float``/``rgba`` and grid size, plus whether a stroke's amount on it is
    metres (a height) or a 0..1 weight."""
    t = _terrain_all(chapter)
    return {"layers": [{"name": n, "kind": lay.kind, "size": lay.size,
                        "metres": n in TR.METRE_LAYERS}
                       for n, lay in t.layers.items()]}


@functools.lru_cache(maxsize=16)
def terrain_layer_json(chapter: Chapter, name: str, n: int = 512) -> dict:
    """One painted layer resampled to ``n`` x ``n`` (cell centres, nearest):
    a float layer as u8 over 0..1, an RGBA layer as ``n*n*4`` bytes."""
    if n not in TERRAIN_GRIDS:
        raise MapEditError(f"grid must be one of {TERRAIN_GRIDS}")
    layer = _terrain_all(chapter).layers.get(name)
    if layer is None:
        raise MapEditError(f"{chapter.key}: no painted layer {name!r}")
    if layer.kind == "float":
        return {"grid": n, "kind": "float", "u8": _b64(TR.resample(layer, n), 0.0, 1.0, 8)}
    s, src, out = layer.size, layer.cells, bytearray(n * n * 4)
    for r in range(n):
        row = min(s - 1, int((r + 0.5) * s / n)) * s
        for c in range(n):
            i = (row + min(s - 1, int((c + 0.5) * s / n))) * 4
            out[(r * n + c) * 4:(r * n + c) * 4 + 4] = src[i:i + 4]
    return {"grid": n, "kind": "rgba", "rgba": base64.b64encode(bytes(out)).decode("ascii")}


# --------------------------------------------------------------------------
# scene -> editor JSON (what the chapter looks like)
# --------------------------------------------------------------------------

#: Chapter levels that hold no placed scenery; skipped rather than decoded.
_NOT_SCENERY = ("_Terrain.level", "_TileGeneration.level", "_NavMeshes.level",
                "_Audio.level", "_Render_Settings.level", "_EntityPooling_Settings.level")


def scenery_levels(chapter: Chapter) -> list[str]:
    """Decoded paths of the chapter's own levels that may place scenery."""
    from .asset_map import decoded_to_encoded

    folder = chapter.decoded.rsplit("/", 1)[0] + "/"
    return sorted(d for d in decoded_to_encoded()
                  if d.startswith(folder) and d.count("/") == 2
                  and d.endswith(".level.ot.GameStream.gen")
                  and not any(s in d for s in _NOT_SCENERY))


def _need_meshes(what: str) -> MapEditError:
    return MapEditError(
        f"{what}: no models to draw — none of the chapter's scenery levels could be "
        "read from the game install")


@functools.lru_cache(maxsize=4)
def scene_json(chapter: Chapter) -> dict:
    """Every mesh instance the chapter's fixed scenery draws, grouped per mesh."""
    from . import map_scene as MS

    parts = []
    for dec in scenery_levels(chapter):
        data = _shipped(dec)
        if data:
            parts.extend(MS.placed_parts(data))
    if not parts:
        raise _need_meshes(chapter.key)
    return MS.to_json(parts)


def _tile_entry(tile: str) -> dict | None:
    """One tile's pool-picking facts, or None when it does not decode."""
    from . import map_pool as MP
    from . import map_scene as MS
    from . import tile_cook as TC

    data = MS._bytes(MP.TILE_CATEGORY, tile)
    if not data:
        return None
    try:
        td = TC.read(data)
    except (TC.TileCookError, ValueError):
        return None
    biome, name = tile.split("\\")[1], tile.rsplit("\\", 1)[-1].removesuffix(".tiledef.ot")
    return {"path": tile, "name": name, "biome": biome, "flags": list(td.kinds),
            "width": td.width, "height": td.height, "weight": td.weight}


@functools.lru_cache(maxsize=4)
def tile_pool_json(chapter: Chapter) -> list[dict]:
    """The tiles this chapter's map may draw, with the flags and size that pick them."""
    from . import map_pool as MP
    from . import map_scene as MS

    root, path = load(chapter).spawner.mapdef
    mapdef = MS._bytes(root, path)
    pool = MP.read_pool(mapdef) if mapdef else None
    if not pool:
        raise MapEditError(f"{chapter.key}: no tile pool in {path}")
    return [e for e in map(_tile_entry, pool) if e]


_TILE_PREFIX = "Definitions/Tiles/"
_TILE_SUFFIX = ".tiledef.ot.DtTileDefinition.gen"


@functools.lru_cache(maxsize=1)
def tile_catalog_json() -> list[dict]:
    """Every tile the game ships, any biome: what a map clone's pool may borrow.

    Listed from the asset map (which the web editor rebuilds from the player's
    own install), so it works wherever the pool view does.
    """
    from .asset_map import decoded_to_encoded

    paths = sorted("Tiles\\" + d[len(_TILE_PREFIX):-len(_TILE_SUFFIX)].replace("/", "\\")
                   + ".tiledef.ot"
                   for d in decoded_to_encoded()
                   if d.startswith(_TILE_PREFIX) and d.endswith(_TILE_SUFFIX))
    return [e for e in map(_tile_entry, paths) if e]


@functools.lru_cache(maxsize=256)
def tile_json(chapter: Chapter, tile: str) -> dict:
    """What one tile draws, in the tile's own space (centred on its slot). Any
    shipped tile, so a tile borrowed into a clone's pool previews too."""
    from . import map_scene as MS
    from . import tile_cook as TC

    if tile not in {t["path"] for t in tile_catalog_json()}:
        raise MapEditError(f"{tile!r} is not a shipped tile")
    from .map_pool import TILE_CATEGORY

    td = TC.read(MS._bytes(TILE_CATEGORY, tile))
    if len(td.entity_ref) != 2 or td.entity_ref[0] != "EntitySettings":
        raise MapEditError(f"{tile}: tile does not name an entity")
    # Empty is legitimate: some tiles only shape terrain (stairs, paths).
    return MS.to_json(list(MS.entity_parts(td.entity_ref[1])))


# --------------------------------------------------------------------------
# edits
# --------------------------------------------------------------------------

def _as_int(v, what: str, lo: int, hi: int) -> int:
    if (isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v != int(v)):
        raise MapEditError(f"{what}: expected a whole number, got {v!r}")
    v = int(v)
    if not lo <= v <= hi:
        raise MapEditError(f"{what}: {v} is outside {lo}..{hi}")
    return v


def _as_float(v, what: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise MapEditError(f"{what}: expected a number, got {v!r}")
    if not lo <= float(v) <= hi:
        raise MapEditError(f"{what}: {v} is outside {lo}..{hi}")
    return float(v)


def _as_bool(v, what: str) -> bool:
    if not isinstance(v, bool):
        raise MapEditError(f"{what}: expected true or false, got {v!r}")
    return v


#: Every section an edit document may carry, in the order they apply.
EDIT_SECTIONS = ("kinds", "quotas", "slots", "fill", "remove_slots", "add_slots")


def apply_edits(tg: TG.TileGen, edits: dict) -> list[str]:
    """Apply an edit document to `tg` in place and return what changed.

    Every name is resolved and every value range-checked before anything is
    written, so an edit that fails leaves `tg` untouched. The result is run
    through `tilegen.validate`, which is what would reject a recipe the engine
    would misread.
    """
    if not isinstance(edits, dict):
        raise MapEditError("edits must be a table")
    unknown = set(edits) - set(EDIT_SECTIONS)
    if unknown:
        raise MapEditError(f"unknown edit section(s): {', '.join(sorted(unknown))}")

    kind_names = tg.kind_names
    by_kind = {tg.kinds[kid].name: tg.kinds[kid] for kid in tg.spawner.kind_ids}
    group_names = tg.size_names
    if len(set(group_names)) != len(group_names):
        raise MapEditError(f"footprint groups are not uniquely named: {group_names}")
    by_quota = {_quota_key(q.flags): q for q in tg.spawner.quotas}

    plan: list[tuple] = []   # (callable, description)

    for name, ke in (edits.get("kinds") or {}).items():
        if name not in by_kind:
            raise MapEditError(f"no kind named {name!r}; have {kind_names}")
        if not isinstance(ke, dict):
            raise MapEditError(f"kinds.{name}: expected a table")
        bad = set(ke) - {"count", "min_distance", "footprints"}
        if bad:
            raise MapEditError(f"kinds.{name}: unknown field(s) {sorted(bad)}")
        k = by_kind[name]
        if "count" in ke:
            v = _as_int(ke["count"], f"kinds.{name}.count", 0, MAX_COUNT)
            if v != k.count:
                plan.append((lambda k=k, v=v: setattr(k, "count", v),
                             f"{name}: count {k.count} -> {v}"))
        if "min_distance" in ke:
            v = _as_float(ke["min_distance"], f"kinds.{name}.min_distance", 0.0, MAX_DISTANCE)
            if abs(v - k.min_distance) > 1e-4:
                plan.append((lambda k=k, v=v: setattr(k, "min_distance", v),
                             f"{name}: min distance {k.min_distance:g} -> {v:g}"))
        for gname, on in (ke.get("footprints") or {}).items():
            if gname not in group_names:
                raise MapEditError(
                    f"kinds.{name}.footprints: no footprint group {gname!r}; have {group_names}")
            on = _as_bool(on, f"kinds.{name}.footprints.{gname}")
            gi = group_names.index(gname)
            if bool(k.footprints[gi]) != on:
                plan.append((lambda k=k, gi=gi, on=on: k.footprints.__setitem__(gi, 1 if on else 0),
                             f"{name}: footprint {gname} {'on' if on else 'off'}"))

    for key, limit in (edits.get("quotas") or {}).items():
        if key not in by_quota:
            raise MapEditError(f"no flag quota {key!r}; have {sorted(by_quota)}")
        q = by_quota[key]
        v = _as_int(limit, f"quotas.{key}", 0, MAX_QUOTA)
        if v != q.limit:
            plan.append((lambda q=q, v=v: setattr(q, "limit", v),
                         f"quota {key}: {q.limit} -> {v}"))

    for sid_raw, se in (edits.get("slots") or {}).items():
        try:
            sid = int(sid_raw)
        except (TypeError, ValueError):
            raise MapEditError(f"slots: {sid_raw!r} is not a slot id") from None
        if sid not in tg.slots:
            raise MapEditError(f"slots.{sid}: no such slot in this recipe")
        if not isinstance(se, dict):
            raise MapEditError(f"slots.{sid}: expected a table")
        bad = set(se) - {"pos", "allow", "move"}
        if bad:
            raise MapEditError(f"slots.{sid}: unknown field(s) {sorted(bad)}")
        s = tg.slots[sid]
        if "pos" in se:
            _anchor(tg, sid, se["pos"], f"slots.{sid}")
        if "move" in se:
            if not s.kinds:
                raise MapEditError(f"slots.{sid}: whole-map slots do not move")
            to = _as_pos(se["move"], f"slots.{sid}.move")
            if to != s.pos:
                plan.append((lambda s=s, to=to: setattr(s, "pos", to),
                             f"slot {sid}: moved to {[round(v, 2) for v in to]}"))
        allow = se.get("allow") or {}
        if allow and not s.kinds:
            raise MapEditError(
                f"slots.{sid}: a whole-map slot has no kind mask; its emptiness is "
                f"what makes it one, so it cannot be given kinds")
        for kname, on in allow.items():
            if kname not in kind_names:
                raise MapEditError(f"slots.{sid}.allow: no kind named {kname!r}")
            on = _as_bool(on, f"slots.{sid}.allow.{kname}")
            ki = kind_names.index(kname)
            if bool(s.kinds[ki]) != on:
                # Keep a shipped non-1 value when the slot already allows it;
                # only a real toggle writes.
                plan.append((lambda s=s, ki=ki, on=on: s.kinds.__setitem__(ki, 1 if on else 0),
                             f"slot {sid}: {kname} {'allowed' if on else 'removed'}"))

    # The FILL pass (TileSpawn_PlaceTiles, after the per-kind loop): every
    # footprint group whose flag filter is non-empty fills each slot still EMPTY
    # with a pool tile carrying those flags. Dark Hills' 40x40/64x64 groups fill
    # with "Camp", which is why a map has 8-9 camps whatever the Camp kind's
    # count says — the count only decides how many land before the fill.
    # An empty list leaves the group's leftover slots empty.
    groups = {n: tg.sizes[i] for n, i in zip(group_names, tg.spawner.size_ids, strict=True)}
    for gname, flags in (edits.get("fill") or {}).items():
        if gname not in groups:
            raise MapEditError(f"fill: no footprint group {gname!r}; have {group_names}")
        if not (isinstance(flags, list) and all(isinstance(f, str) and f for f in flags)):
            raise MapEditError(f"fill.{gname}: expected a list of flag names, [] for no fill")
        g = groups[gname]
        if list(flags) != g.filter.required:
            plan.append((lambda g=g, flags=list(flags): setattr(g.filter, "required", flags),
                         f"fill {gname}: {g.filter.required} -> {list(flags) or 'nothing'}"))

    # Removals and additions change the object count. They run after every
    # edit above, which names slots by their SHIPPED ids, and `tilegen.write`
    # renumbers the result.
    for sid_raw, pos in (edits.get("remove_slots") or {}).items():
        try:
            sid = int(sid_raw)
        except (TypeError, ValueError):
            raise MapEditError(f"remove_slots: {sid_raw!r} is not a slot id") from None
        if sid not in tg.slots:
            raise MapEditError(f"remove_slots.{sid}: no such slot in this recipe")
        _anchor(tg, sid, pos, f"remove_slots.{sid}")
        if not tg.slots[sid].kinds:
            raise MapEditError(f"remove_slots.{sid}: whole-map slots are not removable")
        plan.append((lambda sid=sid: TG.remove_slot(tg, sid), f"slot {sid}: removed"))

    added = edits.get("add_slots") or []
    if not isinstance(added, list) or len(added) > MAX_NEW_SLOTS:
        raise MapEditError(f"add_slots: expected a list of at most {MAX_NEW_SLOTS} slots")
    for n, se in enumerate(added):
        what = f"add_slots[{n}]"
        if not isinstance(se, dict) or set(se) - {"group", "pos", "allow"}:
            raise MapEditError(f"{what}: expected {{group, pos, allow}}")
        if se.get("group") not in group_names:
            raise MapEditError(f"{what}.group: no footprint group {se.get('group')!r}; "
                               f"have {group_names}")
        pos = _as_pos(se.get("pos"), f"{what}.pos")
        allow = se.get("allow") or {}
        if not isinstance(allow, dict):
            raise MapEditError(f"{what}.allow: expected a table of kind = true/false")
        for kname, on in allow.items():
            if kname not in kind_names:
                raise MapEditError(f"{what}.allow: no kind named {kname!r}")
            _as_bool(on, f"{what}.allow.{kname}")
        plan.append((lambda g=se["group"], pos=pos, allow=dict(allow):
                     TG.add_slot(tg, g, pos, allow),
                     f"slot added: {se['group']} at {[round(v, 2) for v in pos]}"))

    for fn, _ in plan:
        fn()
    TG.validate(tg)
    return [d for _, d in plan]


def _as_pos(v, what: str) -> tuple[float, float, float]:
    if not (isinstance(v, (list, tuple)) and len(v) == 3):
        raise MapEditError(f"{what}: expected [x, y, z]")
    return tuple(_as_float(a, what, -MAX_COORD, MAX_COORD) for a in v)


def _anchor(tg: TG.TileGen, sid: int, pos, what: str) -> None:
    """Refuse an edit made against a slot that is no longer where it was."""
    s = tg.slots[sid]
    ok = (isinstance(pos, (list, tuple)) and len(pos) == 3
          and all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in pos))
    if not ok or any(abs(float(a) - b) > POS_TOLERANCE for a, b in zip(pos, s.pos, strict=True)):
        raise MapEditError(
            f"{what}: the edit was made against a slot at {pos}, but slot "
            f"{sid} is at {[round(v, 3) for v in s.pos]} — the recipe changed "
            f"since, so this edit no longer points where it was meant to")


def edits_json_errors(tg: TG.TileGen, edits: dict) -> str | None:
    """Why `edits` would not apply to a COPY of `tg`, or None when it would."""
    import copy

    try:
        apply_edits(copy.deepcopy(tg), edits)
    except (MapEditError, TG.TileGenError) as e:
        return str(e)
    return None


def build_level(chapter: Chapter, edits: dict) -> tuple[bytes, list[str]]:
    """The shipped recipe with `edits` applied, ready to write, and the changes."""
    raw = vanilla_level(chapter)
    tg = TG.read(raw)
    changes = apply_edits(tg, edits)
    return TG.write(raw, tg), changes


# --------------------------------------------------------------------------
# a mod manifest carrying the edits
# --------------------------------------------------------------------------

#: Marks a manifest this editor wrote, so saving never overwrites a hand-made mod.
EDITOR_MARK = "# Written by rsmm map-editor."
_MOD_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


def valid_mod_id(mod_id: str) -> bool:
    """Lower-case id usable as a folder name: letters, digits, dash, underscore."""
    return (isinstance(mod_id, str) and 2 <= len(mod_id) <= 64
            and mod_id[0].isalnum() and set(mod_id) <= _MOD_ID_CHARS)


def _q(s: str) -> str:
    """A TOML basic string. JSON string escaping is valid TOML for these keys."""
    import json

    return json.dumps(str(s), ensure_ascii=False)


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # repr, not a rounding: it reads back as exactly this float, which the
        # manifest's read-back check demands (a terrain height has 15 digits).
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    raise MapEditError(f"cannot write {v!r} into a manifest")


#: The `map` kind's ``base`` for each tile-generated chapter, and the
#: All_Chapters chapter object that plays it (see `rsmm.sdk.kinds.maps`).
MAP_BASES: dict[str, tuple[str, int]] = {
    "DarkHills": ("Dark_Hills", 0), "Storm_Island": ("Storm_Island", 1),
    "Avalon": ("Avalon", 2),
}
_MAP_ID_FIRST = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_MAP_ID_CHARS = _MAP_ID_FIRST | set("0123456789_")


def valid_map_id(map_id: str) -> bool:
    """A map clone's id becomes its mapdef's file name: a letter, then letters,
    digits and underscores."""
    return (isinstance(map_id, str) and 2 <= len(map_id) <= 64
            and map_id[0] in _MAP_ID_FIRST and set(map_id) <= _MAP_ID_CHARS)


def _pool_name(path: str) -> str:
    """``Tiles\\Avalon\\X.tiledef.ot`` -> ``Avalon/X``, the map kind's spelling."""
    parts = path.split("\\")
    if len(parts) != 3 or parts[0] != "Tiles" or not parts[2].endswith(".tiledef.ot"):
        raise MapEditError(f"not a tile path: {path!r}")
    return f"{parts[1]}/{parts[2].removesuffix('.tiledef.ot')}"


def _pool_path(name: str, biome: str) -> str:
    """The inverse; a bare name means the base's own biome, as the kind reads it."""
    where, _, stem = name.rpartition("/")
    return f"Tiles\\{where or biome}\\{stem}.tiledef.ot"


def _edit_lines(table: str, edits: dict) -> list[str]:
    lines: list[str] = []
    for kname, ke in sorted((edits.get("kinds") or {}).items()):
        scalars = {k: v for k, v in ke.items() if k != "footprints"}
        if scalars:
            lines += ["", f"[{table}.kinds.{_q(kname)}]"]
            lines += [f"{k} = {_val(v)}" for k, v in scalars.items()]
        if ke.get("footprints"):
            lines += ["", f"[{table}.kinds.{_q(kname)}.footprints]"]
            lines += [f"{_q(g)} = {_val(on)}" for g, on in ke["footprints"].items()]
    if edits.get("quotas"):
        lines += ["", f"[{table}.quotas]"]
        lines += [f"{_q(k)} = {_val(v)}" for k, v in sorted(edits["quotas"].items())]
    if edits.get("fill"):
        lines += ["", f"[{table}.fill]"]
        lines += [f"{_q(g)} = [{', '.join(_q(f) for f in v)}]"
                  for g, v in sorted(edits["fill"].items())]
    for sid, se in sorted((edits.get("slots") or {}).items(), key=lambda kv: int(kv[0])):
        lines += ["", f"[{table}.slots.{_q(str(sid))}]"]
        if "pos" in se:
            lines.append(f"pos   = {_val([float(x) for x in se['pos']])}")
        if "move" in se:
            lines.append(f"move  = {_val([float(x) for x in se['move']])}")
        if se.get("allow"):
            inner = ", ".join(f"{_q(k)} = {_val(v)}" for k, v in se["allow"].items())
            lines.append(f"allow = {{ {inner} }}")
    if edits.get("remove_slots"):
        lines += ["", f"[{table}.remove_slots]"]
        lines += [f"{_q(str(k))} = {_val([float(x) for x in v])}"
                  for k, v in sorted(edits["remove_slots"].items(), key=lambda kv: int(kv[0]))]
    for se in edits.get("add_slots") or []:
        lines += ["", f"[[{table}.add_slots]]", f"group = {_q(se['group'])}",
                  f"pos   = {_val([float(x) for x in se['pos']])}"]
        if se.get("allow"):
            inner = ", ".join(f"{_q(k)} = {_val(v)}" for k, v in se["allow"].items())
            lines.append(f"allow = {{ {inner} }}")
    return lines


def manifest_toml(mod_id: str, name: str, chapter: Chapter, edits: dict,
                  as_map: dict | None = None, scenery: dict | None = None) -> str:
    """A complete mod manifest carrying `edits`.

    Without `as_map`, one ``tilegen`` declaration: the edits apply to the
    chapter itself, in every run. With ``as_map = {"id", "play", "pool"}``, one
    ``map`` declaration instead: a clone of the chapter's map with its own
    recipe (`edits`) and pool (``pool = {"add": [paths], "remove": [paths]}``),
    tiles pinned by hand (``place = {"<slot id>"|"new<N>": "<Biome>/<Tile>"}``)
    and painted terrain (``terrain = [stroke, ...]``, see
    `rsmm.engine.terrain.apply_strokes`); with ``play`` true the chapter plays
    the clone. Pool edits only exist on
    a clone; the vanilla map's pool is shared with every other mod.

    ``scenery = {"<level decoded path>": {"moves", "removes", "adds"}}`` adds
    one ``scenery`` declaration per edited scenery level (see
    `rsmm.engine.scenery_edit`). Those levels belong to the chapter, so the
    edits show in every run of it, clone or not.
    """
    if not valid_mod_id(mod_id):
        raise MapEditError(
            f"mod id {mod_id!r}: use 2-64 lower-case letters, digits, '-' or '_'")
    if as_map is not None:
        if chapter.key not in MAP_BASES:
            raise MapEditError(f"{chapter.key}: no map to clone for this chapter")
        if not valid_map_id(as_map.get("id", "")):
            raise MapEditError(f"map id {as_map.get('id')!r}: a letter, then 1-63 "
                               f"letters, digits or '_'")
    what = "A new map from" if as_map else "Map generation changes for"
    lines = [
        EDITOR_MARK + " Hand edits are fine; the editor reads this file back.",
        "",
        "[mod]",
        f"id          = {_q(mod_id)}",
        f"name        = {_q(name or mod_id)}",
        'version     = "0.1.0"',
        'author      = "RSMM map editor"',
        f"description = {_q(f'{what} {chapter.label}.')}",
        'sdk_version = ">=3.0,<4"',
        'license     = "MIT"',
        'tags        = ["maps", "generation"]',
    ]
    scenery = {lv: e for lv, e in (scenery or {}).items() if any(e.get(k) for k in _SCENERY_KEYS)}
    if scenery:
        lines += ["# Every player loads the chapter's scenery from their own copy, so",
                  "# everyone in the lobby needs this mod at the same version.",
                  'multiplayer_scope = "deterministic-shared"']
    else:
        lines += ["# The host generates the map, so only the host's copy decides the layout.",
                  'multiplayer_scope = "host-authoritative"']
    if as_map is not None or scenery:
        # The map and scenery kinds are rated experimental; lint wants the
        # opt-in said out loud.
        lines.append("experimental = true")
    if as_map is None:
        if edits:
            lines += ["", "[[content]]", 'kind    = "tilegen"',
                      f"id      = {_q(chapter.key.lower())}",
                      f"chapter = {_q(chapter.key)}"]
            lines += _edit_lines("content", edits)
    else:
        base, index = MAP_BASES[chapter.key]
        lines += ["", "[[content]]", 'kind    = "map"',
                  f"id      = {_q(as_map['id'])}", f"base    = {_q(base)}"]
        if as_map.get("play"):
            lines.append(f"chapter = {index}")
        pool = as_map.get("pool") or {}
        parts = [f"{k} = [{', '.join(_q(_pool_name(p)) for p in pool[k])}]"
                 for k in ("add", "remove") if pool.get(k)]
        if parts:
            lines.append(f"pool    = {{ {', '.join(parts)} }}")
        if as_map.get("place"):
            inner = ", ".join(f"{_q(k)} = {_q(v)}" for k, v in as_map["place"].items())
            lines.append(f"place   = {{ {inner} }}")
        for st in as_map.get("terrain") or []:
            lines += ["", "[[content.terrain]]"]
            lines += [f"{k} = {_q(v) if isinstance(v, str) else _val(v)}" for k, v in st.items()]
        lines += _edit_lines("content.tilegen", edits)
    for level, e in sorted(scenery.items()):
        lines += _scenery_lines(chapter, level, e)
    text = "\n".join(lines) + "\n"

    # Prove it reads back as exactly these edits before anyone writes it.
    back = read_manifest(text)
    want_map = None if as_map is None else {
        "id": as_map["id"], "play": bool(as_map.get("play")),
        "pool": {k: list((as_map.get("pool") or {}).get(k) or []) for k in ("add", "remove")},
        "place": dict(as_map.get("place") or {}), "terrain": list(as_map.get("terrain") or [])}
    if (back is None or back["chapter"] != chapter.key
            or not _same_edits(back["edits"], edits) or back["map"] != want_map
            or _norm_json(back.get("scenery") or {}) != _norm_json(scenery)):
        raise MapEditError(
            "internal: the manifest did not read back as the edits it was built from")
    return text


_SCENERY_KEYS = ("moves", "removes", "adds")


def _norm_json(v):
    import json
    return json.loads(json.dumps(v, sort_keys=True))


def _scenery_lines(chapter: Chapter, level: str, e: dict) -> list[str]:
    stem = level.rsplit("/", 1)[-1].split(".", 1)[0]
    out = ["", "[[content]]", 'kind    = "scenery"',
           f"id      = {_q(re.sub(r'[^a-z0-9_]', '_', stem.lower()))}",
           f"chapter = {_q(chapter.key)}", f"level   = {_q(level)}"]
    for section in ("moves", "removes"):
        for oid, spec in sorted((e.get(section) or {}).items(), key=lambda kv: int(kv[0])):
            out += ["", f'[content.{section}."{int(oid)}"]']
            out += [f"{k} = {_q(v) if isinstance(v, str) else _val(v)}" for k, v in spec.items()]
    for a in e.get("adds") or []:
        out += ["", "[[content.adds]]"]
        out += [f"{k} = {_q(v) if isinstance(v, str) else _val(v)}" for k, v in a.items()]
    return out


def _same_edits(a: dict, b: dict) -> bool:
    import json

    def norm(e):
        return json.loads(json.dumps({k: v for k, v in (e or {}).items() if v}, sort_keys=True))
    return norm(a) == norm(b)


_EDIT_KEYS = EDIT_SECTIONS


def read_manifest(text: str) -> dict | None:
    """The first map-editor declaration in a manifest, ``tilegen`` or ``map``::

        {"chapter": "DarkHills", "edits": {...},
         "map": None | {"id", "play", "pool": {"add": [paths], "remove": [paths]}}}
    """
    import tomllib

    data = tomllib.loads(text)
    scenery = {str(c.get("level", "")): {k: c[k] for k in _SCENERY_KEYS if c.get(k)}
               for c in data.get("content") or [] if c.get("kind") == "scenery"}
    got = _read_first(data)
    if got is None and scenery:
        first = next(c for c in data["content"] if c.get("kind") == "scenery")
        got = {"chapter": str(first.get("chapter", "")), "edits": {}, "map": None}
    if got is not None and scenery:
        got["scenery"] = scenery
    return got


def _read_first(data: dict) -> dict | None:
    for c in data.get("content") or []:
        if c.get("kind") == "tilegen":
            return {"chapter": str(c.get("chapter", "")),
                    "edits": {k: c[k] for k in _EDIT_KEYS if c.get(k)}, "map": None}
        if c.get("kind") == "map":
            key = next((k for k, (b, _i) in MAP_BASES.items() if b == c.get("base")), None)
            if key is None:
                continue
            biome = MAP_BASES[key][0]
            tg = c.get("tilegen") or {}
            pool = c.get("pool") or {}
            return {"chapter": key,
                    "edits": {k: tg[k] for k in _EDIT_KEYS if tg.get(k)},
                    "map": {"id": str(c.get("id", "")), "play": "chapter" in c,
                            "pool": {k: [_pool_path(n, biome) for n in pool.get(k) or []]
                                     for k in ("add", "remove")},
                            "place": dict(c.get("place") or {}),
                            "terrain": list(c.get("terrain") or [])}}
    return None


def read_manifest_edits(text: str) -> tuple[str, dict] | None:
    """``(chapter, edits)`` from the first map-editor declaration in a manifest."""
    got = read_manifest(text)
    return (got["chapter"], got["edits"]) if got else None
