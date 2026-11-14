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
        'local R = require "rsmm"\n'
        'R.on("ready", function() end)\n'
        'R.on("tick", function() end)\n'
        'R.on("level_up", function() end)\n'
        'R.engine.call("Resource_LookupByPath")\n',
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_unknown_event_warns(tmp_path):
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'R.on("levelup", function() end)\n',
    )
    errs, warns = lint._lint_lua_api("LuaMod", d)
    assert errs == 0 and warns == 1


def test_unknown_engine_symbol_warns(tmp_path):
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'R.engine.resolve("Not_A_Real_Function")\n',
    )
    _errs, warns = lint._lint_lua_api("LuaMod", d)
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
    (d / "sub" / "extra.lua").write_text(
        'local R = require "rsmm"\n'
        "R.on('bogus_event', function() end)\n"
    )
    _errs, warns = lint._lint_lua_api("LuaMod", d)
    assert warns == 1


def test_analytics_firehose_events_recognised():
    """The loader republishes the analytics sink's events by raw name, so they
    fire even though no symbol carries them. Warning on those told authors a
    working handler was dead — and pushed them onto the typed event instead."""
    events, _ = lint._engine_vocab()
    assert {"run_start", "levelup_run", "level_up_book", "enemy_killed"} <= events
    # level_up_reach is a FIELD of levelup_run (seen in game 2026-10-10), so a
    # handler on it would never fire and must keep warning.
    assert "level_up_reach" not in events


def test_analytics_event_does_not_warn(tmp_path):
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'R.on("levelup_run", function() end)\n',
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_read_above_its_local_is_an_error(tmp_path, capsys):
    """The closure reads a latch whose `local` is declared below it — nil at run
    time, and silent until the line runs. Lint is the only net a mod has."""
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'R.on("ready", function()\n'
        '    if seen then return end\n'
        'end)\n'
        'local seen = false\n',
    )
    errs, _warns = lint._lint_lua_api("LuaMod", d)
    assert errs == 1
    assert "init.lua:3" in capsys.readouterr().out


def test_unwalkable_lua_warns_instead_of_failing(tmp_path):
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'R.on("ready", function()\n',   # never closed
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 1)


def test_missing_require_rsmm_is_an_error(tmp_path, capsys):
    """`R` without the require is a nil global: the first R.on raises and no
    handler registers, yet lint used to report a clean pass."""
    d = _mod(tmp_path, 'R.on("ready", function() end)\n')
    errs, warns = lint._lint_lua_api("LuaMod", d)
    assert errs == 1 and warns == 0
    assert "init.lua:1" in capsys.readouterr().out


def test_require_rsmm_declaration_stays_clean(tmp_path):
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'R.on("ready", function() end)\n'
        'R.on("tick", function() end)\n',
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_require_rsmm_after_first_use_reports_once(tmp_path, capsys):
    """A declaration below the use is the existing late-local error; the new
    check must not double-report the same read."""
    d = _mod(
        tmp_path,
        'R.on("ready", function() end)\n'
        'local R = require "rsmm"\n',
    )
    errs, _warns = lint._lint_lua_api("LuaMod", d)
    assert errs == 1
    assert "init.lua:1" in capsys.readouterr().out


def test_global_require_rsmm_binding_stays_clean(tmp_path):
    """`R = require "rsmm"` binds the SDK for the whole lua_State, so the rest
    of the file reads R as a global and that is not a nil read."""
    d = _mod(
        tmp_path,
        'R = require "rsmm"\n'
        'R.on("ready", function() end)\n',
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_global_binding_in_init_covers_a_helper(tmp_path):
    """Helpers run in the same lua_State init.lua bound R in, so flagging their
    global reads would fail a mod that works in game."""
    d = _mod(tmp_path, 'R = require "rsmm"\n')
    (d / "helper.lua").write_text('R.on("tick", function() end)\n')
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_a_helper_still_errors_when_nothing_binds_r(tmp_path, capsys):
    """The mod-wide suppression must not swallow the real case: no file binds
    R, so the helper's R.on is still the nil global error."""
    d = _mod(tmp_path, 'print("no binding here")\n')
    (d / "helper.lua").write_text('R.on("tick", function() end)\n')
    errs, _warns = lint._lint_lua_api("LuaMod", d)
    assert errs == 1
    assert "helper.lua:1" in capsys.readouterr().out
