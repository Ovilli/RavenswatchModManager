"""The animatic and level-scaling ability steps (PR #149): `add_cinebloc`,
`animatic_speed`, `scale_with_level`, on a shipped hero."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import ability_edit as AE
from rsmm.engine import entity_check as EC
from rsmm.engine import entity_graph as EG

_RED = "EntitySettings/Heroes/Hero_Red/Hero_Red.entity.ot.EntitySettingsResource.gen"


def _raw():
    from rsmm.engine import corpus
    try:
        return corpus.read(_RED)
    except Exception:  # noqa: BLE001
        return None


needs_corpus = pytest.mark.skipif(_raw() is None, reason="no hero corpus")


def _apply(steps):
    raw = _raw()
    out = AE.apply({"Hero_Red": raw}, steps, main="Hero_Red", seed="t").files["Hero_Red"]
    assert EC.check(out, raw, name="Hero_Red") == []
    return out


def _timeline(ef, comp):
    """(bloc count, duration, play rate) of animatic ``comp``."""
    from rsmm.engine.entity_graph_edit import _B
    c, f, at = ef._field(comp, "bytes_8")
    p = ef.objects[c.index - 1]
    pos = p.find(_B + struct.pack("<I", [x.name for x in ef.cf.classes].index("oCCinematic")))
    n = struct.unpack_from("<I", p, pos + 8)[0]
    return (n, struct.unpack_from("<f", p, pos + 12 + 4 * n)[0],
            struct.unpack_from("<f", p, at + f.offset)[0])


@needs_corpus
def test_a_cine_bloc_is_added_at_its_start_and_the_animatic_rate_rescales_its_length():
    from rsmm.engine.entity_graph_edit import EntityFile
    anim = "Dash Ability Anim"
    n0, dur0, rate0 = _timeline(EntityFile(_raw(), "Hero_Red"), anim)
    out = _apply([
        {"add_cinebloc": anim, "to": "Agressive Defense FMod Event Active", "value": 0.2},
        {"animatic_speed": anim, "value": 2.0}])
    ef = EntityFile(out, "Hero_Red")
    n1, dur1, rate1 = _timeline(ef, anim)
    assert n1 == n0 + 1
    _c, sub = ef._cinebloc(anim, n0)
    assert struct.unpack_from("<f", ef.objects[sub], 4)[0] == pytest.approx(0.2)
    assert rate1 == 2.0
    assert dur1 == pytest.approx(dur0 * (rate0 if rate0 > 0 else 1.0) / 2.0)
    with pytest.raises(AE.AbilityEditError, match="value"):
        _apply([{"animatic_speed": anim}])
    with pytest.raises(AE.AbilityEditError, match="speed must be > 0"):
        _apply([{"animatic_speed": anim, "value": 0}])


@needs_corpus
def test_scale_with_level_reads_the_owners_level_damage():
    mod = "Basic Wide Attacks AP Modifier"
    out = _apply([{"scale_with_level": mod, "value": 10.0}])
    g = {c.name: c for c in EG.parse(out, "Hero_Red").components}
    scaled = g[f"{mod} Level Scaled"]
    assert any(r.guid == scaled.guid for r in g[mod].refs)
    assert {r.path.rsplit("\\", 1)[-1] for r in scaled.refs} >= {
        "Owner Level Damage", f"{mod} Level Ratio"}


@needs_corpus
def test_retarget_updates_owned_fx_subobjects():
    from rsmm.engine.entity_graph_edit import EntityFile
    out = _apply([
        {"clone": ["Fx Howl Hands Trails"], "from": "Heroes/Hero_Red/Hero_Red_FX",
         "rename": {"Fx Howl Hands Trails": "Wolf Innate Claw Trails"}},
        {"retarget": "Wolf Innate Claw Trails",
         "node": "Character_Common/Character_Common|Character Mesh"},
    ])
    ef = EntityFile(out, "Hero_Red")
    fx = ef.component("Wolf Innate Claw Trails")
    picker_cls = [c.name for c in ef.cf.classes].index("oCEntityCpntPicker")
    paths = [r.path for o in sorted(ef.subtree({fx.index - 1}))
             for _, r in EG._pickers(bytes(ef.objects[o]), picker_cls) if r.path]
    assert paths == [
        "[3d graphic object] Character_Common\\Base\\Character Mesh",
        "[3d graphic object] Character_Common\\Base\\Character Mesh",
    ]


# --- graph editing ops (#202, from #192) --------------------------------------

_OP = "Ability Ultimate 1 Final Damage Multiplier Operation"
_VAL = "Ability Ultimate 1 Attack Radius"


def _part(out, name):
    return next(c for c in EG.parse(out, "Hero_Red").components if c.name == name)


@needs_corpus
def test_append_operand_reads_one_more_node():
    val = _part(_raw(), _VAL)
    assert val.guid not in {r.guid for r in _part(_raw(), _OP).refs}
    out = _apply([{"append_operand": _OP, "to": _VAL}])
    assert val.guid in {r.guid for r in _part(out, _OP).refs}
    with pytest.raises(AE.AbilityEditError, match="needs to"):
        _apply([{"append_operand": _OP}])


@needs_corpus
def test_swap_ref_repoints_a_link_across_kinds():
    old = _part(_raw(), _OP).refs[0]
    node = old.path.rsplit("\\", 1)[-1]
    out = _apply([{"swap_ref": _OP, "node": node, "to": _VAL}])
    guids = {r.guid for r in _part(out, _OP).refs}
    assert old.guid not in guids and _part(_raw(), _VAL).guid in guids


@needs_corpus
def test_unlink_reads_drops_the_value_reads():
    assert _part(_raw(), _OP).refs
    out = _apply([{"unlink_reads": _OP}])
    assert len(_part(out, _OP).refs) < len(_part(_raw(), _OP).refs)


# --- talent scaling ops (#202, from #192) ---------------------------------------

_MEL = "EntitySettings/Heroes/Hero_Melusine/Hero_Melusine.entity.ot.EntitySettingsResource.gen"


def _mel_apply(steps):
    from rsmm.engine import corpus
    raw = corpus.read(_MEL)
    if raw is None:
        pytest.skip("no Melusine entity")
    out = AE.apply({"Hero_Melusine": raw}, steps, main="Hero_Melusine",
                   seed="t").files["Hero_Melusine"]
    assert EC.check(out, raw, name="Hero_Melusine") == []
    return {c.name: c for c in EG.parse(out).components}


def _names(c):
    return [r.path.rsplit("\\", 1)[-1] for r in c.refs]


@needs_corpus
def test_scale_by_talent_scales_a_node_by_the_talents_factor():
    node = "Secondary Ability Attack Width"
    g = _mel_apply([{"scale_by_talent": node, "talent": "Trait Dash",
                     "values": 0.3, "tag": "W", "percent": False}])
    assert _names(g[node]) == [f"{node} Scaled"]
    assert _names(g[f"{node} Scaled"])[0] == f"{node} Base"


@needs_corpus
def test_talent_number_adds_a_per_rarity_value_of_the_talent():
    g = _mel_apply([{"talent_number": "Dash Stacks", "talent": "Trait Dash",
                     "values": [1, 2, 3, 4]}])
    assert _names(g["Dash Stacks"]) == ["Dash Stacks Selector"]
    with pytest.raises(AE.AbilityEditError, match="talent = <name>"):
        _mel_apply([{"talent_number": "X", "values": [1]}])


# --- spawned entities: owner_read (#202, from #192) -----------------------------

_WISP = ("EntitySettings/Heroes/Hero_Melusine/Hero_Melusine_Wisp.entity.ot"
         ".EntitySettingsResource.gen")


@needs_corpus
def test_owner_read_reads_the_owners_part_and_switches_on_at_start_up():
    from rsmm.engine import corpus
    mel, wisp = corpus.read(_MEL), corpus.read(_WISP)
    if mel is None or wisp is None:
        pytest.skip("no Melusine family")
    files = {"Hero_Melusine": mel, "Hero_Melusine_Wisp": wisp}
    out = AE.apply(files, [{"owner_read": "Owner Max Health", "entity": "Wisp",
                            "node": "Raw Max Health"}],
                   main="Hero_Melusine", seed="t").files["Hero_Melusine_Wisp"]
    assert EC.check(out, wisp, name="Hero_Melusine_Wisp") == []
    g = {c.name: c for c in EG.parse(out).components}
    owner = next(c for c in EG.parse(mel).components if c.name == "Raw Max Health")
    assert [r.guid for r in g["Owner Max Health"].refs] == [owner.guid]
    assert any(r.guid == g["Owner Max Health"].guid
               for c in g.values() if c.name.endswith("Event Initialize") for r in c.refs)
    with pytest.raises(AE.AbilityEditError, match="node"):
        AE.apply(files, [{"owner_read": "X", "entity": "Wisp"}], main="Hero_Melusine", seed="t")
    with pytest.raises(AE.AbilityEditError, match="itself"):
        AE.apply(files, [{"owner_read": "X", "node": "Raw Max Health"}],
                 main="Hero_Melusine", seed="t")


# --- presentation (#202, from #192) ----------------------------------------------


@needs_corpus
def test_sound_volume_sets_the_decoded_volume_field():
    from rsmm.engine import entity_fields as EF
    snd = "Agressive Defense FMod Event Active"
    out = _apply([{"sound_volume": snd, "value": 0.5}])
    c = next(c for c in EG.parse(out, "Hero_Red").components if c.name == snd)
    assert next(f.text for f in EF.fields(c) if f.name == "volume") == "f32 0.5"
    with pytest.raises(AE.AbilityEditError, match="not a sound"):
        _apply([{"sound_volume": "Dash Ability Anim", "value": 0.5}])


@needs_corpus
def test_animatic_clip_swaps_the_clip_path():
    clip = "Characters\\Heroes\\Kintaro\\Animations\\Kintaro_Power_Out.fbx"
    out = _apply([{"animatic_clip": "Dash Ability Anim", "value": clip}])
    c = next(c for c in EG.parse(out, "Hero_Red").components if c.name == "Dash Ability Anim")
    assert clip.encode() in c.body
    with pytest.raises(AE.AbilityEditError, match=".fbx"):
        _apply([{"animatic_clip": "Dash Ability Anim", "value": "x.png"}])
    with pytest.raises(AE.AbilityEditError, match="not an animatic"):
        _apply([{"animatic_clip": "Agressive Defense FMod Event Active", "value": clip}])


# --- level scaling (#202, from #192) ---------------------------------------------


@needs_corpus
def test_level_linear_is_base_plus_per_level_times_the_xp_level():
    mod = "Basic Wide Attacks AP Modifier"
    out = _apply([{"level_linear": mod, "value": 2.5, "base": 10}])
    g = {c.name: c for c in EG.parse(out, "Hero_Red").components}
    assert any(r.guid == g[f"{mod} Level Linear"].guid for r in g[mod].refs)
    mul = g[f"{mod} Level Mul"]
    assert bytes.fromhex(AE.XP_LEVEL[0]) in {r.guid for r in mul.refs}
    assert g[f"{mod} Per Level"].guid in {r.guid for r in mul.refs}
    with pytest.raises(AE.AbilityEditError, match="per level"):
        _apply([{"level_linear": mod}])


@needs_corpus
def test_the_shared_level_links_name_character_commons_values():
    """A game patch that moves one fails here, not as a mod reading nothing."""
    from rsmm.engine import corpus
    rel = next(iter(corpus.rels("EntitySettings/",
                                "/Character_Common.entity.ot.EntitySettingsResource.gen")))
    g = {c.guid: c for c in EG.parse(corpus.read(rel)).components}
    for guid, label in (AE.LEVEL_DAMAGE, AE.XP_LEVEL):
        c = g[bytes.fromhex(guid)]
        assert label == f"[Value] Character_Common\\{c.path}"
