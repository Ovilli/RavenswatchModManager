"""Components written from field values (``entity_parts``) are the game's own.

The codec must reproduce every shipped component of the classes it writes byte
for byte, and the parts ``item_effect`` writes must be what the shipped items
that react to each trigger carry. Shipped files are only the reference here:
an item built from ``effects`` reads none of them.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import cooked, corpus
from rsmm.engine import entity_graph as EG
from rsmm.engine import entity_parts as P
from rsmm.engine import item_effect as IE
from rsmm.engine import magic_item_cook as C
from rsmm.engine.entity_graph_edit import EntityFile

_MO = "EntitySettings/Objects/Magical_Objects/"
_SHIELD = _MO + "Rare/Increase_Shield.entity.ot.EntitySettingsResource.gen"


def _roundtrip(rels) -> int:
    n = 0
    for rel in rels:
        raw = corpus.read(rel)
        if not raw:
            continue
        ci = [c.name for c in cooked.parse(raw).classes].index
        for c in EG.parse(raw).components:
            if c.cls in P.ROUNDTRIP:
                assert P.encode(c.cls, P.decode(c), ci) == c.body, (rel, c.name)
                n += 1
    return n


def test_every_item_component_round_trips():
    rels = corpus.rels(_MO, ".EntitySettingsResource.gen")
    if not rels:
        pytest.skip("shipped items not available (no mirror, no install)")
    assert _roundtrip(rels) > 500


@pytest.mark.slow
def test_every_shipped_component_round_trips():
    """2026-10-22: 26,133 components of the eight classes, all exact."""
    rels = corpus.rels("EntitySettings/", ".EntitySettingsResource.gen")
    if not rels:
        pytest.skip("shipped entities not available")
    assert _roundtrip(rels) > 20000


#: The shipped item each trigger's listener was read from (reference only).
_SHIPPED = {
    "damage_taken": "Rare/Increase_Shield", "dash": "Common/Dash_Crit_Chance",
    "special": "Epic/Secondary_Gain_Charge", "defense": "Legendary/Defense_Heal",
    "ultimate": "Epic/Reduce_Ultimate_CD", "power": "Legendary/Clear_Dash_Cooldown_On_Defense",
    "day_start": "Legendary/Full_Heal_At_Day_Night",
    "night_start": "Legendary/Full_Heal_At_Day_Night",
    "talent_picked": "Legendary/Upgrade_All_Talents_Once",
    "item_picked_up": "Cursed/Destroy_Legendary_To_Damage",
    "dream_shards_gained": "Cursed/Curse_Stack_Shard_Quest",
    "sandman_purchase": "Common/Reduce_Dream_Shard_Price",
    "reroll": "Common/Reroll_To_Dream_Shards",
}


def _shield() -> bytes:
    raw = corpus.read(_SHIELD)
    if raw is None:
        pytest.skip("shipped items not available (no mirror, no install)")
    return raw


def _build(effects) -> bytes:
    files = C.build_magic_item(new_id="Written_Item_X", base_id="Increase_Shield",
                               base_cooked=_shield(), corpus=[], rarity="Rare",
                               effect=effects, super_effect=False)
    return next(b for p, b in files.items() if p.endswith(".EntitySettingsResource.gen"))


def _listener(raw: bytes, name: str):
    """(header flags, group, settings with class names, firing slots)."""
    ef = EntityFile(raw, "x")
    c = ef.component(name)
    p = bytes(ef.objects[c.index - 1])
    head = len(p) - len(c.body)
    flags = struct.unpack_from("<I", p, head - 8 - len(c.group.encode("latin-1")))[0]
    v = P.decode(c)
    names = [k.name for k in ef.cf.classes]
    raw_settings, settings, i = v["listener"], b"", 0
    while (j := raw_settings.find(cooked.MARK_BEGIN, i)) >= 0:   # class tags -> names
        ci = struct.unpack_from("<I", raw_settings, j + 4)[0]
        settings += raw_settings[i:j + 4] + names[ci].encode()
        i = j + 8
    settings += raw_settings[i:]
    return flags, c.group, settings, {s for s in ("ref_3", "ref_4", "ref_5") if not v[s].empty}


@pytest.mark.parametrize("on", sorted(IE.TRIGGERS))
def test_each_trigger_listener_is_the_shipped_one(on):
    t = IE.TRIGGERS[on]
    shipped = corpus.read(f"{_MO}{_SHIPPED[on]}.entity.ot.EntitySettingsResource.gen")
    if shipped is None:
        pytest.skip("shipped items not available")
    built = _build([{"stat": "Crit chance", "amount": 0.3, "seconds": 5, "on": on}])
    assert _listener(built, t.listener + IE.SUFFIX) == _listener(shipped, t.listener)


def test_an_item_built_from_effects_names_no_other_item():
    """Its parts are written, not copied: nothing points into a donor."""
    effects = [{"stat": "Armour", "amount": 5, "percent": False},
               *({"stat": "Crit chance", "amount": 0.1, "seconds": 3, "on": on}
                 for on in sorted(IE.TRIGGERS))]
    built = _build(effects)
    for rel in _SHIPPED.values():
        stem = rel.rsplit("/", 1)[1]
        if stem != "Increase_Shield":                  # the frame itself
            assert stem.encode() not in built, stem
    refs = {r.scope for c in EG.parse(built).components for r in c.refs}
    assert refs <= {"Written_Item_X", "Magical_Objects_Model", "Character_Common"}, refs


# --- the frame an item with no base is written on ------------------------------

def _blank(item_id: str, effects, super_effects=None) -> bytes:
    from rsmm.engine import item_frame
    from rsmm.engine.entity_check import _corpus_reader
    _shield()
    files = C.build_magic_item(new_id=item_id, base_id=item_frame.FRAME_ID,
                               base_cooked=item_frame.build(_corpus_reader), corpus=[],
                               rarity="Rare", effect=effects, remint_identity=True,
                               name="x", description="x", super_effects=super_effects)
    return next(b for p, b in files.items() if p.endswith(".EntitySettingsResource.gen"))


def test_the_frame_overrides_the_models_slots_and_nothing_else():
    from rsmm.engine import item_frame
    from rsmm.engine.entity_check import _corpus_reader
    _shield()
    comps = EG.parse(item_frame.build(_corpus_reader)).components
    assert {(c.name, c.override.path if c.override else None) for c in comps} == {
        ("State Picked Up", "[State] Magical_Objects_Model\\Child State Equiped"),
        ("Dt Magical Object Data", None),
        ("Descripton Format", "[String Format] Magical_Objects_Model\\Descripton Format"),
        ("Icon Value", "[Value] Magical_Objects_Model\\Icon"),
        ("Name Value", "[Value] Magical_Objects_Model\\Name"),
        ("Quality Value", "[Value] Magical_Objects_Model\\Quality")}


def test_a_blank_item_is_written_whole_and_reads_only_the_model():
    from rsmm.engine import entity_check as CK
    from rsmm.engine import item_frame
    effects = [{"stat": "Crit chance", "amount": 0.1},
               {"stat": "Armour", "amount": 3, "seconds": 5, "on": "damage_taken",
                "percent": False}]
    ent = _blank("Wanderers_Charm", effects)
    assert item_frame.FRAME_ID.encode() not in ent
    scopes = {r.scope for c in EG.parse(ent).components for r in c.refs}
    scopes |= {c.override.scope for c in EG.parse(ent).components if c.override}
    assert scopes <= {"Wanderers_Charm", "Magical_Objects_Model", "Character_Common"}
    assert not [i for i in CK.check(ent, None, name="Wanderers_Charm") if i.error]


def test_two_blank_items_get_their_own_identity_and_save_id():
    a = _blank("Charm_One", [{"stat": "Crit chance", "amount": 0.1}])
    b = _blank("Charm_Two", [{"stat": "Crit chance", "amount": 0.1}])
    assert C.find_type_guid(a) != C.find_type_guid(b)
    assert C.find_identity_guid(a, "Charm_One") != C.find_identity_guid(b, "Charm_Two")


@pytest.mark.parametrize(("during", "shipped_tester"), [
    ("day", "Is Daytime Tester"),
    ("night", "Is Nighttime Tester"),
])
def test_day_and_night_bool_tests_match_character_common(during, shipped_tester):
    """The day/night bool test is byte for byte Character_Common's Is Daytime
    Tester / Is Nighttime Tester sub-object (which Scarlet and Piper read)."""
    cc = corpus.read(
        "EntitySettings/Character_Common/Character_Common.entity.ot.EntitySettingsResource.gen")
    if cc is None:
        pytest.skip("Character_Common not available")

    def sub_norm(raw: bytes, comp_name: str):
        ef = EntityFile(raw, "x")
        c = ef.component(comp_name)
        v = P.decode(c)
        sub_id = struct.unpack_from("<I", v["test"], 14)[0]
        raw_sub = bytes(ef.objects[sub_id])
        names = [k.name for k in ef.cf.classes]
        out, i = names[struct.unpack_from("<I", raw_sub, 0)[0]].encode(), 4
        while (j := raw_sub.find(cooked.MARK_BEGIN, i)) >= 0:
            ci = struct.unpack_from("<I", raw_sub, j + 4)[0]
            out += raw_sub[i:j + 4] + names[ci].encode()
            i = j + 8
        return out + raw_sub[i:]

    built = _build([{"stat": "Crit chance", "amount": 0.2, "during": during}])
    assert (sub_norm(built, "Crit Chance Modifier Active Tester" + IE.SUFFIX)
            == sub_norm(cc, shipped_tester))

# --- super effects ---------------------------------------------------------------

def _super_state_refs(ent: bytes, item_id: str) -> list[str]:
    from rsmm.engine import entity_fields as EF
    ef = EntityFile(ent, item_id)
    f = next(x for x in EF.fields(ef.component("Child State Super Effect"))
             if x.name == "while_active")
    return [i.text.rstrip().rsplit("\\", 1)[-1] for i in f.items]


def test_a_blank_item_gets_the_models_super_slots_and_runs_its_super_effects():
    from rsmm.engine import entity_check as CK
    from rsmm.engine import item_modifier as IM
    supers = [{"stat": "Attack power", "amount": 0.2},
              {"stat": "Crit damage", "amount": 0.3, "seconds": 4, "on": "dash"}]
    ent = _blank("Super_Charm", [{"stat": "Crit chance", "amount": 0.1}], supers)
    over = {c.name: c.override.path for c in EG.parse(ent).components if c.override}
    assert over["Child State Super Effect"].endswith("\\Child State Super Effect")
    assert over["Super Effect Descripton Format"].endswith("\\Super Effect Descripton Format")
    assert IM.super_text_key(ent) == "Super_Charm_SuperEffect"
    mods = {m.name: m.super_effect for m in IM.list_modifiers(ent)}
    assert mods == {"Crit Chance Modifier Effect": False,
                    "Crit Chance Modifier Super Effect": True,
                    "Crit Chance Modifier Super Effect 2": True}
    # The always-on one is held by the super state; the timed one listens there.
    assert set(_super_state_refs(ent, "Super_Charm")) == {
        "Crit Chance Modifier Super Effect", "On Dash Event Listener Super Effect 2",
        "Crit Chance Modifier Active Tester Super Effect 2"}
    ef = EntityFile(ent, "Super_Charm")
    assert len(ef._format_slots(ef.component("Super Effect Descripton Format"))[0]) == 3
    assert not [i for i in CK.check(ent, None, name="Super_Charm") if i.error]


def test_super_effects_replace_the_bases_own():
    from rsmm.engine import item_modifier as IM
    from rsmm.engine.entity_check import _corpus_reader
    raw = _corpus_reader("Objects\\Magical_Objects\\Rare\\Damage_Attack.entity.ot")
    if raw is None:
        pytest.skip("shipped items not available (no mirror, no install)")
    files = C.build_magic_item(new_id="Ace_Two", base_id="Damage_Attack", base_cooked=raw,
                               corpus=[], super_effects=[{"stat": "Crit chance", "amount": 0.05}])
    ent = next(b for p, b in files.items() if p.endswith(".EntitySettingsResource.gen"))
    assert _super_state_refs(ent, "Ace_Two") == ["Crit Chance Modifier Super Effect"]
    assert {m.name for m in IM.list_modifiers(ent) if m.super_effect} >= {
        "Crit Chance Modifier Super Effect"}
