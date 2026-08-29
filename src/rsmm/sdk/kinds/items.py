"""Item (magical-object) content builder — SDK entry point.

Two modes, dispatched by the declaration's ``mode`` field:

* ``mode="clone"`` (default) — ADD a new, distinct, droppable magical object,
  cooked from a vanilla ``base``. Described below.
* ``mode="ban"`` — REMOVE vanilla items from the catalog so no draw can offer
  them, the multiplayer-correct lever for "disable this item". See
  :func:`_emit_ban`.

``emit()`` turns one ``[[content]] kind="item"`` declaration (or
``registry.register("item", ...)``) into the real cooked files a new,
distinct, droppable magical object needs, written straight into the mod's
``assets/`` tree so the applier installs + registers them:

* the cloned entity at
  ``EntitySettings/Objects/Magical_Objects/<rarity>/<id>...gen`` — the
  ``base`` item's cooked bytes with re-minted node GUIDs (distinct
  identity), the id renamed, and any ``value_patches`` applied;
* when a ``name`` is given and the install's text bank is reachable, the
  ``Magical_Objects~GAM.xls`` bank + language siblings with the item's
  ``<id>_Name`` / ``_Description`` appended.

The whole pipeline is length-preserving, so ``id`` must currently match
``base`` in byte length (variable-length ids need the container re-emit
cooker — tracked separately). The mechanism is validated in-game: a
reminted clone with a custom value drops and functions as its own item.
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from ...engine import magic_item_cook as cook
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C
from .item import schema as item_schema
from .item.builder import build_manifest

_log = logging.getLogger(__name__)

#: Where the vanilla magical-object entities + text bank live in-repo.
_MO_DIR = DATA_DIR / "uncooked" / "EntitySettings" / "Objects" / "Magical_Objects"
_RARITIES = ("Common", "Rare", "Epic", "Legendary", "Cursed", "Powerups")

PENDING_ITEMS_SUBDIR = "_pending_items"
PENDING_BANS_SUBDIR = "_pending_bans"
TEXT_BANK_OVERRIDES_SUBDIR = "_pending_text_overrides"


def _find_base(base_id: str) -> tuple[bytes, str] | None:
    """Return (cooked_bytes, rarity) for a vanilla item id, or None if no such
    cooked entity exists under the in-repo magical-object tree.

    Both spellings resolve: the bare id (``Armor_Per_Object``) and the
    rarity-qualified path (``Common/Armor_Per_Object``). Without the latter a
    prefixed base silently missed and fell back to the legacy manifest instead
    of cooking a real clone.
    """
    want_rarity, _, stem = str(base_id).replace("\\", "/").rpartition("/")
    leaf = f"{stem}.entity.ot.EntitySettingsResource.gen"
    for rarity in _RARITIES:
        if want_rarity and rarity.lower() != want_rarity.lower():
            continue
        p = _MO_DIR / rarity / leaf
        if p.is_file():
            return p.read_bytes(), rarity
    return None


def _install_bank_gen() -> Path | None:
    """Best-effort path to the live ``Magical_Objects~GAM.xls.LocalText.gen``
    in the game install, so name/description can be appended to the real bank
    (with its language siblings). None when no install is reachable."""
    try:
        from rsmm.cli.apply_mods import (
            COOKING_REL,
            find_game_dir,
            load_asset_map,
        )
        game = find_game_dir()
        if game is None:
            return None
        enc = load_asset_map().get(cook.MAGIC_TEXT_BANK)
        if not enc:
            return None
        p = game / COOKING_REL / Path(*enc.split("\\"))
        return p if p.exists() else None
    except (ImportError, OSError, ValueError):
        return None


def _maybe_custom_texture(mod_root: Path, icon, item_id: str):
    """If ``icon`` points at a PNG file shipped in the mod, cook it into a new
    oCTexture and return ``(icon_string, {decoded_path: cooked_bytes})``; else
    None (the icon is a vanilla stem/path repoint).

    The cooked texture is registered at
    ``Ui/Objects/UI_Object_<id>.png.Texture.dxt`` and the entity's icon set to
    ``Objects\\UI_Object_<id>.png`` so the engine resolves it.
    """
    if not icon:
        return None
    p = mod_root / str(icon)
    if not (p.is_file() and p.suffix.lower() == ".png"):
        return None
    from ...engine.cooked_schemas.texture import TextureHandler
    cooked_tex = TextureHandler().encode_container(p.read_bytes())
    tex_decoded = f"Ui/Objects/UI_Object_{item_id}.png.Texture.dxt"
    return f"Objects\\UI_Object_{item_id}.png", {tex_decoded: cooked_tex}


def _coerce_icon(raw) -> str | None:
    """Normalise the ``icon`` field into the cooked icon-path string.

    A bare vanilla icon stem (``"BalorEye"``) expands to
    ``Objects\\UI_Object_<stem>.png`` — the form magical objects reference. A
    value already containing a separator or ``.png`` is used verbatim.
    """
    if raw is None:
        return None
    s = str(raw)
    if "\\" in s or "/" in s or s.lower().endswith(".png"):
        return s.replace("/", "\\")
    return f"Objects\\UI_Object_{s}.png"


def _coerce_value_patches(raw) -> list[tuple[str, float, float, bool]]:
    """Normalise ``value_patches`` into ``(label, old, new, clear_override)``.

    Entry forms: a ``[label, old, new]`` list/tuple (optionally a 4th truthy
    element to clear the override), or a dict with ``label``/``old``/``new`` and
    optional ``clear_override`` (alias ``clear``). ``clear_override`` disables a
    *shadowed* node's selector binding so the inline edit actually applies — see
    :func:`rsmm.engine.magic_item_cook.build_magic_item`.
    """
    out: list[tuple[str, float, float, bool]] = []
    for vp in (raw or []):
        clear = False
        if isinstance(vp, dict):
            label, old, new = vp.get("label"), vp.get("old"), vp.get("new")
            clear = bool(vp.get("clear_override", vp.get("clear", False)))
        else:
            label, old, new = vp[0], vp[1], vp[2]
            clear = len(vp) > 3 and bool(vp[3])
        if not label or old is None or new is None:
            raise ContentError(
                f"value_patches entry needs label/old/new, got {vp!r}"
            )
        out.append((str(label), float(old), float(new), clear))
    return out


#: Fields ``mode="ban"`` understands. Enforced (an unknown key raises) because
#: every one of them is a silent no-op when misspelled: a ban that names nothing
#: emits a well-formed file that changes no item, and the mistake only surfaces
#: as "the banned item still dropped" a playtest later.
_BAN_FIELDS = ("mode", "items")


def _vanilla_item_ids() -> set[str]:
    """Every vanilla magical-object id present in the in-repo corpus.

    Empty when ``data/uncooked`` is absent (a frozen build, a fresh checkout),
    in which case ban ids simply go unvalidated here and are checked again at
    apply time against the install's own versiondef vector.
    """
    out: set[str] = set()
    for rarity in _RARITIES:
        d = _MO_DIR / rarity
        if not d.is_dir():
            continue
        for f in d.glob("*.entity.ot.EntitySettingsResource.gen"):
            out.add(f.name.split(".entity.ot", 1)[0])
    return out


def _catalog_item_ids() -> set[str] | None:
    """Item ids actually listed in the install's LiveOps magical-object vector,
    or None when no install is reachable.

    This is a STRICTER set than the corpus and the one a ban is really checked
    against: the shipped corpus carries ~20 entities the catalog never lists
    (``*_Model`` templates, unreleased items), and banning one of those is a
    no-op that a corpus-only check would happily accept.
    """
    try:
        from rsmm.cli.apply_mods import (
            BACKUP_SUFFIX,
            VERSIONDEF_GEN_LEAF,
            _find_mo_vector,
            _locate_cooked_by_leaf,
            _mo_entry_stem,
            _mo_vector_entries,
            find_game_dir,
        )
        game = find_game_dir()
        if game is None:
            return None
        gen = _locate_cooked_by_leaf(game, VERSIONDEF_GEN_LEAF)
        if gen is None:
            return None
        # Read the pristine backup when one exists: the live file may already
        # carry this very ban, which would make the id look unknown.
        bak = gen.with_name(gen.name + BACKUP_SUFFIX)
        blob = (bak if bak.exists() else gen).read_bytes()
        loc = _find_mo_vector(blob)
        if loc is None:
            return None
        co, _end, cnt = loc
        return {_mo_entry_stem(e[2]) for e in _mo_vector_entries(blob, co, cnt)}
    except (ImportError, OSError, ValueError, struct.error):
        return None


def _config_selection(mod_root: Path) -> list[str] | None:
    """The mod's `multiselect` ban picker value, or None if it has no picker.

    Returns a list (possibly empty) only when the mod actually declares the
    field, so "no picker" and "picker with nothing selected" stay
    distinguishable — they mean opposite things for the manifest fallback.
    """
    from rsmm.engine.item_bans import CONFIG_FIELD
    from rsmm.sdk.config import ConfigError, ConfigStore

    if not (mod_root / "config_schema.toml").is_file():
        return None
    try:
        store = ConfigStore(mod_root)
    except (OSError, ConfigError, ValueError):
        return None
    field = store.schema.fields.get(CONFIG_FIELD)
    if field is None or field.type != "multiselect":
        return None
    value = store.get(CONFIG_FIELD) or []
    return sorted({str(x) for x in value}) if isinstance(value, list) else []


def _emit_ban(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Stage a list of vanilla items to drop from the magical-object catalog.

    Emits no cooked asset. The ban is applied by :mod:`rsmm.cli.apply_mods`,
    which rebuilds the LiveOps versiondef MO vector without the named entries,
    so the engine never loads them into ``g_MagicalObjectPool`` and no draw can
    ever offer them.

    **This is the only multiplayer-correct way to ban an item.** The offer draw
    is seeded and host-authoritative deterministic, so a per-peer runtime filter
    (a loader hook, Lua) makes peers disagree about the roll and desyncs the run
    — see ``docs/_re/kinds/rewards.md``. A data-level ban instead leaves every
    peer building an identical pool from identical assets, so the deterministic
    draw stays identical everywhere. That holds only while every peer runs the
    same mod: mismatched installs do not crash (a grant networks by GUID and
    ``MagicalObjectPool_SourceLookup`` guards a miss), but players then see
    different offers.

    Fields:
        ``items`` (list[str], required)  vanilla item ids to ban, e.g.
                                        ``["Armor_Per_Object", "Balor_Eye"]``.
    """
    C.validate_id("item", defn.id)
    unknown = sorted(set(defn.fields) - set(_BAN_FIELDS))
    if unknown:
        raise ContentError(
            f"item {defn.id}: unknown field(s) for mode='ban': "
            f"{', '.join(unknown)}; expected {', '.join(_BAN_FIELDS)}"
        )

    # A mod that declares the `multiselect` picker is EDITED through it, so the
    # picker's saved selection wins over the manifest's `items` list. They are
    # kept in step by `item_bans.write_bans`, but only the picker is live while
    # the player is clicking, and a stale manifest silently re-banning what
    # they just un-banned is the worst failure available here.
    picked = _config_selection(out_dir.parent)
    raw = picked if picked is not None else defn.fields.get("items")
    if isinstance(raw, str):
        raw = [raw]
    if raw is None or not isinstance(raw, (list, tuple)):
        raise ContentError(
            f"item {defn.id}: mode='ban' needs a non-empty 'items' list of "
            f"vanilla item ids to ban"
        )
    if not raw:
        # An empty pick is a real state — "ban nothing" — not a broken manifest,
        # so it emits nothing rather than raising and blocking the whole apply.
        if picked is not None:
            return []
        raise ContentError(
            f"item {defn.id}: mode='ban' needs a non-empty 'items' list of "
            f"vanilla item ids to ban"
        )
    items = [str(x).strip() for x in raw]
    if not all(items):
        raise ContentError(f"item {defn.id}: 'items' contains an empty id")

    # Validate as strictly as the environment allows. A typo here is otherwise
    # invisible until a playtest, because banning a name nothing matches is a
    # perfectly well-formed no-op. Prefer the install's own catalog — the
    # corpus is a superset and would accept ids that can never be banned.
    known, where = _catalog_item_ids(), "the install catalog"
    if known is None:
        known, where = _vanilla_item_ids(), "the asset corpus"
    if known:
        missing = sorted({i for i in items if i not in known})
        if missing:
            raise ContentError(
                f"item {defn.id}: no magical object named "
                f"{', '.join(missing)} in {where} ({len(known)} items). "
                f"Ban ids are bare item ids, e.g. 'Armor_Per_Object'."
            )

    dest = out_dir / PENDING_BANS_SUBDIR / f"{defn.id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"mod": mod_id, "id": defn.id, "items": sorted(set(items))},
                   indent=1),
        encoding="utf-8",
    )
    _log.info("item %s/%s: staged ban of %d item(s)", mod_id, defn.id, len(set(items)))
    return [dest]


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Dispatch on ``mode`` — see :func:`_emit_clone` / :func:`_emit_ban`."""
    mode = defn.fields.get("mode", "clone")
    if mode == "ban":
        return _emit_ban(mod_id, defn, out_dir)
    if mode != "clone":
        raise ContentError(
            f"item {defn.id}: unknown mode {mode!r}; expected 'clone' or 'ban'"
        )
    return _emit_clone(mod_id, defn, out_dir)


def _emit_clone(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one cloned item def into the mod's ``assets/`` tree.

    Fields:
        ``base`` (str, required)   vanilla item id to clone.
        ``name`` / ``display_name`` display name (-> ``<id>_Name``).
        ``description`` (str)       flavour/effect text (-> ``<id>_Description``).
        ``rarity`` (str)            override target rarity subdir; defaults to
                                    the base item's own rarity.
        ``value_patches``           list of ``(label, old, new)`` (or dicts) —
                                    f32 effect edits, e.g.
                                    ``["Armor per Object Value", 2.0, 50.0]``.
    """
    C.validate_id("item", defn.id)
    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise SchemaNotMined(
            f"item {defn.id}: needs a 'base' vanilla item id to clone. "
            f"See docs/_re/kinds/items.md."
        )

    found = _find_base(base)
    if found is None:
        # Base isn't a known vanilla magical object (or data/uncooked is
        # absent): fall back to the legacy manifest so registration/tagging
        # still works. Real cooked output requires a real base id.
        return _emit_legacy_manifest(mod_id, defn, out_dir)

    base_cooked, base_rarity = found
    rarity = str(defn.fields.get("rarity") or base_rarity)
    name = defn.fields.get("name") or defn.fields.get("display_name")
    name = str(name) if name is not None else None
    description = defn.fields.get("description")
    description = str(description) if description is not None else None
    value_patches = _coerce_value_patches(defn.fields.get("value_patches"))
    # Custom PNG icon shipped in the mod is cooked into a new texture;
    # otherwise the icon field repoints to a vanilla icon.
    custom_tex = _maybe_custom_texture(out_dir.parent, defn.fields.get("icon"), defn.id)
    if custom_tex is not None:
        icon, extra_files = custom_tex
    else:
        icon, extra_files = _coerce_icon(defn.fields.get("icon")), {}

    bank_gen = _install_bank_gen() if name is not None else None
    if name is not None and bank_gen is None:
        _log.warning(
            "item %s/%s: no install text bank reachable; entity will be "
            "nameless in-game. Run apply against a Ravenswatch install.",
            mod_id, defn.id,
        )

    try:
        files = cook.build_magic_item(
            new_id=defn.id,
            base_id=base,
            base_cooked=base_cooked,
            # NO GUID remint (corpus=[]): reminting mints fresh GUIDs the engine
            # cannot resolve at instantiation, so the entity silently fails to
            # spawn and never enters the magical-object pool. Verified in-game
            # (remint-only clone -> pool stays 104; rename-only -> 105 + visible).
            # The base's registered node GUIDs are kept; distinct identity comes
            # from the id/path rename, which is enough (the engine does not dedupe
            # the clone out). See memory item-clone-pipeline-verified.
            corpus=[],
            # OPT-IN fix for the owned-set identity collision: a clone keeps its
            # base's identity GUID, so the hero owned-set dedups the clone out at
            # grant time when the base is also owned that run (the custom item
            # silently "doesn't work" — see magic_item_cook.ItemEdit). Setting
            # `unique_identity = true` on the item re-mints ONLY the root identity
            # GUID (spawn-safe: registration is path-keyed). Verify spawn in-game
            # after enabling. Default off so existing mods are unchanged.
            remint_identity=bool(defn.fields.get("unique_identity", False)),
            rarity=rarity,
            name=name,
            description=description,
            value_patches=value_patches,
            icon=icon,
            bank_base_gen=bank_gen,
        )
    except ValueError as e:
        # e.g. a shadowed value_patches target — surface with item context.
        raise ContentError(f"item {mod_id}/{defn.id}: {e}") from e
    files.update(extra_files)  # cooked custom texture, if any

    written: list[Path] = []
    for decoded, blob in files.items():
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    _log.info("item %s/%s: emitted %d cooked file(s) (rarity=%s)",
              mod_id, defn.id, len(written), rarity)
    return written


def _emit_legacy_manifest(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Legacy path: write a `_pending_items/<id>.json` manifest + EN text seed.

    Used when the ``base`` isn't a resolvable vanilla magical object, so
    registration/tagging/summary still work without producing cooked bytes.
    """
    display_name = str(
        defn.fields.get("name") or defn.fields.get("display_name") or defn.id
    )
    manifest = build_manifest(
        mod_id=mod_id, item_id=defn.id,
        fields={**defn.fields, "name": display_name},
        schema_version=max(int(defn.schema_version or 1),
                           item_schema.ITEM_MANIFEST_SCHEMA_VERSION),
    )
    written = [C.write_json(
        out_dir / PENDING_ITEMS_SUBDIR / f"{defn.id}.json", manifest.to_json(),
    )]
    written.append(C.write_json(
        out_dir / TEXT_BANK_OVERRIDES_SUBDIR / f"{mod_id}__{defn.id}__EN.json",
        {"locale": "EN", "mod": mod_id, "id": defn.id,
         "strings": {manifest.text_keys["name"]: display_name},
         "note": "Seeded by rsmm.sdk.kinds.items; lang/<locale>.toml overrides."},
    ))
    return written
