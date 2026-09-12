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
``allow_shared_art`` (bool, optional, ``replace_base`` only)
    Waive the exclusivity check and override a prop whose art other props also
    use. Everything drawing that mesh changes, everywhere.

    This exists because exclusivity and *being seen* turned out to be mutually
    exclusive. A prop whose art is its own is, in this corpus, always a prop in
    a rare tile: the shrine's exclusive donor sits in 1 of the 18 Camp tiles in
    the Dark Hills pool, so it showed up in roughly one run in ten, and two
    playtests in a row found nothing. Meanwhile **all 43 props in the start
    tile — the one tile in every single run — fail the check**, every one of
    them multi-tile, composite, or sharing a mesh.

    So the honest options are "non-collateral but rare" and "guaranteed but it
    re-skins N other tiles". This key is how an author says which they want,
    out loud, per def. It does NOT waive the composite check: a composite donor
    buries the model inside its own children, which is a broken-looking mod
    rather than a deliberately broad one.

``interactive`` (bool, optional, ``replace_base`` only)
    Give the prop the game's own interaction: a hold-to-interact prompt when
    the hero comes near, a progress ring, and the success FX. Mods react to it
    from Lua through ``R.interact.on("success", cb)``.

``[marker]`` (table, optional, ``replace_base`` only)
    Put the POI on the minimap and the map screen.

    ``icon`` (str) is the mod's own art, a file in the POI folder. ``icon_high``
    is the higher-resolution map-screen version; without it ``icon`` is used for
    both. ``donor`` is an escape hatch naming a different shipped entity to take
    the override records from.

    There is no ``repaint`` key: the art is written over two shipped textures
    that nothing in any chapter preloads (:data:`MARKER_ICON`,
    :data:`MARKER_ICON_HIGH`). It has to land on a shipped NAME — a texture
    filed under a name the game does not ship hangs the game at level load.

    ⚠ An in-place override edits the ENTITY, not one placement of it. Point
    ``replaces`` at a prop the tile places exactly ONCE, or the map fills with
    icons; the emitter warns with the single-placement candidates when it does
    not.

How a marker and an interaction actually arrive
-----------------------------------------------
Both are entity COMPONENTS, and neither can simply be spliced on. The engine
composes an entity out of PARENTS — a chest is interactable and map-marked
because it names ``Interactive_Object_Model`` and ``Minimap_Marker_Reveal_Model``
as parents — and a settings component is an *override* whose fields are named
bindings into a parent's namespace. Splicing one onto a host with no such
parent binds to nothing: the component loads, does nothing, and logs nothing
(measured 2026-09-05).

Inheriting alone is not enough either, and that is the part that cost three
playtests. ``Minimap_Marker_Reveal_Model`` ships every texture Value empty, so
a host that only inherits it runs the whole hero-proximity reveal state machine
and draws no icon — which was mis-read as the parent being "gated". So a POI
does both, exactly as the shipped content does:
:func:`rsmm.engine.entity_components.add_parents` for the machinery, then
:func:`~rsmm.engine.entity_components.copy_overrides` for the settings that
machinery reads, taken off the smallest shipped child of that parent
(``Leprechaun_Cauldron_Minimap_Marker``, ``Ingredient_Stock_Model``).

Confidence: ``experimental``, with one half now confirmed. **A mod-authored
mesh + textures on a shipped prop rendered upright in-game on 2026-08-13**
(``replace_base`` + ``prop``), so the art chain — geometry cook, texture cook,
in-place override, resource caches — is proven end to end.

What is NOT proven is the *additive* half — but the REASON changed on
2026-09-11. The old reason, "a level provably cannot reference an entity
resource the mod introduced", was disproved: every asset in the additive chain,
the mod's own entity included, is both requested and resolved. What remains
unproven is VISIBILITY — no additive POI has yet been SEEN in-game, and the run
that got this far was not checked for the prop mesh. Resolution is settled;
placement and rendering are not.
See ``docs/_re/kinds/pois.md``.
"""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Iterable

# aliased: a loop variable named `cache` already exists below
from functools import cache as _memo
from functools import lru_cache
from pathlib import Path

from ...engine import corpus_cache
from ...engine import entity_components as EC
from ...engine import level_placements as LP
from ...engine import map_pool as MP
from ...engine import prop_cook as PC
from ...engine import rsc_cache as RC
from ...engine import tile_cook as TC
from ...engine.cooked_schemas import asset_refs as AR
from ...engine.paths import DATA_DIR
from ...engine.prop_cook import entity_cooked_path
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Whether a cloned prop entity gets fresh component identity GUIDs
#: (:func:`rsmm.engine.prop_cook.restamp_entity_guids`).
#:
#: Re-stamping was inferred from the tile-level GUID precedent — a clone that
#: keeps its donor's identity is a second resource claiming the donor's place.
#:
#: ARMED 2026-08-13 as the leading hypothesis for why additive POIs fail. The
#: evidence it has to explain: a byte-for-byte copy of a shipped entity under a
#: new name — registered in ``UsedRscList.ot``, present at the derived cooked
#: path, listed in the placing tile's sorted ``UsedRscCache.ot`` — still
#: resolved to null during level load. Nothing static was wrong with it, and
#: the one thing a byte copy necessarily duplicates is the donor's component
#: identity GUIDs. If the engine keys instantiation by GUID, the clone collides
#: with the shipped entity and the null is explained exactly.
#:
#: Every additive attempt so far ran with this OFF, so "additive POIs crash" is
#: really "additive POIs crash without re-stamped GUIDs" — an untested
#: variable, not a proven wall. ``mods/additive-poi-test`` is the experiment.
#: If it loads, the ``prop`` kind's in-place-only restriction can be lifted.
#:
#: ⚠ WEAKENED 2026-09-11 by reading the engine, not by a playtest.
#: ``Resource_LookupByPath`` keys the resource registry on the FNV-1a hash of
#: the LOWERCASED path and consults no GUID at any point, so a GUID collision
#: cannot explain a resource that *looks up* as null. The flag is left ON
#: because it is still the right thing to do and may matter at INSTANTIATION,
#: which is a later stage with its own evidence — but it should no longer be
#: described as the leading explanation, and a playtest that fails with it on
#: does not rule the additive route out.
#:
#: What the same reading DID establish is that the symptom is coarser than
#: assumed: ``LevelObject_LoadOrCreate`` destroys the level and returns null if
#: its load step returns anything but 1, so one unresolved reference fails the
#: whole level rather than dropping one prop. "The level did not load" and "one
#: reference was null" are therefore the same observation, and the next
#: experiment has to name WHICH reference rather than re-running the same one.
RESTAMP_ENTITY_GUIDS = True

#: `places[].entity` value meaning "the prop THIS def emits", rather than a
#: shipped entity reference.
#:
#: This is the additive route, and it is the only one that adds a structure
#: without taking something away. Every other way to get a mod's own art into a
#: tile edits a shipped asset: `prop` + `replaces` overwrites a shipped entity's
#: cooked bytes, and a `swaps` entry destroys a vanilla object to borrow its
#: slot (and inherits its transform whole, which is where every "tipped over",
#: "buried" and "offset" report in this kind's history came from).
#:
#: With `@prop`, the mod introduces an entity NAME of its own and stands it at
#: a transform it chose, in a level it owns. Nothing shipped is modified.
#:
#: ⚠ That name is what this repo has recorded as a wall since 2026-08-13: "a
#: level cannot reference a mod-introduced EntitySettings resource". The
#: evidence for it is one crash — the null-resolve signature at 0x1401273b6 —
#: and the SAME investigation later found a second, independent cause of that
#: exact signature: a `UsedRscCache` line that is not in sorted order is never
#: found, and the entity resolves to null. The wall was measured before that was
#: known, so "the name is rejected" and "the cache line was unsorted" have never
#: been separated. `RESTAMP_ENTITY_GUIDS` was also off for every one of those
#: attempts and is on now. Both confounders are gone, so the wall is worth one
#: honest re-test rather than being inherited as fact.
PLACES_OWN_PROP = "@prop"

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
        # The textures of `replaces` ITSELF, because the art is overridden on
        # that prop's own cooked paths. All three belong to the blood fountain
        # alone, as does its mesh and material, which is what makes an in-place
        # override of this prop local to this tile.
        "slots": {
            "albedo":
                "Scenery\\DarkHills\\Blood_Fountain\\T_Blood_Fountain_base_DH_ALB.tga",
            "mra":
                "Scenery\\DarkHills\\Blood_Fountain\\T_Blood_Fountain_base_DH_MRA.tga",
            "normal":
                "Scenery\\DarkHills\\Blood_Fountain\\T_Blood_Fountain_base_DH_NRM.tga",
        },
        "kinds": ["Fountain"],
        "weight": 0.15,
    },
    # The override-mode preset. `clearing` re-dresses the blood fountain, which
    # is correct when the whole entity reference is being swapped out (additive
    # mode) and WRONG in place: the fountain is a composite that spawns eleven
    # children, so an in-place override changes its stone base only and the
    # model renders inside the fountain — confirmed in-game 2026-08-13.
    #
    # This donor is one of the eleven props in the corpus that are placed by
    # exactly one pooled tile, draw a single mesh, spawn no children, and stand
    # at tilt 0.00 deg / y 0.00 / scale 1.00. Its material is shared with the
    # other tombstones, so it carries no `slots`: a def using this preset ships
    # geometry and keeps the shipped stone material. Custom textures need a
    # donor whose material is its own, and exactly one upright pooled prop
    # qualifies (`Cone_Chantier` in `Avalon/6x6_Blocker_Wall_Up_01`).
    "standing_stone": {
        "base": "Dark_Hills/40x40_Cenotaph_Statues_Alley_WhiteLadies_Camp",
        "replaces":
            "DarkHills\\Haunted_Hollow\\SceneryObjects_HauntedHollow"
            "\\Tombstone_Big_A_Scrap_A.entity.ot",
        "entity_base":
            "DarkHills\\Haunted_Hollow\\SceneryObjects_HauntedHollow"
            "\\Tombstone_Big_A_Scrap_A.entity.ot",
        "material_base":
            "Scenery\\DarkHills\\Haunted Hollow\\M_Tombstones_Big_N_Blocks.mat.ot",
        "slots": {},
        "kinds": ["Camp"],
        "weight": 0.0,
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

#: Shipped minimap textures a `[marker]` repaints to carry the mod's own art.
#:
#: A texture filed under a name the game does not ship HANGS the game at level
#: load (measured 2026-09-05), so custom icon art has to arrive over an
#: existing name. These two are chosen because NOTHING in any chapter preloads
#: them -- 23 shipped icons qualify, and these two are referenced only by
#: static tutorial book pages -- so repainting them has no collateral in a run.
#: `High` is the map screen, the other the HUD minimap.
MARKER_ICON = "MiniMap\\Icons\\Map_Icons_Corpse.png"
MARKER_ICON_HIGH = "MiniMap\\Icons\\High\\Minimap_IconHigh_Fountain2.png"

#: How far the hero has to be for a POI marker to reveal itself, in world units.
#:
#: The shipped values are 20-25 (a ruin, an ingredient key) — deliberately
#: small, because a shipped landmark is discovered by walking into it. A mod POI
#: has the opposite problem: the icon IS the discovery mechanism, and at 25
#: units it never appears until the player has already found the structure by
#: eye. 300 covers most of a generated map, so the shrine shows on the map from
#: the start of the chapter. Lower it per def with `[marker] reveal_radius`.
DEFAULT_REVEAL_RADIUS = 300.0

#: How much of a `swaps` target may sit BELOW its donor's base before the swap
#: is refused, as a fraction of the target's own height.
#:
#: A swapped object inherits the donor's transform whole, so a mesh authored to
#: hang below its anchor goes underground. `Pontoon_Pillar_12m_C` is the case
#: that paid for this check: a 12.00-unit pontoon pillar whose geometry spans
#: y -8.84 .. +3.16, because it is meant to be driven down from a platform.
#: Stood on `Bone_A` (a bone lying flat, y -0.06 .. +0.07) it put 8.78 units
#: underground and left a 3.16-unit stub. Its minimap marker and its
#: interaction both worked perfectly — those are components at the entity
#: origin — so in-game this reads as "there is an icon and a prompt and no
#: object", which is indistinguishable from the component work being broken.
#: That is exactly the confusion this whole feature spent playtests on.
#:
#: 0.5 is deliberately generous: half-sinking a rock into a slope is a real
#: thing an author may want. Losing most of the object is not.
MAX_SUNK_FRACTION = 0.5

#: Donor tilt, in degrees, past which a `swaps` target is reported as leaning.
#:
#: A swapped object inherits the donor's ROTATION as well as its position, and
#: level designers lay rubble down at whatever angle looks good: in
#: `6x6_Blocker_02` the median placement tilt is 34 deg. Stand something tall on
#: one of those and it leans — the taller it is, the further its top travels
#: (8.67 units at 11.2 deg puts the tip 1.68 units sideways). Measured in-game
#: twice: "some of them tipped over", then "it is not standing".
#:
#: A warning, not a refusal. A leaning obelisk is a legitimate look, and the
#: decoder behind it (`rsmm.engine.level_placements`) reads 350 of the 390
#: shipped levels, so silence here never means "the slot is upright".
#:
#: ⚠ Every tilt this reported before 2026-09-12 was the NEXT object's. The
#: decoder paired an entity reference with the bytes that follow it, which
#: belong to the following object's block, so the oracle that decides whether a
#: POI stands was reading its neighbour. It reads each object's own block now.
MAX_DONOR_TILT_DEG = 5.0

#: The entity whose placing tile's cache covers BOTH override parents' closures.
#:
#: `Minimap_Marker_Reveal_Model` and `Interactive_Object_Model` each drag a
#: closure in with them -- three UI marker entities, a proximity tester, and
#: seven Ui/FX textures between them -- and a resource the tile's cache never
#: lists resolves to null at level build, which the teardown loop then destroys
#: unchecked. Deriving that closure by hand means getting the ROOT of every
#: texture right (`Ui` vs `FX`), so instead the cache of a shipped tile that
#: already carries both is unioned in whole -- the same `borrow_for` mechanism
#: `swaps` uses. The Dark Hills cauldron is the tile that has both: the
#: cauldron is interactable and its sibling marker entity inherits the reveal
#: model. Checked line by line, its cache covers all 14 closure members.
#:
#: The donor entities themselves are NOT listed here on purpose: their records
#: are copied into the host, so the host never references them at runtime.
_CLOSURE_BORROW = ("Objects\\Leprechaun_Cauldron\\"
                   "Leprechaun_Cauldron_DarkHills_T1.entity.ot")

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


def kind_pool_counts(chapter: str) -> dict[str, int]:
    """How many tiles in this chapter's vanilla pool declare each kind.

    This is the denominator of a POI's spawn share. A chapter draws each slot
    from the pool entries matching that slot's kind, so a kind with two entries
    is a kind the player sees at most twice a run — adding a tile to it makes a
    *rare* structure however many copies it ships, while a kind with fifteen is
    common ground. `weight` does not change any of this (see TIER_WEIGHTS).
    """
    stem = CHAPTERS.get(chapter)
    if not stem:
        return {}
    gen = _MAPS_DIR / f"{stem}{MP.GEN_SUFFIX}"
    if not gen.is_file():
        return {}
    counts: dict[str, int] = {}
    for path in MP.read_pool(gen.read_bytes()) or []:
        # "Tiles\\<Biome>\\<Name>.tiledef.ot" -> data/uncooked path
        parts = path.replace("\\", "/").split("/")
        if len(parts) < 3:
            continue
        stem_name = parts[-1].removesuffix(".tiledef.ot")
        p = _TILES_DIR / parts[-2] / f"{stem_name}{TC.GEN_SUFFIX}"
        if not p.is_file():
            continue
        try:
            kinds = TC.read(p.read_bytes()).kinds
        except TC.TileCookError:
            continue
        for k in kinds:
            counts[k] = counts.get(k, 0) + 1
    return counts


def chapter_kinds(chapter: str) -> set[str]:
    """The tile kinds this chapter's existing pool can supply.

    Used as the validation vocabulary for ``kinds``. It is the kinds actually
    reachable in that map today, which is the honest bar: a kind no pooled tile
    declares is one no slot is known to accept.
    """
    return set(kind_pool_counts(chapter))


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
        # `weight` is NEVER inherited from a preset, in either mode — the one
        # key here that is not a description of WHAT to clone but of how the
        # placement driver TIERS the result (see TIER_WEIGHTS). A preset
        # choosing it silently re-tiers every clone away from the donor it is
        # cloning: `clearing`'s 0.15 landed on every runestone-shrine tiledef
        # whose donor ships 0.0, without the author writing `weight` anywhere.
        #
        # 0.15 is a legitimate value — 16 shipped tiles carry it — so this is
        # not about a bad number. It is that a tile cloned from a T1 blocker
        # silently stopped being one. Left unset the clone keeps the donor's own
        # tier, which is what cloning a tile is supposed to mean.
        no_inherit = ("kinds", "weight") if overriding else ("weight",)
        for key in ("base", "kinds", "weight", "copies", "replace_base",
                    "own_level", "swaps", "places"):
            if key in cfg:
                block[key] = cfg.pop(key)
            elif key in preset and key not in no_inherit:
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

        # Read before the prop block is built: it decides whether `replaces`
        # is inherited, and it has to come off the RAW config because the
        # ContentDef does not exist yet.
        raw_places = cfg.get("places") or block.get("places") or []
        places_own_prop = isinstance(raw_places, list) and any(
            isinstance(i, dict) and i.get("entity") == PLACES_OWN_PROP
            for i in raw_places)

        model = next((m for m in MODEL_NAMES if (d / m).is_file()), None)
        # A folder with no model still gets a prop when it names what the prop
        # takes the place of: the prop is then the donor's shape under a name
        # this mod owns. Without `replaces` there is nothing to stand in for,
        # so a bare folder stays a plain tile clone as before.
        if model or cfg.get("replaces"):
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
            # No texture files is allowed and means "my shape, the donor's
            # material" — see `_emit_prop_art`. It is a legitimate way to ship
            # custom geometry, and the one that does not also exercise the
            # texture and material cooks.
            if not textures:
                _log.info("poi %s: model with no textures — using the donor "
                          "material %s unchanged", d.name,
                          cfg.get("material_base") or preset["material_base"])
            block["prop"] = {
                "model": f"{rel}/{model}" if model else "",
                "textures": textures,
                # NOT inherited by an additive def. Every preset names a
                # `replaces` donor because the presets were written for the
                # in-place path, and a def that places its own prop takes
                # nothing's place — inheriting one made this def validate a
                # victim it never touches (`level places no object
                # Blood_Fountain_DarkHills`, on a tile that has no fountain).
                "replaces": (cfg.pop("replaces", None) if places_own_prop
                             else cfg.pop("replaces", preset["replaces"])),
                "entity_base": cfg.pop("entity_base", preset["entity_base"]),
                "material_base": cfg.pop("material_base", preset["material_base"]),
            }
            if "material" in cfg:
                block["prop"]["material"] = cfg.pop("material")
            if "transform" in cfg:
                block["prop"]["transform"] = cfg.pop("transform")
            if "allow_shared_art" in cfg:
                block["prop"]["allow_shared_art"] = cfg.pop("allow_shared_art")
            if "marker" in cfg:
                mk = cfg.pop("marker")
                if not isinstance(mk, dict):
                    raise ContentError(
                        f"poi {d.name}: `marker` must be a table, got {mk!r}")
                for gone, why in (
                        ("own_icon",
                         "a texture filed under a name the game does not ship "
                         "HANGS the game at level load"),
                        ("repaint",
                         "the repaint target is chosen for you now — two "
                         "shipped icons nothing preloads")):
                    if mk.pop(gone, None) is not None:
                        raise ContentError(
                            f"poi {d.name}: [marker] {gone} is gone: {why}. "
                            f"Ship `icon` (and optionally `icon_high`) and the "
                            f"art is written over those names for you."
                        )
                extra = sorted(set(mk) - {"donor", "icon", "icon_high",
                                          "reveal_radius"})
                if extra:
                    raise ContentError(
                        f"poi {d.name}: unknown key(s) in [marker]: "
                        f"{', '.join(extra)} — expected icon, icon_high, "
                        f"reveal_radius, donor")
                for slot in ("icon", "icon_high"):
                    if mk.get(slot):
                        mk[slot] = f"{rel}/{mk[slot]}"
                block["prop"]["marker"] = mk
            if "interactive" in cfg:
                interactive = cfg.pop("interactive")
                if not isinstance(interactive, bool):
                    raise ContentError(
                        f"poi {d.name}: `interactive` must be true or false, "
                        f"got {interactive!r}")
                block["prop"]["interactive"] = interactive
            if "components" in cfg:
                comps = cfg.pop("components")
                if (not isinstance(comps, list)
                        or not all(isinstance(c, str) for c in comps)):
                    raise ContentError(
                        f"poi {d.name}: `components` must be a list of names, "
                        f"got {comps!r}"
                    )
                for c in comps:
                    try:
                        EC.resolve_parent(c)
                    except EC.EntityComponentError as e:
                        raise ContentError(f"poi {d.name}: {e}") from e
                block["prop"]["components"] = comps
        cfg.pop("slots", None)
        if ("marker" in cfg or "interactive" in cfg) and not places_own_prop:
            # Both hang components off a HOST entity. In place that host is the
            # prop named by `replaces`; additively it is the entity the def
            # emits and stands with `places = [{ entity = "@prop" }]`. With
            # neither there is nothing to put them on.
            raise ContentError(
                f"poi {d.name}: [marker] and `interactive` need a host entity. "
                f"Either set `replaces = \"<Biome>\\\\<Prop>.entity.ot\"` to "
                f"configure a shipped prop in place, or place this def's own "
                f"prop additively with "
                f"places = [{{ entity = \"{PLACES_OWN_PROP}\", ... }}].")

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
    # `replace_base` defs first. They edit the shipped tile that the additive
    # defs then CLONE, and a clone without `own_level` shares that tile's level
    # — so its cache has to be seeded from the edited cache, not the shipped
    # one. Stable, so folder order still decides within each group.
    blocks.sort(key=lambda b: not b.get("replace_base"))
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
        # A RANGE, not a membership test. `TIER_WEIGHTS` describes the
        # tier-suffixed families (cauldrons, grimoires, wishing wells), where
        # T1/T2/T3 really are 0.0/0.333/0.667 — but the wider corpus is not
        # that tidy: measured across all 237 shipped tiledefs the values are
        # 0.0 x149, 0.333333 x31, 0.33 x25, 0.15 x16, 0.666667 x5, 0.66 x4,
        # 0.333 x2, 0.1 x2, and one each of 0.67/0.3/0.33333. So 0.15 and 0.1
        # are things the game itself ships, and refusing them would reject a
        # value 16 shipped tiles carry.
        if not 0.0 <= float(w) <= 1.0:
            raise ContentError(
                f"poi {defn.id}: 'weight' {w} out of range — shipped tiles use "
                f"0.0 to ~0.67 (see TIER_WEIGHTS; it is a tier field, not a "
                f"spawn rate — raise 'copies' or widen 'kinds' for frequency)."
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


#: Below this many vanilla pool entries, a kind is a rare slot: winning every
#: entry of it still leaves the structure mostly unseen. Two of the three kinds
#: in the `clearing` preset's donor sit here, which is why a shrine that WAS
#: correctly pooled could still go a whole run unnoticed.
_RARE_KIND = 3


def _report_share(mod_id: str, defn: ContentDef, td: TC.TileDef,
                  chapters: list[str], copies: int) -> None:
    """Say what share of its slots this POI actually wins, per chapter.

    A POI competes only against pool entries declaring the same kind, so the
    number that decides whether a player ever sees it is ``copies / (copies +
    vanilla entries of that kind)`` — not `weight`, and not the size of the
    pool. Emitting that number is the difference between "it doesn't work" and
    "it works and is meant to be rare".
    """
    for ch in chapters:
        counts = kind_pool_counts(ch)
        for kind in td.kinds:
            vanilla = counts.get(kind, 0)
            share = copies / (copies + vanilla) if copies + vanilla else 0.0
            msg = ("poi %s/%s: %s slots in %s — %d vanilla + %d copies "
                   "= %.0f%% share")
            args = (mod_id, defn.id, kind, ch, vanilla, copies, 100 * share)
            if vanilla < _RARE_KIND:
                _log.warning(
                    msg + "; '%s' is a RARE slot kind, so the structure stays "
                    "uncommon however many copies it ships. Add a commoner kind "
                    "(see `rsmm poi kinds %s`) to be seen more often.",
                    *args, kind, ch)
            else:
                _log.info(msg, *args)


def _emitted_assets(out_dir: Path, written: list[Path]) -> list[str]:
    """Decoded cooked paths of the resources a cache must preload.

    Caches never list each other, and a mapdef is the chapter's own definition
    rather than one of its tiles' resources.
    """
    out = []
    for p in written:
        rel = p.relative_to(out_dir).as_posix()
        if rel.endswith(RC.CACHE_SUFFIX) or rel.startswith(f"{_MAP_ASSET_SUBDIR}/"):
            continue
        out.append(rel)
    return out


@lru_cache(maxsize=512)
def _mesh_y_range(mesh_ref: str) -> tuple[float, float] | None:
    """``(ymin, ymax)`` of a shipped mesh in its own object space, or None.

    The corpus mirrors geometry as `<mesh>.glb`, so this is a straight read —
    no cooking, no game. None when the corpus is absent (this is a dev-checkout
    oracle, like every other guard here) or the mesh is not mirrored.
    """
    from ...engine import geometry_cook as GC

    path = _UNCOOKED / "3D" / (mesh_ref.replace("\\", "/") + ".glb")
    if not path.is_file():
        return None
    try:
        lo, hi = 1e18, -1e18
        for sm in GC.glb_to_submeshes(path.read_bytes()):
            for pos in sm.positions:
                lo = min(lo, pos[1])
                hi = max(hi, pos[1])
    except (OSError, ValueError, KeyError, IndexError, struct.error):
        return None
    return (lo, hi) if hi >= lo else None


def _emitted_mesh_y_range(mesh_ref: str,
                          out_dir: Path | None) -> tuple[float, float] | None:
    """``(ymin, ymax)`` of a mesh THIS MOD has already emitted, or None.

    A mod that overrides a prop's art changes the very bounds this check is
    about, and it is the emitted mesh that ships. `discover` puts `replace_base`
    defs first, so the art override is on disk by the time a later def's swaps
    are validated — which is what makes reading it here correct rather than
    racy.
    """
    if out_dir is None:
        return None
    from ...engine import geometry_cook as GC

    path = out_dir / "3D" / (mesh_ref.replace("\\", "/") + ".Geometry.gen")
    if not path.is_file():
        return None
    try:
        lo, hi = 1e18, -1e18
        for sm in GC.glb_to_submeshes(
                GC._geo.decode_cooked_to_glb(path.read_bytes())):
            for pos in sm.positions:
                lo = min(lo, pos[1])
                hi = max(hi, pos[1])
    except (OSError, ValueError, KeyError, IndexError, struct.error):
        return None
    return (lo, hi) if hi >= lo else None


def _entity_y_range(ref: str, defn_id: str,
                    out_dir: Path | None = None) -> tuple[float, float] | None:
    """``(ymin, ymax)`` over every mesh an entity draws, or None if unknown.

    Prefers this mod's own emitted art over the shipped mesh: overriding a
    prop's geometry is exactly how a donor that hangs below its origin is made
    usable, and judging it by the mesh it no longer draws would refuse the fix.
    """
    from ...engine import entity_strings as ES

    try:
        ent = _corpus(PC.entity_cooked_path(ref), defn_id, f"entity {ref}")
    except (SchemaNotMined, ContentError, ValueError, OSError):
        return None
    ranges = []
    for _s, _o, t in ES.list_strings(ent):
        if not t.lower().endswith(".fbx"):
            continue
        r = _emitted_mesh_y_range(t, out_dir) or _mesh_y_range(t)
        if r:
            ranges.append(r)
    if not ranges:
        return None
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _warn_if_donor_slot_leans(defn_id: str, base: str, src: str) -> None:
    """Report a swap donor whose slot is not upright.

    The replacement adopts this rotation, so it decides whether the POI stands
    or lies over — and nothing else in the pipeline can see it. Silent when the
    level does not decode: `level_placements` fails closed by design.
    """
    try:
        level = _corpus(PC.level_cooked_path(
            _level_ref_of(_prefab_ref_of(base, defn_id), defn_id)),
            defn_id, "the tile's level")
    except (SchemaNotMined, ContentError, ValueError, OSError):
        return
    slots = LP.placements_of(level, src)
    leaning = [p for p in slots if p.tilt_deg > MAX_DONOR_TILT_DEG]
    if not leaning:
        return
    worst = max(p.tilt_deg for p in leaning)
    _log.warning(
        "poi %s: swaps donor %s is placed at %.1f deg from upright (%d of %d "
        "slot(s) lean), and a swapped object inherits the donor's rotation — "
        "the replacement will lean by the same amount. Pick a slot this tile "
        "places upright, or accept the tilt deliberately.",
        defn_id, src.split("\\")[-1], worst, len(leaning), len(slots))


def _inherits_marker(ref: str, defn_id: str, out_dir: Path | None) -> bool:
    """Does this mod emit `ref` inheriting the minimap-marker parent?

    Read from the EMITTED entity, because inheriting it is something this mod
    does — the shipped one has no such parent.
    """
    if out_dir is None:
        return False
    path = out_dir / PC.entity_cooked_path(ref)
    if not path.is_file():
        return False
    try:
        return EC.PARENTS["minimap"] in EC.parents(path.read_bytes())
    except (OSError, ValueError, EC.EntityComponentError):
        return False


def _assert_swap_target_is_not_sunk(defn_id: str, src: str, dst: str,
                                    out_dir: Path | None = None) -> None:
    """Refuse a swap that would bury its target in the ground.

    The target inherits the donor's transform, so what matters is not how tall
    it is but how far it reaches BELOW the donor's own base. Silent in-game and
    silent everywhere else: the object loads, instantiates, resolves, caches and
    draws — underground. See :data:`MAX_SUNK_FRACTION`.
    """
    # The DONOR is read as the game SHIPS it: its mesh defines the slot the
    # level author built, and that is what the replacement has to fit. The
    # TARGET is read as this mod EMITS it, because that is what will actually
    # stand there. Reading both the same way breaks one case or the other —
    # mod art on the donor made a legitimate restore look like a burial.
    # A MARKER ANCHOR is exempt: a host inheriting the reveal parent does not
    # draw its mesh at all (measured 2026-09-06 — the icon appeared and the
    # obelisk did not), so where that mesh would have sat is meaningless. The
    # check is about art being buried, and an anchor is not art.
    if _inherits_marker(dst, defn_id, out_dir):
        return
    donor = _entity_y_range(src, defn_id)
    target = _entity_y_range(dst, defn_id, out_dir)
    if donor is None or target is None:
        return                      # no corpus, or an unmirrored mesh
    height = target[1] - target[0]
    sink = donor[0] - target[0]
    if height <= 0 or sink <= MAX_SUNK_FRACTION * height:
        return
    raise ContentError(
        f"poi {defn_id}: swaps target {dst} would be buried. Its mesh spans "
        f"y {target[0]:.2f}..{target[1]:.2f}, and {src} — whose transform it "
        f"inherits — sits at y {donor[0]:.2f}, so {sink:.2f} of its "
        f"{height:.2f} units ({sink / height:.0%}) end up underground. A "
        f"marker or an interaction on it would still work, which is what makes "
        f"this so hard to read in-game: an icon and a prompt with no object. "
        f"Swap onto a donor whose base is as low, or pick a target whose mesh "
        f"sits on its own origin."
    )


def _places_own_prop(defn: ContentDef) -> bool:
    """Does this def stand its OWN prop, rather than a shipped entity?

    Read straight off the raw fields rather than off `_validated_places`, so it
    is safe to call from inside the validation it would otherwise recurse into.
    """
    raw = defn.fields.get("places")
    return isinstance(raw, list) and any(
        isinstance(i, dict) and i.get("entity") == PLACES_OWN_PROP for i in raw)


def _validated_places(defn: ContentDef) -> list[dict]:
    """Check and return ``places`` — objects this def ADDS to its own level.

    ``places = [{ entity = "...", pos = [x, y, z], scale = 1.0, yaw = 0.0 }]``

    The difference from ``swaps`` is control. A swap re-dresses a slot the level
    author chose and inherits that slot's transform whole — position, rotation
    AND scale — which is where "not standing", "buried in the ground" and "the
    model is offset" all came from, each measured in-game. An added placement
    takes the transform written here and destroys nothing.

    Needs ``own_level``: appending to a SHIPPED level would put the object in
    every placement of that tiledef, vanilla ones included.
    """
    raw = defn.fields.get("places")
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise ContentError(f"poi {defn.id}: 'places' must be a non-empty list")
    if not (defn.fields.get("own_level") or defn.fields.get("replace_base")):
        raise ContentError(
            f"poi {defn.id}: 'places' adds objects to a tile's level, so it "
            f"needs own_level = true (add to a level this mod owns) or "
            f"replace_base = true (add to the SHIPPED level in place).")
    if defn.fields.get("replace_base") and not defn.fields.get("own_level"):
        # ⚠ MEASURED 2026-09-10, and it is why this is allowed at all.
        #
        # A mod-owned level is placed, kept by the engine, and instantiates NONE
        # of its objects — not even the ones it inherited from its donor. The
        # tell was a map with no healing fountains anywhere: this mod held 8 of
        # 10 Fountain pool entries, so its tiles won nearly every fountain slot,
        # and each one built nothing at all. The donor's own fountain vanished
        # with everything else.
        #
        # Editing the SHIPPED level in place is the counterpart that works: the
        # level keeps its path, its bare identifier and its identity GUID,
        # because it is still the same level. Nothing is removed — an added
        # placement destroys nothing — but the addition is GLOBAL, so the object
        # stands in every placement of that tiledef, vanilla ones included.
        _log.warning(
            "poi %s: `places` without own_level edits the SHIPPED level, so the "
            "added object appears in EVERY placement of %s, not only this mod's. "
            "Nothing is removed and `restore` puts the level back.",
            defn.id, defn.fields.get("base", "the base tile"))
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("entity"):
            raise ContentError(
                f"poi {defn.id}: places[{i}] needs an `entity` reference")
        ent = item["entity"]
        if ent == PLACES_OWN_PROP:
            # The guard below asks "has anything ever stood this entity at a
            # transform of its own", which a name that did not exist until this
            # emit obviously fails. Ask it of the DONOR instead: the clone is
            # that donor's component structure wearing this mod's mesh, so what
            # the donor can do it can do. The rule keeps its teeth and stops
            # being unanswerable.
            spec = defn.fields.get("prop")
            if not isinstance(spec, dict):
                raise ContentError(
                    f"poi {defn.id}: places[{i}] is {PLACES_OWN_PROP!r}, which "
                    f"stands the prop this def emits — so the def needs a "
                    f"[prop] table to emit one.")
            donor = spec.get("entity_base")
            if donor not in _placeable_entities():
                raise ContentError(
                    f"poi {defn.id}: places[{i}] is {PLACES_OWN_PROP!r} and "
                    f"prop.entity_base {donor!r} is not placed by any shipped "
                    f"level, so there is no evidence its structure can stand at "
                    f"a transform on its own.")
        elif not ent.lower().endswith(".entity.ot"):
            raise ContentError(
                f"poi {defn.id}: places[{i}].entity must end in .entity.ot, "
                f"got {ent!r}")
        elif ent not in _placeable_entities():
            raise ContentError(
                f"poi {defn.id}: places[{i}] entity {ent} is not placed by any "
                f"shipped level, so nothing shows it can stand at a transform "
                f"on its own — the same rule `swaps` targets obey.")
        pos = item.get("pos") or [0.0, 0.0, 0.0]
        if len(pos) != 3:
            raise ContentError(f"poi {defn.id}: places[{i}].pos needs 3 numbers")
        out.append({"entity": ent,
                    "pos": tuple(float(v) for v in pos),
                    "scale": float(item.get("scale", 1.0)),
                    "yaw": float(item.get("yaw", 0.0))})
    return out


def _validated_swaps(defn: ContentDef, base: str,
                     out_dir: Path | None = None) -> dict[str, str]:
    """Check and return ``swaps`` — re-dress a tile using props the game ships.

    ``swaps = { "<placed>.entity.ot" = "<replacement>.entity.ot" }`` puts a
    different shipped entity at an object's transform. No new asset is created,
    which makes it the cheapest way to change what a tile looks like — and the
    one shape of tile edit whose correctness does not depend on any of this
    module's cooking.

    Both sides are validated here rather than in-game, and **both** must be
    entities the tile's level actually places.

    Being in the tile's resource cache is not enough, though it looks like it
    should be. A cache is a transitive dependency closure, so it also lists
    every sub-entity that placed props merely *reference* — this tile caches
    ``ENV_Model_Selector_Mat_Banner_A_DarkHills``, which exists to be picked
    from by the banner prop and is not a thing that can stand at a transform on
    its own. Swapping to one loads, preloads and validates perfectly and then
    fails to build in-game, which surfaces as the same anonymous access
    violation as everything else in this area. "Already placed somewhere in
    this tile" is the property that actually means "can be placed here", and it
    is checkable, so it is what is checked.
    """
    raw = defn.fields.get("swaps")
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise ContentError(f"poi {defn.id}: 'swaps' must be a non-empty table")
    if not (defn.fields.get("replace_base") or defn.fields.get("own_level")):
        raise ContentError(
            f"poi {defn.id}: 'swaps' rewrites a tile's level, so it needs "
            f"replace_base = true (edit the shipped tile in place) or "
            f"own_level = true (give the clone its own level). A cloned tile "
            f"that wants its own prop should use 'prop' instead."
        )
    for src, dst in raw.items():
        if not isinstance(dst, str) or not dst.lower().endswith(".entity.ot"):
            raise ContentError(
                f"poi {defn.id}: swaps[{src!r}] must be an entity reference "
                f"ending in .entity.ot, got {dst!r}"
            )

    from ...engine import entity_strings as ES

    level_ref = _level_ref_of(_prefab_ref_of(base, defn.id), defn.id)
    level = _corpus(PC.level_cooked_path(level_ref), defn.id, "the tile's level")
    placed = {s for _sec, _off, s in ES.list_strings(level)
              if s.lower().endswith(".entity.ot")}
    for src, dst in raw.items():
        # The SOURCE must be an object this tile actually places — it is the
        # transform being reused, so there is nothing to swap otherwise.
        if src not in placed:
            near = sorted(p for p in placed
                          if Path(src).name.split(".")[0].lower() in p.lower())
            hint = f" Did you mean: {near[0]!r}?" if near else ""
            raise ContentError(
                f"poi {defn.id}: swaps source {src!r} is not an object {base} "
                f"places, so there is no transform to put anything at.{hint} "
                f"`rsmm poi show {base}` lists what this tile places."
            )
        # The TARGET only has to be something SOME shipped level places. The
        # property being tested is "can stand at a transform on its own", and a
        # placement anywhere in the corpus proves that just as well as a
        # placement here. Requiring it in THIS tile made the check simple but
        # also made it impossible to introduce anything the tile lacked —
        # including a minimap-marker entity, which is the only way a POI can
        # ever be marked on the map. Being merely in a resource cache still
        # does not count: a cache is a dependency closure and lists sub-entities
        # that exist only to be selected by a prop, and swapping to one of those
        # builds nothing and crashes.
        if dst not in placed and dst not in _placeable_entities():
            raise ContentError(
                f"poi {defn.id}: swaps target {dst!r} is not placed by any "
                f"shipped level, so nothing shows that it can stand at a "
                f"transform on its own. A reference that only appears in a "
                f"resource cache is usually a sub-entity another prop selects "
                f"from; swapping to one builds nothing and crashes."
            )
        # A multi-mesh target is a STATE MACHINE, not a prop. `Key_Lock` ships
        # ten meshes and a selector component that picks one for the current
        # state; dropped in as level scenery nothing drives that selector, so
        # several draw at once and the result reads as a broken object. Seen
        # in-game 2026-09-05 — "parts of an object that wants a key next to
        # each other". A warning rather than a refusal, because swapping in an
        # interactive entity is a legitimate and so-far unmatched way to put a
        # working prompt at a POI; the author just has to know why it looks
        # like that.
        try:
            meshes = {t for _s, _o, t in ES.list_strings(
                _corpus(PC.entity_cooked_path(dst), defn.id,
                        f"swaps target {dst}"))
                if t.lower().endswith(".fbx")}
        except (SchemaNotMined, ContentError, ValueError):
            meshes = set()
        if len(meshes) > 1:
            _log.warning(
                "poi %s: swaps target %s carries %d meshes, so it is a "
                "state-driven object rather than a prop. Placed as level "
                "scenery nothing drives its selector and several meshes draw "
                "at once — it will look broken. Prefer a single-mesh target.",
                defn.id, dst, len(meshes))
        _assert_swap_target_is_not_sunk(defn.id, src, dst, out_dir)
        _warn_if_donor_slot_leans(defn.id, base, src)
    return dict(raw)


def _extend_map_caches(out_dir: Path, defn_id: str, chapters: list[str],
                       assets: list[str], tile_rels: list[str],
                       written: list[Path],
                       extra_lines: Iterable[str] = ()) -> None:
    """Add this def's tiles and resources to each target chapter's own cache.

    A mapdef has a resource cache like any other definition, and it is a strict
    **superset** of every one of its tiles' caches — measured on the shipped
    data, the Dark Hills start tile's 784 lines all appear in the chapter's
    5636, 784/784. Two consequences, and missing either hides the POI with no
    diagnostic:

    * the chapter lists its pool's tiledefs one for one (77 entries, 77 lines),
      so a tile appended to the pool but not here is never loaded;
    * a tile edited to reference new art needs that art here too, even in
      ``replace_base`` mode where no tile is added to any pool at all.

    `extra_lines` carries whatever `_emit_tile_caches` borrowed in, because
    those are cache LINES rather than paths of ours and nothing else would ever
    bring them here. ⚠ Measured 2026-09-12: the shrine's tile cache named
    `BonFire` and the chapter's did not, which breaks the superset the shipped
    data holds 784/784 — and both halves of a `places` entity have to be
    preloaded or the reference resolves to null at level build.
    """
    for ch in chapters:
        rel = RC.cache_path_for(f"{_MAP_ASSET_SUBDIR}/{CHAPTERS[ch]}{MP.GEN_SUFFIX}")
        dest = out_dir / Path(*rel.split("/"))
        # Build on what an earlier def in this mod already emitted, exactly as
        # the pool edit does — starting from vanilla each time would make the
        # last def win and silently strip the others' resources.
        base_bytes = (dest.read_bytes() if dest.is_file()
                      else _corpus(rel, defn_id, f"the {ch} mapdef's resource cache"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = RC.extend(base_bytes, [*tile_rels, *assets])
        extra = sorted(set(extra_lines))
        if extra:
            data = RC.render(sorted(set(RC.parse(data)) | set(extra)))
        dest.write_bytes(data)
        if dest not in written:
            written.append(dest)


@lru_cache(maxsize=1)
def _placeable_entities() -> frozenset[str]:
    """Every entity some shipped LEVEL places, anywhere in the corpus.

    `_validated_swaps` needs to know whether a reference can stand at a
    transform on its own. Being in a resource cache does not prove that — a
    cache is a dependency closure and lists sub-entities that exist only to be
    selected by a prop. Being *placed by a level* does prove it, and this is
    the corpus-wide version of that evidence, used when the swap target is not
    already in the tile the def is editing.
    """
    from ...engine import entity_strings as ES

    def build() -> list[str]:
        out: set[str] = set()
        for lp in sorted((_UNCOOKED / "Ot").rglob("*.level.ot.GameStream.gen")):
            try:
                out |= {s for _sec, _off, s in ES.list_strings(lp.read_bytes())
                        if s.lower().endswith(".entity.ot")}
            except (OSError, ValueError):
                continue    # a level this codec cannot frame is not evidence
        return sorted(out)

    return frozenset(corpus_cache.load_or_build(
        "placeable_entities", _UNCOOKED, build))


@lru_cache(maxsize=1)
def _tile_cache_by_placed_entity() -> dict[str, str]:
    """Entity ref -> the cooked cache path of a tiledef whose level places it.

    Swapping in an entity the editing tile never referenced means its whole
    dependency closure — mesh, material, textures, icon — is absent from that
    tile's cache, and a resource the level asks for but the cache never listed
    is precisely the null that crashes level build. Rather than re-deriving the
    closure (which would need the full reference graph), borrow the cache of a
    tile that already places the thing: it is guaranteed to contain it. Surplus
    lines only cost a wasted preload of a real shipped file, which is the same
    trade `rsc_cache` already makes by being append-only.
    """
    from ...engine import entity_strings as ES

    def build() -> dict[str, str]:
        out: dict[str, str] = {}
        for tp in sorted((_UNCOOKED / "Definitions" / "Tiles").rglob(f"*{TC.GEN_SUFFIX}")):
            rel = tp.relative_to(_UNCOOKED / "Definitions" / "Tiles")
            base = str(rel).replace(TC.GEN_SUFFIX, "")
            try:
                td = TC.read(tp.read_bytes())
                prefab = td.entity_ref[1] if td.entity_ref else None
                if not prefab:
                    continue
                ep = _UNCOOKED / "EntitySettings" / (
                    prefab.replace("\\", "/") + ".EntitySettingsResource.gen")
                lv = [s for _sec, _off, s in ES.list_strings(ep.read_bytes())
                      if s.lower().endswith(".level.ot")]
                if not lv:
                    continue
                lp = _UNCOOKED / "Ot" / (lv[0].replace("\\", "/") + ".GameStream.gen")
                placed = {s for _sec, _off, s in ES.list_strings(lp.read_bytes())
                          if s.lower().endswith(".entity.ot")}
            except (OSError, ValueError, KeyError, IndexError):
                continue
            cache_rel = RC.cache_path_for(f"{_TILE_ASSET_SUBDIR}/{base}{TC.GEN_SUFFIX}")
            for ent in placed:
                out.setdefault(ent, cache_rel)
        return out

    return corpus_cache.load_or_build(
        "tile_cache_by_placed_entity", _UNCOOKED, build)


#: Cook suffixes by engine class, for the few classes that NAME other resources.
#: Anything absent is a leaf as far as the closure walk is concerned (a texture
#: references nothing; a geometry's materials are already named by the entity
#: that uses it).
_CLOSURE_SUFFIX = {
    "oCEntitySettingsResource": ".EntitySettingsResource.gen",
    "oCMaterial": ".Material.gen",
    "oCGameStream": ".GameStream.gen",
}


def _cache_refs(root: str, path: str, cls: str, out_dir: Path) -> list[str]:
    """Resources named by one cache entry, or `[]` if it names none.

    The mod's OWN copy wins over the corpus. The entity this walk cares about
    most is one the mod has already edited -- the marker host references its
    inherited parents only in the emitted version -- and reading the pristine
    file instead drops exactly the parents the cache exists to preload.
    """
    suffix = _CLOSURE_SUFFIX.get(cls)
    if suffix is None:
        return []
    rel = Path(root) / Path(*f"{path}{suffix}".split("\\"))
    f = out_dir / rel
    if not f.is_file():
        f = _UNCOOKED / rel
    if not f.is_file():
        return []
    try:
        return [r for r in AR._decode(f.read_bytes(), cls)["asset_refs"]
                if not r.startswith("[")]
    except (ValueError, KeyError, IndexError, struct.error) as e:
        # Say so. Returning no references keeps this entry but stops the walk
        # under it, and anything only reachable THROUGH it is then dropped from
        # the cache — which is a null in the preloaded vector, far from here.
        _log.warning("poi: cannot read %s to walk its references (%s) — "
                     "resources reachable only through it will be missing "
                     "from the preload cache", f, e)
        return []


#: Roots a `.png` can be filed under, commonest first. ⚠ There are FIVE, and
#: `Ui` is not even the largest: measured over 80 shipped tile caches, FX 2339,
#: Ui 1590, 3D 485, samples 187, Fonts 21. An earlier version of `_reachable`
#: assumed `Ui` for every texture, which writes a cache line naming a resource
#: that does not exist — a null in the preloaded vector, i.e. exactly the crash
#: this module exists to prevent. `.entity.ot` needs no such table: every one of
#: 14399 shipped entity lines is `EntitySettings`.
_TEXTURE_ROOTS = ("FX", "Ui", "3D", "samples", "Fonts")


def _texture_root_index() -> dict[str, str]:
    """Texture path -> the root the SHIPPED caches file it under.

    The corpus mirror is incomplete (`FX`, the commonest texture root, is not
    mirrored at all), so a corpus probe alone cannot place every texture — and
    a texture that cannot be placed is left out of the preload cache, which is
    a null at level build rather than merely a missing icon. The 575 shipped
    `*.UsedRscCache.ot` files already state the root for every resource the
    game loads, so they answer it without guessing.
    """
    def build() -> dict[str, str]:
        out: dict[str, str] = {}
        for cp in sorted((_UNCOOKED / "Definitions").rglob("*.UsedRscCache.ot")):
            try:
                lines = RC.parse(cp.read_bytes())
            except (OSError, ValueError):
                continue
            for line in lines:
                parts = line.split("|")
                if len(parts) == 3 and parts[1].lower().endswith(".png"):
                    out.setdefault(parts[1], parts[0])
        return out

    return corpus_cache.load_or_build("texture_root_index", _UNCOOKED, build)


@_memo
def _texture_cooked_path(path: str) -> str | None:
    """Cooked path for a texture ref, by finding which root actually has it."""
    # The corpus mirrors textures AS PNG (`extract_uncooked.py` decodes them),
    # so probe for the plain file — the `.Texture.dxt` cook suffix only ever
    # exists in the game install, never in `data/uncooked/`.
    rel = Path(*path.split("\\"))
    for root in _TEXTURE_ROOTS:
        if (_UNCOOKED / root / rel).is_file():
            return f"{root}/{path.replace(chr(92), '/')}.Texture.dxt"
    # Not mirrored — `FX` in particular is absent from `data/uncooked/` while
    # being the commonest texture root of all. The game's own 575 shipped
    # caches are the authoritative answer for where a resource is filed, so ask
    # them rather than give up: a skipped texture is still a missing preload.
    root = _texture_root_index().get(path)
    return (f"{root}/{path.replace(chr(92), '/')}.Texture.dxt"
            if root is not None else None)


def _reachable(seeds: Iterable[str], lines: list[str],
               out_dir: Path) -> tuple[set[str], list[str]]:
    """Cache paths reachable from `seeds` by following resource references.

    `borrow_for` unions in the WHOLE cache of some shipped tile that happens to
    place the swapped-in entity, which is 15x more than the swap actually needs
    -- the blocker tile's cache went 95 -> 1439 lines, 64 of them Avalon- and
    Nightmare-rooted resources in a Dark Hills tile. A surplus line is supposed
    to cost only a wasted preload, but that assumes it RESOLVES, and a resource
    that does not leaves the null in the preloaded vector this whole module
    exists to avoid. So the borrow stays authoritative for CLASS names and the
    walk decides membership.
    """
    index: dict[str, tuple[str, str]] = {}
    for line in lines:
        parts = line.split("|")
        if len(parts) == 3:
            index[parts[1]] = (parts[0], parts[2])
    seen: set[str] = set()
    extra: list[str] = []
    queue = list(seeds)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        if path in index:
            seen.add(path)
            root, cls = index[path]
            queue.extend(_cache_refs(root, path, cls, out_dir))
            continue
        # Reachable, but the borrowed tile never listed it. That is not an
        # exotic case: the marker parent names eight `GameUis\\MinimapMarkers`
        # entities and a primitive, EVERY shipped tile carrying a marker lists
        # all nine, and the tile we borrow from carries no marker at all -- so
        # borrowing alone can never cover a capability the donor lacks. A
        # marker whose display UI is not preloaded is an icon that never draws.
        if path.lower().endswith(".entity.ot"):
            # Only if it actually EXISTS. A cache line for a resource the game
            # does not ship is the same failure as one under a wrong root: the
            # preload resolves to null and the teardown loop destroys it
            # unchecked. `_cache_refs` already degrades quietly on a missing
            # file, so without this check a typo'd or renamed ref would sail
            # through and surface as an access violation at level build.
            cooked_rel = entity_cooked_path(path)
            if not (out_dir / Path(*cooked_rel.split("/"))).is_file() \
                    and not (_UNCOOKED / Path(*cooked_rel.split("/"))).is_file():
                _log.warning(
                    "poi: %s is referenced but exists in neither this mod nor "
                    "the corpus — left out of the preload cache rather than "
                    "listed as a resource that cannot resolve", path)
                continue
            seen.add(path)
            extra.append(cooked_rel)
            queue.extend(_cache_refs("EntitySettings", path,
                                     "oCEntitySettingsResource", out_dir))
        elif path.lower().endswith(".png"):
            cooked_rel = _texture_cooked_path(path)
            if cooked_rel is None:
                # Emitting a line under a GUESSED root names a resource that
                # does not exist, which is a null in the preloaded vector — the
                # very failure this cache prevents. Skip it and say so.
                _log.warning(
                    "poi: cannot place %s under any known texture root — "
                    "left out of the preload cache; if it is needed the "
                    "symptom is a null at level build, not a missing icon",
                    path)
                continue
            seen.add(path)
            extra.append(cooked_rel)
    return seen, extra


def _host_refs(defn: ContentDef) -> list[str]:
    """The entity this def edits in place, if it names one.

    A def that only appends components (`replaces` with no `swaps`) places
    nothing, so the swapped-in list is empty and the reachability walk would
    have no seed at all — leaving the parents it inherited, and their UI
    closure, out of the tile's preload cache.
    """
    # `replaces` lives under the `prop` sub-table, not at the block's top
    # level — reading it from the top returns None, the seed list comes back
    # empty, and the empty-seed fallback then seeds from the BORROW SOURCE,
    # which is the bloat this separation exists to stop.
    prop = defn.fields.get("prop")
    ref = prop.get("replaces") if isinstance(prop, dict) else None
    return [ref] if isinstance(ref, str) and ref else []


def _placed_for_cache(defn: ContentDef) -> list[str]:
    """The entities `places` adds, named as the preload cache needs them.

    A `places` entity counts exactly like a swap target: the donor tile never
    referenced it, so its closure is absent from the donor's cache, and one
    reference the cache never lists resolves to NULL at level build — which
    destroys the WHOLE level, not just that object (`LevelObject_LoadOrCreate`).

    ⚠ Shared by both paths ON PURPOSE. The pooled path grew this on 2026-09-06
    after measuring the shrine's tiles listing the swap target but not
    `BonFire`; `replace_base` arrived later and never got it, so the def that
    adds a shipped entity the donor does not place wrote it into the level and
    into nothing else. Measured again 2026-09-12: `BonFire` appeared 0 times in
    the emitted `6x6_Healing_01.tiledef.UsedRscCache.ot`. That would have failed
    the whole tile, and failed it looking exactly like "`places` does not work"
    — poisoning the one arm that exists to tell those apart.

    `@prop` borrows against its DONOR. The mod's own entity is already in the
    emitted assets, but its dependency closure is the donor's, and only a
    shipped tile can prove a closure is covered.
    """
    prop = defn.fields.get("prop")
    own_donor = prop.get("entity_base") if isinstance(prop, dict) else None
    placed = [own_donor if i["entity"] == PLACES_OWN_PROP else i["entity"]
              for i in _validated_places(defn)]
    return [e for e in placed if e]


def _emit_tile_caches(out_dir: Path, base: str, defn_id: str, assets: list[str],
                      tile_rels: list[str], written: list[Path],
                      borrow_for: Iterable[str] = (),
                      seed_for: Iterable[str] = ()) -> list[str]:
    """Give every tiledef this def emitted its ``*.UsedRscCache.ot`` sibling.

    All 237 shipped tiledefs have one and the engine looks it up by convention,
    so a clone without it preloads nothing: the tile is registered, never
    placed, and says nothing about why. When the tile *is* reached with a cache
    that doesn't list something the level references, the missing resource
    leaves a null in the preloaded vector and the engine's teardown loop
    destroys it unchecked — an access violation nowhere near the real mistake.
    See :mod:`rsmm.engine.rsc_cache`.

    The cache is the donor tile's, plus a line for each asset this def emitted
    and one for the tiledef itself.

    `borrow_for` names entities the def swapped IN that the donor tile never
    referenced. Their dependency closures are absent from the donor's cache, so
    the cache of a tile that already places each one is unioned in — see
    :func:`_tile_cache_by_placed_entity` for why borrowing beats deriving.
    """
    donor_cooked = f"{_TILE_ASSET_SUBDIR}/{base}{TC.GEN_SUFFIX}"
    # Prefer the copy a SIBLING def already wrote over the shipped one. A clone
    # made without `own_level` shares the base tile's level, so whatever a
    # `replace_base` def added to that level's dependencies — an inherited
    # marker parent and its whole closure — is reached through the clone too,
    # and a clone seeded from the pristine corpus cache lists none of it. That
    # is the silent null at level build, on the tiles the mod added rather than
    # on the one it edited. `discover` orders `replace_base` defs first so this
    # copy exists by the time a clone is emitted.
    donor_dest = out_dir / Path(*RC.cache_path_for(donor_cooked).split("/"))
    donor = (donor_dest.read_bytes() if donor_dest.is_file()
             else _corpus(RC.cache_path_for(donor_cooked), defn_id,
                          "the base tile's resource cache"))

    borrowed: list[str] = []
    for ent in sorted(set(borrow_for)):
        cache_rel = _tile_cache_by_placed_entity().get(ent)
        if cache_rel is None:
            # Nothing to borrow from means nothing proves the closure is
            # covered. Say so loudly: the failure mode is a null at level
            # build, which surfaces as an access violation nowhere near here.
            _log.warning(
                "poi %s: no shipped tile places %s, so its resources cannot be "
                "borrowed into the cache — if the swap fails in-game this is "
                "the first thing to suspect", defn_id, ent)
            continue
        try:
            # Same reason as the donor above: prefer the copy a sibling def
            # already wrote. A swapped-in entity is routinely one this mod
            # ALSO edited — standing a re-skinned, map-marked prop in a
            # mod-owned level is the whole point of `swaps` — and the shipped
            # cache of the tile it was borrowed from knows nothing about the
            # marker icon that edit introduced.
            borrow_dest = out_dir / Path(*cache_rel.split("/"))
            borrowed.extend(RC.parse(
                borrow_dest.read_bytes() if borrow_dest.is_file()
                else _corpus(cache_rel, defn_id,
                             f"the cache of a tile placing {ent}")))
        except (ContentError, SchemaNotMined, ValueError) as e:
            _log.warning("poi %s: could not borrow %s's cache (%s)", defn_id, ent, e)

    # Keep only what the swapped-in entities actually reach. See `_reachable`:
    # borrowing whole tile caches pulled 1344 unrelated lines into a 95-line
    # cache, including foreign-biome resources this tile can never resolve.
    if borrowed:
        # ⚠ Seed from what the HOST references, never from the tile we borrowed
        # FROM. `_CLOSURE_BORROW` names a shipped entity whose cache happens to
        # cover a parent's closure; seeding the walk with it makes that whole
        # entity reachable, and the marker tile's cache grew by 367 lines — 53
        # of them Leprechaun cauldron animations and geometry, plus Avalon
        # materials in a Dark Hills tile. A borrow source supplies INDEX LINES
        # (authoritative roots and class names); only the entities this def
        # actually places or edits are seeds.
        seeds = sorted(set(seed_for if seed_for else borrow_for))
        keep, missing = _reachable(seeds, borrowed, out_dir)
        # `len(parts) == 3` for the same reason `_reachable`'s index build
        # checks it: a borrowed cache is a shipped file we do not own, and one
        # malformed line must not be an IndexError in the middle of an apply.
        trimmed = [ln for ln in borrowed
                   if len(ln.split("|")) == 3 and ln.split("|")[1] in keep]
        _log.info("poi %s: borrowed closure trimmed %d -> %d line(s), "
                  "%d reachable resource(s) the donor never listed",
                  defn_id, len(borrowed), len(trimmed), len(missing))
        borrowed = trimmed + [RC.entry_for(c) for c in missing]

    for tile_rel in tile_rels:
        # Build on what an earlier def in this mod already emitted for this
        # cache, exactly as `_extend_map_caches` does. Starting from the corpus
        # copy every time makes the LAST def to touch a shared base tile win
        # and silently drop every earlier def's dependencies — and a resource a
        # cache never lists resolves to null, which is either nothing rendering
        # or an access violation at level build with no connection to the
        # cause. Hit 2026-09-05: `runestone_shrine` and `shrine_marked` both
        # edit the menhir camp, so the shrine's marker icon and machinery
        # parent vanished from the tile's cache.
        dest = out_dir / Path(*RC.cache_path_for(tile_rel).split("/"))
        base_bytes = dest.read_bytes() if dest.is_file() else donor
        data = RC.extend(base_bytes, [*assets, tile_rel])
        if borrowed:
            data = RC.render(sorted(set(RC.parse(data)) | set(borrowed)))
        _write(out_dir, RC.cache_path_for(tile_rel), data, written)
    # Handed back so the chapter cache can stay the superset it is documented
    # to be. A borrowed line reaches a tile cache and nothing else otherwise,
    # and `_extend_map_caches` only ever saw this mod's own emitted files.
    return borrowed


def _asset_dir(ref: str) -> str:
    """The decoded directory an asset reference lives in, or ``""`` at the root.

    Splitting a reference on the last separator is only a directory when there
    IS one; `Dt_GreyColor.mat.ot` has none, and taking the whole string then
    files new art under a directory named after a file.
    """
    norm = ref.replace("\\", "/")
    return norm.rsplit("/", 1)[0] if "/" in norm else ""


def _emit_prop_art(mod_id: str, defn: ContentDef, out_dir: Path,
                   written: list[Path]) -> tuple[str, list[str], list[str]]:
    """Emit the mod's mesh, textures, material and prop entity.

    Returns ``(reference, extra cache deps, borrow sources)``. The deps matter:
    an inherited marker parent drags its own closure in, and a resource the
    placing tile's cache never lists resolves to NULL at level build.
    """
    from ...engine import entity_strings as ES

    spec = defn.fields["prop"]
    if not isinstance(spec, dict):
        raise ContentError(f"poi {defn.id}: 'prop' must be a table")
    # `replaces` names the shipped entity an override writes over, so it is
    # required by the override and swap paths and MEANINGLESS to the additive
    # one: a `@prop` placement stands this art at its own transform and takes
    # nothing's place. Requiring it there would force every additive def to name
    # a victim it never touches.
    required = ("entity_base", "material_base")
    if not _places_own_prop(defn):
        required = ("replaces", *required)
    for key in required:
        if not spec.get(key):
            raise ContentError(
                f"poi {defn.id}: prop.{key} is required — see the `poi` docs."
            )
    # `model` is optional, and omitting it is not a degenerate case: the prop
    # is then the donor's shape under a name this mod owns. That is worth
    # having on its own (two POIs can diverge later without either editing a
    # shipped asset), and it is the narrowest possible test of whether a level
    # can reference an entity resource the mod introduced at all — nothing new
    # but the entity, no geometry, no material, no texture.
    # `textures` is optional: a mod may ship its own SHAPE and wear a shipped
    # material. That is a real authoring choice (stone is stone), and it is
    # also the only way to put custom geometry in front of the engine without
    # depending on the texture and material cooks too — which makes it the
    # bisect when a custom prop misbehaves and it is not clear which cook is
    # at fault.
    textures = spec.get("textures") or {}
    if not isinstance(textures, dict):
        raise ContentError(
            f"poi {defn.id}: prop.textures must be a table mapping a donor "
            f"texture reference to one of this mod's source images."
        )

    tag = f"{mod_id}_{defn.id}".replace("-", "_")
    extra_deps: list[str] = []
    borrow: list[str] = []
    # Custom art is filed beside its donor. Two separate apply-time lookups need
    # a same-kind sibling in the same decoded directory — `synthesize_encoded`
    # (to derive the cooked path) and `build_usedrsc_record` (to register it) —
    # and a brand-new directory satisfies neither.
    #
    # ⚠ A material reference is not always a path. `Dt_GreyColor.mat.ot` sits at
    # the 3D root with no directory at all, so splitting it yielded the FILENAME
    # as the directory and filed the mod's mesh under
    # `3D/Dt_GreyColor.mat.ot/<tag>.fbx` — a directory that does not exist, has
    # no sibling to anchor a cooked path, and was skipped at apply with a
    # warning while the entity that referenced it shipped anyway.
    art_dir = _asset_dir(spec["material_base"])

    donor_ent = _corpus(PC.entity_cooked_path(spec["entity_base"]),
                        defn.id, "prop.entity_base")
    donor_strings = {s for _sec, _off, s in ES.list_strings(donor_ent)}

    # 1. Mesh. The mod ships a .glb; the graft template comes from the donor
    #    prop's own mesh, which the manifest already names — so the author
    #    never has to pre-cook anything or know what a template is.
    donor_meshes = sorted(s for s in donor_strings if s.lower().endswith(".fbx"))
    model_ref = None
    if spec.get("model"):
        if not donor_meshes:
            raise ContentError(
                f"poi {defn.id}: prop.entity_base references no mesh, so there is "
                f"no template to cook prop.model against. Pick a scenery prop."
            )
        model_src = _mod_source(out_dir, spec["model"], defn.id, "prop.model")
        # Beside the DONOR MESH, not beside the material: that directory is
        # where the engine keeps geometry of this shape, so it always has a
        # same-kind sibling for the cooked-path and registration lookups.
        model_ref = f"{_asset_dir(donor_meshes[0])}/{tag}.fbx".replace("/", "\\")
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

    # 3. Material: donor's shader wiring, the mod's maps. Skipped entirely when
    #    the def ships no textures — the prop then keeps `material_base`, so no
    #    material or texture of ours is cooked at all.
    swaps = {s: model_ref for s in donor_meshes} if model_ref else {}
    if tex_refs:
        mat_ref = f"{art_dir}/M_{tag}.mat.ot".replace("/", "\\")
        _write(out_dir, PC.art_cooked_path(mat_ref),
               PC.clone_material(
                   _corpus(PC.art_cooked_path(spec["material_base"]), defn.id,
                           "prop.material_base"), tex_refs), written)
        swaps[spec["material_base"]] = mat_ref

    # 4. Prop entity: donor's component structure, the mod's mesh (+ material).
    #    Every LOD slot is repointed, or the prop pops back to the donor's
    #    shape at distance.
    ent_dir = _asset_dir(spec["entity_base"])
    ent_ref = f"{ent_dir}/{tag}_Prop.entity.ot".replace("/", "\\")
    entity = PC.clone_prop_entity(donor_ent, swaps,
                                  ent_ref if RESTAMP_ENTITY_GUIDS else None)

    # 5. Marker and interaction, ON THIS MOD'S OWN ENTITY.
    #
    # This is the additive half of the icon. `_decorate_host` is the same code
    # the in-place path uses, told it is NOT editing a shipped entity — so it
    # inherits the marker/interaction machinery and copies the override records,
    # and skips the two steps that only make sense for a global edit: the
    # "placed N times, so N icons" warning, and repainting the shipped marker
    # textures. Nothing the game ships is modified.
    entity, deco_deps, deco_borrow = _decorate_host(
        mod_id, defn, out_dir, entity, ent_ref, "", written, in_place=False)
    extra_deps += deco_deps
    borrow += deco_borrow

    _write(out_dir, PC.entity_cooked_path(ent_ref), entity, written)

    _log.info("poi %s/%s: prop from %s (+%d texture(s))", mod_id, defn.id,
              spec.get("model") or f"{spec['entity_base']} unchanged", len(tex_refs))
    return ent_ref, extra_deps, borrow


def _shipped_path(ref: str, defn_id: str) -> str:
    """Where the game really keeps ``ref``'s cooked bytes.

    An in-place override only works if it lands on the path the engine reads,
    and that path is not derivable from the reference: normal maps cook to
    ``.Texture.nrm`` rather than ``.Texture.dxt``. Deriving it by convention
    wrote the mod's normal map to a file nothing loads and registered that dead
    path in ``UsedRscList.ot`` beside the real record — the map silently never
    applied and the manifest gained a duplicate.
    """
    got = PC.vanilla_cooked_path(ref)
    if got is None:
        raise ContentError(
            f"poi {defn_id}: {ref!r} is not an asset the game ships, so there "
            f"is nothing to override in place. An override has to target a "
            f"shipped reference."
        )
    return got


@lru_cache(maxsize=64)
def _defs_preloading(cooked_ref: str, chapters: tuple[str, ...]) -> tuple[str, ...]:
    """Shipped definitions in `chapters` whose preload cache lists `cooked_ref`.

    Repainting a shipped icon is an in-place override, so it changes that icon
    EVERYWHERE — and "everywhere" is not obvious from the name. Checked rather
    than assumed, because assuming got it wrong once:
    `MiniMap\\Icons\\Map_Icons_Npc_Quest.png` reads like an Avalon quest asset
    and is in fact preloaded by four Dark Hills tiles (the three pigs' houses
    and Jack's beanstalk), so repainting it would have silently restyled them.

    Only the mod's own chapters are searched: another chapter's icon changing
    is still a real effect, but it cannot collide with the tile this def edits.
    """
    biomes = {CHAPTERS[c].split("_")[0] for c in chapters if c in CHAPTERS}
    needle = cooked_ref.replace("/", "\\").encode()
    out: list[str] = []
    for root in (_UNCOOKED / "Definitions" / "Tiles",
                 _UNCOOKED / "Definitions" / "Maps"):
        if not root.is_dir():
            continue
        for cache in sorted(root.rglob("*.UsedRscCache.ot")):
            if biomes and not any(b.lower() in str(cache).lower() for b in biomes):
                continue
            try:
                if needle in cache.read_bytes():
                    out.append(cache.name.split(".")[0])
            except OSError:
                continue
    return tuple(out)


def chapters_of(defn: ContentDef) -> tuple[str, ...]:
    """The def's target chapters, as a hashable key for the corpus scans."""
    raw = defn.fields.get("chapters") or []
    return tuple(c for c in raw if isinstance(c, str))


def _tile_level_placements(base: str, defn_id: str) -> dict[str, int]:
    """How many times the tile at `base` places each entity."""
    from ...engine import entity_strings as ES

    level_ref = _level_ref_of(_prefab_ref_of(base, defn_id), defn_id)
    level = _corpus(PC.level_cooked_path(level_ref), defn_id, "the tile's level")
    counts: dict[str, int] = {}
    for _sec, _off, text in ES.list_strings(level):
        if text.lower().endswith(".entity.ot"):
            counts[text] = counts.get(text, 0) + 1
    return counts


def _placements_in_tile(ref: str, base: str, defn_id: str) -> int:
    try:
        return _tile_level_placements(base, defn_id).get(ref, 0)
    except (SchemaNotMined, ContentError, ValueError):
        return 0


def _single_placements(base: str, defn_id: str) -> list[str]:
    """Entities the tile places exactly once — the ones a marker belongs on."""
    try:
        counts = _tile_level_placements(base, defn_id)
    except (SchemaNotMined, ContentError, ValueError):
        return []
    return sorted(r.rsplit("\\", 1)[-1] for r, n in counts.items() if n == 1)


def tag_of(mod_id: str, defn: ContentDef) -> str:
    """The `<mod>_<def>` stem every asset this def owns is named after."""
    return f"{mod_id}_{defn.id}".replace("-", "_")


def _decorate_host(mod_id: str, defn: ContentDef, out_dir: Path, ent: bytes,
                   ref: str, base: str, written: list[Path], *,
                   in_place: bool) -> tuple[bytes, list[str], list[str]]:
    """Hang this def's components, marker and interaction on one entity.

    Returns ``(edited bytes, extra cache deps, borrow sources)``.

    Extracted so the SAME code decorates either host, because there are two and
    they are opposites. In place, the host is a shipped entity edited at its own
    cooked path, and the edit is global: every instance of that entity in the
    game gets the icon and the prompt. Additively, the host is an entity this
    mod introduced, and nothing shipped is touched at all.

    `in_place` gates the two steps that only make sense for the global edit:
    the "this prop is placed N times, so you get N icons" warning, and the
    repaint of the two shipped marker textures. An additive def carries its own
    icon under its own name instead.
    """
    spec = defn.fields.get("prop") or {}
    extra_deps: list[str] = []
    borrow: list[str] = []
    edited = ent
    if spec.get("components"):
        names = list(spec["components"])
        edited = EC.add_parents(edited, names)
        extra_deps += EC.parent_cooked_paths(names)
        _log.info("poi %s/%s: %s now inherits %s", mod_id, defn.id, ref,
                  ", ".join(EC.resolve_parent(n) for n in names))

    # A marker and an interaction are both INHERITED, then CONFIGURED.
    #
    # Inheriting alone is not enough and that is what three playtests measured
    # without being able to name: `Minimap_Marker_Reveal_Model` ships every
    # texture Value empty, so a host that only names it as a parent runs the
    # whole hero-proximity reveal state machine and draws nothing. The missing
    # half is a handful of `oCEntityCpntValueSettings` records whose first
    # string is a binding path into the parent and whose payload is a literal
    # `.png` — which is exactly, and only, what
    # `Leprechaun_Cauldron_Minimap_Marker` is made of. Copy those onto the host
    # and the icon appears. Same shape for the prompt:
    # `Ingredient_Stock_Model` is `Interactive_Object_Model` plus six literal
    # overrides, one of which (`Event Interaction Available At Start`) is what
    # arms the interaction at spawn.
    #
    # Splicing a marker RECORD instead — the previous approach — is inert on a
    # bare host and, once a ping parent was added to supply machinery, drew the
    # PARENT's icon as well as ours: teammate-ping art scattered over the map.
    # Overriding the parent's Value is one icon, ours, with no ping involved.
    for key, want in (("minimap", spec.get("marker")),
                      ("interaction", spec.get("interactive"))):
        if not want:
            continue
        parent, default_donor, prefix = EC.OVERRIDE_DONORS[key]
        cfg = want if isinstance(want, dict) else {}
        donor_ref = cfg.get("donor") or default_donor
        donor = _corpus(PC.entity_cooked_path(donor_ref), defn.id,
                        f"the {key} override donor")

        swaps: dict[str, str] = {}
        if key == "minimap":
            if EC.has_marker(ent):
                raise ContentError(
                    f"poi {defn.id}: {ref} already carries marker records of "
                    f"its own, so adding the reveal model would give it two "
                    f"icons. Repaint its existing icon instead."
                )
            # An in-place override is GLOBAL: it edits the entity, not one
            # placement of it. A marker on an entity the tile places 13 times
            # is 13 icons per camp, times every pooled copy of that camp.
            # Measured 2026-09-05 — the map filled with markers and it read as
            # a bug in the marker code, which it was not.
            placements = _placements_in_tile(ref, base, defn.id) if in_place else 0
            if in_place and placements > 1:
                _log.warning(
                    "poi %s: %s is placed %d times by %s, so the marker puts "
                    "%d icons on the map per instance of that tile. Move it to "
                    "a prop the tile places ONCE — %s.",
                    defn.id, ref.rsplit("\\", 1)[-1], placements, base,
                    placements,
                    ", ".join(_single_placements(base, defn.id)[:3]) or "none")
            # The donor's own icons are re-pointed at two shipped textures that
            # NOTHING in any chapter preloads, and the mod's art is then written
            # over those. Inventing a texture name instead HANGS the game at
            # level load (measured 2026-09-05), so the indirection is the whole
            # trick: a real shipped name, carrying the mod's pixels.
            # WHERE THE ICON ART COMES FROM, and the two answers are opposites.
            #
            # In place, the donor's icons are re-pointed at two SHIPPED textures
            # that nothing in any chapter preloads, and the mod's art is written
            # over those names. That is an override, and it is the only route
            # that works for a shipped host.
            #
            # Additively, the mod owns the entity, so it can own the texture
            # too: the art is cooked under this mod's own UI name and the copied
            # marker records are pointed straight at it. Nothing shipped is
            # repainted — which is the whole difference between "our icon" and
            # "our icon, and also every corpse marker in the game".
            icon_name = (f"MiniMap\\Icons\\{tag_of(mod_id, defn)}.png",
                         f"MiniMap\\Icons\\High\\{tag_of(mod_id, defn)}.png")
            for pic in EC.resource_refs(donor):
                if not pic.lower().endswith(".png"):
                    continue
                high = "\\High\\" in pic
                if in_place:
                    swaps[pic] = MARKER_ICON_HIGH if high else MARKER_ICON
                else:
                    swaps[pic] = icon_name[1] if high else icon_name[0]
            # Both repaint targets, whether or not the mod ships art for them:
            # the copied records name them either way, and an icon the cache
            # never lists is a null.
            targets = ((MARKER_ICON, MARKER_ICON_HIGH) if in_place else icon_name)
            extra_deps += [PC.ui_cooked_path(targets[0]),
                           PC.ui_cooked_path(targets[1])]

        edited = EC.add_parents(edited, [parent])
        edited = EC.copy_overrides(edited, donor, prefix, string_swaps=swaps,
                                   exclude=EC.OVERRIDE_EXCLUDE[key])

        if key == "minimap":
            # The cauldron supplies the ART. It does not supply VISIBILITY, and
            # the parent is a hero-PRESENCE marker: it reveals only once the
            # hero is already close. For a shipped landmark that is right; for a
            # mod POI it is circular, because the icon is how a player finds the
            # thing. Measured 2026-09-05 — eight shrines placed and built in one
            # map, no icon ever seen, so nobody went looking.
            #
            # The parent ships no detection radius at all; exactly two shipped
            # entities override it (`Ruin_Model` 25.0,
            # `Collectible_Ingredient_Key` 20.0) with a plain float at the tail
            # of the record. So the record is copied and the literal retuned.
            radius = float(cfg.get("reveal_radius", DEFAULT_REVEAL_RADIUS))
            for slot, tune in (("radius", radius), ("main_poi", None)):
                d_ref, target, literal = EC.REVEAL_DONORS[slot]
                d = _corpus(PC.entity_cooked_path(d_ref), defn.id,
                            f"the {slot} override donor")
                edited = EC.copy_overrides(
                    edited, d, prefix, only=(target,),
                    f32_swap=(literal, tune) if literal is not None else None)
                borrow.append(_CLOSURE_BORROW)
            _log.info("poi %s/%s: marker reveals within %.0f units and is "
                      "flagged a main POI", mod_id, defn.id, radius)
        if key == "interaction":
            # The parent brings the machinery and no RADIUS, and without one the
            # hero is never detected: no prompt, and nothing on the bus at all.
            d_ref, target, literal = EC.INTERACTION_DONORS["radius"]
            d = _corpus(PC.entity_cooked_path(d_ref), defn.id,
                        "the interaction radius donor")
            edited = EC.copy_overrides(edited, d, prefix, only=(target,))
            borrow.append(_CLOSURE_BORROW)
            _log.info("poi %s/%s: interaction radius %.1f", mod_id, defn.id, literal)
        extra_deps += EC.parent_cooked_paths([parent])
        # The parent drags its own closure in (the reveal model alone names
        # three UI entities and a primitive texture) and a resource the tile's
        # cache never lists resolves to null at level build. Borrowing the
        # cache of a shipped tile that already places the donor is how that
        # closure is proven covered rather than re-derived — same mechanism
        # `swaps` uses.
        borrow.append(_CLOSURE_BORROW)
        _log.info("poi %s/%s: %s inherits %s and takes %s's %s overrides",
                  mod_id, defn.id, ref, parent, donor_ref, key)

        if key != "minimap":
            continue
        for slot, cooked_ref in (("icon", MARKER_ICON),
                                 ("icon_high", MARKER_ICON_HIGH)):
            src_rel = cfg.get(slot) or cfg.get("icon")
            if not src_rel:
                continue
            if not in_place:
                # Our own name, not a shipped one. `apply` registers a path the
                # game does not ship in UsedRscList.ot, which is what makes a
                # brand-new texture loadable at all.
                cooked_ref = (icon_name[1] if slot == "icon_high"
                              else icon_name[0])
            src = _mod_source(out_dir, src_rel, defn.id, f"marker.{slot}")
            _write(out_dir, PC.ui_cooked_path(cooked_ref),
                   PC.cook_texture(src.read_bytes()), written)
            for owner in _defs_preloading(cooked_ref, chapters_of(defn)):
                _log.warning(
                    "poi %s: the marker repaints %s, which %s also preloads — "
                    "its icon changes there too.", defn.id, cooked_ref, owner)

    return edited, extra_deps, borrow




def _emit_prop_override(mod_id: str, defn: ContentDef, out_dir: Path,
                        base: str,
                        written: list[Path]) -> tuple[list[str], list[str]]:
    """Put the mod's art on a shipped prop **in place**, minting no new name.

    ⚠ THE PREMISE BELOW WAS DISPROVED 2026-09-11 — see
    ``docs/_re/kinds/pois.md``. A trace on ``ResourceCache_Submit`` (was it
    REQUESTED) paired with ``ResourceRef_Resolve`` (did it RESOLVE) showed a
    mod-introduced entity being requested AND resolved — three times, state=1 —
    alongside the mod's own tiledefs, level and geometry, with zero null
    resolves. A level CAN reference an asset the mod introduced. This function
    is kept because in-place override is still the only route PROVEN to render,
    not because the additive one is impossible.

    The original reasoning, kept for the record: a byte-for-byte copy of a
    shipped entity under a new name, registered in ``UsedRscList.ot`` and
    listed in the tile's resource cache, still failed to load the level that
    placed it — read at the time as "introducing the *name* is what fails".
    That reading was never taken with an instrument that could tell "never
    requested" from "requested and resolved to null".

    The mechanism that DOES work is the one the ``mesh`` kind uses and that
    rendered in-game:
    write the mod's cooked art over a shipped asset's own cooked path.

    In-place override is global by nature, so the whole trick is picking a prop
    whose art nothing else uses. That is checked here rather than assumed —
    ``replaces`` must be placed only in this tile, and its mesh, material and
    textures must belong to it alone. The corpus makes this practical: 469
    scenery props appear in exactly one tile, and the default preset's own
    donor (``Blood_Fountain_DarkHills`` in ``6x6_Bleeding_01``) is one of them,
    down to its three textures.

    Nothing about the tile changes — no level edit, no swap, no cache line, no
    registration. The tile keeps placing exactly the prop it always placed; the
    prop simply looks like the mod's now.
    """
    from ...engine import entity_strings as ES

    spec = defn.fields["prop"]
    ref = spec.get("replaces")
    if not ref:
        # `_emit_prop_art` validates this for the additive path; the in-place
        # path did not, and a bare KeyError is not one of the exceptions
        # `emit_content_blocks` catches — so a hand-written `[[content]]` block
        # missing one key aborted every other mod's apply too.
        raise ContentError(
            f"poi {defn.id}: an in-place prop needs `replaces` — the shipped "
            f"entity whose art this def overwrites.")
    ent = _corpus(PC.entity_cooked_path(ref), defn.id, "prop.replaces")
    strings = [s for _sec, _off, s in ES.list_strings(ent)]
    meshes = sorted({s for s in strings if s.lower().endswith(".fbx")})
    mats = sorted({s for s in strings if s.lower().endswith(".mat.ot")})
    if not meshes:
        raise ContentError(
            f"poi {defn.id}: {ref} references no mesh, so there is nothing to "
            f"override. Pick a prop that draws a model."
        )
    # The composite guard is NOT opt-outable: a composite donor buries the
    # model inside its own children, so waiving it produces a mod that looks
    # broken rather than a mod that changes more than it meant to.
    _assert_prop_is_not_composite(defn.id, ref, strings)
    if spec.get("allow_shared_art"):
        _log.warning(
            "poi %s: allow_shared_art — %s's art is overridden globally, so "
            "every tile that draws it changes too. Deliberate; see poi.toml.",
            defn.id, ref)
    else:
        _assert_art_is_exclusive(defn.id, ref, base, meshes, mats,
                                 overrides_textures=bool(spec.get("textures")))

    # Checked after the donor guards, so a bad donor is still the error the
    # author hears about first — but before anything is written, because an
    # in-place override that ships neither a mesh nor a texture writes NOTHING.
    # Both branches below are guarded, so such a def emits its caches and
    # tiledef, applies cleanly, reports success and changes not one pixel.
    # That cost a playtest: a canary whose folder happened to have no
    # `model.glb` looked exactly like a canary that was placed and did not
    # render, which is the one ambiguity it existed to resolve. Additive mode
    # is different and stays legal without a model — the clone is then the
    # donor's shape under a name the mod owns.
    if not (spec.get("model") or spec.get("textures")
            or spec.get("components") or spec.get("marker")
            or spec.get("interactive")):
        raise ContentError(
            f"poi {defn.id}: `replaces` names {ref} but the def ships no "
            f"model, textures, components or marker, so an in-place override "
            f"would write nothing at all. Add a model (e.g. `model.glb` in the "
            f"POI folder), a texture, a component, a marker, or drop "
            f"`replaces`."
        )

    # Components are added to the donor's OWN entity, at its own cooked path,
    # so no new name enters the level and the mod-owned-entity wall is never
    # touched. Like every other in-place edit here this is GLOBAL: every entity
    # drawn from `replaces` gets the marker and the prompt, which is the same
    # trade the art override already makes and is checked by the same guards.
    #
    # This appends a PARENT, which is how the game itself does it — a chest is
    # interactable and map-marked because it inherits `Interactive_Object_Model`
    # and `Minimap_Marker_Reveal_Model`. Splicing the component record instead
    # was tried and measured inert on 2026-09-05; `EC.add_parents` carries the
    # full reasoning.
    edited, extra_deps, borrow = _decorate_host(
        mod_id, defn, out_dir, ent, ref, base, written, in_place=True)
    if edited != ent:
        material = spec.get("material")
        if material:
            # Point the HOST at a different SHIPPED material. This is not a
            # texture override: nothing shared is repainted, because the only
            # file that changes is this entity, which the mod already owns.
            #
            # It exists because in-place custom textures are effectively
            # impossible. The host's own material is `M_Wood_Planks_A`, which
            # 231 entities reference and whose albedo feeds 5 materials — a
            # stone obelisk wearing it reads as a nondescript lump, and
            # repainting it would turn every wooden plank in the game to stone.
            # Borrowing a shipped stone material costs nothing and breaks
            # nothing.
            #
            # ⚠ The material must already be in the placing tile's preload
            # closure, or it resolves to null at level build. Prefer one the
            # tile ALREADY loads (`M_Rocks_Big` is in the blocker tile because
            # the tile stands a rock in it); it is added to `extra_deps` either
            # way so the cache lists it.
            mat_cooked = PC.art_cooked_path(material)
            _corpus(mat_cooked, defn.id, "prop.material")
            if not mats:
                raise ContentError(
                    f"poi {defn.id}: {ref} names no material, so there is "
                    f"nothing for `material` to repoint.")
            edited = ES.replace_strings(edited, dict.fromkeys(mats, material))
            extra_deps.append(mat_cooked)      # cooked path: the cache wants one
            _log.info("poi %s/%s: material repointed %s -> %s",
                      mod_id, defn.id, mats[0], material)
        _write(out_dir, PC.entity_cooked_path(ref), edited, written)

    if spec.get("model"):
        src = _mod_source(out_dir, spec["model"], defn.id, "prop.model")
        cooked_model = PC.cook_model(src.read_bytes(),
                                     _donor_geometry(meshes[0], defn.id),
                                     transform=spec.get("transform"))
        for mesh in meshes:
            # Every LOD slot too, or the prop pops back to the shipped shape
            # as soon as the camera pulls away.
            _write(out_dir, _shipped_path(mesh, defn.id), cooked_model, written)

    textures = spec.get("textures") or {}
    if textures:
        _assert_textures_belong_to(defn.id, ref, mats, textures)
    for donor_ref, src_rel in textures.items():
        src = _mod_source(out_dir, src_rel, defn.id, f"prop.textures[{donor_ref}]")
        _write(out_dir, _shipped_path(donor_ref, defn.id),
               PC.cook_texture(src.read_bytes()), written)

    _log.info("poi %s/%s: overriding %s's own art in place (%d mesh, %d texture)",
              mod_id, defn.id, ref, len(meshes), len(spec.get("textures") or {}))
    return extra_deps, borrow


@lru_cache(maxsize=1)
def _prop_placements() -> dict[str, frozenset[str]]:
    """Entity ref -> the tile levels that place it, over the whole corpus."""
    import collections

    from ...engine import entity_strings as ES

    def build() -> dict[str, list[str]]:
        tiles = collections.defaultdict(set)
        for lvl in sorted(_UNCOOKED.glob("Ot/*/Tiles/*.level.ot.GameStream.gen")):
            try:
                refs = {s for _s, _o, s in ES.list_strings(lvl.read_bytes())
                        if s.lower().endswith(".entity.ot")}
            except (OSError, ValueError):
                continue
            for r in refs:
                tiles[r].add(lvl.name)
        return {k: sorted(v) for k, v in tiles.items()}

    raw = corpus_cache.load_or_build("prop_placements", _UNCOOKED, build)
    return {k: frozenset(v) for k, v in raw.items()}


@lru_cache(maxsize=1)
def _art_users() -> dict[str, frozenset[str]]:
    """Mesh/material ref -> the entities that reference it, over the corpus."""
    import collections

    from ...engine import entity_strings as ES

    def build() -> dict[str, list[str]]:
        users = collections.defaultdict(set)
        for p in _UNCOOKED.glob(
                "EntitySettings/**/*.entity.ot.EntitySettingsResource.gen"):
            try:
                strings = {s for _s, _o, s in ES.list_strings(p.read_bytes())}
            except (OSError, ValueError):
                continue  # not a parseable entity container; cannot be a user
            for a in strings:
                if a.lower().endswith((".fbx", ".mat.ot")):
                    users[a].add(p.name.split(".entity.ot")[0])
        return {k: sorted(v) for k, v in users.items()}

    raw = corpus_cache.load_or_build("art_users", _UNCOOKED, build)
    return {k: frozenset(v) for k, v in raw.items()}


@lru_cache(maxsize=512)
def _entity_draws(ref: str) -> bool:
    """Does this ``EntitySettings`` reference any geometry of its own?

    Used to tell a real composite child (a candle, a fountain) from a
    settings-only attachment (a perf-profile tester, a material selector).
    Unresolvable entities answer True so the composite check fails closed —
    an unknown child is treated as one that draws.
    """
    try:
        cooked = _corpus(PC.entity_cooked_path(ref), "_entity_draws", "a child entity")
    except (ContentError, SchemaNotMined, OSError, ValueError):
        return True
    from ...engine import entity_strings as ES

    return any(s.lower().endswith(".fbx")
               for _sec, _off, s in ES.list_strings(cooked))


def _assert_prop_is_not_composite(defn_id: str, ref: str,
                                  strings: list[str]) -> None:
    """Refuse a donor that spawns child entities on top of its own mesh.

    An in-place override replaces the art behind ONE reference. A composite
    prop draws its own mesh *and* spawns a list of child ``EntitySettings``,
    and those children keep their shipped art — so the override lands on the
    base only and everything else still renders in the same spot, hiding the
    mod's model inside it.

    Found in-game 2026-08-13 and it is a nasty failure to diagnose, because
    every other check passes: ``Blood_Fountain_DarkHills`` has exactly one mesh
    (``Blood_Fountain_Base_DH.fbx``, the stone plinth), that mesh and its
    material and all three textures are used by nothing else, and the prop is
    placed by exactly one tile. It is also a composite of eleven children —
    five candles, two parchments, three pebbles and ``Objects_Common\\
    Blood_Fountain``, the animated fountain itself. So the shrine cooked
    correctly, applied correctly, and rendered *underneath the fountain*: the
    author's report was "there is something inside the blood thing".

    Only 14 props in the whole corpus are single-mesh, child-free, exclusively
    placed and exclusively textured. That is the population an in-place
    override may target, and it is small enough that guessing does not work.

    **A child that draws nothing cannot bury anything** (2026-08-14). The first
    version of this check counted every child ``EntitySettings`` reference, and
    that is not what the failure was: what hid the shrine was eleven children
    with *meshes*. Almost every scenery prop in the game carries
    ``Common_Settings\\Environment_Perf_Profile_Tester`` — a settings-only
    entity with no geometry at all — so counting references rejected nearly the
    whole scenery corpus, including `Pebbles_*`, `Wall_Ruins_*`, `Skull` and
    `RibCage`. That false positive is what made "child-free" props look rare
    and pushed donor choice toward odd conditional ones. A child is only
    disqualifying if its own cooked entity references a mesh; a child whose
    entity cannot be resolved counts as drawing, so the check still fails
    closed.
    """
    children = sorted({s for s in strings if s.lower().endswith(".entity.ot")
                       and s != ref})
    children = [c for c in children if _entity_draws(c)]
    if not children:
        return
    raise ContentError(
        f"poi {defn_id}: {ref} is a composite — it spawns {len(children)} "
        f"child entities ({', '.join(c.rsplit(chr(92), 1)[-1] for c in children[:3])}"
        f"…) on top of its own mesh. Overriding its art in place replaces only "
        f"the base, so the children keep their shipped look and the model ends "
        f"up buried inside them. Pick a prop that draws one mesh and spawns "
        f"nothing."
    )


def _assert_art_is_exclusive(defn_id: str, ref: str, base: str,
                             meshes: list[str], mats: list[str],
                             overrides_textures: bool = True) -> None:
    """Refuse an in-place override whose art something else also uses.

    Checked per asset the def ACTUALLY writes, not per asset the donor happens
    to reference. A def that ships only a model overwrites only the mesh, so a
    material shared with fifty other props is none of its business — the mesh
    changes shape and keeps the donor's shader wiring. Demanding exclusivity
    of the material anyway is what made this kind look unusable: of the props
    that are upright, ground-level and placed by exactly one *pooled* tile,
    eleven have an exclusive mesh and only **one** (``Cone_Chantier``) also has
    an exclusive material. Texture overrides are what really leak across props,
    and they are only emitted when the def ships texture files.

    Both corpus sweeps are cached: they read ~4,900 files and every prop in
    every mod asks the same two questions.
    """
    tiles = _prop_placements()
    if len(tiles.get(ref, ())) > 1:
        raise ContentError(
            f"poi {defn_id}: {ref} is placed by {len(tiles[ref])} different "
            f"tiles, and an in-place override changes all of them. Pick a prop "
            f"only {base} places."
        )

    users = _art_users()
    checked = (*meshes, *mats) if overrides_textures else tuple(meshes)
    shared = {a: sorted(users.get(a, ())) for a in checked
              if len(users.get(a, ())) > 1}
    if shared:
        first = next(iter(shared))
        extra = "" if overrides_textures else (
            " (only the mesh is checked here because this def ships no "
            "textures)")
        raise ContentError(
            f"poi {defn_id}: {first} is used by {len(shared[first])} entities "
            f"({', '.join(shared[first][:3])}…), so overriding it would change "
            f"props outside {base}{extra}. Pick a prop whose art is its own."
        )


def _assert_textures_belong_to(defn_id: str, ref: str, mats: list[str],
                               textures: dict) -> None:
    """Refuse to write a texture the overridden prop does not actually use.

    `slots` is inherited from the preset when a def does not set it, and the
    presets name their OWN donor's textures — `clearing`'s slots are the blood
    fountain's. So a def that overrides `replaces` to some other prop, ships
    three images and says nothing about `slots` re-skins that prop's mesh while
    writing its images over the FOUNTAIN's textures, changing every tile that
    draws a fountain. Nothing else catches it: `_shipped_path` only asks "is
    this a shipped asset", and `_assert_art_is_exclusive` inspects the donor's
    meshes and materials rather than the texture refs actually being written.

    The check is what the author meant all along: a texture slot must be one
    the prop being replaced really references, reached through its materials.
    """
    own: set[str] = set()
    for mat in mats:
        try:
            own |= _material_refs(_corpus(PC.art_cooked_path(mat), defn_id,
                                          "the donor material"))
        except (ContentError, SchemaNotMined, ValueError, KeyError):
            # A material this codec cannot read is not evidence of absence, so
            # it must not turn into a refusal of a legitimate override.
            _log.warning("poi %s: cannot read %s to verify texture slots; "
                         "skipping that material", defn_id, mat)
            continue
    if not own:
        return                      # nothing to check against — stay permissive
    stray = sorted(k for k in textures if k not in own)
    if stray:
        raise ContentError(
            f"poi {defn_id}: texture slot(s) {stray} are not used by "
            f"{ref} — writing them would re-skin a DIFFERENT prop everywhere "
            f"it appears. This is what an inherited `slots` from the preset "
            f"looks like when `replaces` was changed without it: set `slots` "
            f"to this prop's own textures ({sorted(own)[:3]}…) or drop the "
            f"images and keep the donor's material."
        )


def _emit_cloned_level(mod_id: str, defn: ContentDef, out_dir: Path,
                       base: str, written: list[Path]) -> str:
    """Additive path with a mod-owned LEVEL but no mod-owned entity.

    This is the missing rung of the ladder. The two rungs either side of it are
    measured (2026-08-14):

    * a mod-owned **tiledef** loads, pools and does not crash;
    * a mod-owned tiledef **+ prefab + level + prop entity** crashes at level
      build with a null resource.

    Four names changed at once between them, so "a mod cannot own a level" and
    "a level cannot reference a mod-owned entity" are still indistinguishable —
    and they have very different consequences. If levels are fine and only
    entity names are cursed, a mod can clone a level and re-dress it with
    SHIPPED entities, which is the only known route to a POI with a minimap
    icon: icons come from a marker component, an in-place override cannot add
    one, and `swaps` can only reuse what the donor tile already places. Owning
    the level is what would let a marker-carrying entity be placed at all.

    So this emits exactly two new names — a level and the prefab that points at
    it — and zero new entity names. `swaps` may re-dress it, but only between
    entities the donor level already places, which `_validated_swaps` enforces.

    Returns the new prefab reference for the cloned tiledef to point at.
    """
    tag = f"{mod_id}_{defn.id}".replace("-", "_")
    swaps = _validated_swaps(defn, base, out_dir)

    donor_prefab_dec = _prefab_ref_of(base, defn.id)
    level_ref = _level_ref_of(donor_prefab_dec, defn.id)
    new_level_ref = level_ref.rsplit("\\", 1)[0] + f"\\{tag}.level.ot"
    level = PC.clone_tile_level(
        _corpus(PC.level_cooked_path(level_ref), defn.id, "the tile's level"),
        level_ref, new_level_ref, swaps)
    places = _validated_places(defn)
    # The mod's OWN entity, emitted once however many times it is placed. This
    # is the additive route: a name this mod introduces, standing in a level
    # this mod owns, taking nothing's place. `_emit_prop_art` writes through
    # `written`, so the entity, its mesh, its material and its textures all
    # reach the tile's `UsedRscCache` and `UsedRscList.ot` by the same route as
    # every other emitted asset — no separate registration to forget.
    own_prop = None
    prop_deps: list[str] = []
    prop_borrow: list[str] = []
    if any(i["entity"] == PLACES_OWN_PROP for i in places):
        own_prop, prop_deps, prop_borrow = _emit_prop_art(
            mod_id, defn, out_dir, written)
        _log.info("poi %s/%s: mod-owned prop entity %s", mod_id, defn.id, own_prop)
    for item in places:
        # yaw only: a POI stands upright by definition, and a full quaternion
        # in a toml file is a footgun no author asked for.
        half = math.radians(item["yaw"]) / 2.0
        entity = own_prop if item["entity"] == PLACES_OWN_PROP else item["entity"]
        level = LP.add_placement(
            level, entity, pos=item["pos"],
            quat=(0.0, math.sin(half), 0.0, math.cos(half)),
            scale=(item["scale"],) * 3)
        _log.info("poi %s: placed %s at %s scale %.2f", defn.id,
                  entity.split("\\")[-1], item["pos"], item["scale"])
    _write(out_dir, PC.level_cooked_path(new_level_ref), level, written)

    new_prefab_ref = donor_prefab_dec.rsplit("\\", 1)[0] + f"\\{tag}.entity.ot"
    _write(out_dir, PC.entity_cooked_path(new_prefab_ref),
           PC.clone_tile_prefab(
               _corpus(PC.entity_cooked_path(donor_prefab_dec), defn.id,
                       "the tile's prefab entity"),
               # `new_prefab_ref` is what restamps the clone's component
               # identity GUIDs. Omitting it (the four-arg call is optional)
               # left this prefab carrying the DONOR's identities — a second
               # resource claiming a shipped resource's place, which is the
               # collision RESTAMP_ENTITY_GUIDS exists to prevent and the
               # prime suspect for every earlier additive failure. On the rung
               # whose whole job is to isolate which name the engine rejects,
               # that would have made the result unreadable.
               level_ref, new_level_ref, new_prefab_ref), written)

    _log.info("poi %s/%s: mod-owned level %s (%d swap(s))",
              mod_id, defn.id, new_level_ref, len(swaps))
    # The prop's decoration deps travel WITH the prefab reference. An inherited
    # marker parent drags its own closure in (the reveal model alone names three
    # UI entities and a primitive texture), and a resource the placing tile's
    # cache never lists resolves to NULL at level build.
    return new_prefab_ref, prop_deps, prop_borrow


def _emit_custom_prop(mod_id: str, defn: ContentDef, out_dir: Path,
                      base: str, written: list[Path]) -> str:
    """Additive path: the mod's prop, plus a cloned tile level and prefab that
    place it. Returns the new prefab reference for the cloned tiledef."""
    spec = defn.fields["prop"]
    tag = f"{mod_id}_{defn.id}".replace("-", "_")
    ent_ref, _deps, _borrow = _emit_prop_art(mod_id, defn, out_dir, written)

    # Tile level: the base tile's dressing, its centrepiece swapped for ours.
    donor_prefab_dec = _prefab_ref_of(base, defn.id)
    level_ref = _level_ref_of(donor_prefab_dec, defn.id)
    new_level_ref = level_ref.rsplit("\\", 1)[0] + f"\\{tag}.level.ot"
    _write(out_dir, PC.level_cooked_path(new_level_ref),
           PC.clone_tile_level(
               _corpus(PC.level_cooked_path(level_ref), defn.id, "the tile's level"),
               level_ref, new_level_ref, {spec["replaces"]: ent_ref}), written)

    # Tile prefab entity: points the tiledef at the new level.
    new_prefab_ref = donor_prefab_dec.rsplit("\\", 1)[0] + f"\\{tag}.entity.ot"
    _write(out_dir, PC.entity_cooked_path(new_prefab_ref),
           PC.clone_tile_prefab(
               _corpus(PC.entity_cooked_path(donor_prefab_dec), defn.id,
                       "the tile's prefab entity"),
               level_ref, new_level_ref, new_prefab_ref), written)
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
                         base: str, td: TC.TileDef,
                         chapters: list[str]) -> list[Path]:
    """Override the base tile in place: no new tiledef, no pool edit.

    "In place" is meant literally. The mod's prop is a new asset either way,
    but the tile's LEVEL is overridden at its own path — same resource name,
    same bare identifier, same identity GUID — with only the swapped objects
    changed. Nothing else about the shipped tile moves: no cloned level, no new
    GUID, no prefab override, no tiledef edit unless the def asked for one.

    It used to clone the level and repoint the prefab, i.e. the additive
    machinery wearing an override hat, and that crashed the game at load on the
    Dark Hills starting tile while the additive path in the same build booted
    fine. A shipped tile can be reached through references a mod does not
    control, so replacing what it *contains* is safe in a way that replacing
    *which level it is* is not.
    """
    written: list[Path] = []
    biome, stem = base.split("/", 1)

    swaps: dict[str, str] = _validated_swaps(defn, base, out_dir)
    extra_deps: list[str] = []
    borrow: list[str] = []
    own_prop: str | None = None
    if defn.fields.get("prop") and not _places_own_prop(defn):
        # In place, on the shipped prop's own cooked paths: the def is restyling
        # something the tile already stands, so there is a `replaces` to write
        # over and the tile itself is not touched.
        extra_deps, borrow = _emit_prop_override(mod_id, defn, out_dir, base,
                                                 written)
    elif defn.fields.get("prop"):
        # ADDITIVE, on a shipped level. The prop is an entity this mod
        # introduces — emitted, decorated with its own marker and interaction,
        # and stood at a transform of its own by the `places` loop below. There
        # is nothing to `replace`, because nothing is being taken over.
        own_prop, extra_deps, borrow = _emit_prop_art(mod_id, defn, out_dir,
                                                      written)
    places = _validated_places(defn)
    if swaps or places:
        level_ref = _level_ref_of(_prefab_ref_of(base, defn.id), defn.id)
        level = _corpus(PC.level_cooked_path(level_ref), defn.id,
                        "the tile's level")
        # Swaps first: they only re-point existing references, so the stream
        # keeps its shape and an insert afterwards has the same anchors to work
        # from as it would on the untouched donor.
        if swaps:
            level = PC.override_tile_level(level, swaps)
        for item in places:
            entity = item["entity"]
            if entity == PLACES_OWN_PROP:
                if own_prop is None:
                    own_prop = _emit_prop_art(mod_id, defn, out_dir, written)[0]
                entity = own_prop
            half = math.radians(item["yaw"]) / 2.0
            level = LP.add_placement(
                level, entity, pos=item["pos"],
                quat=(0.0, math.sin(half), 0.0, math.cos(half)),
                scale=(item["scale"],) * 3)
            _log.info("poi %s: added %s to the shipped level at %s scale %.2f",
                      defn.id, entity.split("\\")[-1], item["pos"], item["scale"])
        _write(out_dir, PC.level_cooked_path(level_ref), level, written)

    # Cosmetic edits (icon / kinds / weight) go onto the base tiledef itself.
    if defn.fields.get("icon_source"):
        _emit_custom_icon(mod_id, defn, out_dir, td, written)
    if any(k in defn.fields for k in ("icon", "icon_source", "kinds", "weight")):
        _write(out_dir, f"{_TILE_ASSET_SUBDIR}/{biome}/{stem}{TC.GEN_SUFFIX}",
               TC.write(td), written)

    # The base tile keeps its own cache path, so this OVERRIDES the shipped
    # one. It has to: the tile now reaches assets the vanilla cache never
    # listed, and an un-updated cache is what crashed the game on 2026-08-10.
    # An inherited parent is a resource the prop now depends on, so it belongs
    # in the preload cache exactly like the mod's own art. `RC.extend` dedupes,
    # so this is a no-op on a tile that already places something carrying the
    # same parent — and load-bearing on one that does not.
    assets = _emitted_assets(out_dir, written) + extra_deps
    # `places` entities belong here for the same reason swap targets do — see
    # `_placed_for_cache`. Without them a def that stands a shipped entity the
    # donor never placed writes it into the level and into nothing else.
    placed = _placed_for_cache(defn)
    borrowed = _emit_tile_caches(
        out_dir, base, defn.id, assets,
        [f"{_TILE_ASSET_SUBDIR}/{base}{TC.GEN_SUFFIX}"], written,
        borrow_for=[*swaps.values(), *placed, *borrow],
        seed_for=[*swaps.values(), *placed, *_host_refs(defn)])
    # No tile is pooled here, but the chapter's cache is a superset of every
    # tile's, so art the overridden tile now reaches has to be listed there too.
    _extend_map_caches(out_dir, defn.id, chapters, assets, [], written,
                       extra_lines=borrowed)

    _log.info("poi %s/%s: REPLACING base tile %s in place (no pool change)",
              mod_id, defn.id, base)
    return written


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize the cloned tiledef + one patched mapdef per target chapter."""
    base, chapters = _validate(defn)

    td = TC.read(_tile_path(base).read_bytes())
    _apply_edits(td, defn, chapters)
    # Validated here as well as in the override path, so an author who writes
    # `swaps` without `replace_base` is told rather than silently ignored.
    _validated_swaps(defn, base, out_dir)

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
        return _emit_replacing_base(mod_id, defn, out_dir, base, td, chapters)

    # File the clone next to its donor. `synthesize_encoded` derives a new
    # asset's encoded path by cloning an existing sibling's encoded prefix, so a
    # brand-new `Definitions/Tiles/<Mod>/` directory would have nothing to
    # anchor on and the asset would be skipped at apply. Reusing the donor's
    # biome directory keeps that resolution working — and is what the game
    # itself does, filing a Storm Island tile that Dark Hills draws from.
    biome = base.split("/", 1)[0]
    # `.replace("-", "_")` for the same reason the prefab, the level, the icon
    # and the prop entity all do it — this was the ONE emitted name that kept
    # the hyphen, so a mod id like `runestone-shrine` produced a tiledef called
    # `runestone-shrine_shrine_pool` sitting beside a prefab and level called
    # `runestone_shrine_shrine_pool`. Zero of the 474 shipped tiledef resources
    # contain a hyphen, so consistency with its own siblings is the reason.
    #
    # ⚠ It is NOT the reason the shrine went unseen, and an earlier version of
    # this comment said it was ("never once placed across four maps"). The log
    # archive disproves that outright: hyphen-era runs logged `6 ours (6 built)`
    # twice (2026-09-06 12:53 and 13:06), and the first underscore run logged
    # `6 ours (6 built)` as well — the placement rate did not move. Placement
    # was never the failing step; keep the sanitisation, drop the story.
    tile_name = f"{mod_id}_{defn.id}".replace("-", "_")
    written: list[Path] = []

    own_deps: list[str] = []
    own_borrow: list[str] = []
    # A custom prop rebuilds the prefab/level/prop/material chain and hands
    # back a new prefab reference for the tiledef to point at. Without it the
    # clone keeps the donor's prefab and shows the donor's structure.
    if defn.fields.get("prop") and defn.fields.get("own_level"):
        # Both rebuild the prefab/level chain and only one can win the
        # `entity_ref`, so the loser's work is thrown away in silence. That is
        # worse than it sounds: `_validated_places` REQUIRES `own_level`, so a
        # def carrying both validates its `places` and `swaps` fully and then
        # never emits them — the tile is placed, the level is the donor's, and
        # nothing on screen says why.
        # ...UNLESS the prop is PLACED rather than swapped in. Then the two
        # are not rivals: `prop` emits art and hands back a reference, and
        # `own_level` owns the prefab/level chain and stands that reference at
        # the transform `places` gives it. Nothing is thrown away, and this is
        # the only combination that adds a structure without editing a shipped
        # asset — see PLACES_OWN_PROP.
        if not _places_own_prop(defn):
            raise ContentError(
                f"poi {defn.id}: 'prop' and 'own_level' both rebuild this "
                f"tile's prefab and level, and only one can own the tiledef's "
                f"entity reference. Pick one: 'prop' to restyle the structure "
                f"the donor already stands, 'own_level' (with 'places'/'swaps') "
                f"to author the tile's contents — or place the prop additively "
                f"with places = [{{ entity = \"{PLACES_OWN_PROP}\", ... }}], "
                f"which needs both."
            )
    # `own_level` wins for an additive def. `_emit_custom_prop` puts the prop in
    # by SWAPPING it over `replaces`, which an additive def does not set — so
    # taking that branch handed the level cloner a swap keyed on None. The two
    # branches are not interchangeable here: one replaces an object, the other
    # adds one, and PLACES_OWN_PROP asked for the second.
    if defn.fields.get("prop") and not _places_own_prop(defn):
        td.entity_ref = ["EntitySettings",
                         _emit_custom_prop(mod_id, defn, out_dir, base, written)]
    elif defn.fields.get("own_level"):
        prefab_ref, own_deps, own_borrow = _emit_cloned_level(
            mod_id, defn, out_dir, base, written)
        td.entity_ref = ["EntitySettings", prefab_ref]

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
    tile_rels: list[str] = []
    for n in range(1, copies + 1):
        name = tile_name if n == 1 else f"{tile_name}_{n}"
        tile_rel = f"{_TILE_ASSET_SUBDIR}/{biome}/{name}{TC.GEN_SUFFIX}"
        tile_dest = out_dir / Path(*tile_rel.split("/"))
        tile_dest.parent.mkdir(parents=True, exist_ok=True)
        tile_dest.write_bytes(TC.write(td))
        written.append(tile_dest)
        tile_rels.append(tile_rel)
        pool_refs.append(f"Tiles\\{biome}\\{name}.tiledef.ot")

    # Every copy is a separate tiledef asset, so every copy needs its own
    # cache — a tiledef the engine cannot preload is never placed.
    assets = _emitted_assets(out_dir, written)
    # `places` entities count exactly like swap targets here — see
    # `_placed_for_cache` for why, and for what it cost both times it was missed.
    placed = _placed_for_cache(defn)
    assets += own_deps
    swapped = list(_validated_swaps(defn, base, out_dir).values())
    borrowed = _emit_tile_caches(out_dir, base, defn.id, assets, tile_rels,
                                 written,
                                 borrow_for=[*swapped, *placed, *own_borrow],
                                 seed_for=[*swapped, *placed])
    _report_share(mod_id, defn, td, chapters, copies)

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


    _extend_map_caches(out_dir, defn.id, chapters, assets, tile_rels, written,
                       extra_lines=borrowed)

    _log.info("poi %s/%s: cloned %s -> %d pool entr%s in %s",
              mod_id, defn.id, base, len(pool_refs),
              "y" if len(pool_refs) == 1 else "ies", ", ".join(chapters))
    return written
