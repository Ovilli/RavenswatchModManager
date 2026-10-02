"""The Scripts tab's block program: Blockly's saved state in, a marked section
of init.lua out. The generator is the only thing that writes code, so these pin
what it will and will not say."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from rsmm.cli import lint
from rsmm.cli.editor import blocks as B
from rsmm.cli.editor import content as C
from rsmm.cli.editor import modio as M


def blk(type_, fields=None, inputs=None, **kw):
    d = {"type": type_, "id": f"{type_}-{id(kw)}", "fields": fields or {}}
    if inputs:
        d["inputs"] = inputs
    d.update(kw)
    return d


def seq(*blocks):
    for a, b in zip(blocks, blocks[1:], strict=False):
        a["next"] = {"block": b}
    return {"block": blocks[0]}


def num(n):
    return {"block": blk("math_number", {"NUM": n})}


def program(*tops, variables=()):
    return {"blocks": {"languageVersion": 0, "blocks": list(tops)}, "variables": list(variables)}


def on_start(*body):
    return blk("rsmm_on_event", {"EVENT": "run:start"}, {"DO": seq(*body)})


FULL = program(
    on_start(
        blk("rsmm_give_item", {"ITEM": "Armor_Per_Object", "COUNT": 3}),
        blk("rsmm_grant_xp", inputs={"AMOUNT": num(5000)}),
        blk("rsmm_stat_add", {"STAT": "Crit chance"}, {"AMOUNT": num(0.5), "SECONDS": num(0)}),
        blk("variables_set", {"VAR": {"id": "v1"}}, {"VALUE": num(1)}),
        blk("procedures_callnoreturn", extraState={"name": "hello", "params": ["x"]},
            inputs={"ARG0": {"block": blk("variables_get", {"VAR": {"id": "v1"}})}})),
    blk("rsmm_on_gameplay", {"NAME": "ENEMY_KILLED"},
        {"DO": seq(blk("rsmm_shards", {"ACTION": "add"}, {"AMOUNT": num(10)}))}),
    blk("procedures_defnoreturn", {"NAME": "hello"},
        {"STACK": seq(blk("rsmm_log", inputs={"TEXT": {"block": blk(
            "variables_get", {"VAR": {"id": "p1"}})}}))},
        extraState={"params": [{"name": "x", "id": "p1"}]}),
    variables=[{"name": "score", "id": "v1"}, {"name": "x", "id": "p1"}])


def test_a_program_becomes_one_marked_section_with_its_state_inside():
    lua, warnings = B.compile_blocks(FULL)
    assert lua.startswith(B.BEGIN) and lua.rstrip().endswith(B.END) and not warnings
    assert 'R.on("run:start"' in lua and 'R.on("gameplay:ENEMY_KILLED"' in lua
    assert '__give("Armor_Per_Object", 3)' in lua and "R.shards.add(10)" in lua
    assert M.read_blocks(lua) == B.validate_state(FULL), "the page could not open its own save"


def test_only_helpers_the_program_uses_are_written():
    lua, _ = B.compile_blocks(program(on_start(blk("rsmm_log", inputs={"TEXT": num(1)}))))
    assert "__run" in lua and "__give" not in lua and "R.xp.arm" not in lua


def test_what_it_writes_passes_the_mod_lua_lint_rules():
    lua, _ = B.compile_blocks(FULL)
    assert not lint._RE_RAW_VA.search(lua)
    assert not lint._RE_LOWLEVEL.search(lua)


@pytest.mark.skipif(shutil.which("luac") is None, reason="no luac")
def test_the_lua_parses(tmp_path):
    p = tmp_path / "init.lua"
    p.write_text(B.compile_blocks(FULL)[0])
    assert subprocess.run(["luac", "-p", str(p)], capture_output=True).returncode == 0


def test_text_cannot_break_out_of_its_string():
    nasty = 'x"); os.execute("rm -rf /") --\n'
    lua, _ = B.compile_blocks(program(on_start(
        blk("rsmm_log", inputs={"TEXT": {"block": blk("text", {"TEXT": nasty})}}))))
    body = lua.split("\ndo\n", 1)[1]
    assert '\\"); os.execute(' in body and '"); os.execute' not in body.replace('\\"', "")


@pytest.mark.parametrize("bad", [
    blk("lua_raw", {"CODE": "os.exit()"}),                      # not a block the editor knows
    blk("rsmm_give_item", {"ITEM": 'a"); evil("', "COUNT": 1}),
    blk("rsmm_give_item", {"ITEM": "Ok", "COUNT": 0}),
    blk("rsmm_stat_add", {"STAT": "x\ny"}, {"AMOUNT": num(1), "SECONDS": num(0)}),
    blk("rsmm_grant_talent", {"TALENT": "Q", "TIER": "9"}),
    blk("rsmm_hp", {"ACTION": "nuke"}, {"AMOUNT": num(1)}),
    blk("procedures_callnoreturn", extraState={"name": "ghost"}),
    blk("variables_set", {"VAR": {"id": "nope"}}, {"VALUE": num(1)}),
])
def test_a_block_outside_the_whitelist_is_refused(bad):
    with pytest.raises(C.EditorError):
        B.compile_blocks(program(on_start(bad)))


def test_bad_events_and_timers_are_refused():
    for top in (blk("rsmm_on_gameplay", {"NAME": 'a"b'}), blk("rsmm_on_every", {"SECONDS": 0}),
                blk("rsmm_on_event", {"EVENT": "tick"})):
        top["inputs"] = {"DO": seq(blk("rsmm_log", inputs={"TEXT": num(1)}))}
        with pytest.raises(C.EditorError):
            B.compile_blocks(program(top))


def test_loops_are_capped_and_while_does_not_exist():
    lua, _ = B.compile_blocks(program(on_start(blk(
        "controls_repeat_ext", inputs={"TIMES": num(10**9), "DO": seq(
            blk("rsmm_log", inputs={"TEXT": num(1)}))}))))
    assert f"math.min(math.floor(1000000000), {B.MAX_REPEAT})" in lua
    with pytest.raises(C.EditorError):
        B.compile_blocks(program(on_start(blk("controls_whileUntil"))))


def test_blocks_outside_an_event_are_reported_not_run():
    lua, warnings = B.compile_blocks(program(blk("rsmm_log", inputs={"TEXT": num(1)})))
    assert lua == "" and any("do nothing" in w for w in warnings)


def test_an_empty_program_writes_nothing_and_removes_an_old_section(tmp_path):
    (tmp_path / "init.lua").write_text('R.log("mine")\n')
    assert M.write_blocks(tmp_path, FULL) == []
    assert "R.log(\"mine\")" in (tmp_path / "init.lua").read_text()
    M.write_blocks(tmp_path, B.empty_state())
    assert (tmp_path / "init.lua").read_text().strip() == 'R.log("mine")'


def test_blocks_and_test_grants_share_init_lua_without_touching_each_other(tmp_path):
    M.write_script(tmp_path, M.script_config({"xp": 100}))
    M.write_blocks(tmp_path, FULL)
    text = (tmp_path / "init.lua").read_text()
    assert M.read_script(text)["xp"] == 100 and M.read_blocks(text) is not None
    M.write_blocks(tmp_path, B.empty_state())
    text = (tmp_path / "init.lua").read_text()
    assert M.read_script(text)["xp"] == 100 and M.read_blocks(text) is None


def test_the_save_route_refuses_a_bad_program_before_writing(tmp_path):
    class Req:
        body = {"program": program(on_start(blk("lua_raw")))}
    with pytest.raises(C.EditorError):
        C._program(Req)


def test_opening_a_mod_returns_its_program(tmp_path):
    mod = tmp_path / "m"
    mod.mkdir()
    (mod / "manifest.toml").write_text('[mod]\nid = "m"\nname = "m"\n')
    M.write_blocks(mod, FULL)
    got = M.load_mod(tmp_path, "m")
    assert got["program"] == B.validate_state(FULL) and not got["kept"]


HARNESS = """
package.preload["rsmm"] = function()
    local R, handlers, log = {}, {}, {}
    R.log = function(s) log[#log + 1] = s end
    R.on = function(name, fn) handlers[name] = fn end
    R.entity = { ready = function() return true end }
    R.schedule = { next_main = function(fn) fn() end, every_main = function() return 1 end,
                   after_main = function(_, fn) fn() end, cancel = function() end }
    R.hp = { heal = function(n) log[#log + 1] = "heal " .. tostring(n) end }
    R.__handlers, R.__log = handlers, log
    return R
end
dofile(arg[1])
local R = require "rsmm"
R.__handlers["gameplay:ENEMY_KILLED"]()
print(table.concat(R.__log, "|"))
"""


@pytest.mark.skipif(shutil.which("lua") is None, reason="no lua")
def test_loops_lists_and_stop_behave_when_run(tmp_path):
    v = lambda i: {"id": i}   # noqa: E731
    get = lambda i: {"block": blk("variables_get", {"VAR": v(i)})}   # noqa: E731
    top = blk("rsmm_on_gameplay", {"NAME": "ENEMY_KILLED"}, {"DO": seq(
        blk("variables_set", {"VAR": v("l")}, {"VALUE": {"block": blk(
            "lists_create_with", extraState={"itemCount": 0})}}),
        blk("controls_for", {"VAR": v("i")}, {"FROM": num(1), "TO": num(10**9), "BY": num(1),
            "DO": seq(
                blk("controls_if", inputs={
                    "IF0": {"block": blk("logic_compare", {"OP": "GT"},
                                           {"A": get("i"), "B": num(3)})},
                    "DO0": seq(blk("controls_flow_statements", {"FLOW": "CONTINUE"}))}),
                blk("lists_setIndex", {"MODE": "INSERT", "WHERE": "LAST"},
                    {"LIST": get("l"), "TO": get("i")}))}),
        blk("controls_forEach", {"VAR": v("i")}, {"LIST": get("l"), "DO": seq(
            blk("rsmm_hp", {"ACTION": "heal"}, {"AMOUNT": get("i")}))}),
        blk("rsmm_stop"),
        blk("rsmm_hp", {"ACTION": "damage"}, {"AMOUNT": num(99)}),     # never reached
    )})
    lua, _ = B.compile_blocks(program(top, variables=[{"name": "l", "id": "l"},
                                                      {"name": "i", "id": "i"}]))
    (tmp_path / "init.lua").write_text(lua)
    (tmp_path / "run.lua").write_text(HARNESS)
    out = subprocess.run(["lua", str(tmp_path / "run.lua"), str(tmp_path / "init.lua")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "heal 1|heal 2|heal 3"
