"""The map editor's 3D tile mode: walk around a shipped tile, add objects to
it, save a mod.

Its routes live under the map mount as ``/api/t3/...`` (the map already has
``catalog``, ``mod``, ``check`` and ``save`` routes of its own); the page side
is ``pages/tilemode.js`` and the engine side :mod:`rsmm.engine.tile_editor`.
Models and textures come from the map's own file route.
"""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from rsmm.cli.editor.app import Fail, Request
from rsmm.engine import map_editor as ME
from rsmm.engine import tile_editor as TE

NEXT_STEP = "Enable the mod, then run: rsmm apply (or apply it in the desktop app)."


def _wrap(fn):
    def route(req: Request):
        try:
            return fn(req)
        except TE.TileEditError as e:
            raise Fail(400, str(e)) from e
    return route


def _tile_mods(root: Path) -> list[dict]:
    """Mods this editor wrote, with the tiles each one edits."""
    out = []
    if not root.is_dir():
        return out
    for man in sorted(root.glob("*/manifest.toml")):
        try:
            if not man.read_text(encoding="utf-8").startswith(TE.TILE_MARK):
                continue
        except OSError:
            continue
        tiles = []
        for poi in sorted((man.parent / "pois").glob("*/poi.toml")):
            try:
                tiles.append(TE.read_places(poi.read_text(encoding="utf-8"))[0])
            except (OSError, ValueError):
                continue
        out.append({"id": man.parent.name, "tiles": tiles})
    return out


def _mod(req: Request) -> dict:
    mod_id = req.arg("id")
    if not ME.valid_mod_id(mod_id):
        raise Fail(400, "bad mod id")
    folder = req.ctx.mods_dir / mod_id
    man = folder / "manifest.toml"
    if not man.is_file() or not man.read_text(encoding="utf-8").startswith(TE.TILE_MARK):
        raise Fail(404, f"{mod_id} is not a tile-editor mod")
    import tomllib
    name = tomllib.loads(man.read_text(encoding="utf-8")).get("mod", {}).get("name", "")
    tiles = {}
    for poi in sorted((folder / "pois").glob("*/poi.toml")):
        tile, places = TE.read_places(poi.read_text(encoding="utf-8"))
        tiles[tile] = places
    return {"id": mod_id, "name": name, "tiles": tiles}


def _check(req: Request) -> dict:
    return {"files": TE.check(str(req.body.get("tile", "")), req.body.get("places"))}


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _save(req: Request) -> dict:
    body = req.body
    tile = str(body.get("tile", ""))
    places = body.get("places") or []
    mod_id = str(body.get("mod_id", "")).strip().lower()
    if not ME.valid_mod_id(mod_id):
        raise Fail(400, "mod id: use 2-64 lower-case letters, digits, '-' or '_'")
    folder = req.ctx.mods_dir / mod_id
    man = folder / "manifest.toml"
    if man.is_file() and not man.read_text(encoding="utf-8").startswith(TE.TILE_MARK):
        raise Fail(409, f"mods/{mod_id} already exists and was not made by the tile "
                        f"editor; pick another id")
    poi_dir = folder / "pois" / TE.poi_id(tile)
    if places:
        TE.check(tile, places)                     # prove it cooks before writing
        _atomic(poi_dir / "poi.toml", TE.poi_toml(tile, places))
    elif poi_dir.is_dir():
        shutil.rmtree(poi_dir)                     # every added object removed
    tiles = [t["tiles"] for t in _tile_mods(req.ctx.mods_dir) if t["id"] == mod_id]
    edited = (tiles[0] if tiles else []) or ([tile] if places else [])
    name = str(body.get("name", "")).strip()[:80]
    _atomic(man, TE.manifest_toml(mod_id, name, edited or [tile]))
    # The web editor zips and downloads a saved mod when the path names its
    # manifest, so it must (index.astro afterSave).
    return {"path": f"mods/{mod_id}/manifest.toml", "tiles": edited, "next": NEXT_STEP}


#: GET routes whose answer depends only on game data (see diskcache).
CACHED = frozenset({"/api/t3/objects", "/api/t3/entity", "/api/t3/props"})

ROUTES = {
    ("GET", "/api/t3/objects"): _wrap(lambda req: TE.objects_json(req.arg("tile"))),
    ("GET", "/api/t3/entity"): _wrap(lambda req: TE.entity_json(req.arg("ref"))),
    ("GET", "/api/t3/props"): lambda req: {"props": TE.props_json()},
    ("GET", "/api/t3/mods"): lambda req: {"mods": _tile_mods(req.ctx.mods_dir)},
    ("GET", "/api/t3/mod"): _wrap(_mod),
    ("POST", "/api/t3/check"): _wrap(_check),
    ("POST", "/api/t3/save"): _wrap(_save),
}
