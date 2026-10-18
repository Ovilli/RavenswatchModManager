"""The Map tab: a chapter's map-generation recipe, on its own terrain.

Shows every tile slot of a chapter on a 3D (or top-down) view of the chapter's
terrain, read from the install at request time, and lets you change how many
of each kind of tile the generator places, how far apart, which footprints
each kind fits, the per-flag quotas, which footprint groups fill their
leftover spots, and which kinds a slot may hold. Saving writes a normal mod
(``mods/<id>/manifest.toml``): either one ``tilegen`` declaration that changes
the chapter itself, or one ``map`` declaration — a clone of the chapter's map
with its own recipe and tile pool, which the chapter then plays. Pool edits
only exist on a clone. The page is ``pages/map.html``.
"""

from __future__ import annotations

import secrets
import tempfile
import tomllib
from pathlib import Path

from rsmm.cli.editor import tiles as _tiles  # the 3D tile mode's routes
from rsmm.cli.editor.app import Fail, Raw, Request, asset_dir
from rsmm.engine import map_editor as ME
from rsmm.engine import map_scene as MS

MOUNT = "map"
PAGE = "map.html"

#: three.js, vendored so the page works offline (and in the web editor).
STATIC_FILES = {"three.module.min.js": "text/javascript; charset=utf-8"}
#: What /api/file serves: meshes and textures under 3D/, nothing else.
FILE_ROOT = "3D"
FILE_TYPES = {".glb": "model/gltf-binary", ".png": "image/png"}
NEXT_STEP = "rsmm restore --all && rsmm apply"
#: Brush dabs one save may carry; a long painting session is a few thousand.
MAX_STROKES = 20000


def _editor_mods(root: Path) -> list[dict]:
    """Mods this editor wrote, with the chapter each one edits."""
    out = []
    if not root.is_dir():
        return out
    for man in sorted(root.glob("*/manifest.toml")):
        try:
            text = man.read_text(encoding="utf-8")
            if not text.startswith(ME.EDITOR_MARK):
                continue
            got = ME.read_manifest(text)
        except (OSError, ValueError):
            continue
        if got:
            out.append({"id": man.parent.name, "chapter": got["chapter"],
                        "map": bool(got["map"])})
    return out


def _chapter(name: str) -> ME.Chapter:
    return ME.find_chapter(name)


def _state(req: Request) -> dict:
    return {"chapters": [{"key": c.key, "label": c.label} for c in ME.chapters()],
            "mods": _editor_mods(req.ctx.mods_dir)}


def _recipe(req: Request) -> dict:
    ch = _chapter(req.arg("chapter"))
    return {"chapter": {"key": ch.key, "label": ch.label}, "recipe": ME.to_json(ME.load(ch))}


def _static(req: Request) -> Raw:
    name = req.path.removeprefix("/static/")
    f = asset_dir("static") / name
    if name not in STATIC_FILES or not f.is_file():
        raise Fail(404, "not found")
    return Raw(f.read_bytes(), STATIC_FILES[name], cache=True)


def _file(req: Request) -> Raw:
    """A mesh (``.glb``) or texture (``.png``) under ``3D/``, or 404.

    Served from the dev mirror when a checkout has one, else converted from the
    cooked file in the user's own install (:func:`map_scene.asset_bytes`) —
    which is the only source on a player's machine and in the web editor.
    """
    rel = req.arg("path")
    parts = rel.split("/")
    ctype = FILE_TYPES.get(Path(rel).suffix.lower())
    if (not ctype or parts[0] != FILE_ROOT or len(parts) < 2 or "\\" in rel
            or any(s in ("", ".", "..") for s in parts)):
        raise Fail(404, "not found")
    data = MS.asset_bytes(rel)
    if data is None:
        raise Fail(404, "not found")
    return Raw(data, ctype, cache=True)


def _drawn(what):
    """Read from the user's own install or local mirror on request. A 404
    just means the page draws less."""
    def route(req: Request):
        ch = _chapter(req.arg("chapter"))
        try:
            return what(req, ch)
        except ME.MapEditError as e:
            raise Fail(404, str(e)) from e
    return route


def _terrain(req: Request, ch: ME.Chapter) -> dict:
    g = req.arg("grid")
    grid = int(g) if g.isdigit() else ME.TERRAIN_GRID
    if grid not in ME.TERRAIN_GRIDS:
        raise Fail(400, "bad grid")
    return ME.terrain_json(ch, grid)


def _mod(req: Request) -> dict:
    mod_id = req.arg("id")
    if not ME.valid_mod_id(mod_id):
        raise Fail(400, "bad mod id")
    man = req.ctx.mods_dir / mod_id / "manifest.toml"
    text = man.read_text(encoding="utf-8") if man.is_file() else ""
    got = ME.read_manifest(text) if text.startswith(ME.EDITOR_MARK) else None
    if not got:
        raise Fail(404, f"{mod_id} is not a map-editor mod")
    name = tomllib.loads(text).get("mod", {}).get("name", "")
    return {**got, "name": name}


def _as_map(body: dict) -> dict | None:
    m = body.get("map")
    if m is None:
        return None
    if not isinstance(m, dict):
        raise Fail(400, "map: expected an object")
    pool = m.get("pool") or {}
    if not isinstance(pool, dict) or not all(
            isinstance(pool.get(k, []), list) and all(isinstance(p, str) for p in pool.get(k, []))
            for k in ("add", "remove")):
        raise Fail(400, "map.pool: expected {add: [paths], remove: [paths]}")
    place = m.get("place") or {}
    if not isinstance(place, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in place.items()):
        raise Fail(400, "map.place: expected {slot: \"<Biome>/<Tile>\"}")
    terrain = m.get("terrain") or []
    if not isinstance(terrain, list) or len(terrain) > MAX_STROKES or not all(
            isinstance(st, dict) for st in terrain):
        raise Fail(400, f"map.terrain: expected at most {MAX_STROKES} brush strokes")
    return {"id": str(m.get("id", "")).strip(), "play": bool(m.get("play")),
            "pool": {k: list(pool.get(k) or []) for k in ("add", "remove")},
            "place": place, "terrain": terrain}


def _changes(ch: ME.Chapter, edits: dict, as_map: dict | None) -> list[str]:
    """What saving would change, proven to cook before anything is written.

    A clone is proven by the `map` kind itself, on the very manifest text the
    save would write, so what the page checks is what ``rsmm apply`` builds.
    """
    _level, changes = ME.build_level(ch, edits)
    if as_map is None:
        return changes
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import maps as map_kind

    text = ME.manifest_toml("map-check", "", ch, edits, as_map)
    block = tomllib.loads(text)["content"][0]
    fields = {k: v for k, v in block.items() if k not in ("kind", "id")}
    with tempfile.TemporaryDirectory() as out:
        map_kind.emit("map-check", ContentDef("map", block["id"], fields), Path(out))
    pool = as_map["pool"]
    return (changes + [f"pool: + {p}" for p in pool["add"]]
            + [f"pool: - {p}" for p in pool["remove"]]
            + [f"place: {t} on slot {k}" for k, t in as_map["place"].items()]
            + ([f"terrain: {len(as_map['terrain'])} brush strokes"] if as_map["terrain"] else []))


def _check(req: Request) -> dict:
    ch = _chapter(str(req.body.get("chapter", "")))
    return {"changes": _changes(ch, req.body.get("edits") or {}, _as_map(req.body))}


def _save(req: Request) -> dict:
    body = req.body
    ch = _chapter(str(body.get("chapter", "")))
    edits = body.get("edits") or {}
    mod_id = str(body.get("mod_id", "")).strip().lower()
    if not ME.valid_mod_id(mod_id):
        raise Fail(400, "mod id: use 2-64 lower-case letters, digits, '-' or '_'")
    as_map = _as_map(body)
    changes = _changes(ch, edits, as_map)          # prove it cooks before writing
    if not changes:
        raise Fail(400, "nothing to save: every value matches the shipped recipe")
    name = str(body.get("name", "")).strip()[:80]
    text = ME.manifest_toml(mod_id, name, ch, edits, as_map)
    folder = req.ctx.mods_dir / mod_id
    man = folder / "manifest.toml"
    if man.is_file() and not man.read_text(encoding="utf-8").startswith(ME.EDITOR_MARK):
        raise Fail(409, f"mods/{mod_id} already exists and was not made by the map "
                        f"editor; pick another id")
    folder.mkdir(parents=True, exist_ok=True)
    tmp = man.with_name(f"manifest.toml.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(man)
    return {"path": f"mods/{mod_id}/manifest.toml", "changes": changes, "next": NEXT_STEP}


#: GET routes whose answer depends only on game data (see diskcache).
CACHED = frozenset({
    "/api/scene", "/api/tiles", "/api/catalog", "/api/layers", "/api/layer",
    "/api/tile", "/api/terrain",
}) | _tiles.CACHED

ROUTES = {
    ("GET", "/api/state"): _state,
    ("GET", "/api/recipe"): _recipe,
    ("GET", "/static/*"): _static,
    ("GET", "/api/file"): _file,
    ("GET", "/api/terrain"): _drawn(_terrain),
    ("GET", "/api/scene"): _drawn(lambda req, ch: ME.scene_json(ch)),
    ("GET", "/api/tiles"): _drawn(lambda req, ch: {"tiles": ME.tile_pool_json(ch)}),
    ("GET", "/api/catalog"): lambda req: {"tiles": ME.tile_catalog_json()},
    ("GET", "/api/layers"): _drawn(lambda req, ch: ME.terrain_layers_json(ch)),
    ("GET", "/api/layer"): _drawn(lambda req, ch: ME.terrain_layer_json(ch, req.arg("name"))),
    ("GET", "/api/tile"): _drawn(lambda req, ch: ME.tile_json(ch, req.arg("path"))),
    ("GET", "/api/mod"): _mod,
    ("POST", "/api/check"): _check,
    ("POST", "/api/save"): _save,
    **_tiles.ROUTES,
}
