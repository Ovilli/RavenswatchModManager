"""The Hero tab's server side (`rsmm.cli.editor.herobuilder`): what the Pets
card and the Summon block pick from, and the burst names a save writes."""

from __future__ import annotations

import pytest

from rsmm.sdk.kinds import heros

needs_corpus = pytest.mark.skipif(not heros.shipped_heroes(), reason="no hero corpus")


def test_a_burst_names_the_heros_own_copy_when_saved_and_the_bases_when_shown():
    """The page lists the base's entities; a hero of its own spawns its renamed
    copy (Hero_Red_Bomb -> Hero_BloodWolf_Bomb, with the mod's edits)."""
    from rsmm.cli.editor.herobuilder import _bursts
    kit = {"pets": {"entity": "Enemies/Wolves/Standard_Wolf_Dire",
                    "burst": "Heroes/Hero_Red/Hero_Red_Bomb"},
           "special": {"replace": True, "steps": [
               {"summon": "Enemies/Wolves/Standard_Wolf_Timber",
                "burst": "Heroes/Hero_Red/Hero_Red_Bomb"},
               {"fire": "Heroes/Hero_Red/Hero_Red_Bomb"}]}}
    saved = _bursts(kit, "Hero_Red", "Hero_BloodWolf")
    assert saved["pets"]["burst"] == "Heroes/Hero_Red/Hero_BloodWolf_Bomb"
    assert saved["special"]["steps"][0]["burst"] == "Heroes/Hero_Red/Hero_BloodWolf_Bomb"
    # Only bursts: a fired projectile keeps the base's (shipped) entity.
    assert saved["special"]["steps"][1]["fire"] == "Heroes/Hero_Red/Hero_Red_Bomb"
    assert _bursts(saved, "Hero_BloodWolf", "Hero_Red") == kit


@needs_corpus
def test_the_pets_card_offers_enemies_their_attacks_and_the_bases_talents():
    from rsmm.cli.editor import herobuilder as HB
    paths = {e["path"] for e in HB.summonables()}
    assert "Enemies/Wolves/Standard_Wolf_Dire" in paths
    assert not any(p.endswith("_Model") for p in paths)
    dire = HB.enemy("Enemies/Wolves/Standard_Wolf_Dire")
    assert "Bite" in dire["attacks"] and dire["clips"]
    o = HB._pet_options("Red", HB._main("Red"))
    assert "Skill Secondary Quick Bombs" in o["talents"]
    assert "Wolf Secondary Ability Desc Format" in {c["part"] for c in o["cards"]}
    assert "Heroes/Hero_Red/Hero_Red_Bomb" in o["own_entities"]
    assert "State Wolf Secondary Ability" in HB._slot_states(HB._main("Red"), "special")
