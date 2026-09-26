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
  (``apply_mods._patch_versiondef_heroes``), the same way new magic items join
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
    ``base``  (str, required)  a shipped hero to clone, e.g. ``Piper``. Paid
                               DLC heroes are refused: a clone would hand out
                               a hero the player has not bought.

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
        normal}}``: a weapon of the hero's own, in its entities only.
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
        still pink in game is what is left to replace; ``albedo``,
        ``weapons`` and ``portrait`` take precedence. ⚠ Many UI images under
        new names: a new-name UI texture hung level load once (a POI icon).
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

import re
import sys
from pathlib import Path
from typing import Final

from ...engine import enemy_pools as EP
from ...engine import rsc_cache as RC
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_HEROES_DIR = "Definitions/Heroes"
_GEN_SUFFIX = ".herodef.ot.DtHeroDefinition.gen"
_HERO_CLASS = "oCDtHeroDefinition"

#: Paid DLC heroes. Never a clone base: cloning one would unlock it for
#: players who have not bought it.
DLC_HEROES: Final[frozenset[str]] = frozenset({"Carmilla", "Merlin"})


_FIELDS = frozenset({"base", "name", "description", "model", "transform", "albedo",
                     "mra", "normal", "portrait", "own_entity", "weapons",
                     "animations", "outfits", "values", "references", "abilities",
                     "skills", "placeholder"})
_TEXTURE_FIELDS = {"albedo": "ALB", "mra": "MRA", "normal": "NRM"}
#: Shipped alias names (ApplicationSettings.ot). Kintaro's has no entity, but a
#: hero of that name would still collide with it.
_RESERVED_IDS = frozenset({"Common", "Kintaro", "Alice"})


def _rel(hero: str) -> str:
    return f"{_HEROES_DIR}/{hero}{_GEN_SUFFIX}"


def _self_line(hero: str) -> str:
    return f"Definitions|Heroes\\{hero}.herodef.ot|{_HERO_CLASS}"


def shipped_heroes() -> list[str]:
    """Hero ids the game ships, from the corpus (mirror or install)."""
    return sorted(r.rsplit("/", 1)[-1][: -len(_GEN_SUFFIX)]
                  for r in EP.corpus_rels(prefix=_HEROES_DIR, suffix=_GEN_SUFFIX))


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Write ``<id>.herodef`` (a copy of the base) and its resource cache."""
    C.validate_id("hero", defn.id)
    unknown = sorted(set(defn.fields) - _FIELDS)
    if unknown:
        raise ContentError(
            f"hero {defn.id}: unsupported field(s) {unknown}; known: {sorted(_FIELDS)}")
    base = defn.fields.get("base")
    if not isinstance(base, str) or not base:
        raise ContentError(f"hero {defn.id}: needs a 'base' (a shipped hero, e.g. Piper)")
    if base in DLC_HEROES:
        raise ContentError(
            f"hero {defn.id}: {base} is a paid DLC hero and cannot be cloned — the "
            f"clone would give it to players who have not bought it.")
    shipped = shipped_heroes()
    if defn.id in shipped:
        raise ContentError(f"hero {defn.id}: the id collides with a shipped hero")

    raw = EP.corpus_read(_rel(base))
    cache = EP.corpus_read(RC.cache_path_for(_rel(base)))
    if raw is None or cache is None:
        if shipped and base not in shipped:
            raise ContentError(
                f"hero {defn.id}: no shipped hero {base!r}; have {', '.join(shipped)}")
        raise SchemaNotMined(
            f"hero {defn.id}: {base}'s herodef or resource cache is not in the "
            f"corpus or the game install")

    if set(defn.fields) - {"base"}:
        return _emit_custom(mod_id, defn, out_dir, base, raw, cache)

    dest = out_dir / Path(*_rel(defn.id).split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    # 12 of 12 shipped herodefs carry a cache listing their own def line; a new
    # name has none unless it is written (the enemy/tile lesson).
    lines = set(RC.parse(cache)) - {_self_line(base)}
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
    from rsmm.cli.apply_mods import COOKING_REL, load_asset_map
    enc = load_asset_map().get(f"Text/{bank}.LocalText.gen")
    p = game / COOKING_REL / Path(*enc.split("\\")) if enc else None
    if p is None or not p.exists():
        raise SchemaNotMined(f"text bank {bank} is not in the game install")
    return p


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
        b = H.resolve_base(base, app)
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
    own = bool(f.get("own_entity") or f.get("model") or textures or weapons
               or animations or outfits or values or references or abilities or skills
               or f.get("placeholder"))
    swaps: dict[str, str] = {}        # whole-string swaps inside the family
    art: list[str] = []               # preload-cache lines for the new art

    def material(donor: str | None, maps: dict, tag: str, what: str) -> str:
        """Clone ``donor`` with the mod's maps (``{"albedo": path, ...}``)."""
        slots = CE.material_slots(donor)
        repoint = {}
        for field_name, slot in _TEXTURE_FIELDS.items():
            if not maps.get(field_name):
                continue
            if slot not in slots:
                raise ContentError(f"hero {hid}: {what}'s material has no {slot} map")
            ref = f"{b.art_dir}\\Textures\\T_{tag}_{slot}.tga"
            put(PC.art_cooked_path(ref), PC.cook_texture(
                _mod_source(out_dir, maps[field_name], hid, f"{what}.{field_name}")
                .read_bytes()))
            repoint[slots[slot]] = ref
            art.append(f"3D|{ref}|oCTexture")
        mat_ref = f"{b.art_dir}\\Textures\\M_{tag}.mat.ot"
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
            if label not in att:
                raise ContentError(f"hero {hid}: {base} has no weapon {label!r}; "
                                   f"have: {', '.join(sorted(att)) or 'none'}")
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
        art.extend(_borrow_closure([str(v) for v in references.values()
                                    if "\\" in str(v) and "." in str(v)], out_dir, hid))

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

    # 2. The gameplay family, renamed, reached through an alias of its own.
    R = H.Renamer(b, f"Hero_{hid}", swaps) if own else None
    default = R.entity_ref(b.default_skin) if R is not None else None
    if R is not None:
        guid = H.alias_guid(mod_id, hid)
        # Numbers first, on the base's bytes and names (as --list-values shows
        # them); the edit is in place, so renaming afterwards cannot move it.
        stem_of = {ref: ref.rsplit("\\", 1)[-1][:-len(".entity.ot")] for ref in b.family}
        base_bytes = {stem_of[ref]: corpus.read(H.entity_rel(ref)) for ref in b.family}
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
            try:
                res = AE.apply(base_bytes, abilities, main=b.stem, seed=f"{mod_id}:{hid}")
            except AE.AbilityEditError as e:
                raise ContentError(f"hero {hid}: {e}") from e
            base_bytes = res.files
            for w in res.warnings:
                print(f"warning: hero {hid}: {w}", file=sys.stderr)
            art.extend(_borrow_closure(sorted(res.resources), out_dir, hid))
        family = {H.entity_rel(R.entity_ref(ref)):
                  R.cooked(base_bytes[stem_of[ref]], b.alias.guid, guid)
                  for ref in b.family}
        for ref in b.family:
            rel = H.entity_rel(ref)
            new_rel = H.entity_rel(R.entity_ref(ref))
            put(new_rel, family[new_rel])
            ecache = corpus.read(RC.cache_path_for(rel))
            if ecache is not None:
                put(RC.cache_path_for(new_rel), R.cache(ecache, tuple(art)))
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
    lines = [ln for ln in lines if ln != _self_line(base)] + [_self_line(hid)]
    base_cache = RC.render(sorted(set(lines)))
    put(RC.cache_path_for(_rel(hid)),
        R.cache(base_cache, extra) if R is not None
        else RC.render(sorted(set(lines) | set(extra))))

    # 4. Identities of its own. Last, so the family, the outfits' copied
    #    override record and the herodef all go through ONE mapping.
    if R is not None:
        mapping = H.family_guid_map([corpus.read(H.entity_rel(r)) for r in b.family],
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


def _borrow_closure(targets: list[str], out_dir: Path, hid: str) -> list[str]:
    """Cache lines for ``targets`` and everything they reach, taken from the
    shipped caches that already preload them (the way `poi` swaps do it)."""
    if not targets:
        return []
    from ...engine import corpus
    from .poi import _reachable
    lines: list[str] = []
    found: set[str] = set()
    for def_rel in corpus.rels("Definitions/", ".gen"):
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
        raise ContentError(f"hero {hid}: no shipped preload cache lists "
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
