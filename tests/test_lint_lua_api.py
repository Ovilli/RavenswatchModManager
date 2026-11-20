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


def test_global_require_rsmm_stays_clean(tmp_path):
    """`R = require "rsmm"` without `local` binds R in the mod's own lua_State,
    so its reads are not nil."""
    d = _mod(
        tmp_path,
        'R = require "rsmm"\n'
        'R.on("ready", function() end)\n',
    )
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_module_reading_global_r_from_init_stays_clean(tmp_path):
    """A module init.lua requires sees the global R init.lua set."""
    d = _mod(
        tmp_path,
        'R = require "rsmm"\n'
        'require "helper"\n',
    )
    (d / "helper.lua").write_text('R.on("ready", function() end)\n')
    assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_module_without_any_binding_is_an_error(tmp_path, capsys):
    """init.lua's `local R` does not reach a module, and nothing in the mod
    sets a global R, so the module's read is nil."""
    d = _mod(
        tmp_path,
        'local R = require "rsmm"\n'
        'require "helper"\n',
    )
    (d / "helper.lua").write_text('R.on("ready", function() end)\n')
    errs, warns = lint._lint_lua_api("LuaMod", d)
    assert (errs, warns) == (1, 0)
    assert "helper.lua:1" in capsys.readouterr().out


# --- #202 lint gaps: SDK surface a mod may not use -------------------------------

import pytest  # noqa: E402

_SDK = 'local R = require "rsmm"\n'


@pytest.mark.parametrize("line, needle", [
    ('R.hook(0x1, function() end)', "R.hook installs"),
    ("R.unhook(h)", "R.unhook removes"),
    ("if R.ptr.plausible(p) then end", "pointer-validation"),
    ('local E = require "rsmm.engine"', 'require "rsmm.engine"'),
    ('local C = require("rsmm.config")', 'require "rsmm.config"'),
    ("R.stat.get = function() return 0 end", "monkey-patching"),
    ("R.my_helper = 1", "monkey-patching"),
    ("function R.my_helper() end", "monkey-patching"),
    ("function R.stat:get() end", "monkey-patching"),
])
def test_sdk_only_surface_is_an_error(tmp_path, capsys, line, needle):
    errs, _warns = lint._lint_lua_api("LuaMod", _mod(tmp_path, _SDK + line + "\n"))
    assert errs == 1 and needle in capsys.readouterr().out


def test_the_rules_follow_any_name_the_sdk_is_bound_to(tmp_path):
    d = _mod(tmp_path, 'local S = require("rsmm")\nS.hook(1, f)\nS.x = 2\n')
    assert lint._lint_lua_api("LuaMod", d)[0] == 2


@pytest.mark.parametrize("body", [
    "local function fill(R) R.x = 1 end",
    "local function fill(t) local R = {} R.x = 1 end",
    "do local R = {}; R.x = 1 end",
    "for _, R in ipairs(list) do R.x = 1 end",
])
def test_shadowed_sdk_name_is_not_the_sdk(body):
    assert lint.sdk_surface_findings(_SDK + body + "\n") == []


@pytest.mark.parametrize("body", [
    "R.x = 1",
    "local function fill(t) R.x = 1 end",
    "do local R = {} end\nR.x = 1",
    "for _, v in ipairs(list) do R.x = 1 end",
])
def test_unshadowed_sdk_write_still_errors(body):
    found = lint.sdk_surface_findings(_SDK + body + "\n")
    assert len(found) == 1 and "monkey-patching" in found[0][2]


def test_lookalikes_are_not_flagged():
    src = (_SDK + 'local ok = R.stat.get("x") == 1\n'
           'local t = { R = 1 }; t.R.hook = 2\n'
           'R.log("R.hook and require \\"rsmm.engine\\" in a string")\n'
           '-- R.hook(1) in a comment\n'
           'local R2 = R\n')
    assert lint.sdk_surface_findings(src) == []


def test_read_block_is_a_low_level_primitive(tmp_path, capsys):
    errs, _ = lint._lint_lua_api("LuaMod", _mod(tmp_path, _SDK + "local b = I.read_block(p, 8)\n"))
    assert errs == 1 and "low-level primitive" in capsys.readouterr().out


def test_r_debug_warns_unless_the_mod_is_tagged_debug_or_test(tmp_path):
    d = _mod(tmp_path, _SDK + "R.debug.dump(e)\n")
    assert lint._lint_lua_api("LuaMod", d) == (0, 1)
    for tag in ("debug", "Test"):
        (d / "manifest.toml").write_text(f'[mod]\nid = "LuaMod"\ntags = ["{tag}"]\n')
        assert lint._lint_lua_api("LuaMod", d) == (0, 0)


def test_sdk_assigned_to_an_earlier_local_is_still_the_sdk():
    found = lint.sdk_surface_findings('local R\nR = require "rsmm"\nR.x = 1\n')
    assert len(found) == 1 and "monkey-patching" in found[0][2]
