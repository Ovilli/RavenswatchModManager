"""Which stat an item's effects give, and its super-effect text.

The stat is a 4-byte key inside each modifier record; changing it must touch
those 4 bytes and nothing else. Needs the shipped items (mirror or install)
for everything but the catalog lookups.
"""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import item_modifier as IM
from rsmm.engine import magic_item_cook as C

_MO = "EntitySettings/Objects/Magical_Objects"
_SUFFIX = ".entity.ot.EntitySettingsResource.gen"


def _item(rarity: str, item_id: str) -> bytes:
    data = corpus.read(f"{_MO}/{rarity}/{item_id}{_SUFFIX}")
    if data is None:
        pytest.skip("shipped items not available (no mirror, no install)")
    return data


# --- the catalog ---------------------------------------------------------------

def test_a_stat_resolves_by_name_any_case_or_by_key():
    assert IM.resolve_stat("Crit chance") == IM.resolve_stat("CRIT CHANCE")
    assert IM.resolve_stat("0x15c7d482") == 0x15C7D482
    assert IM.resolve_stat(0x15C7D482) == 0x15C7D482


def test_armour_keeps_its_zero_key():
    """The Lua table drops key 0; items store exactly 0 for armour."""
    assert IM.resolve_stat("Armour") == 0
    assert IM.stat_name(0) == "Armour"


@pytest.mark.parametrize("bad", ["Crit chanse", "0xnope", "0x1ffffffff", True, -1])
def test_an_unknown_stat_is_refused(bad):
    with pytest.raises(IM.ItemModifierError):
        IM.resolve_stat(bad)


# --- reading and writing an item -----------------------------------------------------

def test_an_items_effects_and_super_effect_are_listed():
    mods = IM.list_modifiers(_item("Common", "Damage_Per_Vitality"))
    assert [(m.name, m.stat, m.super_effect) for m in mods] == [
        ("Damage Modifier", "Attack power", False),
        ("Super Effect Modifier", "Crit chance", True),
    ]


def test_changing_a_stat_touches_only_its_four_bytes():
    data = _item("Common", "Damage_Per_Vitality")
    out = IM.set_modifier_stat(data, "Super Effect Modifier", "Crit damage")
    assert len(out) == len(data)
    assert sum(a != b for a, b in zip(data, out, strict=True)) <= 4
    stats = {m.name: m.stat for m in IM.list_modifiers(out)}
    assert stats == {"Damage Modifier": "Attack power", "Super Effect Modifier": "Crit damage"}


def test_a_missing_modifier_names_the_ones_there_are():
    with pytest.raises(IM.ItemModifierError, match="'Damage Modifier'"):
        IM.set_modifier_stat(_item("Common", "Damage_Per_Vitality"), "Nope", "Armour")


def test_the_super_text_key_is_found_and_repointed():
    data = _item("Common", "Damage_Per_Vitality")
    assert IM.super_text_key(data) == "Crit_Chance_SuperEffect"
    out = IM.set_super_text_key(data, "Zz_Own_Item_SuperEffect")
    assert IM.super_text_key(out) == "Zz_Own_Item_SuperEffect"
    assert b"Crit_Chance_SuperEffect" not in out


def test_an_item_without_super_text_says_so():
    data = _item("Powerups", "Power_Up_Damage")
    assert IM.super_text_key(data) is None
    with pytest.raises(IM.ItemModifierError):
        IM.set_super_text_key(data, "X_SuperEffect")


def test_every_shipped_modifier_can_be_retargeted():
    files = corpus.files(f"{_MO}/Common", _SUFFIX)
    if not files:
        pytest.skip("shipped items not available (no mirror, no install)")
    for rarity in ("Common", "Rare", "Epic", "Legendary", "Cursed", "Powerups"):
        for f in corpus.files(f"{_MO}/{rarity}", _SUFFIX):
            data = f.read_bytes()
            for m in IM.list_modifiers(data):
                out = IM.set_modifier_stat(data, m.name, "Vitality")
                assert len(out) == len(data), (f, m.name)


# --- the item copy -------------------------------------------------------------------

def _copy(base_rarity: str, base_id: str, new_id: str, **kw) -> bytes:
    files = C.build_magic_item(new_id=new_id, base_id=base_id,
                               base_cooked=_item(base_rarity, base_id), corpus=[],
                               rarity=base_rarity, **kw)
    [ent] = [b for p, b in files.items() if p.endswith(_SUFFIX)]
    return ent


def test_a_copy_gets_its_new_stats():
    ent = _copy("Common", "Damage_Per_Vitality", "Damage_Per_Vitality2",
                modifier_stats={"Super Effect Modifier": "Armour"})
    assert {m.name: m.stat for m in IM.list_modifiers(ent)}["Super Effect Modifier"] == "Armour"


def test_a_copy_keeps_the_bases_super_text_when_it_has_none_of_its_own():
    """`Defense_To_Damage_SuperEffect` embeds the base id; the id rename used to
    turn it into a key no bank holds, so the copy showed blank text."""
    ent = _copy("Common", "Defense_To_Damage", "Defense_To_Damag2")
    assert IM.super_text_key(ent) == "Defense_To_Damage_SuperEffect"


def test_a_copy_with_super_text_reads_its_own_key():
    ent = _copy("Common", "Defense_To_Damage", "Defense_To_Damag2",
                super_description="Gain armour.")
    assert IM.super_text_key(ent) == "Defense_To_Damag2_SuperEffect"


def test_super_text_on_an_item_without_a_super_effect_is_refused():
    with pytest.raises(ValueError, match="no super effect text"):
        _copy("Powerups", "Power_Up_Damage", "Power_Up_Damag2", super_description="x")


def _refs(ent: bytes, comp: str) -> dict[str, str]:
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    return {f.name: f.text for f in EF.fields(EntityFile(ent, "x").component(comp))}


def test_steps_scope_an_on_hit_modifier_to_a_timer():
    """Increase_Shield copied as a crit item kept its permanent on-hit modifier,
    so crit stacked for the whole run (bug report 2026-10-20). Hung on the hit
    state it lasted ~1 s: that is an event state. The window is a lasting state
    the hit switches on, running the timer that ends it and the modifier."""
    ent = _copy("Rare", "Increase_Shield", "Increase_Crit_M", steps=[
        {"remove_link": "On Damage Received.activates[1]"},
        {"add_link": "On Damage Received.activates", "to": "State Is In Cooldown"},
        {"add_link": "State Is In Cooldown.while_active", "to": "Shield Reload Timer"},
        {"add_link": "State Is In Cooldown.while_active", "to": "Modifier"},
        {"set": "Modifier.duration", "value": 0.0},
        {"link": "Shield Reload Timer.state", "to": "State Is In Cooldown"},
        {"link": "Modifier.amount", "to": "Shield Value"},
    ])
    hit = _refs(ent, "On Damage Received")
    assert "Modifier" not in hit["activates"] and "State Is In Cooldown" in hit["activates"]
    window = _refs(ent, "State Is In Cooldown")["while_active"]
    assert "Shield Reload Timer" in window and window.endswith("\\Modifier")
    assert _refs(ent, "Shield Reload Timer")["state"].endswith("\\State Is In Cooldown")
    mod = _refs(ent, "Modifier")
    assert mod["duration"] == "f32 0"
    assert mod["amount"].endswith("\\Shield Value")


def test_a_copy_with_its_own_text_reads_its_own_keys():
    """Increase_Shield's description key does not embed its id, so the rename
    left the copy reading the shield's text ("gain 0 shield", 2026-10-20)."""
    ent = _copy("Rare", "Increase_Shield", "Increase_Crit_M", name="P", description="D")
    keys = C.text_keys(ent)
    assert "Increase_Crit_M_Description" in keys and "Increase_Crit_M_Name" in keys
    assert "Shield_Gain_When_Hit_Description" not in keys


def test_a_copy_without_its_own_text_keeps_the_bases_keys():
    keys = C.text_keys(_copy("Rare", "Increase_Shield", "Increase_Crit_M"))
    assert "Shield_Gain_When_Hit_Description" in keys


def test_a_copy_can_drop_its_super_effect():
    """Little Thumb Pebbles never had a super effect; its Increase_Shield base
    does (a healing bonus)."""
    ent = _copy("Rare", "Increase_Shield", "Increase_Crit_M", super_effect=False)
    assert "Super Effect Modifier" not in _refs(ent, "Child State Super Effect")["while_active"]
    # The model's empty text, not a key with a blank row: the card prints a
    # blank row's key ("x5 Increase_Crit_M_SuperEffect", playtest 2026-10-20).
    assert IM.super_text_key(ent) is None
    fmt = _refs(ent, "Super Effect Descripton Format")
    assert fmt["value_2"].endswith("ff ff ff ff 00 00 00 00") and "obj_4" not in fmt


def test_a_step_shows_a_card_number_as_a_percentage():
    """A shield's card shows its amount plain: a 0.3 crit bonus read "+0%"."""
    from rsmm.engine import entity_fields as EF
    from rsmm.engine.entity_graph_edit import EntityFile
    ent = _copy("Rare", "Increase_Shield", "Increase_Crit_M",
                steps=[{"percent": "Descripton Format.obj_4", "value": True}])
    c = EntityFile(ent, "x").component("Descripton Format")
    modes = [c.body[f.offset + f.size - 8] for f in EF.fields(c) if f.name in ("obj_4", "obj_5")]
    assert modes == [1, 0]


def test_dropping_a_super_effect_refuses_super_text_and_bases_without_one():
    with pytest.raises(ValueError, match="drop super_description"):
        _copy("Rare", "Increase_Shield", "Increase_Shiel2", super_effect=False,
              super_description="x")
    with pytest.raises(ValueError, match="no super effect"):
        _copy("Powerups", "Power_Up_Damage", "Power_Up_Damag2", super_effect=False)


def test_parts_cloned_from_another_item_link_to_each_other_by_this_items_name():
    """Pebbles' timed crit copies Dash_Crit_Chance's tester, timer and modifier.
    A copied link to an UNGROUPED copy kept the donor's label
    (`[Modifier] Dash_Crit_Chance\\Crit Chance Modifier`)."""
    ent = _copy("Rare", "Increase_Shield", "Increase_Crit_M", steps=[
        {"clone": ["Crit Chance Modifier Active Tester", "Crit Chance Modifier Timer",
                   "Crit Chance Modifier"],
         "from": "Objects/Magical_Objects/Common/Dash_Crit_Chance", "suffix": " P"},
        {"add_link": "State Picked Up.while_active", "to": "Crit Chance Modifier Active Tester P"},
        # The donor's numbers were not copied: read this item's instead.
        {"link": "Crit Chance Modifier Timer P.duration", "to": "Shield Reload Delay"},
        {"link": "Crit Chance Modifier P.amount", "to": "Shield Value"},
    ])
    assert b"Dash_Crit_Chance\\" not in ent
    assert _refs(ent, "Crit Chance Modifier Active Tester P")["ref_6"] \
        == "<- [Modifier] Increase_Crit_M\\Crit Chance Modifier P"


def test_a_bad_step_names_the_step():
    with pytest.raises(ValueError, match="step 1"):
        _copy("Rare", "Increase_Shield", "Increase_Shiel2",
              steps=[{"link": "Nope.state", "to": "Modifier"}])


# --- card text placeholders -----------------------------------------------------------

def test_a_card_text_names_what_fills_each_placeholder():
    formats = IM.card_formats(_item("Common", "Damage_Per_Vitality"))
    desc = formats["Descripton Format"]
    assert desc.key == "Damage_Per_Vitality_Description"
    assert [(e.node, e.kind) for e in desc.entries] == [
        ("Damage Value Desc Operation", "Multi values operations"),
        ("Vitality Step Value", "Value"),
        ("Current Value Description Selector", "Value Selector"),
    ]
    # A computed placeholder says which plain values it is worked out from.
    assert desc.entries[0].sources == ("Damage Value",)
    sup = formats["Super Effect Descripton Format"]
    assert sup.key == "Crit_Chance_SuperEffect"
    assert [e.node for e in sup.entries] == ["Super Effect Crit Chance Value"]


def test_an_inline_placeholder_is_unnamed_and_its_neighbours_still_are():
    """Copy_Card's heal line mixes a node with an inline value; each entry is
    read on its own, so only the inline one is left unnamed."""
    formats = IM.card_formats(_item("Epic", "Copy_Card"))
    first, second = formats["Current Heal Desc Format"].entries
    assert first.node == "Scalable Heal operations" and second is None
    # Only String Format components count: selectors that name a key are not texts.
    assert "Description Selector" not in formats


def test_every_shipped_card_text_parses():
    for rarity in ("Common", "Rare", "Epic", "Legendary", "Cursed", "Powerups"):
        for f in corpus.files(f"{_MO}/{rarity}", _SUFFIX):
            for fmt in IM.card_formats(f.read_bytes()).values():
                assert len(fmt.entries) <= 64, (f, fmt.key)


# --- data-defined stats -----------------------------------------------------------

@pytest.mark.parametrize("label, key", [
    ("Basic Attack Speed", 0x058E0A5C),     # Ace of Spades' super effect
    ("Has Excalibur", 0x4F045BBB),
    ("Has Holy Grail", 0x41D55285),
])
def test_a_data_value_is_keyed_by_its_label(label, key):
    """No game files needed: the key is the engine's name hash of the label."""
    assert IM.data_value_key(label) == key


def test_data_values_from_the_install_join_the_stat_list():
    IM.data_value_names.cache_clear()
    if not IM.data_value_names():
        pytest.skip("no readable install (ApplicationSettings.ot)")
    assert IM.resolve_stat("basic attack speed") == 0x058E0A5C
    assert IM.stat_name(0x058E0A5C) == "Basic Attack Speed"
    # The engine's own names win where both exist.
    assert IM.stat_name(IM.resolve_stat("Attack power")) == "Attack power"
    mods = IM.list_modifiers(_item("Rare", "Damage_Attack"))
    assert {m.name: m.stat for m in mods}["Super Effect Modifier"] == "Basic Attack Speed"


def test_a_copy_without_its_own_text_reads_the_bases_keys():
    """The id rename turns `Damage_Per_Vitality_Name` into a key no bank holds,
    which the game shows as blank; a copy with no name/description keeps the
    base's keys, and one with its own text points at its own."""
    def keys(**kw):
        ent = _copy("Common", "Damage_Per_Vitality", "Damage_Per_Vitalitz", **kw)
        return {s for _o, s in C.find_lstrings(ent) if s.endswith(("_Name", "_Description"))}
    assert keys() == {"Damage_Per_Vitality_Description", "Damage_Per_Vitality_Name"}
    assert keys(name="X") == {"Damage_Per_Vitality_Description", "Damage_Per_Vitalitz_Name"}
    assert keys(description="D") == {"Damage_Per_Vitalitz_Description", "Damage_Per_Vitality_Name"}


# --- the tier --------------------------------------------------------------------

def test_every_shipped_items_quality_matches_its_folder():
    """The tier the game reads is the Quality int, not the folder; the mapping
    the cooker writes must hold for every shipped item that has one."""
    _item("Common", "Armor_Per_Object")
    for rarity, q in C.QUALITY.items():
        for f in corpus.files(f"{_MO}/{rarity}", _SUFFIX):
            try:
                assert C.get_quality(f.read_bytes()) == q, f.name
            except ValueError:
                pass  # the few non-items in Powerups/Cursed carry no Quality


@pytest.mark.parametrize("rarity", ["Common", "Epic", "Legendary"])
def test_a_copy_takes_the_tier_it_asks_for(rarity):
    """A Rare base copied as another rarity stayed Rare in game (2026-10-18):
    only its folder moved. The Quality int must move with it."""
    files = C.build_magic_item(new_id="Increase_Shiel2", base_id="Increase_Shield",
                               base_cooked=_item("Rare", "Increase_Shield"),
                               corpus=[], rarity=rarity,
                               base_rarity="Rare")
    [(path, ent)] = [(p, b) for p, b in files.items() if p.endswith(_SUFFIX)]
    assert f"/{rarity}/" in path
    assert C.get_quality(ent) == C.QUALITY[rarity]


def test_a_copy_at_its_bases_tier_is_left_byte_identical():
    base = _item("Rare", "Increase_Shield")
    assert C.set_quality(base, "Rare") is base
