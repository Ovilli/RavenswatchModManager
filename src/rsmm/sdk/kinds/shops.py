"""**Shop** editor — change what the Sandman sells and what it costs (SDK entry).

The Sandman shop is the game's in-run vendor. Like ``melody`` and ``reward``,
a ``shop`` def is an **override of retail files**: the emitted assets land at
the vanilla decoded paths and ``rsmm apply`` backs up + replaces the originals.
There is one Sandman, so a mod declares at most one ``shop``.

Two kinds of file carry the shop, and :mod:`rsmm.engine.sandman_shop` explains
which engine routine reads each field:

* the Sandman NPC entity, whose seven offer generators decide how many items
  are offered, of which quality, from which flag pool;
* the magical objects themselves — each carries its own flag list (which pools
  it belongs to) and, for the ten Sandman items, its own price.

Fields:
    ``slots`` (table, optional)    generator -> ``{items = [...], count = n}``.
                                   The same shape an ``item-grid`` config
                                   field stores per section (see ``config``).
                                   Generators: ``minor``, ``medium``,
                                   ``medium_duplicate``, ``medium_object``,
                                   ``major``, ``major_duplicate``,
                                   ``major_object``. The two ``*_object``
                                   slots ship selling a RANDOM magical object
                                   by rarity; giving one an item list makes
                                   it sell those items instead.

                                   * ``items`` — exactly which items that
                                     slot can offer (full ids, e.g.
                                     ``Power_Up_Grimoire_Armor_High``). Only a
                                     shop-eligible item is accepted (see
                                     :mod:`rsmm.engine.shop_catalog`), and a
                                     ``*_duplicate`` slot only takes the
                                     powerups that copy an object.
                                   * ``count`` — how many it rolls, from 1 up
                                     to what the slot ships with (the shop
                                     screen has a fixed number of widgets).
    ``prices`` (table, optional)   item -> new price in dream shards. Keys are
                                   full ids, or Sandman item stems without the
                                   ``Power_Up_Sandman_`` prefix. Only an item
                                   with a price of its own can be repriced.
    ``price_scale`` (float, opt.)  multiplies the vanilla price of every
                                   repriceable item not listed in ``prices``
                                   (rounded, never below 0).
    ``offers`` (table, optional)   generator -> ``{count, weights, pool}``, the
                                   raw generator fields, for what ``slots``
                                   does not cover (the ``*_object`` generators'
                                   quality weights). Weights are a table of
                                   ``common``, ``rare``, ``epic``,
                                   ``legendary``, ``cursed``, ``powerup``;
                                   unlisted qualities keep their vanilla value.

**How a slot's item list is written.** The engine picks an item for a
generator when the item's flags contain every flag of the generator's pool
(``0x1402d21f0``). A slot whose list differs from vanilla gets its own pool tag,
``RSMM_Shop_<slot>``, and each chosen item gets that tag appended to its flags.
Nothing is removed from any item, so the flags other vendors filter on (the
Grimoire's ``Medium``, the Wishing Well's ``WishingWell``) are left intact.

**Config.** ``config = "<field>"`` names one of the mod's ``item-grid`` config
fields (:mod:`rsmm.sdk.config_grid`) to take ``slots`` and ``prices`` from: each
grid section whose id is a slot key becomes that slot, and the grid's numbers
become prices. The grid's layout, labels and look are the mod's own
declaration — this kind only reads the stored value. A section id that is not a
slot key raises, so a mistyped schema cannot silently edit nothing.

Confidence: ``experimental``. Field meaning is read off the generator,
quality-roll, pool-match and price routines in the live exe, and every edit
round-trips byte-for-byte, but no edited shop has been opened in-game yet.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...engine import sandman_shop as S
from ...engine import shop_catalog as SC
from ..content import ContentDef, ContentError
from . import _common as C

_log = logging.getLogger(__name__)

#: Everything this kind writes is rebuilt at apply time from the installing
#: player's own game files (`shop_catalog.vanilla_bytes` reads the install when
#: there is no developer mirror) and their own config. `rsmm pack` therefore
#: leaves the emitted files out of a published archive: shipping them would put
#: edited copies of the game's files on the store, and would bake the packing
#: author's config over every player's.
REGENERATES_FROM_INSTALL = True

_FIELDS = {"prices", "price_scale", "offers", "slots", "config"}
_OFFER_FIELDS = {"count", "weights", "pool"}


def _item_decoded(item_id: str) -> str:
    return f"{S.ITEM_DIR_ASSET}/{item_id}{S.ITEM_SUFFIX}"


def _game_dir() -> Path | None:
    try:
        from rsmm.cli import apply_mods as A

        return A.find_game_dir()
    except Exception:                           # noqa: BLE001 - no install is a normal state
        return None


def config_fields(defn: ContentDef, mod_root: Path, field_name: str) -> dict[str, Any]:
    """``slots`` and ``prices`` from the mod's ``item-grid`` field ``field_name``."""
    from rsmm.sdk.config import ConfigError, ConfigStore

    try:
        store = ConfigStore(mod_root)
    except (OSError, ConfigError, ValueError) as e:
        raise ContentError(f"shop {defn.id}: config unreadable: {e}") from e
    fld = store.schema.fields.get(field_name)
    if fld is None or fld.type != "item-grid":
        raise ContentError(
            f"shop {defn.id}: config = {field_name!r} must name an item-grid field "
            f"in config_schema.toml")
    bad = [s.id for s in fld.grid.sections if s.id not in SC.EDITABLE]
    if bad:
        raise ContentError(
            f"shop {defn.id}: grid section(s) {bad} are not shop slots "
            f"({', '.join(SC.EDITABLE)})")
    value = store.get(field_name) or {}
    return {
        "slots": dict(value.get("sections") or {}),
        "prices": dict(value.get("numbers") or {}),
    }


def _number(defn: ContentDef, what: str, value, *, integer: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ContentError(f"shop {defn.id}: {what} must be a number, got {value!r}")
    if integer and value != int(value):
        raise ContentError(f"shop {defn.id}: {what} must be a whole number, got {value!r}")
    if value < 0:
        raise ContentError(f"shop {defn.id}: {what} cannot be negative, got {value!r}")
    return value


def _resolve_item(defn: ContentDef, data: SC.ShopData, name: str) -> str:
    for candidate in (str(name), S.ITEM_PREFIX + str(name)):
        if candidate in data.items:
            return candidate
    raise ContentError(
        f"shop {defn.id}: {name!r} is not an item the Sandman can sell. "
        f"Eligible: {', '.join(sorted(data.items))}")


def _price_edits(defn: ContentDef, fields: dict, data: SC.ShopData,
                 game_dir: Path | None) -> dict[str, int]:
    prices = fields.get("prices") or {}
    if not isinstance(prices, dict):
        raise ContentError(f"shop {defn.id}: prices must be a table of item = price")
    out: dict[str, int] = {}
    for name, price in prices.items():
        item_id = _resolve_item(defn, data, name)
        if not data.items[item_id].price_editable:
            raise ContentError(
                f"shop {defn.id}: {item_id} has no price of its own (it inherits "
                f"{data.items[item_id].price}), so it cannot be repriced")
        out[item_id] = int(_number(defn, f"price of {name}", price, integer=True))
    scale = fields.get("price_scale")
    if scale is not None:
        scale = _number(defn, "price_scale", scale, integer=False)
        for item in data.items.values():
            if item.price_editable and item.id not in out:
                out[item.id] = max(0, round(item.price * scale))
    return out


def _slot_edits(defn: ContentDef, fields: dict, data: SC.ShopData
                ) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """``(generator edits, item id -> pool tags to add)`` for ``slots``."""
    slots = fields.get("slots") or {}
    if not isinstance(slots, dict):
        raise ContentError(f"shop {defn.id}: slots must be a table of slot tables")
    gen_edits: dict[str, dict] = {}
    tags: dict[str, list[str]] = {}
    for key, slot in slots.items():
        if key not in SC.EDITABLE:
            raise ContentError(
                f"shop {defn.id}: unknown slot {key!r}. Known: {', '.join(SC.EDITABLE)}")
        if not isinstance(slot, dict) or set(slot) - {"items", "count"}:
            raise ContentError(f"shop {defn.id}: slots.{key} takes items and count")
        gen = data.gens[key]
        if "items" in slot:
            items = slot["items"]
            if not isinstance(items, list) or not items:
                raise ContentError(f"shop {defn.id}: slots.{key}.items needs at least one item")
            wanted_role = "duplicate" if key.endswith("_duplicate") else "offer"
            chosen = sorted({_resolve_item(defn, data, i) for i in items})
            wrong = [i for i in chosen if data.items[i].role != wanted_role]
            if wrong:
                raise ContentError(
                    f"shop {defn.id}: slots.{key} only takes "
                    f"{'object-copying' if wanted_role == 'duplicate' else 'non-copying'} "
                    f"powerups; {', '.join(wrong)} is not one")
            if chosen != data.vanilla_members(key):
                gen_edits.setdefault(key, {})["pool"] = S.row_tag(key)
                if key in SC.OBJECT_SLOTS:
                    # It shipped rolling random magical objects by rarity; the
                    # chosen powerups are only ever found at `powerup`.
                    gen_edits[key]["weights"] = S.POWERUP_ONLY
                for item_id in chosen:
                    tags.setdefault(item_id, []).append(S.row_tag(key))
        if "count" in slot:
            count = int(_number(defn, f"slots.{key}.count", slot["count"], integer=True))
            low = S.MIN_ROLLED.get(key, 1)
            if not low <= count <= gen.count:
                raise ContentError(
                    f"shop {defn.id}: slots.{key}.count must be {low} to {gen.count} "
                    f"(the shop screen shows at most {gen.count} there"
                    + (f", and crashes with fewer than {low}" if low > 1 else "") + ")")
            if count != gen.count:
                gen_edits.setdefault(key, {})["count"] = count
    return gen_edits, tags


def _check_rollable(defn: ContentDef, data: SC.ShopData, gen_edits: dict[str, dict],
                    tags: dict[str, list[str]]) -> None:
    """Refuse a shop whose generator could roll fewer items than the game needs.

    Checked on the FINAL edits, whichever of ``slots`` / ``offers`` produced
    them: the count, and how many eligible items the resulting pool matches.
    See :data:`rsmm.engine.sandman_shop.MIN_ROLLED` for why this crashes.
    """
    for key, low in S.MIN_ROLLED.items():
        edit = gen_edits.get(key, {})
        count = edit.get("count", data.gens[key].count)
        pool = edit.get("pool", data.gens[key].pool)
        matching = [i for i in data.items.values()
                    if S.pool_matches(pool, i.flags + tags.get(i.id, []))]
        if count < low or len(matching) < low:
            raise ContentError(
                f"shop {defn.id}: the {key} slot must offer at least {low} items "
                f"(count {count}, {len(matching)} item(s) in its pool) — the game "
                f"crashes when the shop opens with fewer")


def _offer_edits(defn: ContentDef, fields: dict, gens: dict[str, S.OfferGen]) -> dict[str, dict]:
    offers = fields.get("offers") or {}
    if not isinstance(offers, dict):
        raise ContentError(f"shop {defn.id}: offers must be a table of generator tables")
    out: dict[str, dict] = {}
    for key, spec in offers.items():
        if key not in S.GENERATORS:
            raise ContentError(
                f"shop {defn.id}: unknown generator {key!r}. "
                f"Known: {', '.join(S.GENERATORS)}")
        if not isinstance(spec, dict):
            raise ContentError(f"shop {defn.id}: offers.{key} must be a table")
        unknown = set(spec) - _OFFER_FIELDS
        if unknown:
            raise ContentError(
                f"shop {defn.id}: offers.{key} has unknown field(s) {sorted(unknown)}; "
                f"expected {sorted(_OFFER_FIELDS)}")
        edit: dict = {}
        if "count" in spec:
            count = int(_number(defn, f"offers.{key}.count", spec["count"], integer=True))
            if count < 1:
                raise ContentError(f"shop {defn.id}: offers.{key}.count must be at least 1")
            edit["count"] = count
        if "weights" in spec:
            w = spec["weights"]
            if not isinstance(w, dict):
                raise ContentError(
                    f"shop {defn.id}: offers.{key}.weights must be a table of quality = weight")
            bad = set(w) - set(S.QUALITIES)
            if bad:
                raise ContentError(
                    f"shop {defn.id}: offers.{key}.weights has unknown quality "
                    f"{sorted(bad)}; expected {', '.join(S.QUALITIES)}")
            merged = list(gens[key].weights)
            for q, v in w.items():
                merged[S.QUALITIES.index(q)] = _number(
                    defn, f"offers.{key}.weights.{q}", v, integer=False)
            if not any(merged):
                raise ContentError(
                    f"shop {defn.id}: offers.{key}.weights are all zero, so it can roll nothing")
            edit["weights"] = tuple(merged)
        if "pool" in spec:
            if not isinstance(spec["pool"], str):
                raise ContentError(f"shop {defn.id}: offers.{key}.pool must be a string")
            edit["pool"] = spec["pool"]
        if edit:
            out[key] = edit
    return out


def _write(out_dir: Path, decoded: str, blob: bytes) -> Path:
    dest = out_dir / Path(*decoded.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return dest


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one shop def into the mod's ``assets/`` tree."""
    C.validate_id("shop", defn.id)
    unknown = set(defn.fields) - _FIELDS
    if unknown:
        raise ContentError(
            f"shop {defn.id}: unknown field(s) {sorted(unknown)}; expected {sorted(_FIELDS)}")

    fields: dict[str, Any] = dict(defn.fields)
    config_name = fields.pop("config", None)
    if config_name is not None:
        if not isinstance(config_name, str):
            raise ContentError(f"shop {defn.id}: config must name a config field")
        fields.update(config_fields(defn, out_dir.parent, config_name))
    if not any(fields.get(k) for k in ("slots", "prices", "offers")) \
            and fields.get("price_scale") is None:
        if config_name is not None:
            return []                           # an untouched editor is the vanilla shop
        raise ContentError(f"shop {defn.id}: no slots, prices, price_scale or offers given")

    game_dir = _game_dir()
    try:
        data = SC.load(game_dir, icons=False)
        if not data.gens:
            raise ContentError(
                f"shop {defn.id}: the Sandman is not readable — no install found and "
                f"no data/uncooked mirror")
        prices = _price_edits(defn, fields, data, game_dir)
        slot_gens, tags = _slot_edits(defn, fields, data)
        offer_gens = _offer_edits(defn, fields, data.gens)
        for key in set(slot_gens) & set(offer_gens):
            clash = set(slot_gens[key]) & set(offer_gens[key])
            if clash:
                raise ContentError(
                    f"shop {defn.id}: {key} sets {sorted(clash)} in both slots and offers")
            offer_gens[key] = {**offer_gens[key], **slot_gens.pop(key)}
        gen_edits = {**slot_gens, **offer_gens}
        _check_rollable(defn, data, gen_edits, tags)

        written: list[Path] = []
        for item_id in sorted(set(prices) | set(tags)):
            blob = SC.vanilla_bytes(_item_decoded(item_id), game_dir)
            if blob is None:
                raise ContentError(f"shop {defn.id}: {item_id} is not readable")
            if item_id in tags:
                blob = S.set_flags(blob, S.read_flags(blob) + tags[item_id])
            if item_id in prices:
                blob = S.set_price(blob, prices[item_id])
            written.append(_write(out_dir, _item_decoded(item_id), blob))

        if gen_edits:
            npc = SC.vanilla_bytes(S.NPC_ASSET, game_dir)
            assert npc is not None                  # load() read it a moment ago
            written.append(_write(out_dir, S.NPC_ASSET, S.edit_offer_gens(npc, gen_edits)))
    except ContentError:
        raise
    except ValueError as e:
        raise ContentError(f"shop {mod_id}/{defn.id}: {e}") from e

    _log.info("shop %s/%s: wrote %d file(s)", mod_id, defn.id, len(written))
    return written
