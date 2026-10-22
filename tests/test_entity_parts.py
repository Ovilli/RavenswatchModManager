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
