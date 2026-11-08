"""Hero content builder: clone a shipped hero into a new roster entry.

How the roster works (static RE, 2026-09-24):

* The hero-select screen (``oCDtEntityCpntPlayBookPageUiController``, vftable
  ``0x140f35820``) fills its hero vector at ``controller+0x210`` through
  ``FUN_140209b00``: clear it, then copy **every registered instance** of the
  hero-definition class out of the definition registry (``Registry_EnumInstances``
  with the class key at ``0x141475f50``). No filter, no sort, no count: a
  hero's index is its position in that list.
* Unlike enemies, a herodef is NOT loaded by the boot directory scan: a clone
  registered in ``UsedRscList.ot`` alone never loaded (12 defs live, measured
  in game 2026-09-24). Heroes load through the LiveOps versiondef's hero
  vector, so ``apply`` appends each new herodef there
  (``engine/versiondef._patch_versiondef_heroes``), the same way new magic items join
  the versiondef's MO vector.

So a new hero is a new ``.herodef`` file, its resource cache and one
versiondef entry: no library singleton to find, no roster table to patch. A herodef never
names itself (its strings are memoir text keys, codex art, entity refs), so a
byte copy under a new file name is a distinct definition, the same identity
rule as an enemy or map clone.

PROVEN IN GAME 2026-09-24: a Piper clone appeared as a 13th hero, was picked,
and a run started as it with no crash; the save the game wrote checks out. A
clone takes the next index, which no save has unlocked, so it may need
``R.hero.unlock_progression()`` (the ``unlock-heroes`` mod) to be selectable.

Fields:
    ``base``  (str, required)  a shipped hero to clone, e.g. ``Piper``. A paid
                               DLC hero (Merlin) is refused unless the block
                               says ``dlc_owner = true``: a clone plays for
                               anyone who installs the mod, so share it only
                               with players who own the DLC.
    ``dlc_owner`` (bool)       "I own the DLC ``base`` belongs to"; needed to
                               clone a paid hero, ignored otherwise.

With ``base`` alone the clone is its base in every respect (the proven path).
Everything below makes it a hero of its own; see
``docs/_re/kinds/heroes.md`` ("How a hero is assembled from data") for why
each piece is wired the way it is. NOT YET PROVEN IN GAME.

    ``name`` / ``description`` (str)
        Shown on the select screen. Appended to the base's text bank as
        ``Hero_<id>_Name`` / ``Hero_<id>_Desc`` and the herodef re-pointed at
        them.
    ``model`` (str)  a ``.glb`` rigged to the base's skeleton (start from
        ``rsmm export-character <Base>``). Cooked as the hero's body, weights
        bound by bone name (``transform`` defaults to ``{skin = "gltf", submeshes = "map"}``).
        Every skin slot shows it.
    ``albedo`` / ``mra`` / ``normal`` (str)  PNGs for the body material; a
        slot left out keeps the base's map.
    ``portrait`` (str)  PNG for the select-screen and in-run portraits. ⚠ A UI
        texture under a new name hung level load once (a POI minimap icon), so
        this is the riskiest field.
    ``weapons`` (table)  ``{"<graphic object label>" = {model, albedo, mra,
        normal}}``: a weapon of the hero's own, in its entities only. A
        material label with no attachment (a companion's, e.g. Beowulf's
        ``"Chatacter Mesh Wyrm"``) takes maps only.
    ``frame`` (true | table)  the hero WRITTEN FROM SCRATCH (engine/hero_frame.py):
        its main, FX and skin entities hold only its own parts on the shared
        hero base (Hero_Common by alias, Character_Common), not a copy of
        ``base``'s. ``base`` then lends the herodef, alias and preload lists,
        and ``rig`` (default the base's folder, e.g. ``Hero_Kintaro``) lends
        only a skeleton and its on-foot clips (``hero_frame.rig_slots``) until
        the hero has animations of its own. ``mesh`` / ``material`` name its
        body (a ``materials`` repaint applies); ``slots`` overrides any slot's
        fill. Talent rows become empty cards of its own (text from ``skills``).
        Not yet with ``kit``, ``abilities``, ``attacks`` or ``talents``.
        WITHOUT ``base`` (``_emit_scratch``): nothing of any hero is copied;
        its herodef (engine/herodef_frame.py), alias, text and preload lists
        are its own, and ``rig`` lends assets only. Then ``frame`` also takes
        ``albedo`` (its body repainted), ``abilities`` (engine/hero_ability.py),
        ``talents`` (``[{name, title, description, icon, add_stats,
        actions}]``: its own talent list, the name's first word its book
        column) and ``animations`` (``{name = {source, clip, template}}``:
        a glb on the rig's skeleton cooked by anim_cook into a NEW clip of its
        own; ``clip = "anim:<name>"`` in a slot or a button uses it).
    ``materials`` (table)  ``{"<material>" = {albedo, mra, normal}}``: any
        material the hero's own entities use, by file stem (``M_KintaroBear``)
        or full ref, retextured in this hero's files only (its ``_LowRes``
        twin follows). For a body ``albedo`` cannot pick: Kintaro's boy is his
        ``M_Kintaro`` (the "Alt Form" mesh), his main mesh the bear.
    ``animations`` (table)  ``{"<base clip>" = "file.glb" | {source, clip,
        strict}}``: the clip is cooked under ``<id>_<clip>`` and only this
        hero's entities point at it (the ``animation`` kind changes the clip
        for everyone).
    ``outfits`` (list)  ``[{name, model, albedo, mra, normal}]``: more skins,
        the Default look with their own body maps (and, with ``model``, a body
        of their own), in the skin slots after Default.
    ``values`` (table)  ``{"<label>" | "<Entity>/<label>" = number}``: the
        hero's numbers (``rsmm export-character <Base> --list-values``).
    ``abilities`` (list)  ``[[content.abilities]]`` steps that copy, set and
        rewire the base's ability parts (``clone`` / ``set`` / ``link`` /
        ``add_link`` / ``remove_link``; see ``engine/ability_edit.py`` and
        ``rsmm entity-graph <Base>``). Checked before apply: an edit that
        leaves a link bound to nothing is refused.
    ``skills`` (table)  ``{"<card>" = {name, description}}``: talent and
        ability cards of the hero's own: a talent as its skill controller
        names it (``"Dash Trap"`` for ``Skill Controller Dash Trap``) or an
        ability slot (``"Ability Power"``, ``"Ability Ultimate 1"``). The base
        keeps its cards. The count of talents is fixed, so
        this relabels a slot; change what the talent DOES with ``abilities``
        (its parts are the ``Skill <talent>`` group). Keep the card's ``{N}``
        placeholders: the numbers come from the talent's String Format.
    ``placeholder`` (str)  one PNG (a flat pink is the convention) painted over
        every piece of art the hero still borrows from the base: each
        character material's albedo (body, gear, companion, every skin), every
        ability/talent icon and HUD image, and the book's portraits, skin icons
        and codex pictures, each under a name of the hero's own. Whatever is
        still pink in game is what is left to replace (story pages the
        ``memoirs`` field leaves out, and skin slots no outfit takes, read as
        still to write/design); ``albedo``,
        ``weapons`` and ``portrait`` take precedence. ⚠ Many UI images under
        new names: a new-name UI texture hung level load once (a POI icon).
    ``memoirs`` (list)  ``[{title, text}]``: the book's story pages, in
        order (Beowulf has 7). A page left out keeps the base's story, or
        reads as a page still to write when ``placeholder`` is set. Once any
        page is the hero's own, the pages lose the base's voice-over (the
        recordings are named after the base) and are silent.
    ``kit`` (table)  the hero builder's blocks: ``form`` (``"wolf"`` /
        ``"human"`` for Scarlet-type heroes), and per slot (``attack``,
        ``power``, ``special``, ``defense``, ``ultimate``, ``ultimate2``,
        ``trait``, ``dash``) ``"none"``, ``{ fire = <entity>, when = <state> }``, or
        a built ability ``{ replace = true, steps = [...] }`` (blocks ``fire`` with
        ``angles``, ``wait``, ``repeat`` with ``every`` and ``steps``, ``anim``).
        Expanded into ``abilities`` steps, run before the hand-written ones;
        see ``engine/hero_kit.py``.
    ``attacks`` (list)  ``[[content.attacks]]``: attacks of the hero's own,
        each replacing an ability slot: a projectile entity of its own
        (``Hero_<id>_<attack>``, on the engine's generic hero projectile) with
        the mod's mesh and maps, fired at ``beats`` of angles ``delay`` apart,
        with the slot's animation replaced. Fields and how it is built:
        ``engine/attack_build.py``.
    ``effects`` (table)  ``{"<effect>" | "*" = {tint = "#RRGGBB"}}``: particle
        effects of the hero's own. Every effect in the base's own FX folder
        (Beowulf: 99) is copied under ``<id>_<name>`` with its own materials and
        textures, recoloured to the tint at their own brightness (shapes and
        transparency kept): colour textures (never masks, noise or surface
        data), the materials' colour uniforms, and the effect's own colour
        ramps and constants, which are what make fire orange. ``"*"`` tints
        them all; an effect named by itself (``Beowulf_Shockwave_Front_01``)
        wins. With ``placeholder``,
        effects given no tint are pink. Effects shared with other heroes
        (``Common_FX``) are never touched.
    ``hide`` (list)  meshes the hero does not have, by name (``"Wyrm_GEO"``,
        Beowulf's dragon) or full path: each is replaced, in this hero's
        entities only, by an invisible copy (the same mesh and skeleton shrunk
        to nothing), so everything attached to its bones (a breath's origin at
        the head) still works. The logic stays: the dragon's fire still comes.
        Every vertex rides ONE bone: a skinned mesh merely shrunk toward the
        origin scatters back out once its bones move.
    ``references`` (table)  ``{"<old>" = "<new>"}``: any string the hero's
        entities name (a VFX, a sound, a mesh), swapped in them only; a new
        resource's preloads are borrowed from a shipped cache.
    ``own_entity`` (bool)  give the hero its own gameplay entity. Implied by
        every field above except ``name``, ``description`` and ``portrait``.
        The base's whole ``Hero_<Base>*``
        entity family (gameplay entity, FX, pets, projectiles, skins) is cloned
        under ``Hero_<id>*`` with every path and scope renamed, because a pet or
        projectile reads its owner's values by template and scope; and an alias
        with a fresh GUID is added to ``ApplicationSettings.ot`` for the skins
        to reach it. After that the hero's entities are its own to edit.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Final

from ...engine import enemy_pools as EP
from ...engine import herodefs as HD
from ...engine import rsc_cache as RC
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_HEROES_DIR = "Definitions/Heroes"
_GEN_SUFFIX = ".herodef.ot.DtHeroDefinition.gen"
_HERO_CLASS = "oCDtHeroDefinition"

#: Paid DLC heroes. A clone of one would play for a player who has not bought it,
#: so cloning needs the author to say they own it: ``dlc_owner = true`` on the
#: block. The flag is a declaration, not a check; ownership is a Steam
#: entitlement the game makes, which nothing here can see.
DLC_HEROES: Final[frozenset[str]] = frozenset({"Merlin"})


_FIELDS = frozenset({"base", "name", "description", "model", "transform", "albedo",
                     "mra", "normal", "portrait", "own_entity", "weapons",
                     "animations", "outfits", "values", "references", "abilities",
                     "skills", "placeholder", "memoirs", "effects", "hide", "attacks",
                     "dlc_owner", "kit", "borrow", "materials",
                     "talents", "frame"})
_TEXTURE_FIELDS = {"albedo": "ALB", "mra": "MRA", "normal": "NRM"}
#: The engine's shared neutral character maps (Character_Grey.mat.ot):
#: rig-map suffix -> (cooked root, reference). A frame hero with a model of
#: its own wears these in place of the rig's UV-bound maps.
_NEUTRAL_MAPS = {"_MRA.TGA": ("samples", "Dielectric_Rough.tga"),
                 "_NRM.TGA": ("samples", "Textures\\NoNormal.png"),
                 "_EMI.TGA": ("FX", "Textures\\Shapes\\Square_Black.png")}
#: Shipped alias names (ApplicationSettings.ot) that are not heroes: a hero of
#: that name would still collide with the alias. (Kintaro was one until he
#: shipped in Update 6; the shipped-hero check covers him now.)
_RESERVED_IDS = frozenset({"Common", "Kintaro", "Alice"})


def _rel(hero: str) -> str:
    return f"{_HEROES_DIR}/{hero}{_GEN_SUFFIX}"


def _self_line(hero: str) -> str:
    return f"Definitions|Heroes\\{hero}.herodef.ot|{_HERO_CLASS}"


def shipped_heroes() -> list[str]:
    """Hero names the game ships (``Piper``, not its ``Piper_Update6`` herodef)."""
    return HD.names()


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Write ``<id>.herodef`` (a copy of the base) and its resource cache."""
    C.validate_id("hero", defn.id)
    unknown = sorted(set(defn.fields) - _FIELDS)
    if unknown:
        raise ContentError(
            f"hero {defn.id}: unsupported field(s) {unknown}; known: {sorted(_FIELDS)}")
    base = defn.fields.get("base")
    if not base and defn.fields.get("frame"):
        # A hero of its own from the first byte: no shipped hero copied.
        return _emit_scratch(mod_id, defn, out_dir)
    if not isinstance(base, str) or not base:
        raise ContentError(f"hero {defn.id}: needs a 'base' (a shipped hero, e.g. Piper), "
                           "or a `frame` with a `rig` for a hero written from scratch")
    if base in DLC_HEROES and defn.fields.get("dlc_owner") is not True:
        raise ContentError(
            f"hero {defn.id}: {base} is a paid DLC hero. A clone plays for anyone who "
            f"installs the mod, so add `dlc_owner = true` to this block to confirm you own "
            f"the DLC, and share the mod only with players who do.")
    shipped = shipped_heroes()
    if defn.id in shipped or HD.stem(defn.id):
        raise ContentError(f"hero {defn.id}: the id collides with a shipped hero")

    bstem = HD.stem(base) or base
    raw = EP.corpus_read(_rel(bstem))
    cache = EP.corpus_read(RC.cache_path_for(_rel(bstem)))
    if raw is None or cache is None:
        if shipped and base not in shipped:
            raise ContentError(
                f"hero {defn.id}: no shipped hero {base!r}; have {', '.join(shipped)}")
        raise SchemaNotMined(
            f"hero {defn.id}: {base}'s herodef or resource cache is not in the "
            f"corpus or the game install")

    # `dlc_owner` only unlocks cloning a paid hero: it does not make a hero of its own.
    if set(defn.fields) - {"base", "dlc_owner"}:
        return _emit_custom(mod_id, defn, out_dir, base, raw, cache)

    dest = out_dir / Path(*_rel(defn.id).split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    # 12 of 12 shipped herodefs carry a cache listing their own def line; a new
    # name has none unless it is written (the enemy/tile lesson).
    lines = set(RC.parse(cache)) - {_self_line(bstem)}
    lines.add(_self_line(defn.id))
    cache_dest = out_dir / Path(*RC.cache_path_for(_rel(defn.id)).split("/"))
    cache_dest.write_bytes(RC.render(sorted(lines)))
    return [dest, cache_dest]


# --------------------------------------------------------------------------
# a hero of its own
# --------------------------------------------------------------------------

def _game_dir() -> Path:
    from rsmm.cli.apply_mods import find_game_dir
    game = find_game_dir()
    if game is None:
        raise SchemaNotMined("a custom hero needs the game install (its alias table "
                             "and text banks are read from it)")
    return game


def _install_bank(game: Path, bank: str) -> Path:
    from rsmm.cli.apply_mods import load_asset_map
    from rsmm.engine.paths import COOKING_REL
    enc = load_asset_map().get(f"Text/{bank}.LocalText.gen")
    p = game / COOKING_REL / Path(*enc.split("\\")) if enc else None
    if p is None or not p.exists():
        raise SchemaNotMined(f"text bank {bank} is not in the game install")
    return p


def _body_refs(raw: bytes) -> tuple[str | None, str | None]:
    """The body mesh (.fbx) and material its "Character Mesh" draws, when the
    entity sets them itself (a dire wolf's variant does; its model's is the
    Timber wolf's, overridden)."""
    from ...engine import entity_graph as EG
    c = next((x for x in EG.parse(raw).components if x.name == "Character Mesh"
              and x.cls == "oCEntityCpnt3dGraphicObjectSettings"), None)
    if c is None:
        return None, None
    fbx = re.search(rb"Characters\\[^\x00\"]+?\.fbx", c.body)
    mat = re.search(rb"Characters\\[^\x00\"]+?\.mat\.ot", c.body)
    return (fbx.group(0).decode() if fbx else None, mat.group(0).decode() if mat else None)


def _emit_custom(mod_id: str, defn: ContentDef, out_dir: Path, base: str,
                 herodef: bytes, herodef_cache: bytes) -> list[Path]:
    from ...engine import character_export as CE
    from ...engine import cooked, corpus
    from ...engine import entity_strings as ES
    from ...engine import hero_cook as H
    from ...engine import prop_cook as PC
    from ...engine import text_patches as TP
    from .meshes import _mod_source

    hid = defn.id
    f = defn.fields
    if hid in _RESERVED_IDS or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", hid):
        raise ContentError(f"hero {hid}: a custom hero id must be letters and digits "
                           f"(it becomes the Hero_{hid} entity name) and not a reserved "
                           f"name ({', '.join(sorted(_RESERVED_IDS))})")
    game = _game_dir()
    app = H.pristine_app_settings(game)
    if app is None:
        raise SchemaNotMined("ApplicationSettings.ot is not in the game install")
    try:
        b = H.resolve_base(HD.stem(base) or base, app)
    except H.HeroCookError as e:
        raise ContentError(f"hero {hid}: {e}") from e

    written: list[Path] = []

    def put(decoded: str, blob: bytes) -> None:
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)

    textures = {k: v for k, v in _TEXTURE_FIELDS.items() if f.get(k)}
    weapons = _table(f.get("weapons"), "weapons", hid)
    materials = _table(f.get("materials"), "materials", hid)
    animations = _table(f.get("animations"), "animations", hid)
    outfits = f.get("outfits") or []
    if not isinstance(outfits, list) or not all(isinstance(o, dict) for o in outfits):
        raise ContentError(f"hero {hid}: 'outfits' is a list of tables")
    values = _table(f.get("values"), "values", hid)
    references = _table(f.get("references"), "references", hid)
    abilities = f.get("abilities") or []
    if not isinstance(abilities, list):
        raise ContentError(f"hero {hid}: 'abilities' is a list of tables")
    skills = _table(f.get("skills"), "skills", hid)
    attacks = f.get("attacks") or []
    if not isinstance(attacks, list) or not all(isinstance(a, dict) for a in attacks):
        raise ContentError(f"hero {hid}: 'attacks' is a list of tables")
    kit = f.get("kit")
    frame = f.get("frame")
    if frame is True:
        frame = {}
    if frame is not None:
        if not isinstance(frame, dict) or set(frame) - {"rig", "mesh", "material", "slots",
                                                        "abilities"}:
            raise ContentError(f"hero {hid}: frame is true or a table of rig, mesh, "
                               "material, slots, abilities")
        clash = [k for k in ("kit", "abilities", "attacks", "talents") if f.get(k)]
        if clash:
            raise ContentError(f"hero {hid}: a frame hero is written from scratch; "
                               f"{', '.join(clash)} edit a clone's files (not yet for a frame)")
    # Talents of the hero's own (the talent builder, on this hero's copy): each
    # slot's base logic cut and rebuilt from generated parts. Edits the base
    # family's bytes before the kit, which then hangs each action's timeline
    # on the trigger state written here.
    talent_bytes: dict[str, bytes] = {}
    talent_specs = _table(f.get("talents"), "talents", hid)
    if talent_specs:
        talent_bytes, hooks, cards = _build_talents(talent_specs, b, hid, mod_id)
        if hooks:
            kit = dict(kit or {})
            kit["talents"] = list(kit.get("talents") or []) + hooks
        skills = {**cards, **skills}
    kit_copies: list = []             # projectiles of the hero's own (hero_kit.Copy)
    if kit:
        # The hero builder's blocks, as steps run before the hand-written ones
        # (engine/hero_kit.py): so `abilities` can build on what they made.
        from ...engine import hero_kit as HK
        main_ref = next(r for r in b.family
                        if r.rsplit("\\", 1)[-1] == f"{b.stem}.entity.ot")
        try:
            main = talent_bytes.get(b.stem) or corpus.read(H.entity_rel(main_ref))
            abilities = HK.expand(kit, main, b.stem, hid=hid, copies=kit_copies) + list(abilities)
            # `anim` blocks: the slot's clip swapped for another of the hero's
            # own, in this hero's files only (the `references` swap).
            references = {**HK.anim_swaps(kit, main, b.stem), **references}
        except HK.KitError as e:
            raise ContentError(f"hero {hid}: {e}") from e
    own = bool(f.get("own_entity") or f.get("model") or textures or weapons or materials
               or talent_specs or frame is not None
               or animations or outfits or values or references or abilities or skills
               or attacks or f.get("placeholder") or f.get("effects") or f.get("hide"))
    swaps: dict[str, str] = {}        # whole-string swaps inside the family
    art: list[str] = []               # preload-cache lines for the new art
    # Shipped resources to preload, borrowed from shipped caches in ONE pass
    # before the caches are written: each pass reads and walks every shipped
    # cache, and one per source made a hero build take minutes.
    borrow: list[str] = []
    # `borrow = ["Heroes/Hero_X/Thing.entity.ot", ...]`: shipped resources the
    # hero's edits reach that no build step records; each is preloaded with
    # its shipped closure (and refused if no shipped cache lists it).
    extra = f.get("borrow", [])
    if isinstance(extra, str):
        extra = [extra]
    if not isinstance(extra, list) or not all(isinstance(x, str) for x in extra):
        raise ContentError(f"hero {hid}: borrow is a list of resource paths")
    borrow.extend(x.replace("/", "\\") for x in extra)
    for c in kit_copies:
        if c.shipped:
            # Spawned as shipped: preloaded as the game preloads it.
            borrow.append(c.source)
            continue
        # A copy preloads as itself plus everything its source does.
        art.append(f"EntitySettings|{c.ref}|oCEntitySettingsResource")
        borrow.append(c.source)

    def material(donor: str | None, maps: dict, tag: str, what: str) -> str:
        """Clone ``donor`` with the mod's maps (``{"albedo": path, ...}``)."""
        slots = CE.material_slots(donor)
        # Beside the donor: a base whose main mesh is not its body (Kintaro's
        # is the bear) has no art_dir, and "\Textures\M_x.mat.ot" names
        # nothing, so the body drew invisible (select screen, 2026-11-06).
        folder = (donor.rsplit("\\Textures\\", 1)[0] if donor and "\\Textures\\" in donor
                  else b.art_dir)
        if not folder:
            raise ContentError(f"hero {hid}: {what}: cannot tell where {base}'s art lives")
        repoint = {}
        for field_name, slot in _TEXTURE_FIELDS.items():
            if not maps.get(field_name):
                continue
            if slot not in slots:
                raise ContentError(f"hero {hid}: {what}'s material has no {slot} map")
            ref = f"{folder}\\Textures\\T_{tag}_{slot}.tga"
            put(PC.art_cooked_path(ref), PC.cook_texture(
                _mod_source(out_dir, maps[field_name], hid, f"{what}.{field_name}")
                .read_bytes()))
            repoint[slots[slot]] = ref
            art.append(f"3D|{ref}|oCTexture")
        mat_ref = f"{folder}\\Textures\\M_{tag}.mat.ot"
        put(PC.art_cooked_path(mat_ref),
            PC.clone_material(corpus.read(PC.art_cooked_path(donor)), repoint))
        art.append(f"3D|{mat_ref}|oCMaterial")
        return mat_ref

    def mesh(donor_fbx: str, model: str, tag: str, what: str, transform) -> str:
        geo_ref = f"{b.art_dir}\\{tag}_GEO.fbx"
        put(PC.art_cooked_path(geo_ref), PC.cook_model(
            _mod_source(out_dir, model, hid, what).read_bytes(),
            corpus.read(PC.art_cooked_path(donor_fbx)), transform=transform))
        art.append(f"3D|{geo_ref}|oCGeometry")
        return geo_ref

    # 0. A summon's look of its own (kit `look`): its GLB cooked onto the
    # enemy's body mesh (skeleton, animations and bone weights kept; nearest-
    # vertex weights when the GLB has no skin) and its maps into a copy of the
    # enemy's material. Only this hero's copy points at them: the game's own
    # enemies keep their look.
    _looks: dict[int, dict[str, str]] = {}
    for c in kit_copies:
        if not c.look or c.data is None:
            continue
        # The variant's body wins (it overrides its model's: a dire wolf's model
        # names the Alpha wolf's mesh), so look there first.
        donor = next((k for k in sorted(kit_copies, key=lambda k: k.ref.endswith(
                      "_Model.entity.ot")) if k.look is c.look and k.data is not None
                      and _body_refs(k.data)[0]), None)
        if donor is None:
            raise ContentError(f"hero {hid}: look: {c.source} has no body mesh to replace")
        fbx, mat = _body_refs(donor.data)
        tag = donor.ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot").removeprefix("Hero_")
        if id(c.look) not in _looks:
            sw: dict[str, str] = {}
            if c.look.get("model"):
                sw[fbx] = mesh(fbx, c.look["model"], tag, "look.model", c.look.get("transform"))
            if any(c.look.get(k) for k in _TEXTURE_FIELDS):
                if not mat:
                    raise ContentError(f"hero {hid}: look: {c.source}'s material was not found")
                sw[mat] = material(mat, c.look, tag, "look")
            _looks[id(c.look)] = sw
        c.data = ES.replace_strings(c.data, _looks[id(c.look)], require_all=False)

    # 1. The look: a body of its own and a material of its own.
    if f.get("model"):
        if not b.body_fbx:
            raise ContentError(f"hero {hid}: {base}'s body mesh was not found")
        swaps[b.body_fbx] = mesh(b.body_fbx, f["model"], hid, "model",
                                 f.get("transform") or {"skin": "gltf", "submeshes": "map"})
    body_mat = b.body_mat
    if textures:
        body_mat = material(b.body_mat, f, hid, "body")
        swaps[b.body_mat] = body_mat
        swaps[b.body_mat.replace(".mat.ot", "_LowRes.mat.ot")] = body_mat

    # Weapons, keyed by the base's graphic-object label ("Weapon In Left Hand
    # Mesh"): a mesh and/or maps of their own, in THIS hero's entities only.
    if weapons:
        from rsmm.cli.cmd_export_character import _asset_paths, resolve_setup
        # resolve_setup keys on the ART folder (Wukong, RED, SnowQueen).
        setup = resolve_setup(b.art_dir.rsplit("\\", 1)[-1], None, _asset_paths())
        att, mats = setup.get("attachments") or {}, setup.get("mats") or {}
        for n, (label, spec) in enumerate(sorted(weapons.items()), 1):
            spec = spec if isinstance(spec, dict) else {"model": spec}
            # A material-only label (a companion: Beowulf's "Chatacter Mesh
            # Wyrm") takes maps but no model: it has no attachment to cook onto.
            if label not in att and not (label in mats and not spec.get("model")):
                have = sorted(att) + sorted(f"{m} (maps only)" for m in mats if m not in att)
                raise ContentError(f"hero {hid}: {base} has no weapon {label!r}; "
                                   f"have: {', '.join(have) or 'none'}")
            tag = f"{hid}_Weapon{n}"
            if spec.get("model"):
                swaps[att[label]["mesh"]] = mesh(att[label]["mesh"], spec["model"], tag,
                                                 f"weapons.{label}",
                                                 # A weapon keeps its authored shape: the
                                                 # prop fit's auto-upright turned the
                                                 # flute on end and squeezed it to a
                                                 # sliver (in game 2026-09-25).
                                                 spec.get("transform") or {"fit": "rig"})
            wmat = mats.get(label) or mats.get(label.removesuffix(" Mesh"))
            if any(spec.get(k) for k in _TEXTURE_FIELDS):
                if not wmat:
                    raise ContentError(f"hero {hid}: {label}'s material was not found")
                swaps[wmat] = material(wmat, spec, tag, f"weapons.{label}")

    # Materials by name: any material the hero's own entities use (a mount's,
    # a companion's, a second body: Kintaro's boy is his "Alt Form" mesh and
    # his main mesh the bear), retextured in this hero's files only.
    if materials:
        named = sorted({t for ref in b.family
                        for _s, _o, t in ES.list_strings(corpus.read(H.entity_rel(ref)))
                        if t.endswith(".mat.ot") and not t.endswith("_LowRes.mat.ot")})
        for n, (key, spec) in enumerate(sorted(materials.items()), 1):
            if not isinstance(spec, dict) or not spec or set(spec) - set(_TEXTURE_FIELDS):
                raise ContentError(f"hero {hid}: materials.{key} takes "
                                   f"{', '.join(sorted(_TEXTURE_FIELDS))}")
            stem = str(key).rsplit("\\", 1)[-1].removesuffix(".mat.ot")
            hits = [m for m in named if m == key
                    or m.rsplit("\\", 1)[-1].removesuffix(".mat.ot") == stem]
            if len(hits) != 1:
                raise ContentError(
                    f"hero {hid}: materials names {key!r}, which is "
                    f"{'ambiguous' if hits else 'not a material'} in {base}'s entities; have: "
                    f"{', '.join(m.rsplit(chr(92), 1)[-1][:-len('.mat.ot')] for m in named)}")
            new = material(hits[0], spec, f"{hid}_Mat{n}", f"materials.{key}")
            swaps[hits[0]] = new
            swaps[hits[0].replace(".mat.ot", "_LowRes.mat.ot")] = new

    # Attacks of the hero's own (engine/attack_build.py): each one a projectile
    # entity of its own, the steps that fire it, and its slot's animation.
    # Built here so its clip joins `animations` and its steps join
    # `abilities`; its entity is written with the family, once every swap
    # (its trail and impact are the hero's recoloured effects) is known.
    attack_entities: list = []
    if attacks:
        from ...engine import attack_build as AB
        main_ref = next(r for r in b.family
                        if r.rsplit("\\", 1)[-1] == f"{b.stem}.entity.ot")
        base_main = corpus.read(H.entity_rel(main_ref))
        abilities = list(abilities)
        animations = dict(animations)
        for spec in attacks:
            try:
                built = AB.build(spec, hero=hid, base=base, base_main=base_main,
                                 mesh=mesh, material=material)
            except AB.AttackError as e:
                raise ContentError(f"hero {hid}: attack: {e}") from e
            abilities += built.steps
            if built.animation:
                clip, anim = built.animation
                if clip in animations:
                    raise ContentError(f"hero {hid}: attack {spec.get('id')} and "
                                       f"'animations' both set clip {clip}")
                animations[clip] = anim
            art.append(f"EntitySettings|{built.entity_ref}|oCEntitySettingsResource")
            attack_entities.append(built)

    # Animations: a clip of this hero's own, under a new name, so the base
    # keeps its moves (the `animation` kind overrides a clip for everyone).
    if animations:
        from ...engine import anim_cook as AC
        for name, spec in sorted(animations.items()):
            spec = spec if isinstance(spec, dict) else {"source": spec}
            old = f"{b.art_dir}\\Animations\\{name}.fbx"
            tpl_raw = corpus.read(f"3D/{old.replace(chr(92), '/')}.Animation.gen")
            if tpl_raw is None:
                raise ContentError(f"hero {hid}: {base} has no clip {name!r} "
                                   f"(names as `rsmm export-character {base}` prints them)")
            cf = cooked.parse(tpl_raw)
            try:
                payload, _notes = AC.cook(
                    _mod_source(out_dir, spec["source"], hid, f"animations.{name}")
                    .read_bytes(),
                    b"".join(sec.payload for sec in cf.sections),
                    name=spec.get("clip") or name, strict=bool(spec.get("strict")))
            except AC.AnimCookError as e:
                raise ContentError(f"hero {hid}: animation {name}: {e}") from e
            head = len(cf.sections[0].payload)
            cf.sections[0] = cooked.Section(payload=payload[:head])
            cf.sections[1] = cooked.Section(payload=payload[head:])
            new = f"{b.art_dir}\\Animations\\{hid}_{name}.fbx"
            put(f"3D/{new.replace(chr(92), '/')}.Animation.gen", cooked.emit(cf))
            swaps[old] = new
            art.append(f"3D|{new}|oCAnimation")

    # Any other reference inside the hero's own entities: a VFX, a sound event,
    # a mesh or a clip of another hero. Checked against the base's strings, so
    # a typo fails here instead of shipping a no-op.
    if references:
        have = {t for ref in b.family
                for _s, _o, t in ES.list_strings(corpus.read(H.entity_rel(ref)))}
        unknown = sorted(k for k in references if k not in have)
        if unknown:
            raise ContentError(f"hero {hid}: 'references' names strings {base}'s entities "
                               f"never use: {', '.join(map(repr, unknown))}")
        swaps.update({str(k): str(v) for k, v in references.items()})
        # A swapped-in resource the preload caches do not list is a null in
        # the preloaded vector (the stale-cache crash), so borrow its closure
        # from a shipped cache that already loads it.
        borrow.extend(str(v) for v in references.values() if "\\" in str(v) and "." in str(v))

    # Talent cards of the hero's own. A card's text is read by the key its
    # skill controller names (the herodef row is not what is shown, 2026-09-12),
    # so the controller in THIS hero's entities is pointed at new keys and the
    # base keeps its cards. The keys are appended with the name (one append:
    # two would each write the whole bank).
    bank_pairs: dict[str, str] = {}
    # Cards format the hero's own name in ("{0} dash forward", "{0} can act at
    # the same time"): in this hero's entities that argument is its name.
    for fld, key in (("name", "Hero_Name"), ("description", "Hero_Desc")):
        if f.get(fld):
            swaps[key] = f"Hero_{hid}_{key.split('_')[1]}"
    if skills:
        keys = _skill_keys(b, H, corpus)
        for talent, spec in sorted(skills.items()):
            spec = spec if isinstance(spec, dict) else {"name": spec}
            want = str(talent)
            if not want.startswith("Ability "):
                want = want.removeprefix("Skill Controller ").removeprefix("Skill ")
            if want not in keys:
                raise ContentError(f"hero {hid}: {base} has no talent {talent!r}; have: "
                                   f"{', '.join(sorted(keys))}")
            bank, name_key, desc_key = keys[want]
            if bank != b.text_bank:
                raise ContentError(f"hero {hid}: talent {talent!r} reads its text from "
                                   f"{bank}, not {b.text_bank}")
            unknown = sorted(set(spec) - {"name", "description"})
            if unknown:
                raise ContentError(f"hero {hid}: talent {talent!r}: unsupported field(s) "
                                   f"{unknown}; known: ['description', 'name']")
            for fld, key in (("name", name_key), ("description", desc_key)):
                if spec.get(fld) and key:
                    swaps[key] = f"Hero_{hid}_{key}"
                    bank_pairs[swaps[key]] = str(spec[fld])
                elif spec.get(fld):
                    raise ContentError(f"hero {hid}: talent {talent!r} has no {fld} key")

    # A placeholder look: every piece of art the hero still borrows from the
    # base (character materials, ability/talent icons, HUD art; the book art
    # further down) painted with ONE image, so what is left to replace shows
    # at a glance. Anything given explicitly (albedo, weapons, portrait) wins.
    placeholder = f.get("placeholder")
    ph_png = None
    if placeholder:
        ph_png = PC.cook_texture(
            _mod_source(out_dir, placeholder, hid, "placeholder").read_bytes())
        mats: set[str] = set()
        ui: set[str] = set()
        for ref in b.family:
            for _s, _o, t in ES.list_strings(corpus.read(H.entity_rel(ref))):
                if t.endswith(".mat.ot") and t.startswith(b.art_dir + "\\"):
                    mats.add(t)
                elif t.lower().endswith(".png"):
                    ui.add(t)
        for m in sorted(mats - set(swaps)):
            tag = f"{hid}_PH_{m.rsplit(chr(92), 1)[-1][:-len('.mat.ot')]}"
            try:
                swaps[m] = material(m, {"albedo": placeholder}, tag, "placeholder")
            except ContentError:
                continue                    # a material with no albedo map
        for t in sorted(ui - set(swaps)):
            new = _placeholder_ref(t, hid)
            put(f"Ui/{new.replace(chr(92), '/')}.Texture.dxt", ph_png)
            art.append(f"Ui|{new}|oCTexture")
            swaps[t] = new

    # Meshes the hero does not have (a companion, a prop): an invisible copy,
    # the same mesh on the same skeleton shrunk to nothing, so every bone the
    # game logic attaches to (a breath's origin at the head) is still there.
    hide = f.get("hide") or []
    if not isinstance(hide, list) or not all(isinstance(x, str) for x in hide):
        raise ContentError(f"hero {hid}: 'hide' is a list of mesh names")
    if hide:
        meshes = sorted({t for ref in b.family
                         for _s, _o, t in ES.list_strings(corpus.read(H.entity_rel(ref)))
                         if t.lower().endswith(".fbx") and "\\Animations\\" not in t})
        for n, want in enumerate(hide, 1):
            stem = want.rsplit("\\", 1)[-1].removesuffix(".fbx").lower()
            hits = [t for t in meshes if t == want
                    or t.rsplit("\\", 1)[-1].removesuffix(".fbx").lower() == stem]
            if len(hits) != 1:
                raise ContentError(
                    f"hero {hid}: 'hide' names {want!r}, which is "
                    f"{'ambiguous' if hits else 'not a mesh'} in {base}'s entities; "
                    f"have: {', '.join(t.rsplit(chr(92), 1)[-1] for t in meshes)}")
            ref = hits[0]
            donor = corpus.read(PC.art_cooked_path(ref))
            if donor is None:
                raise ContentError(f"hero {hid}: mesh {ref} is not in the game files")
            new = f"{ref.rsplit(chr(92), 1)[0]}\\{hid}_Hidden{n}_GEO.fbx"
            put(PC.art_cooked_path(new), PC.cook_model(
                _shrunk_glb(CE.export(donor, textures=False)), donor,
                transform={"skin": "gltf", "submeshes": "map"}))
            art.append(f"3D|{new}|oCGeometry")
            swaps[ref] = new

    # Effects of the hero's own: every particle effect in the base's own FX
    # folder is copied under this hero's name with its own materials and
    # textures, recoloured by `effects` tints, or pink under a placeholder.
    effects = _table(f.get("effects"), "effects", hid)
    if placeholder or effects:
        fx_swaps, fx_art, fx_notes = _own_effects(b, hid, effects, bool(placeholder), put)
        for k, v in fx_swaps.items():
            swaps.setdefault(k, v)
        art.extend(fx_art)
        for n in fx_notes:
            print(f"warning: hero {hid}: {n}", file=sys.stderr)

    # 2. The gameplay family, renamed, reached through an alias of its own.
    R = H.Renamer(b, f"Hero_{hid}", swaps) if own else None
    default = R.entity_ref(b.default_skin) if R is not None else None
    if R is not None:
        guid = H.alias_guid(mod_id, hid)
        # Numbers first, on the base's bytes and names (as --list-values shows
        # them); the edit is in place, so renaming afterwards cannot move it.
        stem_of = {ref: ref.rsplit("\\", 1)[-1][:-len(".entity.ot")] for ref in b.family}
        base_bytes = {stem_of[ref]: talent_bytes.get(stem_of[ref]) or corpus.read(H.entity_rel(ref))
                      for ref in b.family}
        if values:
            try:
                base_bytes = H.set_values(base_bytes,
                                          {str(k): float(v) for k, v in values.items()})
            except (H.HeroCookError, TypeError, ValueError) as e:
                raise ContentError(f"hero {hid}: {e}") from e
        if abilities:
            # Wiring after numbers, on the same base names; checked before
            # anything is written (engine/ability_edit.py).
            from ...engine import ability_edit as AE
            from ...engine import entity_check as CK
            shipped = HK.reader(kit_copies) if kit_copies else CK._corpus_reader

            def read(ref: str):
                # An entity the mod ships in its own assets/ wins over the game's.
                own = _mod_file(out_dir, ref)
                return own.read_bytes() if own else shipped(ref)
            try:
                res = AE.apply(base_bytes, abilities, main=b.stem, seed=f"{mod_id}:{hid}",
                               read=read)
            except AE.AbilityEditError as e:
                raise ContentError(f"hero {hid}: {e}") from e
            base_bytes = res.files
            for w in res.warnings:
                print(f"warning: hero {hid}: {w}", file=sys.stderr)
            # An attack's own projectile is preloaded by the lines its build
            # recorded (the entity, its mesh, maps and effects); no shipped
            # cache can list it, so it is not borrowed.
            # Nor is an entity the mod ships itself: no shipped cache lists it.
            own_refs = ({a.entity_ref for a in attack_entities}
                        | {c.ref for c in kit_copies if not c.shipped}
                        | {r for r in res.resources if _mod_file(out_dir, r)})
            borrow.extend(res.resources - own_refs)
        art.extend(_borrow_closure(sorted(set(borrow)), out_dir, hid))
        family = {H.entity_rel(R.entity_ref(ref)):
                  R.cooked(base_bytes[stem_of[ref]], b.alias.guid, guid)
                  for ref in b.family}
        if frame is not None:
            # The hero written from scratch: its own main, FX and skins replace
            # the renamed copies (engine/hero_frame.py); the rest of the
            # pipeline (herodef, alias, caches, text) is the clone's.
            family.update(_frame_family(frame, b, R, H, app, herodef, guid, hid, mod_id,
                                        swaps, corpus, bank_pairs))
            _no_effect(family.values(), put, art)
        # Every renamed member preloads with the hero. The base's skin caches
        # do not list all of them: Update 6 members (Scarlet's Update 6
        # ultimate projectiles) are preloaded by LiveOps6.versiondef's cache,
        # which names the base's files, not these. A spawner whose template is
        # not loaded returns without spawning (EntitySpawner_SpawnOne reads the
        # settings' resolved template at +0x1a8, Ghidra b9c3 2026-11-03): the
        # ultimate fired nothing.
        art.extend(f"EntitySettings|{R.entity_ref(ref)}|oCEntitySettingsResource"
                   for ref in b.family)
        for ref in b.family:
            rel = H.entity_rel(ref)
            new_rel = H.entity_rel(R.entity_ref(ref))
            put(new_rel, family[new_rel])
            ecache = corpus.read(RC.cache_path_for(rel))
            if ecache is not None:
                put(RC.cache_path_for(new_rel), R.cache(ecache, tuple(art)))
        for ref in b.satellites:
            # Its UI (the life bar), reading this hero's names instead of the base's.
            put(H.entity_rel(R.entity_ref(ref)), R.cooked(corpus.read(H.entity_rel(ref))))
        for built in attack_entities:
            # Its trail/impact name the base's effects; the swaps turn them
            # into this hero's recoloured copies (and leave anything else).
            blob = ES.replace_strings(built.entity, swaps, require_all=False)
            # Fresh part ids: it must not share the template projectile's.
            put(built.entity_rel, PC.restamp_entity_guids(blob, built.entity_rel))
        for c in kit_copies:
            if c.shipped:
                continue
            if c.data is not None:
                # A summoned ally: built whole, its two files sharing ONE
                # identity mapping (a per-file restamp would cut the variant
                # off from the model parts it overrides). A pet's reads of its
                # owner (where an attack order sends it) aimed at this hero.
                blob = c.data
                if c.reads:
                    mref = R.entity_ref(main_ref)
                    blob = HK.build_copy(c, family[H.entity_rel(mref)], mref)
                put(H.entity_rel(c.ref), blob)
                continue
            # Its reads of its owner aimed at this hero's final entity.
            mref = R.entity_ref(main_ref)
            blob = HK.build_copy(c, family[H.entity_rel(mref)], mref)
            put(H.entity_rel(c.ref), PC.restamp_entity_guids(blob, H.entity_rel(c.ref)))
        put(H.APP_SETTINGS_DECODED, H.add_alias(
            app, H.Alias(guid, f"Hero_{hid}", R.entity_ref(b.alias.stream))).encode(
                "utf-8", errors="surrogateescape"))

    # Outfits: more skins of this hero, each the Default skin wearing its own
    # body material. They take the base's skin slots in order.
    outfit_refs: list[tuple[str, str]] = []           # (entity ref, display name)
    if outfits:
        d_rel = H.entity_rel(default)
        d_bytes = (out_dir / Path(*d_rel.split("/"))).read_bytes()
        d_cache = corpus.read(RC.cache_path_for(H.entity_rel(b.default_skin)))
        for i, o in enumerate(outfits, 1):
            if not any(o.get(k) for k in (*_TEXTURE_FIELDS, "model")):
                raise ContentError(f"hero {hid}: outfit {i} needs a model or maps")
            # Donor = the shipped material (ours is not in the corpus); the swap
            # below still replaces whatever the Default skin wears now.
            omat = material(b.body_mat, o, f"{hid}_Outfit{i}", f"outfits[{i}]")
            oref = default.replace("_Default.entity.ot", f"_Outfit{i}.entity.ot")
            orel = H.entity_rel(oref)
            obytes = ES.replace_strings(d_bytes, {body_mat: omat})
            if o.get("model"):
                obytes = _outfit_body(b, R, obytes, o, i, hid, omat, mesh)
            put(orel, obytes)
            if d_cache is not None:
                oc = RC.parse(R.cache(d_cache, tuple(art)))
                self_ = f"EntitySettings|{default}|oCEntitySettingsResource"
                put(RC.cache_path_for(orel),
                    RC.render(sorted({ln for ln in oc if ln != self_}
                                     | {f"EntitySettings|{oref}|oCEntitySettingsResource"})))
            outfit_refs.append((oref, str(o.get("name") or f"Outfit {i}")))

    # 3. The herodef: its skins, its name, its portraits.
    hswap: dict[str, str] = {}
    pairs: dict[str, str] = dict(bank_pairs)
    for fld, key in (("name", "Hero_Name"), ("description", "Hero_Desc")):
        if f.get(fld):
            hswap[key] = f"Hero_{hid}_{key.split('_')[1]}"
            pairs[hswap[key]] = str(f[fld])
    # Rows the appended keys take, per bank: every reference to them is
    # re-pointed at its row once everything is written (repoint_text_rows).
    text_rows: dict[str, dict[str, int]] = {}
    if pairs:
        text_rows[b.text_bank] = TP.appended_rows(_install_bank(game, b.text_bank), pairs)
        banks = TP.append_bank_keys(_install_bank(game, b.text_bank), pairs)
        dec = f"Text/{b.text_bank}.LocalText.gen"
        for tok, blob in banks.items():
            put(dec if tok == "__base__" else dec + tok, blob)

    # The book's story pages (memoirs): each page's title and text keys in the
    # base's memoirs bank, re-pointed at keys of the hero's own. A page the
    # manifest leaves out keeps the base's story, unless a placeholder is set:
    # then it reads as a page still to write, like the pink art.
    memoirs = f.get("memoirs") or []
    if not isinstance(memoirs, list) or not all(isinstance(m, dict) for m in memoirs):
        raise ContentError(f"hero {hid}: 'memoirs' is a list of tables ({{title, text}})")
    pages = _memoir_keys(herodef)
    if len(memoirs) > len(pages):
        raise ContentError(f"hero {hid}: {base} has {len(pages)} story pages; "
                           f"'memoirs' lists {len(memoirs)}")
    mem_pairs: dict[str, str] = {}
    mem_bank = None
    for n, (bank, title_key, desc_key) in enumerate(pages, 1):
        page = memoirs[n - 1] if n <= len(memoirs) else {}
        unknown = sorted(set(page) - {"title", "text"})
        if unknown:
            raise ContentError(f"hero {hid}: memoir {n}: unsupported field(s) {unknown}; "
                               f"known: ['text', 'title']")
        if not page and placeholder:
            page = {"title": f"[Story page {n}: to be written]",
                    "text": f"PLACEHOLDER: {f.get('name') or hid}'s story, page {n}, "
                            f"is still to be written."}
        for fld, key in (("title", title_key), ("text", desc_key)):
            if page.get(fld):
                hswap[key] = f"Hero_{hid}_Memoir{n}_{key.rsplit('_', 1)[1]}"
                mem_pairs[hswap[key]] = str(page[fld])
                mem_bank = bank
    if mem_pairs:
        # The pages' voice-over: `<Hero>/<Hero>_Memoir{}_Desc` names the
        # recordings in Voice_<lang>.bank (Beowulf_Memoir1_Desc ...), so the
        # base's pages would still be READ ALOUD over the new text. A name of
        # the hero's own has no recordings: its pages are silent.
        for t in (t for _s, _o, t in ES.list_strings(herodef)):
            if re.fullmatch(r"[^\\/]+/[^\\/]+_Memoir\{\}_Desc", t):
                hswap[t] = f"{hid}/{hid}_Memoir{{}}_Desc"
        text_rows[mem_bank] = TP.appended_rows(_install_bank(game, mem_bank), mem_pairs)
        banks = TP.append_bank_keys(_install_bank(game, mem_bank), mem_pairs)
        dec = f"Text/{mem_bank}.LocalText.gen"
        for tok, blob in banks.items():
            put(dec if tok == "__base__" else dec + tok, blob)
    portrait_lines: list[str] = []
    if f.get("portrait"):
        png = _mod_source(out_dir, f["portrait"], hid, "portrait").read_bytes()
        cooked_png = PC.cook_texture(png)
        for s in (t for _s, _o, t in ES.list_strings(herodef)):
            if s.lower().endswith(".png") and (
                    s.startswith("BookMenu\\Heroes\\UI_HeroPortrait_")
                    or s.rsplit("\\", 1)[-1].startswith("Portrait_")):
                new = _portrait_ref(s, hid)
                hswap[s] = new
                put(f"Ui/{new.replace(chr(92), '/')}.Texture.dxt", cooked_png)
                portrait_lines.append(f"Ui|{new}|oCTexture")
    if ph_png is not None:
        # The book's art: portraits, skin icons, codex pictures.
        for s in sorted({t for _s, _o, t in ES.list_strings(herodef)
                         if t.lower().endswith(".png")} - set(hswap)):
            new = _placeholder_ref(s, hid)
            hswap[s] = new
            put(f"Ui/{new.replace(chr(92), '/')}.Texture.dxt", ph_png)
            portrait_lines.append(f"Ui|{new}|oCTexture")

    # Skin slots in herodef order: slot 0 is Default, outfits take 1..n, and
    # with a body of its own every other slot shows Default too (the base's
    # skins would dress it in the base's meshes).
    slot_of: dict[str, str] = {}
    if R is not None:
        by_sec: dict[int, list[str]] = {}
        for sec, _o, t in ES.list_strings(herodef):
            by_sec.setdefault(sec, []).append(t)
        skin_secs = [ss for _sec, ss in sorted(by_sec.items())
                     if any(t.endswith(".entity.ot") and t in b.family
                            and "_LowRes" not in t for t in ss)]
        skins_bank_pairs: dict[str, str] = {}
        skins_bank = None
        for n, ss in enumerate(skin_secs):
            path = next(t for t in ss if t.endswith(".entity.ot") and t in b.family)
            if n == 0:
                slot_of[path] = default
            elif n <= len(outfit_refs):
                oref, oname = outfit_refs[n - 1]
                slot_of[path] = oref
                bank_i = next((k for k, t in enumerate(ss) if t.endswith("~GAM.xls")), None)
                if bank_i is not None and bank_i + 1 < len(ss):
                    skins_bank = skins_bank or ss[bank_i]
                    if ss[bank_i] == skins_bank:
                        key = f"Hero_{hid}_Outfit{n}_Title"
                        hswap[ss[bank_i + 1]] = key
                        skins_bank_pairs[key] = oname
            elif f.get("model"):
                slot_of[path] = default
            if n > len(outfit_refs) and placeholder:
                # A slot still showing the base's skin: its name and blurb read
                # as a skin still to design, like the pink art.
                for k in range(1, len(ss)):
                    t = ss[k]
                    if not ss[k - 1].endswith("~GAM.xls") or t in hswap:
                        continue
                    part = ("Title" if t.endswith("_Title") else
                            "Description" if t.endswith("_Description") else None)
                    if part is None:
                        continue
                    skins_bank = skins_bank or ss[k - 1]
                    if ss[k - 1] != skins_bank:
                        continue
                    key = f"Hero_{hid}_Skin{n}_{part}"
                    hswap[t] = key
                    skins_bank_pairs[key] = (
                        f"[Skin {n}: to be designed]" if part == "Title" else
                        f"PLACEHOLDER: {f.get('name') or hid}'s skin {n} is still "
                        f"to be designed.")
        if skins_bank_pairs:
            text_rows[skins_bank] = TP.appended_rows(_install_bank(game, skins_bank),
                                                     skins_bank_pairs)
            banks = TP.append_bank_keys(_install_bank(game, skins_bank), skins_bank_pairs)
            dec = f"Text/{skins_bank}.LocalText.gen"
            for tok, blob in banks.items():
                put(dec if tok == "__base__" else dec + tok, blob)

    def herodef_string(s: str) -> str:
        if s in hswap:
            return hswap[s]
        if s in slot_of:
            return slot_of[s]
        return R.string(s) if R is not None else s

    new_def, _n = ES.rewrite_strings(herodef, herodef_string)
    cooked.parse(new_def)
    put(_rel(hid), new_def)
    extra = tuple(art + portrait_lines
                  + [f"EntitySettings|{r}|oCEntitySettingsResource" for r, _n in outfit_refs])
    lines = RC.parse(herodef_cache)
    own = _self_line(HD.stem(base) or base)     # once: it lists every herodef
    lines = [ln for ln in lines if ln != own] + [_self_line(hid)]
    base_cache = RC.render(sorted(set(lines)))
    put(RC.cache_path_for(_rel(hid)),
        R.cache(base_cache, extra) if R is not None
        else RC.render(sorted(set(lines) | set(extra))))

    # 4. Identities of its own. Last, so the family, the outfits' copied
    #    override record and the herodef all go through ONE mapping.
    if R is not None:
        mapping = H.family_guid_map([corpus.read(H.entity_rel(r))
                                     for r in (*b.family, *b.satellites)],
                                    f"{mod_id}:{hid}")
        outfit_files = {H.entity_rel(r) for r, _n in outfit_refs}
        for path in written:
            rel = path.relative_to(out_dir).as_posix()
            if rel.endswith(H.ENTITY_SUFFIX) or rel == _rel(hid):
                blob = H.apply_guid_map(path.read_bytes(), mapping)
                if rel in outfit_files:
                    # A copy of Default: without this it shares Default's.
                    blob = PC.restamp_entity_guids(blob, rel)
                path.write_bytes(blob)

    # 5. Text references to appended keys still carry the base key's cached
    #    row, which the book and the HUD read instead of the key.
    for path in written:
        rel = path.relative_to(out_dir).as_posix()
        if text_rows and (rel.endswith(H.ENTITY_SUFFIX) or rel == _rel(hid)):
            blob = path.read_bytes()
            for bank, rows in text_rows.items():
                blob = TP.repoint_text_rows(blob, bank, rows)
            path.write_bytes(blob)
    return written


def _skill_keys(b, H, corpus) -> dict[str, tuple[str, str, str]]:
    """Card -> ``(bank, name key, description key)``: each talent from its skill
    controller (``Skill Controller Dash Trap`` -> ``Dash Trap``; the name key
    sits in the controller, the description key in the String Format it links)
    and each ability slot from its ability controller (``Ability_Power_Name``
    -> ``Ability Power``, description ``Ability_Power_Desc``)."""
    from ...engine import entity_fields as EF
    from ...engine import entity_graph as EG
    from ...engine import entity_strings as ES

    text = re.compile(r"'([^']+~GAM\.xls)' '([^']+)'")
    out: dict[str, tuple[str, str, str]] = {}
    for ref in b.family:
        raw = corpus.read(H.entity_rel(ref))
        if raw is None:
            continue
        g = EG.parse(raw, ref)
        by_guid = {c.guid: c for c in g.components}
        by_name = {c.name: c for c in g.components}
        strings = {t for _s, _o, t in ES.list_strings(raw)}
        for c in g.components:
            if c.cls == "oCDtEntityCpntAbilityControllerSettings":
                for f in EF.fields(c):
                    for bk, k in (m.groups() for m in text.finditer(f.text)):
                        if k.startswith("Ability_") and k.endswith("_Name"):
                            d = k[:-5] + "_Desc"
                            out.setdefault("Ability " + k[8:-5].replace("_", " "),
                                           (bk, k, d if d in strings else ""))
                continue
            if not c.name.startswith("Skill Controller ") or c.name[17:] in out:
                continue
            found = [m.groups() for f in EF.fields(c) for m in text.finditer(f.text)]
            name = next(((bk, k) for bk, k in found if k.endswith("_Name")), None)
            desc = ""
            # A linked String Format's OWN key is its first text; later ones
            # are arguments (Special Sends Power formats Ability_Power_Name
            # in), never the card's. The ultimates name themselves this way.
            for _o, r in EG._pickers(c.body, c.classes.index("oCEntityCpntPicker")
                                     if "oCEntityCpntPicker" in c.classes else -1):
                # Override records carry another GUID than the one a picker
                # names, so fall back on the path the picker also carries.
                t = by_guid.get(r.guid) or by_name.get(r.path.rsplit("\\", 1)[-1])
                if t is None or t.cls != "oCEntityCpntStringFormatValueSettings":
                    continue
                own = next((m.groups() for f in EF.fields(t)
                            for m in text.finditer(f.text)), None)
                if own and own[1].endswith("_Name") and name is None:
                    name = own
                elif own and own[1].endswith("_Desc") and not desc:
                    desc = own[1]
            if name is None:
                continue
            out[c.name[17:]] = (name[0], name[1], desc)
    return out


def _outfit_body(b, R, outfit: bytes, o: dict, i: int, hid: str, omat: str, mesh) -> bytes:
    """Give an outfit a body of its own.

    The Default skin draws the gameplay entity's body; a skin with its own body
    OVERRIDES the ``<Base>\\Base\\Character Mesh`` graphic object. That override
    record is taken from one of the base's own body-swap skins (every base hero
    ships one), re-scoped to this hero and outfit, and pointed at the outfit's
    mesh and material.
    """
    from ...engine import character_export as CE
    from ...engine import cooked, corpus
    from ...engine import entity_components as EC
    from ...engine import hero_cook as H
    from ...engine import prop_cook as PC

    def bones(fbx: str) -> set[str]:
        raw = corpus.read(PC.art_cooked_path(fbx))
        return {x["name"] for x in CE.read_skeleton(cooked.parse(raw))} if raw else set()

    # The donor's body must carry the base skeleton the model is rigged to;
    # some skins (Albino) ship a body on a trimmed one.
    want = bones(b.body_fbx) if b.body_fbx else set()
    target = f"[3d graphic object] {b.stem}\\Base\\Character Mesh"
    donor = rec = None
    best = -1
    for ref in b.family:
        if ref == b.default_skin or "_LowRes" in ref:
            continue
        raw = corpus.read(H.entity_rel(ref))
        for sec in cooked.parse(raw).sections[1:-1]:
            ss = EC._record_strings(sec.payload)
            if ss and ss[0] == target and any(t.lower().endswith(".fbx") for t in ss):
                score = len(want & bones(next(t for t in ss if t.lower().endswith(".fbx"))))
                if score > best:
                    donor, rec, best = (ref, raw), ss, score
                break
    if donor is None:
        raise ContentError(f"hero {hid}: outfit {i}: {b.herodef} ships no skin with a "
                           f"body of its own to copy the override from")
    dstem = donor[0].rsplit("\\", 1)[-1][:-len(".entity.ot")]
    ostem = f"Hero_{hid}_Outfit{i}"
    fbx = next(t for t in rec if t.lower().endswith(".fbx"))
    # Cooked against the BASE body, not the donor skin's: each submesh carries
    # its own bone palette (Piper 42/63, Combat 38/63/35), and a model rigged
    # like the base body only fits the base body's split. The override record
    # then lists at least as many materials as there are submeshes, which
    # shipped skins do too (Wukong God: 5 for 3).
    geo = mesh(b.body_fbx or fbx, o["model"], ostem.removeprefix("Hero_"),
               f"outfits[{i}].model", o.get("transform") or {"skin": "gltf", "submeshes": "map"})

    def new(t: str) -> str:
        if t == fbx:
            return geo
        if t.endswith(".mat.ot"):
            return omat
        return R.string(t.replace(f"] {dstem}\\", f"] {ostem}\\"))
    swaps = {t: new(t) for t in set(rec) if new(t) != t}
    return EC.copy_overrides(outfit, donor[1], target.split("] ", 1)[1],
                             only=("\\Base\\Character Mesh",), string_swaps=swaps)


def _mod_file(out_dir: Path, ref: str) -> Path | None:
    """The mod's own copy of entity ``ref`` in its assets/, if it ships one:
    at its cooked name, or at the plain path the reference spells."""
    from ...engine import hero_cook as H
    for p in (out_dir / H.entity_rel(ref), out_dir / Path(*ref.split("\\"))):
        if p.is_file():
            return p
    return None


_TALENT_KEYS = frozenset({"rebuild", "add_stats", "actions", "name", "description"})


def _build_talents(specs: dict, b, hid: str, mod_id: str):
    """The ``talents`` field: per talent slot, its base logic cut (``rebuild``,
    default true), generated stat bonuses (``add_stats``, the talent kind's
    entries without ``talent``) and generated actions (``actions``: ``{ on =
    <game event>, steps = [...] }``, a kit timeline run each time the event
    fires while the talent is owned). Returns the edited base family bytes by
    file stem, the kit hooks for the actions, and the card relabels."""
    from ...engine import corpus
    from ...engine import hero_cook as H
    from ...engine import talent_add_stat as TA
    from .talents import _coerce_add_stats, _owns_talent
    files = {ref.rsplit("\\", 1)[-1][:-len(".entity.ot")]: corpus.read(H.entity_rel(ref))
             for ref in b.family}
    edited: dict[str, bytes] = {}
    hooks: list[dict] = []
    cards: dict[str, dict] = {}
    for talent, spec in specs.items():
        talent = str(talent).removeprefix("Skill Controller ")
        if not isinstance(spec, dict):
            raise ContentError(f"hero {hid}: talents.{talent} is a table")
        unknown = set(spec) - _TALENT_KEYS
        if unknown:
            raise ContentError(f"hero {hid}: talents.{talent} has no "
                               f"{', '.join(sorted(unknown))}; it takes "
                               f"{', '.join(sorted(_TALENT_KEYS))}")
        ctl = f"Skill Controller {talent}".encode()
        homes = [st for st, raw in files.items()
                 if ctl in (edited.get(st) or raw or b"")]
        if len(homes) > 1:
            homes = [st for st in homes if _owns_talent(edited.get(st) or files[st], talent)]
        if len(homes) != 1:
            raise ContentError(f"hero {hid}: {len(homes)} of {b.stem}'s files hold a "
                               f"talent {talent!r}")
        home = homes[0]
        raw = edited.get(home) or files[home]
        seed = f"{mod_id}:{hid}:{talent}"
        try:
            if spec.get("rebuild", True):
                raw, _cleared = TA.rebuild_talent(raw, talent=talent, seed=seed)
            for e in _coerce_add_stats([{**x, "talent": talent} if isinstance(x, dict) else x
                                        for x in (spec.get("add_stats") or [])]):
                raw, _added = TA.add_stat(
                    raw, talent=talent, stat=e["stat"], values=e["values"],
                    percent=e["percent"], seed=seed, during=e["during"], after=e["after"],
                    seconds=e["seconds"], cooldown=e["cooldown"], next_ability=e["next"],
                    on=e["on"])
            actions = spec.get("actions") or []
            if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
                raise ContentError(f"hero {hid}: talents.{talent}.actions is a list of "
                                   "{ on = <game event>, steps = [...] }")
            for n, a in enumerate(actions, 1):
                if set(a) - {"on", "steps"} or not a.get("on") or not a.get("steps"):
                    raise ContentError(f"hero {hid}: talents.{talent}.actions[{n}] is "
                                       "{ on = <game event>, steps = [...] }")
                if home != b.stem:
                    raise ContentError(f"hero {hid}: talent {talent!r} lives in {home}, "
                                       f"not {b.stem}; its actions cannot be built yet")
                raw, state = TA.add_action_trigger(raw, talent=talent, on=str(a["on"]),
                                                   n=n, seed=seed)
                hooks.append({"when": state, "steps": a["steps"]})
        except TA.AddStatError as e:
            raise ContentError(f"hero {hid}: {e}") from e
        edited[home] = raw
        card = {k: spec[k] for k in ("name", "description") if spec.get(k)}
        if card:
            cards[talent] = card
    return edited, hooks, cards


#: Where a hero written from scratch keeps its files: the shared heroes'
#: folder (a new cooked path needs a folder the game ships), and the bank its
#: text is appended to.
_SCRATCH_FOLDER, _SCRATCH_BANK = "Hero_Common", "Common~GAM.xls"
_SCRATCH_SORT = 14000
_SCRATCH_FIELDS = frozenset({"rig", "mesh", "material", "albedo", "slots", "abilities",
                             "ultimates", "weapon",
                             "talents", "sort", "portrait", "animations", "model",
                             "projectiles", "book", "new_hero", "skin_icon", "codex",
                             "banner", "effects"})
#: An effect layer's particle material, written as the hero's own: the
#: engine's sprite shader (texture = the shape, its colours tinted by the
#: layer's `colors`, as most shipped billboard particles are drawn), in the
#: format of the generic shape library's material (soft: fades into the
#: ground). Its one texture is the layer's.
_FX_MATERIAL = {False: ("Materials\\Dot_Blurred_Square_01.mat.ot",
                        "Textures\\Shapes\\Dot_Blurred_Square_Alpha.png"),
                True: ("Materials\\Dot_Blurred_Square_01_SOFT.mat.ot",
                       "Textures\\Shapes\\Dot_Blurred_Square_Alpha.png")}
#: Where a hero's own effects are written: a shipped effects folder.
_FX_FOLDER = "Settings\\FX\\Common_FX"
_FX_PREFIX = "fx:"


def _fx_cooked(ref: str, suffix: str) -> str:
    return "FX/" + ref.replace("\\", "/") + suffix


def _no_effect(blobs, put, art: list[str]) -> None:
    """The effect of nothing (vfx_writer.NO_EFFECT), written and preloaded
    when a hero's files name it (a hit with ``shake = "none"``)."""
    from ...engine import vfx_writer as VW
    if not any(VW.NO_EFFECT.encode("latin-1") in b for b in blobs):
        return
    put(_fx_cooked(VW.NO_EFFECT, ".ScheduledVfxSettings.gen"), VW.build([], empty=True))
    line = f"FX|{VW.NO_EFFECT}|oCScheduledVfxSettings"
    if line not in art:
        art.append(line)
#: A talent card with no icon of its own; also the folder new card icons go in.
_DEFAULT_ICON = "Heroes\\Ultimate_Power_1_Default.png"
#: The book's four hero portraits, in herodef order.
_BOOK_STATES = ("standard", "active", "locked", "unavailable")
#: ``clip = "anim:<name>"`` in a slot or a button names one of the hero's own
#: clips (``frame.animations``).
_OWN_CLIP = "anim:"


def _descends(skel, i: int, ancestor: int) -> bool:
    """Bone ``i`` sits below bone ``ancestor`` in ``skel``'s hierarchy."""
    p = skel.bones[i].parent
    while p >= 0:
        if p == ancestor:
            return True
        p = skel.bones[p].parent
    return False


def _emit_scratch(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """A hero written from scratch (no ``base``): its own gameplay entities
    (engine/hero_frame.py), its own buttons (engine/hero_ability.py), its own
    roster record (engine/herodef_frame.py), alias, text and preload lists.
    ``frame.rig`` lends ASSETS only (its skeleton, on-foot clips and UI art)."""
    from ...engine import cooked, corpus
    from ...engine import hero_ability as HA
    from ...engine import hero_cook as H
    from ...engine import hero_frame as HF
    from ...engine import herodef_frame as HDF
    from ...engine import prop_cook as PC
    from ...engine import text_patches as TP
    from ...engine.character_export import material_slots
    from .meshes import _mod_source
    hid, f = defn.id, defn.fields
    if hid in _RESERVED_IDS or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", hid):
        raise ContentError(f"hero {hid}: a hero id is letters and digits, not a reserved name")
    frame = f.get("frame")
    if not isinstance(frame, dict) or set(frame) - _SCRATCH_FIELDS:
        raise ContentError(f"hero {hid}: frame is a table of {', '.join(sorted(_SCRATCH_FIELDS))}")
    unknown = sorted(set(f) - {"frame", "name", "description", "memoirs"})
    if unknown:
        raise ContentError(f"hero {hid}: a hero written from scratch takes frame, name, "
                           f"description, memoirs (not yet {', '.join(unknown)})")
    rig = str(frame.get("rig") or "")
    mesh, material = str(frame.get("mesh") or ""), str(frame.get("material") or "")
    if not (rig and mesh and material):
        raise ContentError(f"hero {hid}: frame needs rig, mesh and material (shipped assets)")
    game = _game_dir()
    app = H.pristine_app_settings(game)
    if app is None:
        raise SchemaNotMined("ApplicationSettings.ot is not in the game install")
    aliases = {a.name: a for a in H.aliases(app)}
    if "Hero_Common" not in aliases:
        raise ContentError(f"hero {hid}: no Hero_Common alias in ApplicationSettings.ot")
    rig_def = next((n for n, a in aliases.items() if n == rig), None)
    rig_herodef = EP.corpus_read(_rel(HD.stem(rig.removeprefix("Hero_")) or ""))
    if rig_def is None or rig_herodef is None:
        raise ContentError(f"hero {hid}: rig {rig!r} is not a shipped hero (e.g. Hero_Kintaro)")
    rig_rec = HDF.decode(rig_herodef)

    written: list[Path] = []

    def put(decoded: str, blob: bytes) -> None:
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)

    def read(ref: str):
        return corpus.read(H.entity_rel(ref))

    scope = f"Hero_{hid}"
    folder = f"Heroes\\{_SCRATCH_FOLDER}"
    main_ref, fx_ref = f"{folder}\\{scope}.entity.ot", f"{folder}\\{scope}_FX.entity.ot"
    skin_ref, lowres_ref = (f"{folder}\\{scope}_Default.entity.ot",
                            f"{folder}\\{scope}_Default_LowRes.entity.ot")
    bank = _SCRATCH_BANK
    pairs: dict[str, str] = {}

    def key(name: str, text) -> str:
        k = f"{scope}_{name}"
        pairs[k] = str(text)
        return k

    art: list[str] = []

    def ui_art(value, sibling: str, name: str, what: str) -> tuple[str, str] | None:
        """``value`` as a UI picture. A PNG in the mod (``art/x.png``) is cooked
        as one of the hero's own, ``<scope>_<name>.png`` in ``sibling``'s
        folder (a new cooked path needs a folder the game ships), and listed
        in its preload caches (an icon or portrait loads through the herodef's
        cache). A ``\\``-separated value names a picture the game ships."""
        if not value:
            return None
        v = str(value)
        if "\\" in v:
            return ("Ui", v)
        if not v.lower().endswith(".png"):
            raise ContentError(f"hero {hid}: {what} is a .png in the mod or a shipped "
                               f"UI path, got {v!r}")
        new = f"{sibling.rsplit(chr(92), 1)[0]}\\{scope}_{re.sub(r'[^A-Za-z0-9]+', '_', name)}.png"
        if new not in cooked_ui:
            put(f"Ui/{new.replace(chr(92), '/')}.Texture.dxt",
                PC.cook_texture(_mod_source(out_dir, v, hid, what).read_bytes()))
            art.append(f"Ui|{new}|oCTexture")
            cooked_ui.add(new)
        return ("Ui", new)
    cooked_ui: set[str] = set()

    def own_art(value, rig_ref: tuple[str, str], name: str, what: str) -> tuple[str, str]:
        """Its own picture when the frame gives one, else the rig's."""
        return ui_art(value, rig_ref[1] or _DEFAULT_ICON, name, what) or rig_ref

    rr = rig_rec.root
    portrait = own_art(frame.get("portrait"), rr["portrait"], "Portrait", "frame.portrait")

    # Its own effects (engine/vfx_writer.py): each written from its layers,
    # no shipped effect copied; `fx:<name>` anywhere in the frame (a hit's fx,
    # a projectile's trail / impact, a talent action's hit) names one.
    own_fx: dict[str, str] = {}
    own_fx_assets: set[str] = set()       # its own effect files, materials, textures
    shipped_fx: set[str] = set()          # shipped materials its layers draw with
    effects = frame.get("effects") or {}
    if effects:
        from ...engine import vfx_writer as VW
        if not isinstance(effects, dict):
            raise ContentError(f"hero {hid}: effects is a table of named effects")
        for ename, espec in sorted(effects.items()):
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", str(ename)) or not isinstance(espec, dict):
                raise ContentError(f"hero {hid}: effects.{ename}: a letters-and-digits name "
                                   "with layers = [...]")
            layers = []
            for n, layer in enumerate(espec.get("layers") or [], 1):
                if not isinstance(layer, dict):
                    raise ContentError(f"hero {hid}: effects.{ename}.layers[{n}] is a table")
                layer = dict(layer)
                tex = layer.pop("texture", None)
                soft = bool(layer.pop("soft", False))
                if tex:
                    donor_mat, donor_tex = _FX_MATERIAL[soft]
                    tag = f"{scope}_{ename}_{n}"
                    tref = f"Textures\\Shapes\\{tag}.png"
                    put(_fx_cooked(tref, PC.TEXTURE_SUFFIX), PC.cook_texture(_mod_source(
                        out_dir, tex, hid, f"effects.{ename}.layers[{n}].texture").read_bytes()))
                    mref = f"Materials\\{tag}.mat.ot"
                    put(_fx_cooked(mref, ".Material.gen"), PC.clone_material(
                        corpus.read(_fx_cooked(donor_mat, ".Material.gen")), {donor_tex: tref}))
                    art += [f"FX|{tref}|oCTexture", f"FX|{mref}|oCMaterial"]
                    own_fx_assets.update((tref, mref))
                    layer["material"] = mref
                elif not layer.get("material"):
                    raise ContentError(f"hero {hid}: effects.{ename}.layers[{n}] needs a "
                                       "texture (a .png in the mod) or a shipped material")
                else:
                    shipped_fx.add(str(layer["material"]))
                layer.setdefault("name", f"{ename} {n}")
                layers.append(layer)
            ref = f"{_FX_FOLDER}\\{scope}_{ename}.vfx.ot"
            try:
                blob = VW.build(layers, length=espec.get("length"))
            except VW.EffectError as e:
                raise ContentError(f"hero {hid}: effects.{ename}: {e}") from e
            put(_fx_cooked(ref, ".ScheduledVfxSettings.gen"), blob)
            art.append(f"FX|{ref}|oCScheduledVfxSettings")
            own_fx[str(ename)] = ref
            own_fx_assets.add(ref)

    def with_own_fx(v, where: str = "frame"):
        """Every ``fx:<name>`` string in ``v`` made that effect's path."""
        if isinstance(v, str) and v.startswith(_FX_PREFIX):
            name = v[len(_FX_PREFIX):]
            if name not in own_fx:
                raise ContentError(f"hero {hid}: {where}: no effects.{name}")
            return own_fx[name]
        if isinstance(v, dict):
            return {k: with_own_fx(x, f"{where}.{k}") for k, x in v.items()}
        if isinstance(v, list):
            return [with_own_fx(x, f"{where}[{i}]") for i, x in enumerate(v)]
        return v

    frame = with_own_fx({k: x for k, x in frame.items() if k != "effects"})

    # Its body material: the rig's, or a copy wearing the hero's own albedo.
    if frame.get("albedo"):
        slots = material_slots(material)
        if "ALB" not in slots:
            raise ContentError(f"hero {hid}: {material} has no albedo map")
        here = material.rsplit("\\Textures\\", 1)[0]
        tex = f"{here}\\Textures\\T_{scope}_ALB.tga"
        put(PC.art_cooked_path(tex), PC.cook_texture(
            _mod_source(out_dir, frame["albedo"], hid, "frame.albedo").read_bytes()))
        mat = f"{here}\\Textures\\M_{scope}.mat.ot"
        repoint, roots = {slots["ALB"]: tex}, {}
        if frame.get("model"):
            # Its own body has its own UV layout: the rig's normal, MRA and
            # glow maps were painted for the RIG's, and on these UVs they put
            # random bumps, shine and glow patches all over it (playtest
            # 2026-11-08: blotchy, hatched book portrait). The engine's
            # neutral ones instead, as Character_Grey.mat.ot uses them.
            donor_refs = PC._refs_doc("oCMaterial", corpus.read(PC.art_cooked_path(material)))[1][
                "asset_refs"]
            for suffix, (root, neutral) in _NEUTRAL_MAPS.items():
                old = next((r for r in donor_refs if r.upper().endswith(suffix)), None)
                if old is not None:
                    repoint[old], roots[old] = neutral, root
        put(PC.art_cooked_path(mat), PC.clone_material(
            corpus.read(PC.art_cooked_path(material)), repoint, roots))
        art += [f"3D|{tex}|oCTexture", f"3D|{mat}|oCMaterial"]
        body_mat = mat
    else:
        body_mat = material

    # Its own animations (step E): each a Blender clip on the rig's skeleton,
    # cooked by anim_cook onto a rig clip as template (bone order, tail
    # fields) into a NEW clip file of its own beside the rig's; the rig's
    # clips are untouched. `clip = "anim:<name>"` then names it.
    own_clips: dict[str, tuple[str, float]] = {}
    anims = frame.get("animations") or {}
    if anims:
        from ...engine import anim_cook as AC
        rig_dir = mesh.rsplit("\\", 1)[0] + "\\Animations"
        for name, spec in sorted(anims.items()):
            spec = spec if isinstance(spec, dict) else {"source": spec}
            if not spec.get("source") or not spec.get("template"):
                raise ContentError(f"hero {hid}: animations.{name} needs source (a .glb) "
                                   "and template (a rig clip, e.g. Kintaro_FightingIdle_Loop)")
            tpl_ref = f"{rig_dir}\\{spec['template']}.fbx"
            tpl_raw = corpus.read(f"3D/{tpl_ref.replace(chr(92), '/')}.Animation.gen")
            if tpl_raw is None:
                raise ContentError(f"hero {hid}: animations.{name}: the rig has no clip "
                                   f"{spec['template']!r}")
            tcf = cooked.parse(tpl_raw)
            glb = _mod_source(out_dir, spec["source"], hid, f"animations.{name}").read_bytes()
            try:
                payload, _notes = AC.cook(glb, b"".join(x.payload for x in tcf.sections),
                                          name=spec.get("clip"), strict=bool(spec.get("strict")))
            except AC.AnimCookError as e:
                raise ContentError(f"hero {hid}: animation {name}: {e}") from e
            head = len(tcf.sections[0].payload)
            tcf.sections[0] = cooked.Section(payload=payload[:head])
            tcf.sections[1] = cooked.Section(payload=payload[head:])
            ref = f"{rig_dir}\\{scope}_{name}.fbx"
            put(f"3D/{ref.replace(chr(92), '/')}.Animation.gen", cooked.emit(tcf))
            art.append(f"3D|{ref}|oCAnimation")
            from ...engine.cooked_schemas import animation as A
            own_clips[str(name)] = (ref, A.parse_payload(payload).duration)

    def own(fill: dict, what: str) -> dict:
        """``anim:<name>`` resolved to the hero's own clip (and its length)."""
        fill = dict(fill)
        clip = fill.get("clip")
        clips = clip if isinstance(clip, list) else [clip]
        out = []
        for c in clips:
            if isinstance(c, str) and c.startswith(_OWN_CLIP):
                n = c[len(_OWN_CLIP):]
                if n not in own_clips:
                    raise ContentError(f"hero {hid}: {what}: no animations.{n}")
                out.append(own_clips[n][0])
                if not isinstance(clip, list) and "duration" not in fill:
                    fill["duration"] = own_clips[n][1]
            else:
                out.append(c)
        if clip is not None:
            fill["clip"] = out if isinstance(clip, list) else out[0]
        if isinstance(fill.get("texture"), str):
            # A picture slot: a PNG in the mod, or a shipped UI path.
            fill["texture"] = ui_art(fill["texture"], _DEFAULT_ICON,
                                     what.rsplit(".", 1)[-1], f"{what}.texture")
        return fill

    # Its own body (step D): a glb with the rig's bones at proportions of its
    # own, cooked onto the rig's mesh as template, then its SKELETON rewritten
    # with the glb armature's rest pose (engine/skeleton_codec.py), so mesh,
    # skeleton and the clips retargeted onto that armature agree.
    if frame.get("model"):
        from ...engine import skeleton_codec as SK
        glb = _mod_source(out_dir, frame["model"], hid, "frame.model").read_bytes()
        template = corpus.read(PC.art_cooked_path(mesh))
        if template is None:
            raise ContentError(f"hero {hid}: the rig mesh {mesh!r} is not in the game files")
        try:
            geo = PC.cook_model(glb, template, transform={"skin": "gltf", "submeshes": "map"})
            skel = SK.decode(geo)
            rest = SK.locals_from_glb(glb)
            # A whole branch may be left out (Kintaro's DEF.Bear.* rig on a
            # hero with no bear): it keeps the rig's rest pose and drives
            # nothing. So a missing bone is refused only when it is the root
            # or some bone below it IS present (a hole inside the skeleton) --
            # a model rigged to some other skeleton (mixamo names) misses the
            # root itself.
            names = [b.name for b in skel.bones]
            present = [b.name in rest for b in skel.bones]

            def gap(i: int) -> bool:
                if present[i]:
                    return False
                p = skel.bones[i].parent
                if p < 0:
                    return True                     # the root must be there
                return any(present[j] and _descends(skel, j, i)
                           for j in range(len(names)))
            missing = [names[i] for i in range(len(names)) if gap(i)]
            if missing:
                raise ContentError(f"hero {hid}: frame.model has no bone(s) "
                                   f"{', '.join(missing[:6])} of the rig")
            geo = SK.encode(geo, SK.with_rest(skel, rest))
        except SK.SkeletonError as e:
            raise ContentError(f"hero {hid}: frame.model: {e}") from e
        own_mesh = f"{mesh.rsplit(chr(92), 1)[0]}\\{scope}_GEO.fbx"
        put(PC.art_cooked_path(own_mesh), geo)
        art.append(f"3D|{own_mesh}|oCGeometry")
        mesh = own_mesh

    # Its talents: its own controllers (rows of its own herodef), and the 6
    # ultimate rows on Hero_Common's own controllers, as every hero's are.
    talents, rows = [], []
    effects: dict[str, dict] = {}
    hooks: list[dict] = []            # kit timelines (engine/hero_kit.py) on its own states
    for n, t in enumerate(frame.get("talents") or []):
        if not isinstance(t, dict) or not t.get("name"):
            raise ContentError(f"hero {hid}: frame.talents[{n}] is {{ name, title, description }}")
        name = str(t["name"])
        word = re.sub(r"\W+", "_", name)
        g = HF.guid(scope, f"talent:{name}")
        fx_spec = {k: t[k] for k in ("add_stats", "actions") if t.get(k)}
        if fx_spec:
            effects[name] = fx_spec
        for na, act in enumerate(t.get("actions") or [], 1):
            if isinstance(act, dict) and act.get("steps"):
                # A talent action's kit timeline, on its own action state.
                from ...engine import talent_add_stat as TA
                hooks.append({"when": TA.action_state_name(name, na), "steps": act["steps"]})
        talents.append((name, g, {
            "bank": bank, "name_key": key(f"Skill_{word}_Name", t.get("title", name)),
            "desc_key": key(f"Skill_{word}_Desc", t.get("description", "")),
            "icon": ui_art(t.get("icon") or _DEFAULT_ICON, _DEFAULT_ICON, f"Skill_{word}",
                           f"frame.talents[{n}].icon")[1],
            # starting-pick cards (pool 0); the rest are dealt at level-up
            "pool": HF.POOL_STARTER if t.get("starter") else HF.POOL_LEVEL_UP}))
        rows.append(HDF.Talent(f"Skill Controller {name}", g))
    hc = HF.common(read)
    for c in hc.graph().components:
        if c.name.startswith("Skill Controller Ultimate"):
            rows.append(HDF.Talent(c.name, c.guid, ultimate=True))
    # Its ultimate cards, on Hero_Common's own six controllers (left alone they
    # are blank cards); an upgrade's effects hang off a state of its own.
    ultimates = []
    for uname, u in (frame.get("ultimates") or {}).items():
        if not isinstance(u, dict):
            raise ContentError(f"hero {hid}: ultimates.{uname} is {{ title, description, icon }}")
        word = re.sub(r"\W+", "_", str(uname))
        ultimates.append((str(uname), {
            "bank": bank, "name_key": key(f"Skill_{word}_Name", u.get("title", uname)),
            "desc_key": key(f"Skill_{word}_Desc", u.get("description", "")),
            "icon": (ui_art(u.get("icon"), _DEFAULT_ICON, f"Skill_{word}",
                            f"frame.ultimates.{uname}.icon") or ("", ""))[1]}))
        fx_spec = {k: u[k] for k in ("add_stats", "actions") if u.get(k)}
        if fx_spec:
            effects[str(uname)] = fx_spec
    # Its hand weapon: a shipped hero's, hung on its own body's weapon bone.
    weapon = None
    wspec = frame.get("weapon")
    if wspec is not None:
        if not isinstance(wspec, dict) or not wspec.get("from") or \
                set(wspec) - {"from", "mesh", "material"}:
            raise ContentError(f"hero {hid}: weapon is {{ from = <shipped hero>, mesh = <fbx>, "
                               "material = <mat.ot> }")
        from ...engine.entity_graph_edit import EntityFile as _WEF
        wref = f"Heroes\\Hero_{wspec['from']}\\Hero_{wspec['from']}.entity.ot"
        wraw = read(wref)
        if wraw is None:
            raise ContentError(f"hero {hid}: weapon.from = {wspec['from']!r} is not a shipped hero")
        weapon = (_WEF(wraw, f"Hero_{wspec['from']}"), str(wspec.get("mesh") or ""),
                  str(wspec.get("material") or ""))

    abilities = []
    for slot, raw in (frame.get("abilities") or {}).items():
        raw = dict(raw)
        word = str(slot).title()
        if raw.get("steps"):
            hooks.append({"when": f"State {word} Ability", "steps": raw["steps"]})
        raw.pop("steps", None)
        card = {}
        if "name" in raw:
            card["name_key"] = key(f"Ability_{word}_Name", raw.pop("name"))
        if "description" in raw:
            card["desc_key"] = key(f"Ability_{word}_Desc", raw.pop("description"))
        try:
            raw = own(raw, f"frame.abilities.{slot}")
            abilities.append(HA.Ability.parse(str(slot), {**raw, "bank": bank, **card}))
        except HA.AbilityError as e:
            raise ContentError(f"hero {hid}: {e}") from e

    try:
        slots = HF.rig_slots(read, rig)
        for slot, fill in (frame.get("slots") or {}).items():
            slots[str(slot)] = own(dict(fill), f"frame.slots.{slot}")
        # The HUD's portrait and ability banner: Hero_Common leaves the
        # portrait blank and shows RED's banner; every shipped hero fills both.
        slots.setdefault("Portrait Picture", {"texture": portrait})
        if frame.get("banner"):
            slots.setdefault("Abilities Banner Picture", {"texture": ui_art(
                frame["banner"], "Heroes\\Red\\HUD_Banner_RED.png", "HUD_Banner",
                "frame.banner")})
        main, fx, skin_values = HF.build_hero(
            read, scope=scope, fx_ref=fx_ref, common_alias=aliases["Hero_Common"].guid,
            mesh=mesh, material=body_mat, slots=slots, talents=talents,
            abilities=abilities, effects=effects, seed=f"{mod_id}:{hid}", indicators=False,
            ultimates=ultimates, weapon=weapon)
    except (HF.FrameError, HA.AbilityError) as e:
        raise ContentError(f"hero {hid}: {e}") from e

    # Projectiles of its own (engine/attack_build.py): the engine's generic
    # hero projectile wearing the mod's mesh and maps, its own lifetime, trail
    # and impact; fired by `steps` as fire = "own:<id>", each shot tuned there
    # (speed, damage, size, explode, knockback, root, burn ...).
    own_projectiles: dict[str, bytes] = {}
    own_ref: dict[str, str] = {}
    projectiles = frame.get("projectiles") or {}
    if projectiles:
        from ...engine import attack_build as AB
        here = mesh.rsplit("\\", 1)[0]

        def p_mesh(donor_fbx: str, model: str, tag: str, what: str, transform) -> str:
            geo_ref = f"{here}\\{tag}_GEO.fbx"
            # a thrown prop: one rigid piece, never weights borrowed from the
            # template's (they tear a shape that does not overlap it)
            put(PC.art_cooked_path(geo_ref), PC.cook_model(
                _mod_source(out_dir, model, hid, what).read_bytes(),
                corpus.read(PC.art_cooked_path(donor_fbx)),
                transform={**(transform or {}), "skin": "rigid"}))
            art.append(f"3D|{geo_ref}|oCGeometry")
            return geo_ref

        def p_material(donor: str, maps: dict, tag: str, what: str) -> str:
            mslots = material_slots(donor)
            repoint = {}
            for fld, slot in _TEXTURE_FIELDS.items():
                if not maps.get(fld):
                    continue
                if slot not in mslots:
                    raise ContentError(f"hero {hid}: {what}'s material has no {slot} map")
                tref = f"{here}\\Textures\\T_{tag}_{slot}.tga"
                put(PC.art_cooked_path(tref), PC.cook_texture(
                    _mod_source(out_dir, maps[fld], hid, f"{what}.{fld}").read_bytes()))
                repoint[mslots[slot]] = tref
                art.append(f"3D|{tref}|oCTexture")
            mref = f"{here}\\Textures\\M_{tag}.mat.ot"
            put(PC.art_cooked_path(mref),
                PC.clone_material(corpus.read(PC.art_cooked_path(donor)), repoint))
            art.append(f"3D|{mref}|oCMaterial")
            return mref

        from ...engine import projectile_frame as PF
        for pid, spec in sorted(projectiles.items()):
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", str(pid)) or not isinstance(spec, dict) \
                    or set(spec) - PF.FIELDS:
                raise ContentError(f"hero {hid}: projectiles.{pid}: a letters-and-digits id "
                                   f"with {', '.join(sorted(PF.FIELDS))}")
            if not spec.get("model"):
                raise ContentError(f"hero {hid}: projectiles.{pid} needs a `model` (its mesh)")
            stem, tag, what = f"{scope}_{pid}", f"{hid}_{pid}", f"projectiles.{pid}"
            ref = f"{folder}\\{stem}.entity.ot"
            # Written from data on the shared hero projectile (engine/
            # projectile_frame.py): no shipped projectile is copied. The dagger
            # mesh and material lend only their format (vertex layout, shader).
            p_geo = p_mesh(AB.TEMPLATE_MESH, spec["model"], tag, f"{what}.model",
                           {"fit": "none", "scale": float(spec.get("scale", 1.0))})
            maps = {k: spec[k] for k in ("albedo", "mra", "normal") if spec.get(k)}
            p_mat = p_material(AB.TEMPLATE_MAT, maps, tag, what) if maps else ""
            try:
                own_projectiles[ref] = PF.build(
                    read, stem=stem, mesh=p_geo, material=p_mat,
                    lifetime=float(spec.get("lifetime", 1.0)),
                    trail=str(spec.get("trail") or ""), impact=str(spec.get("impact") or ""),
                    pierce=bool(spec.get("pierce", True)),
                    size=float(spec.get("size", PF.SIZE)),
                    pitch=math.radians(float(spec["pitch"])) if "pitch" in spec else PF.PITCH)
            except PF.ProjectileError as e:
                raise ContentError(f"hero {hid}: {e}") from e
            own_ref[str(pid)] = ref

    def own_fire(steps):
        """``fire = "own:<id>"`` -> that projectile's entity."""
        out = []
        for st in steps or []:
            st = dict(st)
            if isinstance(st.get("fire"), str) and st["fire"].startswith("own:"):
                pid = st["fire"][4:]
                if pid not in own_ref:
                    raise ContentError(f"hero {hid}: fire = {st['fire']!r}: no projectiles.{pid}")
                st["fire"] = own_ref[pid]
            if st.get("steps"):
                st["steps"] = own_fire(st["steps"])
            out.append(st)
        return out
    hooks = [{**h, "steps": own_fire(h["steps"])} for h in hooks]

    # Kit timelines (projectiles, hit areas placed ahead, heals, summons): the
    # hero builder's kit, given donors of its own, run on its own states.
    kit_copies: list = []
    kit_resources: set[str] = set()
    if hooks:
        from ...engine import ability_edit as AE
        from ...engine import hero_kit as HK
        def shipped(ref: str):
            return own_projectiles.get(ref) or HK.reader(kit_copies)(ref)
        try:
            main = AE.apply({scope: main}, HF.KIT_DONORS, main=scope,
                            seed=f"{mod_id}:{hid}:kit-donors", read=shipped).files[scope]
            steps = HK.expand({"talents": hooks}, main, scope, hid=hid, copies=kit_copies,
                              own=own_projectiles)
            res = AE.apply({scope: main}, steps, main=scope, seed=f"{mod_id}:{hid}:kit",
                           read=shipped)
        except (HK.KitError, AE.AbilityEditError) as e:
            raise ContentError(f"hero {hid}: {e}") from e
        main = res.files[scope]
        kit_resources = set(res.resources)
        for w in res.warnings:
            print(f"warning: hero {hid}: {w}", file=sys.stderr)
    # Range discs last (hero_ability.add_indicator says why).
    if any(ab.indicator for ab in abilities):
        from ...engine.entity_graph_edit import EntityFile as _EF
        ief = _EF(main, scope)
        try:
            for ab in abilities:
                HA.add_indicator(ief, ab, seed=f"{mod_id}:{hid}")
        except HA.AbilityError as e:
            raise ContentError(f"hero {hid}: {e}") from e
        main = ief.to_bytes()
    _no_effect([main, fx], put, art)
    from ...engine import vfx_writer as _VW
    own_fx_assets.add(_VW.NO_EFFECT)
    alias = H.alias_guid(mod_id, hid)
    entities = {main_ref: main, fx_ref: fx}
    for ref, blob in own_projectiles.items():
        put(H.entity_rel(ref), PC.restamp_entity_guids(blob, H.entity_rel(ref)))
        art.append(f"EntitySettings|{ref}|oCEntitySettingsResource")
    for c in kit_copies:
        if c.shipped:
            continue
        try:
            blob = c.data if c.data is not None and not c.reads else \
                HK.build_copy(c, main, main_ref)
        except HK.KitError as e:
            raise ContentError(f"hero {hid}: {e}") from e
        if c.data is None:
            blob = PC.restamp_entity_guids(blob, H.entity_rel(c.ref))
        put(H.entity_rel(c.ref), blob)
        art.append(f"EntitySettings|{c.ref}|oCEntitySettingsResource")
    for ref in (skin_ref, lowres_ref):
        entities[ref] = HF.skin_frame(alias, HF.guid(scope, ref), skin_values,
                                      seed=f"{mod_id}:{hid}:{ref}")

    # Its roster record, every value its own; the rig lends only UI art.
    rr = rig_rec.root
    pages = []
    rig_pages = [d for c, d in rig_rec.objects if c == HDF.STORY]
    for n, m in enumerate(f.get("memoirs") or [], 1):
        if not isinstance(m, dict):
            raise ContentError(f"hero {hid}: memoirs[{n}] is {{ title, text }}")
        art_page = rig_pages[(n - 1) % len(rig_pages)] if rig_pages else None
        pages.append(HDF.Page(
            HDF.Text.of(bank, key(f"Memoir{n}_Title", m.get("title", ""))),
            HDF.Text.of(bank, key(f"Memoir{n}_Desc", m.get("text", ""))),
            art_page["footer"] if art_page else ("", ""),
            art_page["footer_selected"] if art_page else ("", ""),
            art_page["corner"] if art_page else ("", "")))
    rig_skin = next((d for c, d in rig_rec.objects if c == HDF.SKIN), None)
    # Its UI art: each picture its own when the frame gives one (a PNG in the
    # mod), else the rig's.
    book_spec = frame.get("book")
    if book_spec is not None and not isinstance(book_spec, str | dict):
        raise ContentError(f"hero {hid}: frame.book is a .png or "
                           f"{{ {', '.join(_BOOK_STATES)} }}")
    book = tuple(
        own_art(book_spec.get(s) if isinstance(book_spec, dict) else book_spec,
                rr[f"book_{s}"], f"Book_{s.title()}", f"frame.book.{s}")
        for s in _BOOK_STATES)
    codex = list(rr["codex"])
    if frame.get("codex"):
        pics = frame["codex"]
        if not isinstance(pics, list) or not pics:
            raise ContentError(f"hero {hid}: frame.codex is a list of .png")
        # The book has one slot per rig codex picture: fill each, cycling.
        codex = [own_art(pics[i % len(pics)], codex[i], f"Codex_{i % len(pics) + 1}",
                         f"frame.codex[{i % len(pics)}]") for i in range(len(codex))]
    record = HDF.Record(
        hid=hid, sort=int(frame.get("sort", _SCRATCH_SORT)),
        name=HDF.Text.of(bank, key("Name", f.get("name") or hid)),
        desc=HDF.Text.of(bank, key("Desc", f.get("description") or "")),
        portrait=portrait, book=book,
        new_hero=own_art(frame.get("new_hero"), rr["new_hero"], "NewHero", "frame.new_hero"),
        codex=codex, talents=rows, pages=pages,
        skins=[HDF.Skin(skin_ref, own_art(frame.get("skin_icon"),
                                          rig_skin["icon"] if rig_skin else ("", ""),
                                          "Skin_Default", "frame.skin_icon"))],
        lowres=lowres_ref)
    herodef = HDF.build(record, rig_herodef)

    # Its text: appended to the bank; every reference re-pointed at its row.
    bank_path = _install_bank(game, bank)
    rows_of = TP.appended_rows(bank_path, pairs)
    dec = f"Text/{bank}.LocalText.gen"
    for tok, blob in TP.append_bank_keys(bank_path, pairs).items():
        put(dec if tok == "__base__" else dec + tok, blob)
    for ref, blob in entities.items():
        put(H.entity_rel(ref), TP.repoint_text_rows(blob, bank, rows_of))
    put(_rel(hid), TP.repoint_text_rows(herodef, bank, rows_of))

    # Its alias: what its skins inherit it through.
    put(H.APP_SETTINGS_DECODED, H.add_alias(app, H.Alias(alias, scope, main_ref)).encode(
        "utf-8", errors="surrogateescape"))

    # Its preload lists: its own files, and the closure of every shipped asset
    # its files name (the rig's mesh and clips, the shared hero base, UI art),
    # taken from the game's own caches.
    own = {main_ref, fx_ref, skin_ref, lowres_ref, *own_projectiles} | \
        {c.ref for c in kit_copies if not c.shipped}
    # its own projectiles preload the shared hero projectile they are written
    # on (and what it preloads) and their trail and impact effects
    from ...engine import projectile_frame as _PF
    targets = {*(kit_resources - own), *(c.source for c in kit_copies if not c.shipped),
               *([_PF.MODEL, _PF.BASE] if own_projectiles else []),
               *(str(sp.get(k) or "") for sp in projectiles.values() for k in ("trail", "impact")
                 if sp.get(k)),
               "Heroes\\Hero_Common\\Hero_Common.entity.ot",
               "Heroes\\Hero_Common\\Hero_Common_Update5.entity.ot",
               "Character_Common\\Character_Common.entity.ot"}
    for blob in [*entities.values(), herodef]:
        for m in re.finditer(rb"[ -~]+?\.(?:fbx|png|mat\.ot|entity\.ot|vfx\.ot)", blob):
            t = m.group(0).decode()
            if t not in own and not t.startswith(("[", "Definitions")) and \
                    f"\\T_{scope}_" not in t and f"\\M_{scope}" not in t and \
                    f"\\{scope}_" not in t:      # its own clips: listed as art
                targets.add(t)
    # its own effects are listed as art; the shipped materials they draw with
    # preload what the game's caches list for them
    targets = (targets - own_fx_assets) | shipped_fx
    lines = set(_borrow_closure(sorted(targets), out_dir, hid)) | set(art)
    lines |= {f"EntitySettings|{r}|oCEntitySettingsResource" for r in own}
    lines.add(_self_line(hid))
    put(RC.cache_path_for(_rel(hid)), RC.render(sorted(lines)))
    for ref in (skin_ref, lowres_ref):
        put(RC.cache_path_for(H.entity_rel(ref)), RC.render(sorted(lines - {_self_line(hid)})))
    return written


def _frame_family(frame: dict, b, R, H, app: str, herodef: bytes, hero_alias: bytes,
                  hid: str, mod_id: str, swaps: dict, corpus,
                  bank_pairs: dict[str, str]) -> dict[str, bytes]:
    """``{cooked rel: bytes}`` of the from-scratch hero's own files: main, FX,
    and every skin of the base's (all wearing the hero's material). The
    talent controllers carry the base rows' GUIDs, so the herodef's rows reach
    them through the family mapping the pipeline applies to every file."""
    import re

    from ...engine import entity_components as EC
    from ...engine import entity_graph as EG
    from ...engine import hero_frame as HF

    def read(ref: str):
        return corpus.read(H.entity_rel(ref))

    main_ref = next(r for r in b.family if r.rsplit("\\", 1)[-1] == f"{b.stem}.entity.ot")
    main_raw = read(main_ref)
    fx_base = EC.parents(main_raw)[0]
    common_alias = next((a.guid for a in H.aliases(app) if a.name == "Hero_Common"), None)
    if common_alias is None:
        raise ContentError(f"hero {hid}: no Hero_Common alias in ApplicationSettings.ot")
    rig = str(frame.get("rig") or b.folder)
    mesh = str(frame.get("mesh") or b.body_fbx or "")
    material = str(frame.get("material") or b.body_mat or "")
    if not mesh or not material:
        raise ContentError(f"hero {hid}: frame needs mesh and material (the base names none)")
    material = swaps.get(material, material)       # a `materials` repaint applies
    try:
        slots = HF.rig_slots(read, rig)
        for slot, fill in (frame.get("slots") or {}).items():
            slots[str(slot)] = dict(fill)
        # Talent rows: the base's controllers in herodef order, each card read
        # through the hero's own text keys (the `skills` relabels) and icon.
        keys = _skill_keys(b, H, corpus)
        ctls = {c.guid: c for ref in b.family for c in EG.parse(read(ref) or b"").components
                if c.name.startswith("Skill Controller ")}
        talents = []
        for g, c in sorted(((g, c) for g, c in ctls.items() if g in herodef),
                           key=lambda gc: herodef.find(gc[0])):
            talent = c.name.removeprefix("Skill Controller ")
            bank, name_key, desc_key = keys.get(talent, (b.text_bank, "", ""))
            icon = re.search(rb"[ -~]+?\.png", c.body)
            talents.append((talent, g, {
                "bank": bank, "name_key": swaps.get(name_key, name_key),
                "desc_key": swaps.get(desc_key, desc_key),
                "icon": icon.group(0).decode() if icon else ""}))
        # Buttons written from data (engine/hero_ability.py); their card text
        # appended to the base's bank as the hero's own keys.
        from ...engine import hero_ability as HA
        abilities = []
        for slot, raw in (frame.get("abilities") or {}).items():
            raw = dict(raw)
            card = {k: raw.pop(k) for k in ("name", "description") if k in raw}
            word = str(slot).title()
            keys = {"name": f"Hero_{hid}_Ability_{word}_Name",
                    "description": f"Hero_{hid}_Ability_{word}_Desc"}
            for k, text in card.items():
                bank_pairs[keys[k]] = str(text)
            abilities.append(HA.Ability.parse(str(slot), {
                **raw, "bank": b.text_bank,
                **({"name_key": keys["name"]} if "name" in card else {}),
                **({"desc_key": keys["description"]} if "description" in card else {})}))
        main, fx, skin = HF.build_hero(
            read, scope=f"Hero_{hid}", fx_ref=R.entity_ref(fx_base), common_alias=common_alias,
            mesh=mesh, material=material, slots=slots, talents=talents,
            abilities=abilities, seed=f"{mod_id}:{hid}")
    except HA.AbilityError as e:
        raise ContentError(f"hero {hid}: {e}") from e
    except HF.FrameError as e:
        raise ContentError(f"hero {hid}: frame: {e}") from e
    out = {H.entity_rel(R.entity_ref(main_ref)): main, H.entity_rel(R.entity_ref(fx_base)): fx}
    for ref in b.family:
        raw = read(ref) or b""
        if ref not in (main_ref, fx_base) and b.alias.guid in raw:
            # A skin of the base (it inherits the hero by alias): the hero's own.
            name = R.entity_ref(ref)
            out[H.entity_rel(name)] = HF.skin_frame(hero_alias, HF.guid(f"Hero_{hid}", name),
                                                    skin, seed=f"{mod_id}:{hid}:{name}")
    return out


def _borrow_closure(targets: list[str], out_dir: Path, hid: str) -> list[str]:
    """Cache lines for ``targets`` and everything they reach, taken from the
    shipped caches that already preload them (the way `poi` swaps do it)."""
    if not targets:
        return []
    from ...engine import corpus
    from .poi import _reachable
    lines: list[str] = []
    found: set[str] = set()
    # Definitions first; then entities, whose caches are the only ones naming
    # some art (a skin's full-resolution material: a herodef lists _LowRes).
    import itertools
    for def_rel in itertools.chain(corpus.rels("Definitions/", ".gen"),
                                   corpus.rels("EntitySettings/", ".gen")):
        raw = corpus.read(RC.cache_path_for(def_rel))
        if raw is None:
            continue
        cache = RC.parse(raw)
        refs = {ln.split("|")[1] for ln in cache if ln.count("|") == 2}
        hit = [t for t in targets if t in refs and t not in found]
        if hit:
            found.update(hit)
            lines.extend(cache)
        if found == set(targets):
            break
    missing = sorted(set(targets) - found)
    if missing:
        raise ContentError(f"{hid}: no shipped preload cache lists "
                           f"{', '.join(map(repr, missing))}, so it cannot be referenced "
                           f"safely (a resource the caches miss is a crash at load)")
    seen, extra = _reachable(targets, lines, out_dir)
    return sorted({ln for ln in lines if ln.count("|") == 2 and ln.split("|")[1] in seen}
                  | set(extra))


def _table(v, what: str, hid: str) -> dict:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ContentError(f"hero {hid}: {what!r} is a table (name = file or {{...}})")
    return v


def _shrunk_glb(glb: bytes, factor: float = 1e-3) -> bytes:
    """``glb`` made invisible: every vertex bound rigidly to ONE joint (the
    one carrying the most weight in the mesh, so it is in the mesh's own bone
    palette; the root often is not) and shrunk by ``factor`` onto that joint's
    rest position. The skeleton is untouched, so every bone the game attaches to (a
    breath's origin at the head) still moves.

    Shrinking toward the model's origin alone is NOT enough on a skinned mesh
    (in game 2026-09-26: the dragon still showed): each vertex follows its own
    bone, so once the bones move the collapsed points scatter back out along
    them. One bone for every vertex keeps it a speck in any pose. 1e-3, not
    0: the cooker drops zero-area triangles; at 1e-4 it dropped 168."""
    import struct

    from ...engine.gltf import read_glb, write_glb
    gltf, raw_bin = read_glb(glb)
    binary = bytearray(raw_bin)

    def view_of(acc: dict, size: int) -> tuple[int, int]:
        v = gltf["bufferViews"][acc["bufferView"]]
        return v.get("byteOffset", 0) + acc.get("byteOffset", 0), v.get("byteStride", size)

    def rest_position(skin: dict, joint: int) -> tuple[float, float, float]:
        """A joint's rest position: the translation of its inverse bind matrix
        inverted (column-major 4x4, affine)."""
        acc = gltf["accessors"][skin["inverseBindMatrices"]]
        at, stride = view_of(acc, 64)
        m = struct.unpack_from("<16f", binary, at + joint * stride)
        r = [[m[0], m[4], m[8]], [m[1], m[5], m[9]], [m[2], m[6], m[10]]]
        t = (m[12], m[13], m[14])
        det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
               - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
               + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
        if abs(det) < 1e-12:
            return (0.0, 0.0, 0.0)
        inv = [[(r[(j + 1) % 3][(i + 1) % 3] * r[(j + 2) % 3][(i + 2) % 3]
                 - r[(j + 1) % 3][(i + 2) % 3] * r[(j + 2) % 3][(i + 1) % 3]) / det
                for j in range(3)] for i in range(3)]
        return tuple(-sum(inv[i][k] * t[k] for k in range(3)) for i in range(3))

    def skin_views(attrs: dict):
        ja = gltf["accessors"][attrs["JOINTS_0"]]
        wa = gltf["accessors"][attrs["WEIGHTS_0"]]
        jfmt = {5121: "<4B", 5123: "<4H"}[ja["componentType"]]
        jat, jstride = view_of(ja, struct.calcsize(jfmt))
        wat, wstride = view_of(wa, 16)
        return ja["count"], jfmt, jat, jstride, wat, wstride

    skin = (gltf.get("skins") or [None])[0]
    prims = [p for m in gltf.get("meshes", []) for p in m.get("primitives", [])]
    anchor, origin = 0, (0.0, 0.0, 0.0)
    if skin and "inverseBindMatrices" in skin:
        load: dict[int, float] = {}
        for prim in prims:
            if "JOINTS_0" in prim["attributes"] and "WEIGHTS_0" in prim["attributes"]:
                count, jfmt, jat, jstride, wat, wstride = skin_views(prim["attributes"])
                for i in range(count):
                    js = struct.unpack_from(jfmt, binary, jat + i * jstride)
                    ws = struct.unpack_from("<4f", binary, wat + i * wstride)
                    for jj, ww in zip(js, ws, strict=True):
                        load[jj] = load.get(jj, 0.0) + ww
        if load:
            anchor = max(load, key=load.get)
        origin = rest_position(skin, anchor)
    for prim in prims:
        attrs = prim["attributes"]
        acc = gltf["accessors"][attrs["POSITION"]]
        at, stride = view_of(acc, 12)
        lo, hi = [1e30] * 3, [-1e30] * 3
        for i in range(acc["count"]):
            v = struct.unpack_from("<3f", binary, at + i * stride)
            w = [origin[k] + v[k] * factor for k in range(3)]
            struct.pack_into("<3f", binary, at + i * stride, *w)
            lo = [min(lo[k], w[k]) for k in range(3)]
            hi = [max(hi[k], w[k]) for k in range(3)]
        if acc["count"]:
            acc["min"], acc["max"] = lo, hi
        if skin and "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
            count, jfmt, jat, jstride, wat, wstride = skin_views(attrs)
            for i in range(count):
                struct.pack_into(jfmt, binary, jat + i * jstride, anchor, anchor, anchor, anchor)
                struct.pack_into("<4f", binary, wat + i * wstride, 1.0, 0.0, 0.0, 0.0)
    return write_glb(gltf, bytes(binary))


#: The placeholder colour: an effect still showing the base's look is pink.
PLACEHOLDER_TINT = (1.0, 0.0, 1.0)


def _tint(value, hid: str, what: str) -> tuple[float, float, float]:
    """``"#7ad0ff"`` or ``[0.48, 0.82, 1.0]`` -> an (r, g, b) in 0..1."""
    if isinstance(value, str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
        h = value.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if isinstance(value, (list, tuple)) and len(value) in (3, 4) and all(
            isinstance(x, (int, float)) and 0 <= x <= 1 for x in value[:3]):
        return tuple(float(x) for x in value[:3])
    raise ContentError(f"hero {hid}: {what}: tint is \"#RRGGBB\" or [r, g, b] in 0..1")


def _tinted_texture(cooked_raw: bytes, rgb, max_edge: int = 512) -> bytes | None:
    """A recoloured copy of a cooked texture: every pixel becomes ``rgb`` at
    its own brightness, alpha untouched, so an effect keeps its shapes (rings,
    sparks, masks) in the new colour. None when the format cannot be decoded."""
    from ...engine import cooked, icon_decode
    from ...engine import prop_cook as PC
    from ...engine.cooked_schemas.texture import TextureHandler
    try:
        sch = TextureHandler.parse_payload(cooked.parse(cooked_raw).sections[-1].payload)
        px = icon_decode.decode_to_rgba(sch.pixels, sch.width, sch.height, sch.format_name)
    except (ValueError, KeyError, IndexError):
        return None
    px, w, h = icon_decode.resize_to_max(px, sch.width, sch.height, max_edge)
    r, g, b = rgb
    out = bytearray(len(px))
    for i in range(0, len(px), 4):
        lum = max(px[i], px[i + 1], px[i + 2]) / 255
        out[i] = int(r * lum * 255)
        out[i + 1] = int(g * lum * 255)
        out[i + 2] = int(b * lum * 255)
        out[i + 3] = px[i + 3]
    return PC.cook_texture(icon_decode.rgba_to_png(bytes(out), w, h))


#: Colour classes inside an effect, by the verified layout of their section
#: (all 6859 in the shipped game, 2026-09-26): u32 class, u32, u8, f32 t0,
#: f32 t1, u32 n, n x {f32 time, f32 r, g, b, a}, then an optional u32 tail.
_RAMP_TAILS = {"oC3dParticleEffectorColorRampSettings": (4,),
               "oC3dTrailEffectorColorRampSettings": (0, 4),
               "oC3dBeamEffectorColorRampSetting": (0, 4)}
#: Material texture slots that hold COLOUR. Masks, noise that distorts, and
#: surface data (MRA, normals) are data a shader reads channel by channel: a
#: recolour would break shapes or lighting, so they are never touched.
_COLOUR_SLOTS = frozenset({"u_texture", "u_Texture_A", "u_Texture_B", "u_ALB", "u_EMI"})
#: Material colour uniforms: lstr name, u32 hash, f32 r, g, b, a, MARK_END.
_COLOUR_UNIFORMS = ("u_color", "u_color_a", "u_color_b", "u_fresnel_color")


def _texture_slots(mat_raw: bytes) -> dict[str, str]:
    """Texture path -> the uniform it is bound to (``u_Texture_Mask``...): a
    material lists ``<uniform>, <root>, <path>``."""
    from ...engine import entity_strings as ES
    ss = [t for _s, _o, t in ES.list_strings(mat_raw)]
    return {t: ss[i - 2] for i, t in enumerate(ss)
            if i >= 2 and t.lower().endswith((".png", ".tga"))}


def _recolour_uniforms(mat_raw: bytes, rgb) -> bytes:
    """Recolour a material's colour uniforms to ``rgb`` at their brightness,
    alpha kept. Only a uniform whose value is followed by the section end
    marker (a 4-float colour, as laid out in the shipped materials) is touched."""
    import struct
    out = bytearray(mat_raw)
    for name in _COLOUR_UNIFORMS:
        n = name.encode()
        tag = struct.pack("<I", len(n)) + n
        at = out.find(tag)
        while at != -1:
            v = at + len(tag) + 4
            if out[v + 16:v + 20] == b"\x22\x22\xbb\xaa":
                r0, g0, b0 = struct.unpack_from("<3f", out, v)
                m = max(r0, g0, b0)
                struct.pack_into("<3f", out, v, rgb[0] * m, rgb[1] * m, rgb[2] * m)
            at = out.find(tag, at + 1)
    return bytes(out)


#: A single colour: u32 class, u8, f32 r, g, b, a, u32 (25 bytes).
_COLOUR_CONST = "oC3dParticleEffectorColorConstantSettings"


def _recolour_effect(raw: bytes, rgb) -> tuple[bytes, int]:
    """Recolour an effect's own colour keys (particle, trail and beam colour
    ramps, constant colours) to ``rgb`` at each key's brightness. They are
    what makes fire orange whatever the texture: HDR multipliers (Beowulf's
    are up to ~4.0) on top of it. Alpha is kept. Section 0 is the file's
    class-index table and is never a colour. Returns the bytes and how many
    colour-class sections did not match the layout (left untouched)."""
    import struct

    from ...engine import cooked
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    ids = {names.index(n): n for n in (*_RAMP_TAILS, _COLOUR_CONST) if n in names}
    skipped = 0

    def paint(p: bytearray, at: int) -> None:
        r0, g0, b0 = struct.unpack_from("<3f", p, at)
        m = max(r0, g0, b0)
        struct.pack_into("<3f", p, at, rgb[0] * m, rgb[1] * m, rgb[2] * m)

    for i, sec in enumerate(cf.sections):
        p = sec.payload
        if i == 0 or len(p) < 4 or struct.unpack_from("<I", p, 0)[0] not in ids:
            continue
        name = ids[struct.unpack_from("<I", p, 0)[0]]
        out = bytearray(p)
        if name == _COLOUR_CONST:
            if len(p) != 25:
                skipped += 1
                continue
            paint(out, 5)
        else:
            n = struct.unpack_from("<I", p, 17)[0] if len(p) >= 21 else -1
            if not (0 <= n < 64 and any(len(p) == 21 + 20 * n + t for t in _RAMP_TAILS[name])):
                skipped += 1
                continue
            for k in range(n):
                paint(out, 21 + 20 * k + 4)
        cf.sections[i] = cooked.Section(payload=bytes(out))
    return cooked.emit(cf), skipped


def _own_effects(b, hid: str, effects: dict, placeholder: bool, put):
    """``(swaps, preload lines, notes)`` giving the hero its own copies of the
    base's own particle effects (``Settings\\Heroes\\<Base>_FX\\*.vfx.ot``).

    An effect file names no path of its own and reaches its look only through
    its materials (``Materials\\X.mat.ot``), which reach textures; so each
    effect is copied under ``<id>_<name>`` in the same folder (a new cooked path
    needs a shipped sibling), its materials likewise, and each texture replaced
    by a copy recoloured by the effect's tint (``effects."<name>"`` or
    ``effects."*"``, else pink under a placeholder, else untouched). Shared
    effects (``Common_FX``, other heroes') are left alone: other heroes play
    them too.
    """
    from ...engine import corpus
    from ...engine import entity_strings as ES
    from ...engine import hero_cook as H

    folder = f"Settings\\Heroes\\{b.stem}_FX\\"
    own = sorted({t for ref in b.family
                  for _s, _o, t in ES.list_strings(corpus.read(H.entity_rel(ref)))
                  if t.startswith(folder) and t.endswith(".vfx.ot")})
    known = {v.rsplit("\\", 1)[-1][:-len(".vfx.ot")] for v in own}
    unknown = sorted(set(effects) - known - {"*"})
    if unknown:
        raise ContentError(f"hero {hid}: 'effects' names effects {b.stem} does not play: "
                           f"{', '.join(map(repr, unknown))}")

    def spec_of(name: str):
        spec = effects.get(name, effects.get("*"))
        if isinstance(spec, dict):
            bad = sorted(set(spec) - {"tint"})
            if bad:
                raise ContentError(f"hero {hid}: effect {name!r}: unsupported field(s) "
                                   f"{bad}; known: ['tint']")
            spec = spec.get("tint")
        if spec is not None:
            return _tint(spec, hid, f"effect {name!r}")
        return PLACEHOLDER_TINT if placeholder else None

    def cooked_path(root: str, ref: str, cls: str) -> str:
        return f"{root}/{ref.replace(chr(92), '/')}.{cls}"

    def roots(raw: bytes) -> dict[str, str]:
        """Every path in a cooked file -> the root written just before it
        (``FX``, ``3D``, ...). Effect textures are not all under FX: Volcanic
        Rage's rocks borrow a level's ``3D`` rock atlas (2026-09-26)."""
        ss = [t for _s, _o, t in ES.list_strings(raw)]
        return {t: ss[i - 1] for i, t in enumerate(ss) if i and "." in t}

    def renamed(ref: str, tag: str) -> str:
        folder_, _, name = ref.rpartition("\\")
        name = f"{hid}_{name}" if tag == "ff00ff" else f"{hid}_{tag}_{name}"
        return f"{folder_}\\{name}" if folder_ else name

    swaps: dict[str, str] = {}
    lines: list[str] = []
    notes: list[str] = []
    done_tex: dict[tuple, str | None] = {}
    done_mat: dict[tuple, str] = {}

    def texture(t: str, root: str, rgb, tag: str) -> str:
        if (t, tag) not in done_tex:
            traw = corpus.read(cooked_path(root, t, "Texture.dxt"))
            blob = _tinted_texture(traw, rgb) if traw else None
            if blob is None:
                notes.append(f"texture {root}\\{t} could not be recoloured; kept as is")
                done_tex[(t, tag)] = None
            else:
                new = renamed(t, tag)
                put(cooked_path(root, new, "Texture.dxt"), blob)
                lines.append(f"{root}|{new}|oCTexture")
                done_tex[(t, tag)] = new
        return done_tex[(t, tag)] or t

    def material(m: str, root: str, rgb, tag: str) -> str:
        if (m, tag) in done_mat:
            return done_mat[(m, tag)]
        mraw = corpus.read(cooked_path(root, m, "Material.gen"))
        if mraw is None:
            notes.append(f"material {root}\\{m} is not in the game files; kept as is")
            done_mat[(m, tag)] = m
            return m
        where = roots(mraw)
        slot = _texture_slots(mraw)
        new_raw, _n = ES.rewrite_strings(
            mraw, lambda s: texture(s, where.get(s, "FX"), rgb, tag)
            if s.lower().endswith((".png", ".tga")) and slot.get(s) in _COLOUR_SLOTS else s)
        new_raw = _recolour_uniforms(new_raw, rgb)
        new_m = renamed(m, tag)
        put(cooked_path(root, new_m, "Material.gen"), new_raw)
        lines.append(f"{root}|{new_m}|oCMaterial")
        done_mat[(m, tag)] = new_m
        return new_m

    for vfx in own:
        rgb = spec_of(vfx.rsplit("\\", 1)[-1][:-len(".vfx.ot")])
        if rgb is None:
            continue
        raw = corpus.read(cooked_path("FX", vfx, "ScheduledVfxSettings.gen"))
        if raw is None:
            notes.append(f"effect {vfx} is not in the game files; left as the base's")
            continue
        tag = "".join(f"{int(x * 255):02x}" for x in rgb)
        where = roots(raw)
        new_raw, _n = ES.rewrite_strings(
            raw, lambda s, rgb=rgb, tag=tag, where=where: material(s, where.get(s, "FX"), rgb, tag)
            if s.endswith(".mat.ot") else s)
        new_raw, skipped = _recolour_effect(new_raw, rgb)
        if skipped:
            notes.append(f"effect {vfx}: {skipped} colour section(s) of an unknown "
                         f"layout kept as is")
        new_vfx = f"{vfx.rsplit(chr(92), 1)[0]}\\{hid}_{vfx.rsplit(chr(92), 1)[1]}"
        put(cooked_path("FX", new_vfx, "ScheduledVfxSettings.gen"), new_raw)
        lines.append(f"FX|{new_vfx}|oCScheduledVfxSettings")
        swaps[vfx] = new_vfx
    return swaps, lines, notes


def _memoir_keys(herodef: bytes) -> list[tuple[str, str, str]]:
    """``(bank, title key, text key)`` for each story page of a herodef, in
    page order (``Beowulf_Memoir1_Title`` ... in ``Hero_<X>_Memoirs~GAM.xls``)."""
    from ...engine import entity_strings as ES
    ss = [t for _s, _o, t in ES.list_strings(herodef)]
    pages: dict[int, dict] = {}
    for i, t in enumerate(ss):
        m = re.fullmatch(r".+_Memoir(\d+)_(Title|Desc)", t)
        if m and i and ss[i - 1].endswith("Memoirs~GAM.xls"):
            pages.setdefault(int(m.group(1)), {"bank": ss[i - 1]})[m.group(2)] = t
    return [(p["bank"], p.get("Title", ""), p.get("Desc", ""))
            for _n, p in sorted(pages.items()) if p.get("Title") and p.get("Desc")]


def _placeholder_ref(ref: str, hid: str) -> str:
    """``Heroes\\Beowulf\\Skill Dash Attack.png`` ->
    ``Heroes\\Beowulf\\<id>_Skill Dash Attack.png`` (same folder: a new cooked
    path needs a shipped sibling)."""
    folder, name = ref.rsplit("\\", 1)
    return f"{folder}\\{hid}_{name}"


def _portrait_ref(ref: str, hid: str) -> str:
    """``BookMenu\\Heroes\\UI_HeroPortrait_Piper_Active.png`` ->
    ``BookMenu\\Heroes\\UI_HeroPortrait_<id>_Active.png`` (same folder: a new
    cooked path needs a shipped sibling)."""
    folder, name = ref.rsplit("\\", 1)
    stem, ext = name.rsplit(".", 1)
    parts = stem.split("_")
    # UI_HeroPortrait_<Hero>_<State> / Portrait_<Hero>_01
    i = 2 if stem.startswith("UI_HeroPortrait_") else 1
    parts[i] = hid
    return f"{folder}\\{'_'.join(parts)}.{ext}"
