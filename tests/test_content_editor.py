"""The Items and Talents tabs of `rsmm editor`: the blocks they build and
where they write them.

All of it runs on plain dicts with no game data. Routing, the token and the
Host check are shared by every editor and tested in test_editor_hub.py.
"""

from __future__ import annotations

import tomllib

import pytest

from rsmm.cli.editor import content as E

# --- item blocks -------------------------------------------------------------

def _item(**kw):
    req = {"base": "Dash_Crit_Chance", "id": "Dash_Crit_Chan_M"}
    req.update(kw)
    return E.item_defs(req)


def test_an_item_block_carries_only_what_changed():
    defs = _item(name="Thorn", description="", rarity="", icon="", values=[
        {"label": "A Value", "old": 0.5, "new": 1.0},
        {"label": "B Value", "old": 2.0, "new": 2.0},        # unchanged: dropped
    ])
    [(kind, cid, fields)] = defs
    assert (kind, cid) == ("item", "Dash_Crit_Chan_M")
    assert fields == {"kind": "item", "id": "Dash_Crit_Chan_M", "base": "Dash_Crit_Chance",
                      "name": "Thorn", "value_patches": [["A Value", 0.5, 1.0]]}


def test_an_overridden_item_value_asks_to_clear_the_override():
    [(_k, _i, fields)] = _item(values=[{"label": "A", "old": 1, "new": 2, "shadowed": True}])
    assert fields["value_patches"] == [["A", 1.0, 2.0, True]]


def test_an_icon_is_written_as_its_full_path():
    """A bare stem would be read as `UI_Object_<stem>`, and most icons are not."""
    [(_k, _i, fields)] = _item(icon="Icon_Object_Dreamcatcher")
    assert fields["icon"] == "Objects\\Icon_Object_Dreamcatcher.png"


def test_an_items_stats_and_super_text_are_carried():
    [(_k, _i, fields)] = _item(
        stats=[{"modifier": "Crit Chance Modifier", "stat": "Armour"},
               {"modifier": "Crit Chance Damage Modifier", "stat": "0x15c7d482"},
               {"modifier": "Untouched", "stat": ""}],
        superDescription="Gain #armour@.")
    assert fields["stats"] == {"Crit Chance Modifier": "Armour",
                               "Crit Chance Damage Modifier": "0x15c7d482"}
    assert fields["super_description"] == "Gain #armour@."


def test_stats_are_written_as_an_inline_table_that_parses_back():
    defs = _item(stats=[{"modifier": "Crit Chance Modifier", "stat": "Crit damage"}])
    parsed = tomllib.loads(E.to_toml(defs))["content"][0]
    assert parsed["stats"] == {"Crit Chance Modifier": "Crit damage"}


@pytest.mark.parametrize("kw, message", [
    ({"stats": [{"modifier": "M", "stat": "Not a stat"}]}, "unknown stat"),
    ({"id": "short"}, "exactly as long"),
    ({"id": "Dash_Crit_Chance"}, "id of its own"),
    ({"id": "Dash Crit Chan M"}, "letters, digits"),
    ({"base": ""}, "pick a base"),
    ({"icon": "../evil"}, "no icon"),
    ({"values": [{"label": "A", "old": 1, "new": "x"}]}, "not a number"),
])
def test_a_bad_item_is_refused(kw, message):
    with pytest.raises(E.EditorError, match=message):
        _item(**kw)


# --- talent blocks -------------------------------------------------------------

@pytest.fixture
def herodefs(monkeypatch):
    monkeypatch.setattr(E, "_herodefs", lambda: {"Juliet": "Juliet", "SunWukong": "Sun_Wukong"})


def test_talent_values_group_into_one_block_per_file(herodefs):
    defs = E.talent_defs({"hero": "Juliet", "prefix": "jt", "values": [
        {"file": "Hero_Juliet", "label": "F", "type": "float", "old": 1.0, "new": 2.5},
        {"file": "Hero_Juliet", "label": "I", "type": "int", "old": 3, "new": 4},
        {"file": "Hero_Juliet_Projectile", "label": "B", "type": "bool", "old": False,
         "new": True, "shadowed": True},
    ]})
    assert [(k, i) for k, i, _f in defs] == [("talent", "jt"), ("talent", "jt_Projectile")]
    assert defs[0][2] == {"kind": "talent", "id": "jt", "hero": "Juliet",
                          "file": "Hero_Juliet.entity",
                          "value_patches": [["F", 1.0, 2.5], ["I", 3, 4]]}
    assert defs[1][2]["value_patches"] == [["B", False, True, True]]


def test_an_int_value_must_stay_whole(herodefs):
    with pytest.raises(E.EditorError, match="whole number"):
        E.talent_defs({"hero": "Juliet", "prefix": "jt", "values": [
            {"file": "Hero_Juliet", "label": "I", "type": "int", "old": 3, "new": 3.5}]})


def test_a_card_block_names_the_hero_by_its_herodef(herodefs):
    """The talent kind takes the folder name, the skill kind the herodef."""
    defs = E.talent_defs({"hero": "SunWukong", "prefix": "w", "cards": [
        {"source": "Attack Beam", "name": "Big Beam", "description": ""},
        {"source": "Dash Cloud", "name": "", "description": ""},          # untouched
    ]})
    assert defs == [("skill", "w_Attack_Beam", {
        "kind": "skill", "id": "w_Attack_Beam", "hero": "Sun_Wukong",
        "source": "Attack Beam", "name": "Big Beam"})]


def test_no_change_is_nothing_to_write(herodefs):
    with pytest.raises(E.EditorError, match="nothing changed"):
        E.talent_defs({"hero": "Juliet", "prefix": "jt", "values": [
            {"file": "Hero_Juliet", "label": "F", "type": "float", "old": 1.0, "new": 1.0}]})


def test_the_toml_parses_back_to_the_same_blocks(herodefs):
    defs = E.talent_defs({"hero": "Juliet", "prefix": "jt", "values": [
        {"file": "Hero_Juliet", "label": 'Quote " and \\ slash', "type": "float",
         "old": 1.0, "new": 2.0},
        {"file": "Hero_Juliet", "label": "Two", "type": "bool", "old": True, "new": False},
    ], "cards": [{"source": "Attack Power", "name": "Ünïcode ✓",
                  "description": "line one\nline two {0}"}]})
    parsed = tomllib.loads(E.to_toml(defs))["content"]
    assert parsed == [f for _k, _i, f in defs]


# --- saving ------------------------------------------------------------------------

def _defs():
    return _item(name="Thorn")


def test_a_new_mod_is_created_with_the_blocks(tmp_path):
    path = E.save(_defs(), "thorn", tmp_path, create=True, name="Thorn")
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    assert doc["mod"]["id"] == "thorn" and doc["mod"]["name"] == "Thorn"
    assert doc["content"][0]["id"] == "Dash_Crit_Chan_M"
    assert (tmp_path / "thorn" / "assets").is_dir()
    assert E.list_mods(tmp_path) == [{"id": "thorn", "name": "Thorn"}]


def test_blocks_are_appended_to_an_existing_manifest(tmp_path):
    m = tmp_path / "mine" / "manifest.toml"
    m.parent.mkdir()
    m.write_text('[mod]\nid = "mine"\n\n[[content]]\nkind = "item"\nid = "Other"\n')
    E.save(_defs(), "mine", tmp_path)
    assert [c["id"] for c in tomllib.loads(m.read_text())["content"]] == [
        "Other", "Dash_Crit_Chan_M"]


def test_an_id_the_manifest_already_uses_is_refused_and_nothing_is_written(tmp_path):
    E.save(_defs(), "mine", tmp_path, create=True)
    m = tmp_path / "mine" / "manifest.toml"
    before = m.read_text()
    with pytest.raises(E.EditorError, match="already has item 'Dash_Crit_Chan_M'"):
        E.save(_defs(), "mine", tmp_path)
    assert m.read_text() == before


@pytest.mark.parametrize("mod_id, create, message", [
    ("../escape", True, "letters, digits"),
    ("a/b", False, "letters, digits"),
    ("missing", False, "no mod 'missing'"),
])
def test_a_bad_save_target_is_refused(tmp_path, mod_id, create, message):
    with pytest.raises(E.EditorError, match=message):
        E.save(_defs(), mod_id, tmp_path, create=create)
    assert not (tmp_path.parent / "escape").exists()


def test_creating_over_an_existing_mod_is_refused(tmp_path):
    (tmp_path / "taken").mkdir()
    with pytest.raises(E.EditorError, match="already exists"):
        E.save(_defs(), "taken", tmp_path, create=True)


def test_list_mods_skips_folders_without_a_readable_manifest(tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "manifest.toml").write_text("not = [toml")
    (tmp_path / "empty").mkdir()
    (tmp_path / "_log").mkdir()
    assert E.list_mods(tmp_path) == []
    assert E.list_mods(tmp_path / "missing") == []


def test_the_stat_list_puts_numbers_on_the_stats_items_give():
    from rsmm.engine import corpus
    if not corpus.files("EntitySettings/Objects/Magical_Objects/Common",
                        ".entity.ot.EntitySettingsResource.gen"):
        pytest.skip("shipped items not available")
    stats = {s["name"]: s["used"] for s in E.stats()}
    assert stats["Attack power"] > 0 and stats["Armour"] > 0
    assert len(stats) > 200
