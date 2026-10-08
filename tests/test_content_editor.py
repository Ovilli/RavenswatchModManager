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


def test_a_replacement_is_a_block_for_the_shipped_item_itself():
    [(kind, cid, fields)] = _item(mode="replace", name="Thorn", rarity="Epic", values=[
        {"label": "A Value", "old": 0.5, "new": 1.0}])
    assert (kind, cid) == ("item", "Dash_Crit_Chance")
    # No id of its own and no rarity: the shipped file keeps both.
    assert fields == {"kind": "item", "id": "Dash_Crit_Chance", "mode": "replace",
                      "base": "Dash_Crit_Chance", "name": "Thorn",
                      "value_patches": [["A Value", 0.5, 1.0]]}


def test_an_unchanged_replacement_is_nothing_to_write():
    with pytest.raises(E.EditorError, match="nothing changed"):
        _item(mode="replace", name="", values=[])


def test_a_replacements_uploaded_icon_is_not_named_like_the_shipped_one():
    [(_k, _i, fields)] = _item(mode="replace", iconUpload=_png_b64())
    assert fields["icon"] == "icons/Dash_Crit_Chance_Custom.png"


def test_saving_a_second_replacement_of_one_item_says_so(tmp_path):
    defs = _item(mode="replace", name="Thorn")
    E.save(defs, "m", tmp_path, create=True)
    with pytest.raises(E.EditorError, match="already changes Dash_Crit_Chance"):
        E.save(defs, "m", tmp_path)


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
    # Game state the engine keeps beside the stats is not offered (Pam: "Is in
    # book scene" ... "should probably be removed"); real stats all stay.
    assert not any(n.startswith(("Is in ", "GameModifier")) for n in stats)
    assert "Ability_Charge_Trait" in stats and "Strength" in stats
    assert len(stats) > 150


def test_card_textures_are_an_allowlist():
    """The texture route serves the card's own files and nothing else."""
    assert E.card_texture("../../Ravenswatch.exe") is None
    assert E.card_texture("Ui/Description/Description_Frame_Back.png") is None
    assert E.card_font("nope") is None
    assert set(E.CARD_FONTS) == {"title", "body"}
    assert all(p.startswith(("Ui/", "Fonts/")) for p in E.CARD_TEXTURES.values())


def test_tier_numbers_and_effect_stats_join_their_files_block():
    defs = E.talent_defs({"hero": "Aladdin", "prefix": "t", "tiers": [
        {"file": "Hero_Aladdin", "label": "Dive Selector", "index": 1, "old": 7, "new": 9},
        {"file": "Hero_Aladdin", "label": "Dive Selector", "index": 3, "old": 6, "new": 6}],
        "stats": [{"file": "Hero_Aladdin", "modifier": "Shield Modifier", "stat": "Armour"}]})
    [(kind, tid, fields)] = defs
    assert (kind, tid) == ("talent", "t")
    assert fields["union_patches"] == [
        {"label": "Dive Selector", "index": 1, "old": 7.0, "new": 9.0}]
    assert fields["stats"] == {"Shield Modifier": "Armour"}
    parsed = tomllib.loads(E.to_toml(defs))["content"][0]
    assert parsed["union_patches"][0]["new"] == 9.0


def test_a_hero_texture_must_be_one_the_hero_names():
    hero = (E.heroes() or [None])[0]
    if hero is None:
        pytest.skip("shipped heroes not available")
    assert E.hero_png(hero, "..\\\\..\\\\Ravenswatch.exe") is None
    assert E.hero_png(hero, "Heroes\\\\Nobody\\\\Skill X.png") is None


# --- your own icons -------------------------------------------------------------

def _png_b64() -> str:
    import base64

    from rsmm.engine.image import encode_png
    return "data:image/png;base64," + base64.b64encode(
        encode_png(4, 4, bytes([200, 30, 30, 255]) * 16)).decode()


def test_an_uploaded_item_icon_ships_in_the_mod_beside_the_block():
    [(_k, _i, fields)] = _item(iconUpload=_png_b64(), icon="GreenArmor")
    assert fields["icon"] == "icons/Dash_Crit_Chan_M.png"          # the upload wins
    assert fields[E.FILES]["icons/Dash_Crit_Chan_M.png"].startswith(b"\x89PNG")
    toml = E.to_toml([("item", "Dash_Crit_Chan_M", fields)])
    assert "_files" not in toml and 'icon = "icons/Dash_Crit_Chan_M.png"' in toml


def test_a_talent_card_icon_alone_is_a_skill_block():
    defs = E.talent_defs({"hero": "Aladdin", "prefix": "t",
                          "cards": [{"source": "Attack Dive", "iconUpload": _png_b64()}]})
    [(kind, _sid, fields)] = defs
    assert kind == "skill" and fields["icon"] == "icons/Aladdin_Attack_Dive.png"
    assert "name" not in fields and "description" not in fields


@pytest.mark.parametrize("upload, message", [
    ("data:image/png;base64,!!!", "intact"),
    ("data:image/png;base64,R0lGODlhAQABAAAAACw=", "must be a PNG"),
])
def test_a_bad_upload_is_refused(upload, message):
    with pytest.raises(E.EditorError, match=message):
        _item(iconUpload=upload)


def test_saving_writes_the_icon_into_the_mod(tmp_path):
    defs = _item(iconUpload=_png_b64())
    E.save(defs, "icons_mod", tmp_path, create=True)
    mod = tmp_path / "icons_mod"
    assert (mod / "icons" / "Dash_Crit_Chan_M.png").read_bytes()[:4] == b"\x89PNG"
    assert 'icon = "icons/Dash_Crit_Chan_M.png"' in (mod / "manifest.toml").read_text()


def test_only_icon_paths_are_written_into_a_mod(tmp_path):
    with pytest.raises(E.EditorError, match="refusing"):
        E._write_files(tmp_path, {E.FILES: {"../escape.png": b"x"}})


# --- every pending change at once ------------------------------------------------

def _edit(tab, label, **edit):
    return {"tab": tab, "name": label, "edit": edit}


def test_edits_over_several_items_and_heroes_make_one_list_of_blocks():
    defs, errors = E.collect({"edits": [
        _edit("items", "Dash", base="Dash_Crit_Chance", id="Dash_Crit_Chan_M", name="A"),
        _edit("items", "Armor", base="Armor_Per_Object", id="Armor_Per_Obje_M", name="B"),
        _edit("talents", "Aladdin", hero="Aladdin", prefix="al",
              values=[{"file": "Hero_Aladdin", "label": "X", "type": "float", "old": 1, "new": 2}]),
    ]})
    assert errors == []
    assert [(k, i) for k, i, _f in defs] == [
        ("item", "Dash_Crit_Chan_M"), ("item", "Armor_Per_Obje_M"), ("talent", "al")]


def test_a_broken_edit_is_reported_by_name_and_the_rest_still_build():
    defs, errors = E.collect({"edits": [
        _edit("items", "Dash", base="Dash_Crit_Chance", id="short"),
        _edit("items", "Armor", base="Armor_Per_Object", id="Armor_Per_Obje_M"),
    ]})
    assert [i for _k, i, _f in defs] == ["Armor_Per_Obje_M"]
    assert errors[0]["name"] == "Dash" and "exactly as long" in errors[0]["error"]


def test_an_untouched_hero_is_skipped_not_an_error():
    defs, errors = E.collect({"edits": [_edit("talents", "Aladdin", hero="Aladdin", prefix="al")]})
    assert (defs, errors) == ([], [])


def test_two_edits_making_one_block_id_is_an_error():
    same = {"base": "Dash_Crit_Chance", "id": "Dash_Crit_Chan_M"}
    _defs, errors = E.collect({"edits": [_edit("items", "One", **same),
                                         _edit("items", "Two", **same)]})
    assert errors and errors[0]["name"] == "Two" and "also made by One" in errors[0]["error"]


def test_the_old_single_edit_request_still_works():
    defs, errors = E.collect({"tab": "items", "edit": {"base": "Dash_Crit_Chance",
                                                        "id": "Dash_Crit_Chan_M"}})
    assert len(defs) == 1 and errors == []


# --- a new mod's details ------------------------------------------------------------

def test_a_new_mod_gets_the_details_the_store_shows(tmp_path):
    meta = {"name": "Ogre Crit", "author": "Ovilli", "version": "1.2.0",
            "summary": "Crit damage instead.", "description": "Line one\nLine two",
            "tags": ["gameplay", "Balance", "gameplay"], "license": "MIT",
            "homepage_url": "https://rsmm.me", "repo_url": ""}
    E.save(_item(), "ogre-crit", tmp_path, create=True, meta=meta)
    mod = tomllib.loads((tmp_path / "ogre-crit" / "manifest.toml").read_text())["mod"]
    assert mod["name"] == "Ogre Crit" and mod["author"] == "Ovilli" and mod["version"] == "1.2.0"
    assert mod["summary"] == "Crit damage instead." and mod["description"] == "Line one\nLine two"
    assert mod["tags"] == ["gameplay", "balance"] and mod["license"] == "MIT"
    assert mod["homepage_url"] == "https://rsmm.me" and "repo_url" not in mod
    from rsmm.sdk.manifest_spec import MOD_FIELDS
    assert set(mod) <= set(MOD_FIELDS)


@pytest.mark.parametrize("meta, message", [
    ({"version": "one"}, "not like 1.0.0"),
    ({"tags": ["no spaces please"]}, "letters, digits"),
    ({"tags": [f"t{i}" for i in range(17)]}, "at most 16"),
    ({"homepage_url": "rsmm.me"}, "http"),
    ({"summary": "x" * 513}, "over 512"),
])
def test_bad_mod_details_are_refused_before_anything_is_written(tmp_path, meta, message):
    with pytest.raises(E.EditorError, match=message):
        E.save(_item(), "bad-mod", tmp_path, create=True, meta=meta)
    assert not (tmp_path / "bad-mod").exists()


def test_an_item_missing_from_the_text_catalog_still_gets_its_icon():
    """The catalog skips shipped items with no text entry, which left 21 of them
    (Increase_Damage_To_Boss, ...) iconless in the list although the item's own
    bytes name an icon."""
    from rsmm.engine import corpus
    if not corpus.rels("Ui/Objects/"):
        pytest.skip("no game data (no mirror, no install)")
    got = {i["id"]: i["icon"] for i in E.items()}
    assert got.get("Increase_Damage_To_Boss") == "Icon_Object_VoodooDoll"


# --- stat picker -------------------------------------------------------------

@pytest.mark.parametrize(("name", "aka"), [
    ("CD reduce trait", "TRAIT cooldown"),        # Pam searched "trait cooldown": no hit
    ("CD reduce secondary", "SPECIAL cooldown"),
    ("Attack power primary", "POWER damage"),
    ("Crit chance defensive", "DEFENSE crit chance"),
    ("Ability_Charge_Primary", "+ POWER charge"),
    ("CD reduce", "all cooldowns"),
    ("Armour", None),
    ("Attack power", None),
])
def test_a_per_ability_stat_is_searchable_by_the_cards_words(name, aka):
    assert E.stat_aka(name) == aka


# --- talent builder: when an added stat applies ----------------------------------

def _added(**row):
    base = {"talent": "Trait Fire", "stat": "Attack power", "values": [0.1, 0.2, 0.3, 0.4]}
    defs = E.talent_defs({"hero": "SunWukong", "prefix": "w", "addStats": [{**base, **row}]})
    [(_kind, _id, fields)] = defs
    return fields["add_stats"][0]


def test_an_added_stat_for_a_while_after_an_ability_carries_its_seconds():
    assert _added(after="defense", seconds=4) == {
        "talent": "Trait Fire", "stat": "Attack power", "values": [0.1, 0.2, 0.3, 0.4],
        "after": "DEFENSE", "seconds": 4.0}


def test_an_after_window_carries_its_cooldown_and_an_empty_one_means_every_use():
    assert _added(after="DEFENSE", seconds=3, cooldown=8)["cooldown"] == 8.0
    assert "cooldown" not in _added(after="DEFENSE", seconds=3, cooldown="")


@pytest.mark.parametrize(("row", "msg"), [
    ({"after": "DEFENSE"}, "not a number"),
    ({"after": "DEFENSE", "seconds": 0}, "above 0"),
    ({"after": "JUMP", "seconds": 3}, "unknown ability"),
    ({"after": "DEFENSE", "during": "POWER", "seconds": 3}, "not both"),
    ({"after": "DEFENSE", "seconds": 3, "cooldown": 0}, "above 0"),
    ({"cooldown": 8}, "only limits"),
    ({"next": "ATTACK"}, "only ends"),
    ({"after": "DEFENSE", "seconds": 3, "next": "DEFENSE"}, "must differ"),
    ({"after": "DEFENSE", "seconds": 3, "next": "JUMP"}, "unknown ability"),
])
def test_a_bad_after_is_refused(row, msg):
    with pytest.raises(E.EditorError, match=msg):
        _added(**row)


def test_an_included_effect_joins_the_builder_block():
    defs = E.talent_defs({"hero": "Red", "prefix": "r", "include": [
        {"talent": "Trait Active", "from": "Secondary Quick Bombs"}]})
    [(_kind, cid, fields)] = defs
    assert cid == "r_builder"
    assert fields["include"] == [{"talent": "Trait Active", "from": "Secondary Quick Bombs"}]


@pytest.mark.parametrize("row", [{"talent": "Trait Active"}, {"talent": "A", "from": "A"}])
def test_a_bad_include_row_is_refused(row):
    with pytest.raises(E.EditorError):
        E.talent_defs({"hero": "Red", "prefix": "r", "include": [row]})


@pytest.mark.parametrize(("name", "tally"), [
    ("Defensive Object Count", "defensive object"),
    ("Joker Card Count", "joker card"),
    ("Rare MO Collection Count", "rare magical object"),
    ("Counter attack damage", None),       # "count" only inside "counter"
    ("Armour", None),
])
def test_count_stats_are_labelled_as_tallies(name, tally):
    # Pam: "what is the point of modifiers that have count in the name". They
    # are counters other effects read; the picker lists them apart.
    assert E.stat_tally(name) == tally
    if tally:
        assert E.stat_aka(name) == f"tally: {tally}s held"


def test_an_inherited_talent_can_take_a_stat_but_not_a_rebuild():
    # Love Shield is built in the Romeo/Juliet common file; Romeo's own file only
    # overrides its controller. Its abilities are the ones that file builds.
    if "Romeo" not in E.heroes():
        pytest.skip("shipped heroes not available")
    card = next(c for c in E.talent_cards("Romeo") if c["source"] == "Special Invulnerable")
    info = card["addStat"]
    assert info["ok"] and info["during"] == ["SPECIAL", "TRAIT"]
    assert info["rebuild"] is False and info["rebuildWhy"]
    assert card["file"] == "Hero_Romeo_Juliet_Common" and card["entries"]
