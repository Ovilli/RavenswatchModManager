"""The Hero tab's server side (`rsmm.cli.editor.herobuilder`): heroes written
from scratch, listed, checked and saved without losing a hand-written line."""

from __future__ import annotations

import tomllib
from types import SimpleNamespace

import pytest

from rsmm.cli.editor import herobuilder as HB
from rsmm.sdk.kinds import heros

needs_corpus = pytest.mark.skipif(not heros.shipped_heroes(), reason="no hero corpus")

MANIFEST = '''[mod]
id = "m"

# Jack, by hand.
[[content]]
kind        = "hero"
id          = "Nyx"
name        = "Nyx"

[content.frame]
rig      = "Hero_Kintaro"
mesh     = "Characters\\\\Heroes\\\\Kintaro\\\\Kintaro_GEO.fbx"
material = "Characters\\\\Heroes\\\\Kintaro\\\\Textures\\\\M_Kintaro.mat.ot"

[content.frame.abilities.power]
clip     = "anim:Chop"     # his own clip
cooldown = 6
hits     = [ { at = 0.4, radius = 3, damage = 200, fx = "fx:Burst" } ]

[content.frame.animations.Chop]
source   = "art/chop.glb"
template = "Kintaro_BasicAttack01"

[content.frame.effects.Burst]
layers = [ { light = 3, burst = 1, size = 2 } ]

[[content]]
kind = "hero"
id   = "Clone"
base = "Red"
'''


@pytest.fixture
def mods(tmp_path, monkeypatch):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "manifest.toml").write_text(MANIFEST, encoding="utf-8")
    (tmp_path / "m" / "art").mkdir()
    (tmp_path / "m" / "art" / "chop.glb").write_bytes(b"glTF")
    # No install needed: the check reads the rig list from here.
    monkeypatch.setattr(HB, "schema", lambda: {"rigs": ["Hero_Kintaro", "Hero_Juliet"]})
    return tmp_path


def _req(mods, body=None, **query):
    return SimpleNamespace(ctx=SimpleNamespace(mods_dir=mods), body=body or {},
                           arg=lambda k, d="": query.get(k, d))


def _block(mods, hid="Nyx") -> dict:
    text = (mods / "m" / "manifest.toml").read_text(encoding="utf-8")
    return next(c for c in tomllib.loads(text)["content"] if c.get("id") == hid)


def test_the_tab_lists_heroes_written_from_scratch_and_names_the_others(mods):
    got = HB._heroes(_req(mods, mod="m"))
    assert [h["id"] for h in got["heroes"]] == ["Nyx"]
    assert got["heroes"][0]["frame"]["abilities"]["power"]["cooldown"] == 6
    assert got["others"] == [{"id": "Clone", "base": "Red"}]


def test_a_sound_hero_has_no_problems_and_broken_references_are_named(mods):
    nyx = _block(mods)
    assert HB.problems(nyx, mods / "m") == []
    nyx["frame"]["abilities"]["power"]["clip"] = "anim:Nope"
    nyx["frame"]["abilities"]["power"]["hits"][0]["fx"] = "fx:Gone"
    nyx["frame"]["animations"]["Chop"]["source"] = "art/missing.glb"
    nyx["frame"]["abilities"]["power"]["sideways"] = True
    nyx["frame"]["talents"] = [{"name": "Sharp Axe"}, {"name": "Attack X"}, {"name": "Attack X"}]
    got = "\n".join(HB.problems(nyx, mods / "m"))
    assert "no animations.Nope" in got and "no effects.Gone" in got
    assert "no file art/missing.glb" in got
    assert "sideways" in got                                  # Ability.parse's own refusal
    assert "starts with its column" in got and "a second talent named 'Attack X'" in got


def test_the_check_refuses_ids_and_keys_the_build_refuses(mods):
    bad = {"kind": "hero", "id": "9lives", "base": "Red", "frame": {"rig": "Hero_Nobody"}}
    got = "\n".join(HB.problems(bad))
    assert "id:" in got and "takes no base" in got and "frame.mesh" in got
    assert "'Hero_Nobody' is not a shipped hero" in got


def test_saving_an_edit_keeps_every_hand_written_line(mods):
    nyx = _block(mods)
    nyx["frame"]["abilities"]["power"]["cooldown"] = 8
    got = HB._save(_req(mods, {"mod": "m", "block": "Nyx", "hero": nyx}))
    assert got == {"mod": "m", "block": "Nyx", "problems": []}
    text = (mods / "m" / "manifest.toml").read_text(encoding="utf-8")
    assert "# Jack, by hand." in text and '"anim:Chop"     # his own clip' in text
    assert "cooldown = 8" in text and _block(mods) == nyx
    # a hero written from scratch marks its mod experimental (rsmm lint)
    assert tomllib.loads(text)["mod"]["experimental"] is True


def test_a_new_hero_is_appended_and_a_taken_id_refused(mods):
    hero = {"id": "Vex", "name": "Vex", "frame": {"rig": "Hero_Juliet", "mesh": "a\\b.fbx",
                                                    "material": "a\\m.mat.ot"}}
    got = HB._save(_req(mods, {"mod": "m", "block": "", "hero": hero}))
    assert got["block"] == "Vex" and _block(mods, "Vex")["frame"]["rig"] == "Hero_Juliet"
    with pytest.raises(ValueError, match="already"):
        HB._save(_req(mods, {"mod": "m", "block": "", "hero": hero}))
    with pytest.raises(ValueError, match="already has a hero 'Vex'"):
        HB._save(_req(mods, {"mod": "m", "block": "Nyx", "hero": {**_block(mods), "id": "Vex"}}))
    with pytest.raises(ValueError, match="id"):
        HB._save(_req(mods, {"mod": "m", "block": "", "hero": {"id": "", "frame": {}}}))


def test_removing_a_hero_takes_only_its_block(mods):
    HB._delete(_req(mods, {"mod": "m", "block": "Nyx"}))
    ids = [c["id"] for c in tomllib.loads((mods / "m" / "manifest.toml").read_text())["content"]]
    assert ids == ["Clone"]
    with pytest.raises(ValueError, match="written from scratch"):
        HB._delete(_req(mods, {"mod": "m", "block": "Clone"}))


def test_the_page_is_offered_the_mods_own_art(mods):
    (mods / "m" / "assets").mkdir()
    (mods / "m" / "assets" / "cooked.png").write_bytes(b"")
    assert HB._files(_req(mods, mod="m"))["files"] == ["art/chop.glb"]


@needs_corpus
def test_the_schema_is_the_engines_own():
    from rsmm.engine import hero_ability as HA
    HB.schema.cache_clear()
    s = HB.schema()
    assert set(s["keys"]["button"]) >= {"hold", "charges", "buffs", "combo", "steps", "icon"}
    assert "variant" not in s["keys"]["button"]
    assert s["slots"] == list(HA.CONTROLLERS) and "Hero_Kintaro" in s["rigs"]
    assert "Invulnerable" in s["enums"]["stat"] and "Crit chance basic" in s["enums"]["stat"]


@needs_corpus
def test_a_rig_suggests_its_on_foot_body_and_its_clips():
    kin = HB.rig("Hero_Kintaro")
    assert kin["mesh"].endswith("Kintaro_GEO.fbx") and "Bear" not in kin["mesh"]
    assert kin["material"].endswith(".mat.ot") and "Default Idle Anim" in kin["slots"]
    clips = HB.clips(kin["mesh"])
    assert "Kintaro_FightingIdle_Loop" in clips["templates"]
    assert any(t["name"] == "Red: Wolf Primary" or "Red: Wolf Primary" in t["names"]
               for t in HB.templates())


@needs_corpus
def test_the_shipped_lists_offer_names_in_the_form_the_build_reads(install_only):
    HB.shipped.cache_clear(); HB.rig.cache_clear()
    from rsmm.engine import hero_ability as HA
    from rsmm.engine import vfx_writer as VW
    s = HB.shipped()
    assert HA.IMPACT_FX in s["effects"]
    assert "decal" in s["fx_meshes"] and all(VW.mesh_ref(m) for m in s["fx_meshes"][:20])
    assert all(x.count("|") == 1 and x.split("|")[0].strip().endswith(".entity.ot")
               for x in s["sounds"])
    assert not any("Merlin" in x for x in s["sounds"])     # DLC hero: not handed out
    assert "DEF.Chest" in HB.rig("Hero_Kintaro")["bones"]
    assert "Heroes\\Kintaro\\Portrait_Kintaro_01.png" in s["pictures"]
