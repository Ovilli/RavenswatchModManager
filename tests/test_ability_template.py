"""A shipped hero's button lent whole to a hero written from scratch
(engine/ability_template.py), and the shipped linking rules it relies on."""

from __future__ import annotations

import pytest

from rsmm.engine import hero_frame as HF


def _read(ref: str):
    from rsmm.engine import corpus
    return corpus.read("EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen")


def _corpus() -> bool:
    try:
        return _read(HF.HERO_COMMON) is not None and \
            _read("Heroes\\Hero_Red\\Hero_Red.entity.ot") is not None
    except Exception:  # noqa: BLE001
        return False


needs_corpus = pytest.mark.skipif(not _corpus(), reason="no hero corpus")


def _hero(scope: str = "Hero_T"):
    from rsmm.engine import talent_writer as TW
    from rsmm.engine.entity_graph_edit import EntityFile
    ef = EntityFile(HF.main_frame(f"Heroes\\{scope}\\{scope}_FX.entity.ot",
                                  HF.guid(scope, "main")), scope)
    TW.TalentWriter(ef, "k", "Kit").state(HF.KIT_EVENT, flags=TW.EVENT)
    return ef


def _lend(spec: str, slot: str, **knobs):
    from rsmm.engine import ability_template as AT
    ef, hc = _hero(), HF.common(_read)
    HF.fill_slot(ef, hc, slot, seed="t")
    lent = AT.lend(ef, hc, _read, AT.Template.parse(spec, knobs), slot_ctl=slot, seed="t",
                   sink=HF.KIT_EVENT)
    ef.set_ref(slot, "ref_2", lent.entry)
    return ef, hc, lent


@needs_corpus
def test_scarlets_wolf_bite_is_lent_whole():
    """The rush, the bite in reach, the bite clip and its recovery, intangible
    throughout, her effects (from Hero_Red_FX): all copied; her talents, UI
    and combo-point systems cut; nothing left that the hero cannot reach."""
    import re

    from rsmm.engine import ability_template as AT
    from rsmm.engine import entity_fields as EF
    ef, hc, lent = _lend("Red: Wolf Primary", "Primary Ability Controller")
    assert lent.entry == "State Wolf Primary Ability"
    parts = set(lent.parts)
    assert {"Wolf Primary Ability Clip Rush", "Wolf Primary Ability Clip Bite",
            "Wolf Primary Ability Instant Bite Tester", "Fx Wolf Bite"} <= parts
    assert not any(n.startswith("Skill ") for n in parts)      # her talents stay hers
    st = {f.name: f.text for f in EF.fields(ef.component("State Wolf Primary Ability"))}
    assert "Character_Common\\Base\\State Intangible" in st["while_active"]
    out = ef.to_bytes()
    assert not re.findall(rb"\] Hero_Red(?:_FX)?\\", out)       # no donor labels
    assert AT.unresolved(ef, hc, _read, only={ef.component(n).guid for n in lent.parts}) == []
    # the alt-form anim player became the plain one
    anim = {f.name: f.text for f in EF.fields(ef.component("Wolf Primary Ability Anim Bite"))}
    assert any("Main Anim Player" in v for v in anim.values())
    assert not any("Alt Form" in v for v in anim.values())


@needs_corpus
def test_a_lent_combo_links_its_button_by_the_base_slots_guid():
    ef, hc, lent = _lend("Geppetto: Basic Attack", "Basic Attack Controller")
    combo = next(n for n in lent.parts if ef.component(n).cls ==
                 "oCDtEntityCpntAttackComboSettings" and "Finisher" not in n)
    ctl = next(r for r in ef.component(combo).refs if "Controller" in r.path)
    assert ctl.guid == hc.component("Basic Attack Controller").guid


@needs_corpus
def test_template_knobs_set_numbers_and_swap_clips():
    from rsmm.engine import ability_template as AT
    from rsmm.engine import entity_fields as EF
    new = "Characters\\Heroes\\RED\\Animations\\Skills\\RED_Wolf_Attack_Flurry.fbx"
    ef, _hc, _l = _lend("Red: Wolf Primary", "Primary Ability Controller",
                        values={"Wolf Primary Ability Damage Multiplier Default": 1.0},
                        clips={"RED_Wolf_Pimary_Bite_Out": new})
    v = {f.name: f.text for f in EF.fields(ef.component(
        "Wolf Primary Ability Damage Multiplier Default"))}
    assert v["value"] == "f32 1"
    assert b"RED_Wolf_Attack_Flurry.fbx" in ef.component("Wolf Primary Ability Anim Bite").body
    with pytest.raises(AT.TemplateError, match="no part"):
        _lend("Red: Wolf Primary", "Primary Ability Controller", values={"Nope": 1})
    with pytest.raises(AT.TemplateError, match="plays no"):
        _lend("Red: Wolf Primary", "Primary Ability Controller", clips={"Nope.fbx": new})
    with pytest.raises(AT.TemplateError, match="no button"):
        _lend("Red: Flying Kick", "Primary Ability Controller")


@needs_corpus
def test_two_buttons_of_one_donor_share_their_common_parts():
    """Scarlet's bite and wolf combo both reach her combo-point parts: the
    second lend reuses the first one's copies instead of duplicating them."""
    from rsmm.engine import ability_template as AT
    ef, hc = _hero(), HF.common(_read)
    for spec, slot in (("Red: Wolf Primary", "Primary Ability Controller"),
                       ("Red: Wolf Basic", "Basic Attack Controller")):
        HF.fill_slot(ef, hc, slot, seed="t")
        lent = AT.lend(ef, hc, _read, AT.Template.parse(spec, {}), slot_ctl=slot, seed="t",
                       sink=HF.KIT_EVENT)
        ef.set_ref(slot, "ref_2", lent.entry)
    names = [c.name for c in ef.graph().components]
    assert len(names) == len(set(names))
    ef.to_bytes()


@needs_corpus
def test_timer_records_convert_between_18_and_19():
    """Update 6 added one picker after a timer's last field (version 1.9):
    copies convert both ways, and only an empty tail may be dropped."""
    from rsmm.engine import cooked
    from rsmm.engine import entity_components as EC
    raw = _read("Heroes\\Hero_Geppetto\\Hero_Geppetto.entity.ot")
    cf = cooked.parse(raw)
    up = EC.UPGRADES[("oCEntityCpntTimerSettings", (1, 8), (1, 9))]
    down = EC.UPGRADES[("oCEntityCpntTimerSettings", (1, 9), (1, 8))]
    rec = b"\x00" * 40
    assert down(up(rec, cf), cf) == rec
    pick = [c.name for c in cf.classes].index("oCEntityCpntPicker")
    set_tail = rec + cooked.MARK_BEGIN + pick.to_bytes(4, "little") + b"\x01" * 16 \
        + b"\x00" * 4 + cooked.MARK_END
    with pytest.raises(EC.EntityComponentError, match="tail link is set"):
        down(set_tail, cf)


@needs_corpus
def test_links_to_overrides_name_the_shared_parts_guid():
    """``link_overrides_by_base``: a link to the hero's override of a shared
    part names the SHARED part's GUID, as every shipped hero's does."""
    from rsmm.engine import hero_ability as HA
    ef, hc = _hero(), HF.common(_read)
    ab = HA.Ability.parse("attack", {"combo": [
        {"clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_BasicAttack01.fbx",
         "hits": [{}]},
        {"clip": "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_BasicAttack01.fbx",
         "hits": [{}]}]})
    HA.build(ef, hc, ab, seed="t")
    raw = ef.to_bytes()
    # break it the way 0.2 was, then fix it
    from rsmm.engine.entity_graph_edit import EntityFile
    e2 = EntityFile(raw, "Hero_T")
    own = e2.component("Basic Attack Controller").guid
    base = hc.component("Basic Attack Controller").guid
    combo = e2.component("Attack Ability Combo")
    p = e2.objects[combo.index - 1]
    p[:] = bytes(p).replace(base, own)
    broken = e2.to_bytes()
    assert HF.override_links(broken, "Hero_T", _read)
    fixed = HF.link_overrides_by_base(broken, "Hero_T", _read)
    assert HF.override_links(fixed, "Hero_T", _read) == []


@needs_corpus
def test_a_manifest_button_names_a_template():
    from rsmm.engine import hero_ability as HA
    ab = HA.Ability.parse("power", {"template": "Red: Wolf Primary", "cooldown": 6,
                                    "values": {"Wolf Primary Ability Target Max Distance": 9}})
    assert ab.template is not None and ab.cooldown == 6
    keep = HA.Ability.parse("power", {"template": "Red: Wolf Primary"})
    assert keep.cooldown < 0                        # the donor's own cooldown stays
    with pytest.raises(HA.AbilityError, match="template button takes"):
        HA.Ability.parse("power", {"template": "Red: Wolf Primary", "hits": [{}]})
    ef, hc = _hero(), HF.common(_read)
    assert HA.build(ef, hc, ab, seed="t", read=_read) == "State Wolf Primary Ability"


@needs_corpus
@pytest.mark.slow
def test_every_shipped_button_can_be_lent():
    """The catalog's every button lends into a hero written from scratch and
    leaves nothing the hero cannot reach (121 buttons at Update 6)."""
    from rsmm.engine import ability_template as AT
    from rsmm.engine import entity_graph as EG
    slots = {"Basic": "Basic Attack Controller", "Secondary": "Secondary Ability Controller",
             "Defensive": "Defensive Ability Controller", "Trait": "Trait Ability Controller",
             "Ultimate Power 1": "Ultimate Power 1 Controller",
             "Ultimate Power 2": "Ultimate Power 2 Controller"}
    entries = AT.catalog(_read)
    assert len(entries) > 100
    failed = []
    for e in entries:
        d = AT.Family(_read, e.hero).main
        ctl = AT.controllers(d)[e.button].name
        slot = next((v for k, v in slots.items() if k in ctl), "Primary Ability Controller")
        try:
            ef, _hc, _l = _lend(f"{e.hero}: {e.button}", slot)
            EG.parse(ef.to_bytes(), "Hero_T")
        except Exception as x:  # noqa: BLE001 — collect every failure
            failed.append(f"{e.hero}: {e.button}: {x}")
    assert failed == []
