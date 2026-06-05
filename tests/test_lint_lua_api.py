"""Lint guard: mod Lua must reference real events + engine symbols.

A typo in R.on("...") or R.engine.call("...") fails silently at runtime
(the handler simply never fires / resolves), so lint warns at author time
against the canonical event + symbol vocabulary.
"""

from __future__ import annotations

from rsmm.cli import lint


def _mod(tmp_path, lua: str, name="LuaMod"):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.toml").write_text('[mod]\nid = "LuaMod"\n')
    (d / "init.lua").write_text(lua)
    return d


def test_valid_events_and_calls_pass(tmp_path):
    d = _mod(
        tmp_path,
        'R.on("ready", function() end)\n'
        'R.on("tick", function() end)\n'
        'R.on("level_up", function() end)\n'
        'R.engine.call("Resource_LookupByPath")\n',
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_unknown_event_warns(tmp_path):
    d = _mod(tmp_path, 'R.on("levelup", function() end)\n')
    errs, warns = lint._lint_lua_api("LuaMod", d)
    assert errs == 0 and warns == 1


def test_unknown_engine_symbol_warns(tmp_path):
    d = _mod(tmp_path, 'R.engine.resolve("Not_A_Real_Function")\n')
    errs, warns = lint._lint_lua_api("LuaMod", d)
    assert warns == 1


def test_builtin_events_recognised():
    events, callables = lint._engine_vocab()
    assert {"ready", "tick", "exit", "setup"} <= events
    # gameplay events from the symbol map are merged in
    assert "level_up" in events and "run_end" in events
    # callables come from the map's cabi-tagged symbols
    assert "Resource_LookupByPath" in callables


def test_single_quotes_and_subdir_lua(tmp_path):
    d = _mod(tmp_path, "")
    (d / "sub").mkdir()
    (d / "sub" / "extra.lua").write_text("R.on('bogus_event', function() end)\n")
    errs, warns = lint._lint_lua_api("LuaMod", d)
    assert warns == 1
