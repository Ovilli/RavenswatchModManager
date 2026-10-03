"""The editor's Scripts tab (test grants in init.lua) and opening a saved mod
to keep working on it."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tomllib

import pytest

from rsmm.cli.editor import content as C
from rsmm.cli.editor import modio as M

CFG = {"hero": "SunWukong", "xp": 5000, "items": [{"id": "Damage_Attack", "count": 15}],
       "talents": [{"name": "Quick Bombs", "tier": 3}]}


def test_script_section_round_trips_and_leaves_the_authors_code_alone(tmp_path):
    (tmp_path / "init.lua").write_text('local R = require "rsmm"\nR.log("mine")\n')
    assert M.write_script(tmp_path, M.script_config(CFG)) == "written"
    text = (tmp_path / "init.lua").read_text()
    assert text.startswith('local R = require "rsmm"\nR.log("mine")\n'), "the author's code moved"
    assert M.read_script(text) == M.script_config(CFG)
    assert 'R.hero.entity_is(HERO)' in text and '"Hero_SunWukong"' in text, (
        "a hero filter is what stops a test grant reaching every hero")

    M.write_script(tmp_path, M.script_config({**CFG, "xp": 10}))
    text = (tmp_path / "init.lua").read_text()
    assert text.count(M.BEGIN) == 1, "a second save appended a second section"
    assert M.read_script(text)["xp"] == 10

    assert M.write_script(tmp_path, M.script_config({})) == "written"
    assert (tmp_path / "init.lua").read_text().strip() == 'local R = require "rsmm"\nR.log("mine")'


def test_a_script_only_init_lua_is_removed_when_it_grants_nothing(tmp_path):
    M.write_script(tmp_path, M.script_config(CFG))
    assert M.write_script(tmp_path, M.script_config({"hero": "Piper"})) == "removed"
    assert not (tmp_path / "init.lua").exists()


@pytest.mark.skipif(shutil.which("luac") is None, reason="no luac")
def test_generated_lua_parses(tmp_path):
    p = tmp_path / "init.lua"
    p.write_text(M.script_lua(M.script_config(CFG)) + M.script_lua(M.script_config({"xp": 1})))
    assert subprocess.run(["luac", "-p", str(p)], capture_output=True).returncode == 0


@pytest.mark.parametrize("bad", [{"xp": -1}, {"xp": True}, {"items": [{"id": 'x"); os.exit()--'}]},
                                 {"items": [{"id": "A", "count": 0}]},
                                 {"talents": [{"name": "Q", "tier": 4}]}, {"hero": "a\nb"}])
def test_script_config_refuses_what_could_not_be_written_safely(bad):
    with pytest.raises(C.EditorError):
        M.script_config(bad)


MANIFEST = """[mod]
id = "m"

# the copy
[[content]]
kind = "item"
id = "A"
base = "X"

[[content]]
kind = "talent"
id = "t"
hero = "Piper"
[content.values]
x = 1

# hand-written, keep me
[[content]]
kind = "enemy"
id = "e"
base = "Y"
"""


def test_remove_blocks_takes_out_exactly_the_opened_blocks():
    out = M.remove_blocks(MANIFEST, {("item", "A"), ("talent", "t")})
    doc = tomllib.loads(out)
    assert [(c["kind"], c["id"]) for c in doc["content"]] == [("enemy", "e")]
    assert "# hand-written, keep me" in out and "# the copy" not in out
    assert M.remove_blocks(MANIFEST, set()) == MANIFEST


def test_remove_blocks_refuses_a_layout_it_cannot_cut_cleanly():
    inline = 'content = [{ kind = "item", id = "A" }]\n[mod]\nid = "m"\n'
    with pytest.raises(C.EditorError):
        M.remove_blocks(inline, {("item", "A")})


def test_import_writes_only_editable_files_and_never_over_a_mod(tmp_path):
    b = lambda s: base64.b64encode(s).decode()  # noqa: E731
    files = {"manifest.toml": b(b'[mod]\nid = "imp"\n'), "init.lua": b(b"-- x"),
             "icons/a.png": b(b"\x89PNG"), "../evil.lua": b(b"x"), "assets/big.gen": b(b"x")}
    assert M.import_mod(tmp_path, files) == "imp"
    got = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert got == ["imp/icons/a.png", "imp/init.lua", "imp/manifest.toml"]
    with pytest.raises(C.EditorError):
        M.import_mod(tmp_path, files)


def _game() -> bool:
    try:
        return bool(C.item_detail("Damage_Attack")["values"]) and bool(C.talent_values("Piper"))
    except Exception:  # noqa: BLE001 - no install, no corpus
        return False


@pytest.mark.skipif(not _game(), reason="no game data")
def test_an_opened_mod_rebuilds_its_own_blocks_and_saves_over_them(tmp_path):
    v = C.item_detail("Damage_Attack")["values"][0]
    item = {"mode": "replace", "base": "Damage_Attack", "description": "• x",
            "values": [{"label": v["label"], "old": v["value"], "new": 0.75,
                        "shadowed": v["shadowed"]}],
            "stats": [{"modifier": "Modifier", "stat": "Basic Attack Speed"}]}
    f0 = C.talent_values("Piper")[0]
    r0 = f0["values"][0]
    talent = {"hero": "Piper", "prefix": "piper_talents",
              "values": [{"file": f0["file"], "label": r0["label"], "type": r0["type"],
                          "old": r0["value"], "new": r0["value"] + 1, "shadowed": r0["shadowed"]}]}
    defs = C.defs_for("items", item) + C.defs_for("talents", talent)
    C.save(defs, "m1", tmp_path, create=True, name="M1", script=M.script_config(CFG))

    got = M.load_mod(tmp_path, "m1")
    assert got["kept"] == [] and got["script"] == M.script_config(CFG)
    rebuilt = (C.defs_for("items", got["items"]["Damage_Attack"]["payload"])
               + C.defs_for("talents", got["talents"]["Piper"]["payload"]))
    assert rebuilt == defs, "an opened block would not save back as itself"

    pay = got["items"]["Damage_Attack"]["payload"]
    pay["values"][0]["new"] = 0.9
    blocks = {tuple(b) for b in got["items"]["Damage_Attack"]["blocks"]}
    C.save(C.defs_for("items", pay), "m1", tmp_path, replace=blocks)
    doc = tomllib.loads((tmp_path / "m1" / "manifest.toml").read_text())
    items = [c for c in doc["content"] if c["kind"] == "item"]
    assert len(items) == 1 and items[0]["value_patches"][0][2] == 0.9
    assert sum(c["kind"] == "talent" for c in doc["content"]) == 1, "an untouched block moved"


HERO_MANIFEST = """[mod]
id = "m"

[[content]]
kind = "hero"
id = "Nyx"
base = "Piper"

[[content.abilities]]
set = "Old.value"
value = 1.0

[content.values]
"X" = 3

# the next block's own comment
[[content]]
kind = "item"
id = "A"
base = "B"
"""


def test_hero_abilities_are_replaced_whole_and_nothing_else_moves():
    # The steps are a sequence the build replays: a second save must not
    # append the same copy again, so the list is replaced.
    steps = [{"set": "New.value", "value": 2.5}, {"copy": "G", "as": "H"}]
    out = M.set_hero_abilities(HERO_MANIFEST, "Nyx", steps)
    assert M.hero_blocks(out)[0]["steps"] == steps
    assert M.set_hero_abilities(out, "Nyx", steps) == out, "saving twice changed the file"
    doc = tomllib.loads(out)
    assert doc["content"][0]["values"] == {"X": 3} and doc["content"][1]["id"] == "A"
    assert "# the next block's own comment" in out
    assert "abilities" not in tomllib.loads(M.set_hero_abilities(out, "Nyx", []))["content"][0]


def test_hero_abilities_refuse_an_inline_list_and_an_unknown_block():
    inline = ('[[content]]\nkind = "hero"\nid = "Nyx"\nbase = "Piper"\n'
              'abilities = [{ set = "a", value = 1 }]\n')
    with pytest.raises(C.EditorError):
        M.set_hero_abilities(inline, "Nyx", [{"set": "b", "value": 2}])
    with pytest.raises(C.EditorError):
        M.set_hero_abilities(HERO_MANIFEST, "Nope", [])


def test_abilities_save_route_only_writes_a_hero_built_on_that_hero(tmp_path):
    from types import SimpleNamespace

    from rsmm.cli.editor import abilities as AB
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "manifest.toml").write_text(HERO_MANIFEST)
    req = SimpleNamespace(ctx=SimpleNamespace(mods_dir=tmp_path),
                          body={"mod": "m", "block": "Nyx", "hero": "Beowulf", "steps": []})
    with pytest.raises(ValueError, match="not a custom hero built on Beowulf"):
        AB._save(req)
    req.body["hero"] = "Piper"
    assert AB._save(req)["steps"] == 0
    saved = tomllib.loads((tmp_path / "m" / "manifest.toml").read_text())
    assert "abilities" not in saved["content"][0]


def test_a_custom_hero_block_is_added_for_ability_changes():
    """The Abilities tab saves into a `kind = "hero"` block; one can be made for
    a mod that has none, and its steps can then be written."""
    text = '[mod]\nid = "m"\n\n[[content]]\nkind = "item"\nid = "X"\nbase = "Y"\n'
    new = M.add_hero_block(text, "BeowulfEdit", "Beowulf", "Beowulf (edited)")
    assert [b["id"] for b in M.hero_blocks(new)] == ["BeowulfEdit"]
    assert M.hero_blocks(new)[0]["base"] == "Beowulf"
    step = {"set": "A.value", "value": 1}
    saved = M.set_hero_abilities(new, "BeowulfEdit", [step])
    assert M.hero_blocks(saved)[0]["steps"] == [step]
    with pytest.raises(C.EditorError, match="already"):
        M.add_hero_block(new, "BeowulfEdit", "Beowulf", "x")
