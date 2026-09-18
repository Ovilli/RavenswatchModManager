"""The `[[content]] kind="shop"` builder edits the Sandman shop in place:
per-item prices on the `Power_Up_Sandman_*` entities, and the offer generators
(count, quality weights, flag pool) on the Sandman NPC.

Runs against the real vanilla corpus (skipped if absent).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import sandman_shop as S
from rsmm.engine import shop_catalog as SC
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.config import ConfigError, ConfigStore
from rsmm.sdk.content import KIND_CONFIDENCE, KINDS, ContentDef, ContentError, _load_kind
from rsmm.sdk.kinds import shops

_MIRROR = DATA_DIR / "uncooked"
_NPC = _MIRROR / S.NPC_ASSET

#: The retail shop, as traced 2026-09-13. A game patch that changes it should
#: fail here before a mod writes onto a layout it no longer understands.
_VANILLA_GENS = {
    "minor": (4, (0, 0, 0, 0, 0, 1), "Sandman; Minor"),
    "medium": (1, (0, 0, 0, 0, 0, 1), "Sandman; Medium"),
    "medium_duplicate": (1, (0, 0, 0, 0, 0, 1), "Sandman; MediumDuplicate"),
    "medium_object": (1, (0.5, 0.5, 0, 0, 0, 0), ""),
    "major": (1, (0, 0, 0, 0, 0, 1), "Sandman; Major"),
    "major_duplicate": (1, (0, 0, 0, 0, 0, 1), "Sandman; MajorDuplicate"),
    "major_object": (1, (0, 0, 0.5, 0.25, 0.25, 0), ""),
}
_VANILLA_PRICES = {
    "Minor_Heal": 50, "Minor_Reroll": 50, "Minor_Shield": 75, "Minor_Strength": 75,
    "Medium_Duplicate_Common_Object": 100, "Medium_Duplicate_Object": 150,
    "Medium_Duplicate_Rare_Object": 200, "Medium_Upgrade_2_Talent": 200,
    "Major_Duplicate_Epic_Object": 250, "Major_Upgrade_Talent_To_Legendary": 250,
}
_GRIMOIRE = "Power_Up_Grimoire_Armor_High"


@pytest.fixture(autouse=True)
def _mirror_only(monkeypatch):
    """Emit against the in-repo mirror, never a developer's live install."""
    monkeypatch.setattr(shops, "_game_dir", lambda: None)


def _require_corpus():
    if not _NPC.is_file():
        pytest.skip("vanilla Sandman corpus not present")


def _emit(tmp_path: Path, **fields) -> list[Path]:
    assets = tmp_path / "assets"
    return shops.emit("TestShopMod", ContentDef(kind="shop", id="sandman", fields=fields),
                      assets)


def _item(short: str) -> Path:
    return _MIRROR / S.ITEM_DIR_ASSET / f"{S.ITEM_PREFIX}{short}{S.ITEM_SUFFIX}"


def _price(path: Path) -> int:
    return S.read_price(path.read_bytes())


# --- registry wiring -------------------------------------------------------

def test_kind_is_registered_and_resolves_to_this_module():
    assert "shop" in KINDS
    assert _load_kind("shop") is shops


def test_kind_confidence_is_honest():
    # Proven in game 2026-09-13: edited prices were what the Sandman charged.
    assert KIND_CONFIDENCE["shop"] == "confirmed"


# --- the evidence this kind rests on ---------------------------------------

def test_retail_generators_decode_to_the_traced_shop():
    _require_corpus()
    gens = S.read_offer_gens(_NPC.read_bytes())
    assert {k: (g.count, g.weights, g.pool) for k, g in gens.items()} == _VANILLA_GENS


def test_retail_prices_decode():
    _require_corpus()
    data = SC.load(None, icons=False)
    editable = {i.id: i.price for i in data.items.values() if i.price_editable}
    assert editable == {S.ITEM_PREFIX + k: v for k, v in _VANILLA_PRICES.items()}
    for short, price in _VANILLA_PRICES.items():
        assert _price(_item(short)) == price


def test_eligible_items_and_vanilla_slots():
    _require_corpus()
    data = SC.load(None, icons=False)
    assert _GRIMOIRE in data.items and not data.items[_GRIMOIRE].price_editable
    # An item that inherits its flags has no node to tag, so it is not offered.
    assert "Power_Up_Heal" not in data.items
    assert data.vanilla_members("minor") == sorted(
        S.ITEM_PREFIX + k for k in ("Minor_Heal", "Minor_Reroll", "Minor_Shield", "Minor_Strength"))
    assert data.vanilla_members("medium_duplicate") == sorted(
        S.ITEM_PREFIX + k for k in ("Medium_Duplicate_Common_Object", "Medium_Duplicate_Object",
                                    "Medium_Duplicate_Rare_Object"))


def test_pool_match_is_all_include_and_no_exclude():
    assert S.pool_matches("Sandman; Minor", ["Sandman", "Minor", "WishingWell"])
    assert not S.pool_matches("Sandman; Minor", ["Sandman"])
    assert not S.pool_matches("Sandman; !Minor", ["Sandman", "Minor"])
    assert S.pool_matches("", ["anything"])


def test_flag_edit_round_trips():
    _require_corpus()
    raw = (_MIRROR / S.ITEM_DIR_ASSET / f"{_GRIMOIRE}{S.ITEM_SUFFIX}").read_bytes()
    tagged = S.set_flags(raw, S.read_flags(raw) + [S.row_tag("minor")])
    assert S.read_flags(tagged) == ["Grimoire", "High", "RSMM_Shop_minor"]
    assert S.set_flags(tagged, ["Grimoire", "High"]) == raw


def test_undoing_every_generator_edit_restores_the_file_byte_for_byte():
    _require_corpus()
    raw = _NPC.read_bytes()
    edited = S.edit_offer_gens(raw, {
        "minor": {"count": 2},
        "major_object": {"weights": (0, 0, 0, 1, 0, 0)},
        "medium": {"pool": "Sandman; Major; Longer Than Before"},
    })
    assert edited != raw
    back = S.edit_offer_gens(edited, {
        "minor": {"count": 4},
        "major_object": {"weights": _VANILLA_GENS["major_object"][1]},
        "medium": {"pool": "Sandman; Medium"},
    })
    assert back == raw


# --- emit ------------------------------------------------------------------

def test_prices_and_scale(tmp_path):
    _require_corpus()
    out = _emit(tmp_path, price_scale=0.5, prices={
        "Minor_Heal": 10, "Power_Up_Sandman_Major_Duplicate_Epic_Object": 0})
    by_name = {p.name.split(".")[0][len(S.ITEM_PREFIX):]: p for p in out}
    assert set(by_name) == set(_VANILLA_PRICES)
    assert _price(by_name["Minor_Heal"]) == 10
    assert _price(by_name["Major_Duplicate_Epic_Object"]) == 0
    assert _price(by_name["Minor_Shield"]) == round(75 * 0.5)
    for p in out:
        assert p.parent == tmp_path / "assets" / Path(*S.ITEM_DIR_ASSET.split("/"))


def test_slot_items_tag_the_chosen_items_and_repoint_only_that_generator(tmp_path):
    _require_corpus()
    heal = S.ITEM_PREFIX + "Minor_Heal"
    out = _emit(tmp_path, slots={"minor": {"items": [heal, _GRIMOIRE], "count": 2}})
    # (two items, count 2: the least the Minor slot may offer)
    by_name = {p.name.split(".")[0]: p for p in out}
    assert set(by_name) == {heal, _GRIMOIRE, "NPC_Sandman"}
    assert S.read_flags(by_name[_GRIMOIRE].read_bytes()) == ["Grimoire", "High", "RSMM_Shop_minor"]
    assert S.read_flags(by_name[heal].read_bytes())[-1] == "RSMM_Shop_minor"
    gens = S.read_offer_gens(by_name["NPC_Sandman"].read_bytes())
    assert (gens["minor"].pool, gens["minor"].count) == ("RSMM_Shop_minor", 2)
    assert gens["medium"].pool == "Sandman; Medium"
    # The other Minor items were not touched, and no longer match the new pool.
    assert not S.pool_matches(gens["minor"].pool,
                              S.read_flags(_item("Minor_Shield").read_bytes()))


def test_object_slot_sells_chosen_items_instead_of_a_random_magical_object(tmp_path):
    _require_corpus()
    data = SC.load(None, icons=False)
    # Shipped: no item list, so an untouched object slot stays a random object.
    assert data.vanilla_members("medium_object") == []
    out = {p.name.split(".")[0]: p for p in _emit(
        tmp_path, slots={"medium_object": {"items": [_GRIMOIRE]}})}
    gens = S.read_offer_gens(out["NPC_Sandman"].read_bytes())
    assert gens["medium_object"].pool == "RSMM_Shop_medium_object"
    assert gens["medium_object"].weights == S.POWERUP_ONLY
    assert S.read_flags(out[_GRIMOIRE].read_bytes())[-1] == "RSMM_Shop_medium_object"
    assert gens["major_object"].weights == _VANILLA_GENS["major_object"][1]


def test_a_slot_equal_to_vanilla_writes_nothing(tmp_path):
    _require_corpus()
    vanilla = SC.load(None, icons=False).vanilla_members("major")
    with pytest.raises(ContentError, match="no slots"):
        _emit(tmp_path)
    assert _emit(tmp_path, slots={"major": {"items": vanilla, "count": 1}}) == []


_GRID_SCHEMA = """
[fields.shop]
type = "item-grid"
source = "shop-items"
number = { attr = "price", min = 0, max = 99999, editable = "priceEditable" }

[[fields.shop.sections]]
id = "minor"
accepts = { role = "offer" }
count = { min = 2, max = 4, default = 4 }

[[fields.shop.sections]]
id = "major_duplicate"
accepts = { role = "duplicate" }
"""


def test_config_names_an_item_grid_whose_value_replaces_slots_and_prices(tmp_path):
    _require_corpus()
    (tmp_path / "config_schema.toml").write_text(_GRID_SCHEMA)
    store = ConfigStore(tmp_path)
    # An untouched grid is the vanilla shop, whatever the manifest says.
    assert _emit(tmp_path, config="shop", prices={"Minor_Heal": 1}) == []
    store.set("shop", {"sections": {"minor": {"items": [_GRIMOIRE, S.ITEM_PREFIX + "Minor_Heal"],
                                             "count": 2}},
                       "numbers": {S.ITEM_PREFIX + "Minor_Shield": 7}})
    out = {p.name.split(".")[0]: p for p in _emit(tmp_path, config="shop")}
    assert set(out) == {_GRIMOIRE, S.ITEM_PREFIX + "Minor_Heal", S.ITEM_PREFIX + "Minor_Shield",
                        "NPC_Sandman"}
    assert _price(out[S.ITEM_PREFIX + "Minor_Shield"]) == 7
    assert S.read_offer_gens(out["NPC_Sandman"].read_bytes())["minor"].count == 2


def test_config_must_name_an_item_grid_of_shop_slots(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="must name an item-grid"):
        _emit(tmp_path, config="shop")
    (tmp_path / "config_schema.toml").write_text(
        _GRID_SCHEMA.replace('id = "major_duplicate"', 'id = "deluxe"'))
    with pytest.raises(ContentError, match="not shop slots"):
        _emit(tmp_path, config="shop")


def test_shop_items_provider_attrs(monkeypatch):
    _require_corpus()
    mirror_load = SC.load
    monkeypatch.setattr(SC, "load", lambda _game_dir, **kw: mirror_load(None, **kw))
    opts = {o["id"]: o for o in SC.options(Path("/any-install"))}
    assert opts[S.ITEM_PREFIX + "Minor_Heal"]["attrs"] == {
        "role": "offer", "price": 50, "priceEditable": True, "defaultIn": ["minor"]}
    assert opts[_GRIMOIRE]["attrs"]["defaultIn"] == []
    assert opts[_GRIMOIRE]["attrs"]["priceEditable"] is False


@pytest.mark.parametrize("fields, match", [
    ({}, "no slots"),
    ({"price": 5}, "unknown field"),
    ({"prices": {"Not_An_Item": 5}}, "not an item the Sandman can sell"),
    ({"prices": {_GRIMOIRE: 5}}, "no price of its own"),
    ({"slots": {"minor_object": {"count": 1}}}, "unknown slot"),
    ({"slots": {"minor": {"items": []}}}, "at least one item"),
    ({"slots": {"minor": {"count": 5}}}, "must be 2 to 4"),
    # The shop screen picks two different Minor offers; fewer crashes the game.
    ({"slots": {"minor": {"count": 1}}}, "crashes with fewer than 2"),
    ({"slots": {"minor": {"items": [_GRIMOIRE]}}}, "at least 2 items"),
    ({"offers": {"minor": {"count": 1}}}, "at least 2 items"),
    ({"offers": {"minor": {"pool": "Nothing_Has_This"}}}, "at least 2 items"),
    ({"slots": {"medium_duplicate": {"items": [_GRIMOIRE]}}}, "only takes object-copying"),
    ({"slots": {"minor": {"count": 2}}, "offers": {"minor": {"count": 3}}}, "in both"),
    ({"prices": {"Minor_Heal": -1}}, "cannot be negative"),
    ({"prices": {"Minor_Heal": 1.5}}, "whole number"),
    ({"offers": {"giant": {"count": 2}}}, "unknown generator"),
    ({"offers": {"minor": {"amount": 2}}}, "unknown field"),
    ({"offers": {"minor": {"count": 0}}}, "at least 1"),
    ({"offers": {"minor": {"weights": {"mythic": 1}}}}, "unknown quality"),
    ({"offers": {"minor": {"weights": {"powerup": 0}}}}, "all zero"),
    ({"offers": {"minor": {"pool": 3}}}, "must be a string"),
])
def test_mistakes_raise_instead_of_emitting_a_no_op(tmp_path, fields, match):
    _require_corpus()
    with pytest.raises(ContentError, match=match):
        _emit(tmp_path, **fields)


def test_a_reshaped_generator_is_refused():
    _require_corpus()
    import struct

    from rsmm.engine.talent_values import class_names

    raw = bytearray(_NPC.read_bytes())
    union = S._BEGIN + struct.pack("<I", class_names(bytes(raw)).index("oCEntityValueUnion"))
    name = S.GENERATORS["minor"].encode()
    at = raw.find(struct.pack("<I", len(name)) + name)
    first_union = raw.find(union, at)
    assert at > 0 and first_union > 0
    # Flip the count union's type code from int to f32: the layout no longer
    # matches the traced shape, so nothing may be written.
    assert raw[first_union + 8:first_union + 12] == (1).to_bytes(4, "little")
    raw[first_union + 8:first_union + 12] = (0).to_bytes(4, "little")
    with pytest.raises(ValueError, match="union layout"):
        S.read_offer_gens(bytes(raw))
