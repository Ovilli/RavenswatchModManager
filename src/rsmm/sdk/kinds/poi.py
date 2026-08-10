"""**POI / structure** builder — put a point of interest into any chapter.

A ``poi`` def clones a shipped ``*.tiledef.ot`` (a placeable map chunk: shrine,
cauldron, teleporter, camp, ruin, …), optionally retunes it, and adds it to the
tile pool of every chapter you name. From the player's side that is a structure
appearing somewhere it never did before — Avalon's Leprechaun Cauldron turning
up in Dark Hills, a second Altar of Heroes, a Storm Island refugee camp on the
Dark Hills map.

Two assets come out of one def:

* a **new tiledef** under an existing biome's ``Definitions/Tiles/<Biome>/``
  directory, registered into ``UsedRscList.ot`` by the normal new-asset path;
* an **override of each target mapdef**, with the new tile appended to its pool
  (:mod:`rsmm.engine.map_pool`). The edit is purely additive — vanilla entries
  keep their order — and multiple ``poi`` mods targeting the same chapter are
  merged rather than fighting (see ``apply_mods._merge_map_pool``).

The short way: a POI is a folder
--------------------------------
Drop a directory into ``mods/<id>/pois/`` and it is discovered automatically —
no manifest entry:

.. code-block:: text

    pois/runestone_shrine/
        poi.toml        chapters, plus anything you want to override
        model.glb       the mesh
        albedo.png      \
        mra.png          }  matched to texture slots by filename
        normal.png      /

``poi.toml`` usually only needs ``chapters``. Everything else comes from a
preset (``preset = "clearing"`` / ``"landmark"``; see :data:`PRESETS`), which
bundles the donor tile, the object to replace, the prop and material to inherit
structure from, and the role-to-slot texture map. Omit the art entirely and you
get a plain clone of the preset's tile.

Discovery builds exactly the ``[[content]]`` dict documented below, so the
explicit form still works and a declared block wins on id collision.

Fields (the explicit ``[[content]]`` form)
------------------------------------------
``base`` (str, required)
    Tiledef to clone, as ``<Biome>/<Name>`` — e.g.
    ``Avalon/40x40_Avalon_Cauldron_T1``. Browse with ``rsmm poi list``.
``chapters`` (list[str], required)
    Which maps get it: ``Dark_Hills``, ``Avalon``, ``Storm_Island``. Baba Yaga
    is the scripted boss arena and has no tile pool, so it is rejected.
``weight`` (float, optional)
    **Tier**, not a spawn rate — see :data:`TIER_WEIGHTS`. Raising it to make a
    POI commoner is backwards; use ``copies``.
``copies`` (int, optional, default 1)
    How many pool entries this POI gets. A chapter fills a slot from the
    entries matching that slot's kind, so the share is
    ``copies / (copies + vanilla entries of that kind)`` — each biome ships two
    ``Fountain`` tiles, so ``copies = 8`` is ~80% of every fountain slot.
    Capped at :data:`MAX_COPIES`.
``kinds`` (list[str], optional)
    Override the tile's kind list — the join key to the map's slot vocabulary.
    Every entry must be a kind the target chapters actually declare, or the tile
    can never be placed; that is validated up front rather than failing silently
    in-game.
``icon`` (str, optional)
    Minimap icon path, e.g. ``MiniMap\\Icons\\Map_Icons_Crow_Mark.png``. Pass
    ``""`` to strip the icon (the structure still spawns, it just stops showing
    on the minimap).
``prop`` (table, optional)
    Put the mod's **own** model and textures in the tile — see below.

Two modes
---------
**Without ``prop``**, a POI re-points a tiledef at a prefab the game already
ships. That is a real, fully functional structure, but it is one that already
existed somewhere; the ceiling is the shipped content.

**With ``prop``**, the mod's own art goes in. The engine reaches a structure
through a chain of string references — mapdef pool → tiledef → tile prefab →
tile level → prop entity → geometry / material → textures — and a ``prop``
block clones the last four and rewrites the refs so they land on the mod's
mesh and maps (:mod:`rsmm.engine.prop_cook`). The donors supply *structure*
(component wiring, LODs, terrain patch, grass scatter); the art is the mod's.

``prop`` fields:

``model`` (str, required)
    Reference form of the mod's mesh, e.g. ``Scenery\\DarkHills\\My.fbx``. The
    mod must ship the cooked geometry at the matching
    ``assets/3D/Scenery/DarkHills/My.fbx.Geometry.gen``.
``textures`` (table, required)
    Maps a texture reference in ``material_base`` to the mod's replacement,
    both in reference form. Every key must exist in the donor.
``replaces`` (str, required)
    The object reference in the base tile's level that the custom prop takes
    over — it inherits that object's transform, so the structure lands where
    the donor's centrepiece stood.
``entity_base`` (str, required)
    Vanilla scenery-prop entity to clone for component structure, e.g.
    ``DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot``.
``material_base`` (str, required)
    Vanilla material to clone, e.g. ``Scenery\\DarkHills\\M_Walls_Ruins.mat.ot``.

Confidence: ``experimental``. The tile/pool codecs round-trip the entire
shipped corpus byte-for-byte (237/237 tiledefs, 3/3 tile-generated mapdefs) and
the pool is demonstrably the per-chapter gate — retail itself lists a Storm
Island tile in Dark Hills' pool — but no in-game playtest has confirmed a
mod-added tile being placed, nor a custom prop rendering.
See ``docs/_re/kinds/pois.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import map_pool as MP
from ...engine import prop_cook as PC
from ...engine import tile_cook as TC
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

_UNCOOKED = DATA_DIR / "uncooked"
_TILES_DIR = _UNCOOKED / "Definitions" / "Tiles"
_MAPS_DIR = _UNCOOKED / "Definitions" / "Maps"

_TILE_ASSET_SUBDIR = "Definitions/Tiles"
_MAP_ASSET_SUBDIR = "Definitions/Maps"

#: Chapter name -> shipped mapdef stem. Baba Yaga is deliberately absent: it is
#: the scripted boss arena, is not tile-generated, and has no pool to add to.
CHAPTERS: dict[str, str] = {
    "Dark_Hills": "Dark_Hills_LiveOps_Update5",
    "Avalon": "Avalon_LiveOps_Update5",
    "Storm_Island": "Storm_Island_LiveOps_Update5",
}


#: Donor bundles. Everything a custom prop needs to hang on — which tile to
#: build in, which object in it to take the place of, and which prop/material to
#: inherit structure from — collapsed to one name. Authors pick a preset (or
#: none, and get the default) instead of naming five engine paths.
#:
#: `slots` maps a conventional source-image name to the donor material's
#: texture reference, so `albedo.png` in a POI folder simply works.
#:
#: Every field here is checked against the corpus by
#: `tests/test_poi.py::test_every_preset_is_wired_to_real_donors` — including
#: that `replaces` names an object the base tile's level actually places, which
#: is not guessable from the tile's name (a "Giant_Ruin_Crystal_Field" tile
#: turns out to place bone and skull props, not a ruin). A preset is a promise
#: to every mod that uses it, so a stale path here breaks all of them at once.
PRESETS: dict[str, dict] = {
    # A 6x6 clearing built around a single centrepiece: small footprint, its own
    # terrain patch, grass and props. The default because it is the least
    # opinionated place to stand something new.
    "clearing": {
        "base": "Dark_Hills/6x6_Bleeding_01",
        "replaces": "DarkHills\\Objects_DarkHills\\Blood_Fountain_DarkHills.entity.ot",
        "entity_base":
            "DarkHills\\SceneryObjects_DarkHills\\Wall_Ruins_Block_Small_A.entity.ot",
        "material_base": "Scenery\\DarkHills\\M_Walls_Ruins.mat.ot",
        "slots": {
            "albedo": "Scenery\\DarkHills\\T_Walls_Ruins_ALB.tga",
            "mra": "Scenery\\DarkHills\\T_Walls_Ruins_MRA.tga",
            "normal": "Scenery\\DarkHills\\T_Walls_Ruins_NRM.tga",
        },
        "kinds": ["Fountain"],
        "weight": 0.15,
    },
}

DEFAULT_PRESET = "clearing"

#: `weight` is a TIER field, not a spawn frequency. Across every tier-suffixed
#: family in the corpus — cauldrons, grimoires and wishing wells, in all three
#: biomes — the T1/T2/T3 variants carry exactly these values, with no
#: exceptions. T1 tiles sit at 0.0 and plainly do appear in game, so a 0 weight
#: does NOT mean "never placed".
#:
#: The practical consequence: raising `weight` to make something commoner is
#: backwards. It marks the tile as a higher-tier variant, which if anything
#: gates it behind run progression. To change how often a POI turns up, change
#: how many pool entries it has (`copies`) or how many slot kinds it can fill
#: (`kinds`).
TIER_WEIGHTS = {1: 0.0, 2: 0.333, 3: 0.667}

#: Upper bound on `copies`. A POI with more entries than the whole vanilla pool
#: for its kind crowds every other tile out of those slots, which is a mistake
#: far more often than an intention.
MAX_COPIES = 16

#: Conventional source-art filenames inside a POI folder. `model.glb` is the
#: mesh; the rest are texture roles resolved through the preset's `slots`.
MODEL_NAMES = ("model.glb", "model.gltf")
TEXTURE_ROLES = ("albedo", "mra", "normal")

#: Drop an `icon.png` in a POI folder and it becomes the minimap icon. Shipped
#: icons are 48x48 with a transparent background, a thick dark outline and a
#: flat saturated fill; anything else still works but reads as out of place.
ICON_NAMES = ("icon.png", "icon.tga")

#: Where a mod's own minimap icons are filed. UI art cooks under the `Ui/` root
#: (not `3D/`), and the directory has to be one the game already ships into so
#: `synthesize_encoded` and `build_usedrsc_record` both find a sibling.
ICON_DIR = "MiniMap\\Icons"


def known_tiles() -> list[str]:
    """Every clonable tile as ``<Biome>/<Name>``."""
    if not _TILES_DIR.is_dir():
        return []
    out = []
    for p in _TILES_DIR.rglob("*" + TC.GEN_SUFFIX):
        out.append(f"{p.parent.name}/{p.name[: -len(TC.GEN_SUFFIX)]}")
    return sorted(out)


def _tile_path(base: str) -> Path:
    return _TILES_DIR / Path(*base.split("/")).with_name(
        Path(base).name + TC.GEN_SUFFIX
    )


def chapter_kinds(chapter: str) -> set[str]:
    """The tile kinds this chapter's existing pool can supply.

    Used as the validation vocabulary for ``kinds``. It is the kinds actually
    reachable in that map today, which is the honest bar: a kind no pooled tile
    declares is one no slot is known to accept.
    """
    stem = CHAPTERS.get(chapter)
    if not stem:
        return set()
    gen = _MAPS_DIR / f"{stem}{MP.GEN_SUFFIX}"
    if not gen.is_file():
        return set()
    pool = MP.read_pool(gen.read_bytes()) or []
    kinds: set[str] = set()
    for path in pool:
        # "Tiles\\<Biome>\\<Name>.tiledef.ot" -> data/uncooked path
        parts = path.replace("\\", "/").split("/")
        if len(parts) < 3:
            continue
        stem_name = parts[-1].removesuffix(".tiledef.ot")
        p = _TILES_DIR / parts[-2] / f"{stem_name}{TC.GEN_SUFFIX}"
        if p.is_file():
            try:
                kinds.update(TC.read(p.read_bytes()).kinds)
            except TC.TileCookError:
                continue
    return kinds


#: Folder under a mod root that holds convention-discovered POIs.
POIS_DIRNAME = "pois"


def discover(mod_root: Path) -> list[dict]:
    """Turn ``mods/<id>/pois/<name>/`` folders into ``[[content]]`` blocks.

    The Minecraft-style half of this kind: a POI is a *directory*, not a wall of
    manifest keys. Drop a folder in, and its contents say what it is —

    .. code-block:: text

        pois/runestone_shrine/
            poi.toml        chapters + any overrides (optional)
            model.glb       the mesh
            albedo.png      \\
            mra.png          }  texture roles, matched to the preset's slots
            normal.png      /

    Everything not stated is inherited from the preset (``preset = "..."`` in
    ``poi.toml``, default :data:`DEFAULT_PRESET`), so the common case needs no
    engine paths at all. Anything a preset sets can still be overridden key by
    key, which is why the explicit ``prop`` form remains supported — this
    function only builds the same dict a hand-written block would.

    Returns blocks in folder-name order so an apply is deterministic.
    """
    root = mod_root / POIS_DIRNAME
    if not root.is_dir():
        return []
    import tomllib

    blocks: list[dict] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        cfg: dict = {}
        cfg_path = d / "poi.toml"
        if cfg_path.is_file():
            try:
                cfg = tomllib.load(cfg_path.open("rb"))
            except (OSError, tomllib.TOMLDecodeError) as e:
                raise ContentError(f"poi {d.name}: {cfg_path} is not valid TOML: {e}") from e

        preset_name = cfg.pop("preset", DEFAULT_PRESET)
        preset = PRESETS.get(preset_name)
        if preset is None:
            raise ContentError(
                f"poi {d.name}: unknown preset {preset_name!r}. "
                f"Available: {', '.join(sorted(PRESETS))}."
            )

        block: dict = {"kind": "poi", "id": cfg.pop("id", None) or d.name}
        # In replace_base mode the tile already exists and already has a job.
        # Inheriting the preset's `kinds`/`weight` would rewrite the identity of
        # a shipped tile — pointing the preset at the Start tile would have
        # replaced its `Start` kind with `Fountain` and broken run spawning.
        # Only an explicit value in poi.toml may change those in override mode.
        overriding = bool(cfg.get("replace_base"))
        for key in ("base", "kinds", "weight", "copies", "replace_base"):
            if key in cfg:
                block[key] = cfg.pop(key)
            elif key in preset and not (overriding and key in ("kinds", "weight")):
                block[key] = preset[key]
        for key in ("chapters", "icon"):
            if key in cfg:
                block[key] = cfg.pop(key)

        icon_src = next((n for n in ICON_NAMES if (d / n).is_file()), None)
        if icon_src:
            # A custom icon file wins over an `icon = "..."` vanilla ref.
            block["icon_source"] = f"{POIS_DIRNAME}/{d.name}/{icon_src}"
            cfg.pop("icon", None)
            block.pop("icon", None)

        model = next((m for m in MODEL_NAMES if (d / m).is_file()), None)
        if model:
            rel = f"{POIS_DIRNAME}/{d.name}"
            textures = {}
            for role in TEXTURE_ROLES:
                img = next((f"{role}{e}" for e in (".png", ".dds")
                            if (d / f"{role}{e}").is_file()), None)
                if not img:
                    continue
                slot = (cfg.get("slots") or preset["slots"]).get(role)
                if slot:
                    textures[slot] = f"{rel}/{img}"
            if not textures:
                raise ContentError(
                    f"poi {d.name}: has {model} but no texture next to it — add "
                    f"at least one of {', '.join(n + '.png' for n in TEXTURE_ROLES)}."
                )
            block["prop"] = {
                "model": f"{rel}/{model}",
                "textures": textures,
                "replaces": cfg.pop("replaces", preset["replaces"]),
                "entity_base": cfg.pop("entity_base", preset["entity_base"]),
                "material_base": cfg.pop("material_base", preset["material_base"]),
            }
            if "transform" in cfg:
                block["prop"]["transform"] = cfg.pop("transform")
        cfg.pop("slots", None)

        # Anything left is a typo, not a feature. Silently ignoring it is how a
        # mod ships with a setting the author believes is in effect.
        unknown = sorted(cfg)
        if unknown:
            raise ContentError(
                f"poi {d.name}: unknown key(s) in poi.toml: {', '.join(unknown)}"
            )
        if not block.get("chapters"):
            raise ContentError(
                f"poi {d.name}: poi.toml must set `chapters` — which maps it "
                f"appears in. Valid: {', '.join(sorted(CHAPTERS))}."
            )
        blocks.append(block)
    return blocks


def kind_footprints(kind: str) -> set[tuple[int, int]]:
    """Tile footprints the shipped corpus uses for ``kind``.

    A slot has a size as well as a kind, so declaring a kind whose tiles are all
    a different size buys nothing. Empty when the corpus is absent (do not
    block) or the kind is unknown (the vocabulary check already covers that).
    """
    out: set[tuple[int, int]] = set()
    if not _TILES_DIR.is_dir():
        return out
    for p in _TILES_DIR.rglob("*" + TC.GEN_SUFFIX):
        try:
            td = TC.read(p.read_bytes())
        except TC.TileCookError:
            continue
        if kind in td.kinds:
            out.add((td.width, td.height))
    return out


def _validate(defn: ContentDef) -> tuple[str, list[str]]:
    C.validate_id("poi", defn.id)
    f = defn.fields

    base = f.get("base")
    if not base or not isinstance(base, str):
        raise ContentError(
            f"poi {defn.id}: needs a 'base' tiledef to clone, as "
            f'"<Biome>/<Name>" (e.g. base="Avalon/40x40_Avalon_Cauldron_T1"). '
            f"List them with `rsmm poi list`."
        )
    if not _tile_path(base).is_file():
        known = known_tiles()
        hint = ""
        if known:
            near = [k for k in known if base.rsplit("/", 1)[-1].lower() in k.lower()][:5]
            hint = f" Did you mean: {', '.join(near)}?" if near else \
                   f" {len(known)} tiles available — see `rsmm poi list`."
        raise SchemaNotMined(f"poi {defn.id}: base {base!r} not found.{hint}")

    chapters = f.get("chapters")
    if not chapters or not isinstance(chapters, (list, tuple)):
        raise ContentError(
            f"poi {defn.id}: needs 'chapters' — a list of maps to add it to. "
            f"Valid: {', '.join(sorted(CHAPTERS))}."
        )
    chapters = list(chapters)
    for ch in chapters:
        if ch not in CHAPTERS:
            extra = ""
            if isinstance(ch, str) and ch.lower().startswith("baba"):
                extra = (" Baba Yaga is the scripted boss arena — it is not "
                         "tile-generated and has no pool to add to.")
            raise ContentError(
                f"poi {defn.id}: unknown chapter {ch!r}. "
                f"Valid: {', '.join(sorted(CHAPTERS))}.{extra}"
            )
    return base, chapters


def _apply_edits(td: TC.TileDef, defn: ContentDef, chapters: list[str]) -> None:
    f = defn.fields

    if "weight" in f:
        w = f["weight"]
        if not isinstance(w, (int, float)) or isinstance(w, bool):
            raise ContentError(f"poi {defn.id}: 'weight' must be a number, got {w!r}")
        if not 0.0 <= float(w) <= 1.0:
            raise ContentError(
                f"poi {defn.id}: 'weight' {w} out of range — shipped tiles use "
                f"0.0 to ~0.67 (see TIER_WEIGHTS; it is a tier field)."
            )
        td.weight = float(w)

    if "kinds" in f:
        kinds = f["kinds"]
        if not isinstance(kinds, (list, tuple)) or not kinds:
            raise ContentError(
                f"poi {defn.id}: 'kinds' must be a non-empty list of tile kinds."
            )
        for k in kinds:
            if not isinstance(k, str) or not k:
                raise ContentError(f"poi {defn.id}: kind entries must be strings, got {k!r}")
        # A kind no target chapter can supply means the tile is dead weight —
        # it would be registered, loaded, and never placed. Catch it here.
        for ch in chapters:
            vocab = chapter_kinds(ch)
            if not vocab:
                continue  # corpus absent; can't validate, don't block
            unknown = [k for k in kinds if k not in vocab]
            if unknown:
                raise ContentError(
                    f"poi {defn.id}: chapter {ch} has no slot for kind(s) "
                    f"{', '.join(unknown)} — the tile would load but never be "
                    f"placed. Kinds {ch} uses: {', '.join(sorted(vocab))}."
                )
        # A kind's slots have a footprint. Every shipped `Wishing_Well` tile is
        # 40x40, so a 6x6 tile claiming that kind can never fill one of its
        # slots — it looks like a free way to compete for more slots and is
        # actually dead weight.
        for k in kinds:
            sizes = kind_footprints(k)
            if sizes and (td.width, td.height) not in sizes:
                pretty = ", ".join(f"{w}x{h}" for w, h in sorted(sizes))
                raise ContentError(
                    f"poi {defn.id}: kind {k!r} is only used by {pretty} tiles, "
                    f"but this one is {td.width}x{td.height} — it could never "
                    f"fill a {k} slot."
                )
        td.kinds = list(kinds)

    if "icon" in f:
        icon = f["icon"]
        if not isinstance(icon, str):
            raise ContentError(f"poi {defn.id}: 'icon' must be a string path, got {icon!r}")
        resolved, cat, _old = td.icon
        if icon:
            td.icon = (resolved, cat or "Ui", icon)
        else:
            td.icon = (resolved, "", "")


def _emit_custom_icon(mod_id: str, defn: ContentDef, out_dir: Path,
                      td: TC.TileDef, written: list[Path]) -> None:
    """Cook the mod's own `icon.png` and point the tiledef's icon slot at it."""
    src_rel = defn.fields["icon_source"]
    src = _mod_source(out_dir, src_rel, defn.id, "icon_source")
    tag = f"{mod_id}_{defn.id}".replace("-", "_")
    ref = f"{ICON_DIR}\\{tag}.png"
    _write(out_dir, PC.ui_cooked_path(ref), PC.cook_texture(src.read_bytes()), written)
    # `_res` stays as the donor left it; only the path moves.
    td.icon = (td.icon[0], "Ui", ref)
    _log.info("poi %s/%s: custom minimap icon from %s", mod_id, defn.id, src_rel)


def _corpus(decoded: str, defn_id: str, what: str) -> bytes:
    """Read a cooked asset out of the mirrored corpus, or explain what's missing."""
    p = _UNCOOKED / Path(*decoded.split("/"))
    if not p.is_file():
        raise SchemaNotMined(
            f"poi {defn_id}: {what} not found at {p} — pass a path that exists "
            f"in the vanilla corpus, or run `python scripts/extract_uncooked.py`."
        )
    return p.read_bytes()


def _mod_source(out_dir: Path, rel: str, defn_id: str, field: str) -> Path:
    """Resolve a source-art path the manifest gave, relative to the mod root.

    ``out_dir`` is the mod's ``assets/`` directory; source art lives OUTSIDE it
    (``mods/<id>/art/…``) so the raw ``.glb``/``.png`` are never mistaken for
    cooked overrides and copied into the game install. Both are accepted so an
    author can keep everything in one place if they prefer.
    """
    if not isinstance(rel, str) or not rel:
        raise ContentError(f"poi {defn_id}: {field} must be a path, got {rel!r}")
    clean = rel.replace("\\", "/")
    if ".." in clean.split("/"):
        raise ContentError(f"poi {defn_id}: {field} may not escape the mod ({rel!r})")
    for root in (out_dir.parent, out_dir):
        p = root / Path(*clean.split("/"))
        if p.is_file():
            return p
    raise ContentError(
        f"poi {defn_id}: {field} {rel!r} is not in this mod — expected it at "
        f"{(out_dir.parent / clean)}. Ship the source art with the mod."
    )


def _donor_geometry(mesh_ref: str, defn_id: str) -> bytes:
    """Cooked oCGeometry for a vanilla mesh, to graft a custom model onto.

    `extract_uncooked.py` mirrors geometry as **uncooked GLB**, not as the
    cooked `.Geometry.gen`, so the corpus usually has only the GLB — but an
    `rsmm uncook` GLB carries the original cooked bytes in
    `extras.rsmm.cooked_b64`, which is exactly the template needed. Prefer a
    real cooked file when one is present, else unwrap the GLB.
    """
    from ...engine import geometry_cook as GC

    cooked_rel = PC.art_cooked_path(mesh_ref)
    cooked_p = _UNCOOKED / Path(*cooked_rel.split("/"))
    if cooked_p.is_file():
        return cooked_p.read_bytes()

    glb_p = _UNCOOKED / Path(*f"3D/{mesh_ref.replace(chr(92), '/')}.glb".split("/"))
    if glb_p.is_file():
        try:
            return GC.template_from_uncooked_glb(glb_p.read_bytes())
        except ValueError as e:
            raise SchemaNotMined(
                f"poi {defn_id}: donor mesh {mesh_ref!r} is mirrored at {glb_p} "
                f"but carries no cooked template ({e}) — re-mirror it with "
                f"`python scripts/extract_uncooked.py`."
            ) from e
    raise SchemaNotMined(
        f"poi {defn_id}: donor mesh {mesh_ref!r} not in the corpus (looked for "
        f"{cooked_p} and {glb_p}) — run `python scripts/extract_uncooked.py`."
    )


def _material_refs(cooked_bytes: bytes) -> set[str]:
    import json

    from ...engine import cooked_schemas
    doc = json.loads(cooked_schemas.get("oCMaterial").decode_cooked(cooked_bytes))
    return set(doc.get("asset_refs") or [])


def _write(out_dir: Path, decoded: str, data: bytes,
           written: list[Path]) -> None:
    dest = out_dir / Path(*decoded.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    written.append(dest)


def _emit_custom_prop(mod_id: str, defn: ContentDef, out_dir: Path,
                      base: str, written: list[Path]) -> str:
    """Build the mod's own prop + the tile that shows it, return the new
    prefab's entity reference for the tiledef to point at."""
    from ...engine import entity_strings as ES

    spec = defn.fields["prop"]
    if not isinstance(spec, dict):
        raise ContentError(f"poi {defn.id}: 'prop' must be a table")
    for key in ("model", "textures", "replaces", "entity_base", "material_base"):
        if not spec.get(key):
            raise ContentError(
                f"poi {defn.id}: prop.{key} is required — see the `poi` docs."
            )
    textures = spec["textures"]
    if not isinstance(textures, dict) or not textures:
        raise ContentError(
            f"poi {defn.id}: prop.textures must be a non-empty table mapping a "
            f"donor texture reference to one of this mod's source images."
        )

    tag = f"{mod_id}_{defn.id}".replace("-", "_")
    # Custom art is filed beside its donor. Two separate apply-time lookups need
    # a same-kind sibling in the same decoded directory — `synthesize_encoded`
    # (to derive the cooked path) and `build_usedrsc_record` (to register it) —
    # and a brand-new directory satisfies neither.
    art_dir = spec["material_base"].replace("\\", "/").rsplit("/", 1)[0]

    donor_ent = _corpus(PC.entity_cooked_path(spec["entity_base"]),
                        defn.id, "prop.entity_base")
    donor_strings = {s for _sec, _off, s in ES.list_strings(donor_ent)}

    # 1. Mesh. The mod ships a .glb; the graft template comes from the donor
    #    prop's own mesh, which the manifest already names — so the author
    #    never has to pre-cook anything or know what a template is.
    model_src = _mod_source(out_dir, spec["model"], defn.id, "prop.model")
    donor_meshes = sorted(s for s in donor_strings if s.lower().endswith(".fbx"))
    if not donor_meshes:
        raise ContentError(
            f"poi {defn.id}: prop.entity_base references no mesh, so there is "
            f"no template to cook prop.model against. Pick a scenery prop."
        )
    model_ref = f"{art_dir}/{tag}.fbx".replace("/", "\\")
    _write(out_dir, PC.art_cooked_path(model_ref),
           PC.cook_model(model_src.read_bytes(),
                         _donor_geometry(donor_meshes[0], defn.id),
                         transform=spec.get("transform")), written)

    # 2. Textures. Source PNGs in, cooked oCTexture out, named after the mod.
    tex_refs: dict[str, str] = {}
    for donor_ref, src_rel in textures.items():
        if donor_ref not in donor_strings and donor_ref not in _material_refs(
                _corpus(PC.art_cooked_path(spec["material_base"]), defn.id,
                        "prop.material_base")):
            raise ContentError(
                f"poi {defn.id}: prop.textures key {donor_ref!r} is not a "
                f"texture the material donor uses."
            )
        slot = Path(str(donor_ref)).name.rsplit(".", 1)[0].rsplit("_", 1)[-1]
        src = _mod_source(out_dir, src_rel, defn.id, f"prop.textures[{donor_ref}]")
        ref = f"{art_dir}/T_{tag}_{slot}.tga".replace("/", "\\")
        _write(out_dir, PC.art_cooked_path(ref),
               PC.cook_texture(src.read_bytes()), written)
        tex_refs[donor_ref] = ref

    # 3. Material: donor's shader wiring, the mod's maps.
    mat_ref = f"{art_dir}/M_{tag}.mat.ot".replace("/", "\\")
    _write(out_dir, PC.art_cooked_path(mat_ref),
           PC.clone_material(
               _corpus(PC.art_cooked_path(spec["material_base"]), defn.id,
                       "prop.material_base"), tex_refs), written)

    # 4. Prop entity: donor's component structure, the mod's mesh + material.
    #    Every LOD slot is repointed, or the prop pops back to the donor's
    #    shape at distance.
    ent_dir = spec["entity_base"].replace("\\", "/").rsplit("/", 1)[0]
    ent_ref = f"{ent_dir}/{tag}_Prop.entity.ot".replace("/", "\\")
    swaps = {s: model_ref for s in donor_meshes}
    swaps[spec["material_base"]] = mat_ref
    _write(out_dir, PC.entity_cooked_path(ent_ref),
           PC.clone_prop_entity(donor_ent, swaps), written)

    # 3. Tile level: the base tile's dressing, its centrepiece swapped for ours.
    tile_stem = base.split("/", 1)[1]
    donor_prefab_dec = _prefab_ref_of(base, defn.id)
    level_ref = _level_ref_of(donor_prefab_dec, defn.id)
    new_level_ref = level_ref.rsplit("\\", 1)[0] + f"\\{tag}.level.ot"
    _write(out_dir, PC.level_cooked_path(new_level_ref),
           PC.clone_tile_level(
               _corpus(PC.level_cooked_path(level_ref), defn.id, "the tile's level"),
               level_ref, new_level_ref, {spec["replaces"]: ent_ref}), written)

    # 4. Tile prefab entity: points the tiledef at the new level.
    new_prefab_ref = donor_prefab_dec.rsplit("\\", 1)[0] + f"\\{tag}.entity.ot"
    _write(out_dir, PC.entity_cooked_path(new_prefab_ref),
           PC.clone_tile_prefab(
               _corpus(PC.entity_cooked_path(donor_prefab_dec), defn.id,
                       "the tile's prefab entity"),
               level_ref, new_level_ref), written)

    _log.info("poi %s/%s: custom prop from %s (+%d texture(s)) in tile %s",
              mod_id, defn.id, spec["model"], len(tex_refs), tile_stem)
    return new_prefab_ref


def _prefab_ref_of(base: str, defn_id: str) -> str:
    """The ``entity_ref`` the base tiledef points at (its prefab)."""
    td = TC.read(_tile_path(base).read_bytes())
    if len(td.entity_ref) < 2:
        raise SchemaNotMined(f"poi {defn_id}: base tile {base!r} has no entity_ref")
    return td.entity_ref[1]


def _level_ref_of(prefab_ref: str, defn_id: str) -> str:
    """The single ``*.level.ot`` a tile prefab points at."""
    from ...engine import entity_strings as ES

    raw = _corpus(PC.entity_cooked_path(prefab_ref), defn_id,
                  "the tile's prefab entity")
    levels = sorted({s for _sec, _off, s in ES.list_strings(raw)
                     if s.lower().endswith(".level.ot")})
    if len(levels) != 1:
        raise SchemaNotMined(
            f"poi {defn_id}: expected the tile prefab to reference exactly one "
            f"level, found {levels} — pick a simpler base tile for a custom prop."
        )
    return levels[0]


def _emit_replacing_base(mod_id: str, defn: ContentDef, out_dir: Path,
                         base: str, td: TC.TileDef) -> list[Path]:
    """Override the base tile in place: no new tiledef, no pool edit.

    The custom prop still gets its own level and prop entity — those are new
    assets either way — but the base tile's PREFAB is overridden so it points at
    the new level, and the base tiledef is overridden only if the def asked for
    cosmetic changes (icon/kinds/weight). Nothing is added to any pool, so the
    structure appears exactly where and as often as the vanilla tile did.
    """
    written: list[Path] = []
    biome, stem = base.split("/", 1)

    if defn.fields.get("prop"):
        # Reuse the normal chain, then point the BASE prefab at the new level
        # instead of emitting a separate prefab under a new name.
        from ...engine import entity_strings as ES

        new_prefab = _emit_custom_prop(mod_id, defn, out_dir, base, written)
        base_prefab = _prefab_ref_of(base, defn.id)
        # The prop path emits its prefab under a NEW name. In override mode we
        # want the ORIGINAL prefab path carrying the new level reference, so
        # take the level out of the clone and drop the clone itself — the
        # vanilla tiledef then resolves to a prefab that shows our structure.
        clone_path = out_dir / Path(*PC.entity_cooked_path(new_prefab).split("/"))
        new_level = sorted({
            s for _a, _b, s in ES.list_strings(clone_path.read_bytes())
            if s.lower().endswith(".level.ot")})[0]
        clone_path.unlink()
        written.remove(clone_path)
        _write(out_dir, PC.entity_cooked_path(base_prefab),
               PC.clone_tile_prefab(
                   _corpus(PC.entity_cooked_path(base_prefab), defn.id,
                           "the base tile's prefab entity"),
                   _level_ref_of(base_prefab, defn.id), new_level), written)

    # Cosmetic edits (icon / kinds / weight) go onto the base tiledef itself.
    if defn.fields.get("icon_source"):
        _emit_custom_icon(mod_id, defn, out_dir, td, written)
    if any(k in defn.fields for k in ("icon", "icon_source", "kinds", "weight")):
        _write(out_dir, f"{_TILE_ASSET_SUBDIR}/{biome}/{stem}{TC.GEN_SUFFIX}",
               TC.write(td), written)

    _log.info("poi %s/%s: REPLACING base tile %s in place (no pool change)",
              mod_id, defn.id, base)
    return written


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize the cloned tiledef + one patched mapdef per target chapter."""
    base, chapters = _validate(defn)

    td = TC.read(_tile_path(base).read_bytes())
    _apply_edits(td, defn, chapters)

    # `replace_base` mode: rewrite the BASE tile in place instead of adding a
    # new one to the pool. The tile keeps its own id, path, prefab reference and
    # pool membership — only what it *shows* changes.
    #
    # This exists for two reasons. It is the honest way to ship a re-skin of a
    # structure that already exists (the same reason `reward` and `melody` are
    # override-only). And it is the diagnostic that separates the two halves of
    # this feature: if a POI appears in override mode but not in additive mode,
    # the art chain is fine and the fault is in pool membership; if it appears
    # in neither, the fault is in the art chain.
    if defn.fields.get("replace_base"):
        return _emit_replacing_base(mod_id, defn, out_dir, base, td)

    # File the clone next to its donor. `synthesize_encoded` derives a new
    # asset's encoded path by cloning an existing sibling's encoded prefix, so a
    # brand-new `Definitions/Tiles/<Mod>/` directory would have nothing to
    # anchor on and the asset would be skipped at apply. Reusing the donor's
    # biome directory keeps that resolution working — and is what the game
    # itself does, filing a Storm Island tile that Dark Hills draws from.
    biome = base.split("/", 1)[0]
    tile_name = f"{mod_id}_{defn.id}"
    written: list[Path] = []

    # A custom prop rebuilds the prefab/level/prop/material chain and hands
    # back a new prefab reference for the tiledef to point at. Without it the
    # clone keeps the donor's prefab and shows the donor's structure.
    if defn.fields.get("prop"):
        td.entity_ref = ["EntitySettings",
                         _emit_custom_prop(mod_id, defn, out_dir, base, written)]

    # After _apply_edits, so a shipped icon.png beats an `icon = "..."` ref.
    if defn.fields.get("icon_source"):
        _emit_custom_icon(mod_id, defn, out_dir, td, written)

    # `copies` is the frequency dial. A chapter draws a slot's tile from the
    # pool entries matching that slot's kind, so a POI's share is entries-of-its
    # -kind / total-of-that-kind — Dark Hills ships two `Fountain` tiles, so one
    # copy is a third of fountain slots and four copies is two thirds. `weight`
    # does NOT do this (see TIER_WEIGHTS); it marks a tier variant, and turning
    # it up to get more spawns is backwards.
    #
    # The pool is a list of refs and `add_to_pool` de-duplicates, so repeating
    # one ref cannot work — each copy has to be its own tiledef asset.
    copies = defn.fields.get("copies", 1)
    if not isinstance(copies, int) or isinstance(copies, bool) or copies < 1:
        raise ContentError(
            f"poi {defn.id}: 'copies' must be a positive integer, got {copies!r}")
    if copies > MAX_COPIES:
        raise ContentError(
            f"poi {defn.id}: 'copies' {copies} exceeds {MAX_COPIES} — that many "
            f"entries crowds every vanilla tile out of the slots it shares.")

    pool_refs: list[str] = []
    for n in range(1, copies + 1):
        name = tile_name if n == 1 else f"{tile_name}_{n}"
        tile_rel = f"{_TILE_ASSET_SUBDIR}/{biome}/{name}{TC.GEN_SUFFIX}"
        tile_dest = out_dir / Path(*tile_rel.split("/"))
        tile_dest.parent.mkdir(parents=True, exist_ok=True)
        tile_dest.write_bytes(TC.write(td))
        written.append(tile_dest)
        pool_refs.append(f"Tiles\\{biome}\\{name}.tiledef.ot")

    for ch in chapters:
        stem = CHAPTERS[ch]
        map_rel = f"{_MAP_ASSET_SUBDIR}/{stem}{MP.GEN_SUFFIX}"
        map_dest = out_dir / Path(*map_rel.split("/"))

        # Build on what this mod already emitted for this chapter, if anything.
        # Every `poi` def in a mod is emitted independently into the same
        # out_dir, so starting from vanilla each time would make the last def
        # win and silently drop the earlier ones' tiles — the same failure the
        # cross-mod merge exists to prevent, one level down.
        if map_dest.is_file():
            base_bytes = map_dest.read_bytes()
        else:
            map_gen = _MAPS_DIR / f"{stem}{MP.GEN_SUFFIX}"
            if not map_gen.is_file():
                raise SchemaNotMined(
                    f"poi {defn.id}: mapdef for {ch} not found at {map_gen} — "
                    f"run `python scripts/extract_uncooked.py` to mirror the corpus."
                )
            base_bytes = map_gen.read_bytes()

        map_dest.parent.mkdir(parents=True, exist_ok=True)
        map_dest.write_bytes(MP.add_to_pool(base_bytes, pool_refs))
        written.append(map_dest)

    _log.info("poi %s/%s: cloned %s -> %d pool entr%s in %s",
              mod_id, defn.id, base, len(pool_refs),
              "y" if len(pool_refs) == 1 else "ies", ", ".join(chapters))
    return written
