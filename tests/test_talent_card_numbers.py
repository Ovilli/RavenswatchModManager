"""Every number a talent card shows should be editable where the game keeps it.

The Ice Clone card (Snow Queen, ``Defense Clone``) is the case that was wrong in
all three ways at once; needs the shipped heroes (mirror or install).
"""

from __future__ import annotations

import pytest

from rsmm.cli.editor import content as C
from rsmm.engine import corpus
from rsmm.engine import talent_values as TV

_HERO = "Snow_Queen"
_MAIN = "EntitySettings/Heroes/Hero_Snow_Queen/Hero_Snow_Queen.entity.ot.EntitySettingsResource.gen"


@pytest.fixture(scope="module")
def card():
    if corpus.read(_MAIN) is None:
        pytest.skip("shipped heroes not available (no mirror, no install)")
    cards = {c["source"]: c for c in C.talent_cards(_HERO)}
    return cards["Defense Clone"]


def test_a_plain_value_the_card_names_is_listed_even_though_its_name_is_not_whitelisted(card):
    """``... Lifetime`` is a real authored number; the generic list keeps it out
    by name, the card is what admits it."""
    assert {"file": "Hero_Snow_Queen", "label": "Skill Defense Clone Lifetime"} in card["values"]
    main = next(f for f in C.talent_values(_HERO) if f["file"] == "Hero_Snow_Queen")
    assert "Skill Defense Clone Lifetime" in {v["label"] for v in main["values"]}


def test_a_computed_node_reaches_the_selector_it_reads(card):
    op = next(e for e in card["entries"] if e and e["kind"] == "Multi values operations")
    assert op["tierNode"] == "Skill Defense Clone Damage Multiplier Selector"
    assert {t: v["value"] for t, v in op["tiers"].items()} == {
        "Common": 4.0, "Rare": 6.0, "Epic": 8.0, "Legendary": 10.0}


def test_a_selector_with_one_number_is_editable_as_a_single(card):
    sel = next(e for e in card["entries"] if e and e["kind"] == "Value Selector")
    assert "tiers" not in sel
    assert sel["tierNode"] == sel["node"]
    assert sel["single"]["value"] == pytest.approx(0.4)
    # ... and the index it hands back is one set_union_value writes.
    raw = corpus.read(_MAIN)
    out = TV.set_union_value(raw, sel["node"], sel["single"]["index"], 0.55, expect=0.4)
    written = TV.list_union_values(out, sel["node"])[sel["single"]["index"]][1]
    assert written == pytest.approx(0.55, abs=1e-6)


def test_a_card_value_can_be_patched_by_its_label():
    raw = corpus.read(_MAIN)
    if raw is None:
        pytest.skip("shipped heroes not available (no mirror, no install)")
    label = "Skill Defense Clone Lifetime"
    old = next(v.value for v in TV.list_talent_values(raw, extra_labels=(label,))
               if v.label == label)
    out = TV.set_talent_value(raw, label, old + 1, expect=old)
    assert next(v.value for v in TV.list_talent_values(out, extra_labels=(label,))
                if v.label == label) == pytest.approx(old + 1)


def test_the_card_numbers_that_cannot_be_traced_stay_few():
    """Across every hero, placeholders left as 'worked out in game' were 144 of
    460 before selector sources and name-admitted values; a regression here
    means a card quietly lost its editable numbers again."""
    if corpus.read(_MAIN) is None:
        pytest.skip("shipped heroes not available (no mirror, no install)")
    unresolved = named = 0
    for hero in C.heroes():
        labels = {(f["file"], v["label"]) for f in C.talent_values(hero) for v in f["values"]}
        for c in C.talent_cards(hero):
            for e in c["entries"]:
                if e is None:
                    continue
                named += 1
                if e.get("tiers") or e.get("single"):
                    continue
                names = [e["node"]] if e["kind"] == "Value" else e["sources"]
                if not any((c["file"], n) in labels for n in names):
                    unresolved += 1
    assert named > 300
    assert unresolved <= 40, f"{unresolved} of {named} card placeholders have nothing editable"
