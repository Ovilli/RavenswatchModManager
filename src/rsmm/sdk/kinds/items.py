"""Item (magical-object) content builder — SDK entry point.

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

import logging
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
TEXT_BANK_OVERRIDES_SUBDIR = "_pending_text_overrides"


def _find_base(base_id: str) -> tuple[bytes, str] | None:
    """Return (cooked_bytes, rarity) for a vanilla item id, or None if no such
    cooked entity exists under the in-repo magical-object tree."""
    leaf = f"{base_id}.entity.ot.EntitySettingsResource.gen"
    for rarity in _RARITIES:
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


def _coerce_value_patches(raw) -> list[tuple[str, float, float]]:
    """Normalise the optional ``value_patches`` field into (label, old, new)."""
    out: list[tuple[str, float, float]] = []
    for vp in (raw or []):
        if isinstance(vp, dict):
            label, old, new = vp.get("label"), vp.get("old"), vp.get("new")
        else:
            label, old, new = vp
        if not label or old is None or new is None:
            raise ContentError(
                f"value_patches entry needs label/old/new, got {vp!r}"
            )
        out.append((str(label), float(old), float(new)))
    return out


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one item def into the mod's ``assets/`` tree.

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

    files = cook.build_magic_item(
        new_id=defn.id,
        base_id=base,
        base_cooked=base_cooked,
        corpus=cook.load_corpus(_MO_DIR),
        rarity=rarity,
        name=name,
        description=description,
        value_patches=value_patches,
        icon=icon,
        bank_base_gen=bank_gen,
    )
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
