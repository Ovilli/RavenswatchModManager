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
import sys
from dataclasses import dataclass
from pathlib import Path

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


class MapEditError(ValueError):
    """An edit that does not apply to this recipe."""


@dataclass(frozen=True)
class Chapter:
    """One tile-generated chapter."""

    key: str        # the biome directory, e.g. "DarkHills"
    decoded: str    # decoded asset path of its recipe level

    @property
    def label(self) -> str:
        stem = self.decoded.rsplit("/", 1)[-1].removesuffix(_SUFFIX)
        return stem.removeprefix("Map_").replace("_", " ")


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
            bak = p.with_name(p.name + ".rsmm.bak")
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
        groups.append({"name": name, "flag": s.name, "slots": list(s.slots)})
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
        f"{what}: no models to draw — the editor draws meshes from data/uncooked "
        "(run scripts/extract_uncooked.py once)")


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


@functools.lru_cache(maxsize=4)
def tile_pool_json(chapter: Chapter) -> list[dict]:
    """The tiles this chapter's map may draw, with the flags and size that pick them."""
    from . import map_pool as MP
    from . import map_scene as MS
    from . import tile_cook as TC

    root, path = load(chapter).spawner.mapdef
    mapdef = MS._bytes(root, path)
    pool = MP.read_pool(mapdef) if mapdef else None
    if not pool:
        raise MapEditError(f"{chapter.key}: no tile pool in {path}")
    out = []
    for tile in pool:
        data = MS._bytes(MP.TILE_CATEGORY, tile)
        if not data:
            continue
        try:
            td = TC.read(data)
        except (TC.TileCookError, ValueError):
            continue
        name = tile.rsplit("\\", 1)[-1].removesuffix(".tiledef.ot")
        out.append({"path": tile, "name": name, "flags": list(td.kinds),
                    "width": td.width, "height": td.height, "weight": td.weight})
    return out


@functools.lru_cache(maxsize=256)
def tile_json(chapter: Chapter, tile: str) -> dict:
    """What one pool tile draws, in the tile's own space (centred on its slot)."""
    from . import map_scene as MS
    from . import tile_cook as TC

    if tile not in {t["path"] for t in tile_pool_json(chapter)}:
        raise MapEditError(f"{tile!r} is not in {chapter.key}'s tile pool")
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


def apply_edits(tg: TG.TileGen, edits: dict) -> list[str]:
    """Apply an edit document to `tg` in place and return what changed.

    Every name is resolved and every value range-checked before anything is
    written, so an edit that fails leaves `tg` untouched. The result is run
    through `tilegen.validate`, which is what would reject a recipe the engine
    would misread.
    """
    if not isinstance(edits, dict):
        raise MapEditError("edits must be a table")
    unknown = set(edits) - {"kinds", "quotas", "slots"}
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
        bad = set(se) - {"pos", "allow"}
        if bad:
            raise MapEditError(f"slots.{sid}: unknown field(s) {sorted(bad)}")
        s = tg.slots[sid]
        if "pos" in se:
            pos = se["pos"]
            ok = (isinstance(pos, (list, tuple)) and len(pos) == 3
                  and all(isinstance(a, (int, float)) and not isinstance(a, bool)
                          for a in pos))
            if not ok or any(abs(float(a) - b) > POS_TOLERANCE
                             for a, b in zip(pos, s.pos, strict=True)):
                raise MapEditError(
                    f"slots.{sid}: the edit was made against a slot at {pos}, but slot "
                    f"{sid} is at {[round(v, 3) for v in s.pos]} — the recipe changed "
                    f"since, so this edit no longer points where it was meant to")
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

    for fn, _ in plan:
        fn()
    TG.validate(tg)
    return [d for _, d in plan]


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
        return repr(round(v, 6))
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    raise MapEditError(f"cannot write {v!r} into a manifest")


def manifest_toml(mod_id: str, name: str, chapter: Chapter, edits: dict) -> str:
    """A complete mod manifest carrying `edits` as one ``tilegen`` declaration."""
    if not valid_mod_id(mod_id):
        raise MapEditError(
            f"mod id {mod_id!r}: use 2-64 lower-case letters, digits, '-' or '_'")
    lines = [
        EDITOR_MARK + " Hand edits are fine; the editor reads this file back.",
        "",
        "[mod]",
        f"id          = {_q(mod_id)}",
        f"name        = {_q(name or mod_id)}",
        'version     = "0.1.0"',
        'author      = "RSMM map editor"',
        f"description = {_q(f'Map generation changes for {chapter.label}.')}",
        'sdk_version = ">=3.0,<4"',
        'license     = "MIT"',
        'tags        = ["maps", "generation"]',
        "# The tilegen kind is rated experimental: an edited recipe has not yet",
        "# been shown to change what generates.",
        "experimental = true",
        "# The host generates the map, so only the host's copy decides the layout.",
        'multiplayer_scope = "host-authoritative"',
        "",
        "[[content]]",
        'kind    = "tilegen"',
        f"id      = {_q(chapter.key.lower())}",
        f"chapter = {_q(chapter.key)}",
    ]
    for kname, ke in sorted((edits.get("kinds") or {}).items()):
        scalars = {k: v for k, v in ke.items() if k != "footprints"}
        if scalars:
            lines += ["", f"[content.kinds.{_q(kname)}]"]
            lines += [f"{k} = {_val(v)}" for k, v in scalars.items()]
        if ke.get("footprints"):
            lines += ["", f"[content.kinds.{_q(kname)}.footprints]"]
            lines += [f"{_q(g)} = {_val(on)}" for g, on in ke["footprints"].items()]
    if edits.get("quotas"):
        lines += ["", "[content.quotas]"]
        lines += [f"{_q(k)} = {_val(v)}" for k, v in sorted(edits["quotas"].items())]
    for sid, se in sorted((edits.get("slots") or {}).items(), key=lambda kv: int(kv[0])):
        lines += ["", f"[content.slots.{_q(str(sid))}]"]
        if "pos" in se:
            lines.append(f"pos   = {_val([float(x) for x in se['pos']])}")
        if se.get("allow"):
            inner = ", ".join(f"{_q(k)} = {_val(v)}" for k, v in se["allow"].items())
            lines.append(f"allow = {{ {inner} }}")
    text = "\n".join(lines) + "\n"

    # Prove it reads back as exactly these edits before anyone writes it.
    back = read_manifest_edits(text)
    if back is None or back[0] != chapter.key or not _same_edits(back[1], edits):
        raise MapEditError(
            "internal: the manifest did not read back as the edits it was built from")
    return text


def _same_edits(a: dict, b: dict) -> bool:
    import json

    def norm(e):
        return json.loads(json.dumps({k: v for k, v in (e or {}).items() if v}, sort_keys=True))
    return norm(a) == norm(b)


def read_manifest_edits(text: str) -> tuple[str, dict] | None:
    """``(chapter, edits)`` from the first tilegen declaration in a manifest."""
    import tomllib

    data = tomllib.loads(text)
    for c in data.get("content") or []:
        if c.get("kind") == "tilegen":
            edits = {k: c[k] for k in ("kinds", "quotas", "slots") if c.get(k)}
            return str(c.get("chapter", "")), edits
    return None
