"""Deriving whether a mod is client-only (`rsmm.engine.mod_scope`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine.mod_scope import (
    asset_is_client_only,
    classify_mod_dir,
    classify_runtime,
    lua_reasons,
)

SDK = 'local R = require "rsmm"\n'


def make_mod(root: Path, *, manifest: str = "", lua: str | None = None,
             assets: tuple[str, ...] = ()) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.toml").write_text('[mod]\nid = "m"\nversion = "1.0.0"\n' + manifest,
                                        encoding="utf-8")
    if lua is not None:
        (root / "init.lua").write_text(lua, encoding="utf-8")
    for rel in assets:
        f = root / "assets" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    return root


# --- Lua ---------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    'R.log("hi")',
    'R.on("run_start", function() end)',
    'R.overlay.publish({rows = {}})',
    'R.damage.enable(); local t = R.damage.total()',
    'R.camera.set("Default", 1.5)',
    'R.config.get("x"); R.kv.set("a", 1); R.schedule.every(1, function() end)',
    'local h = R.entity.hero(); local hp = R.hp.get(h); local s = R.stat.get(h, "x")',
    'local exp = R.exp or {}',  # aliasing a namespace that is client-only as a whole
    'local peers = R.net.peers()',  # the damage meter's peer-name read
    # a wheel handler: local input, a menu-state read, a key-binding read
    'R.input.on_wheel(function(n) if not R.game.flag("is_menu_open") '
    'and R.input.wheel_free() then R.log(n) end end)',
    # a drag handler: local input, a menu-state read, a middle-binding read
    'R.input.on_drag(function(phase, dx, dy) if not R.game.flag("is_menu_open") '
    'and R.input.middle_free() then R.log(phase, dx, dy) end end)',
])
def test_read_only_and_presentation_lua_is_client_only(body):
    assert lua_reasons(SDK + body) == []


@pytest.mark.parametrize("body, needle", [
    ('R.give.by_name("x")', "R.give.by_name"),
    ('R.stat.modify(h, "x", 2)', "R.stat.modify"),
    ('R.hp.set(h, 1)', "R.hp.set"),
    ('R.talent.grant(1)', "R.talent.grant"),
    ('R.emit("EVENT")', "R.emit"),
    ('R.options.set("x", 1)', "R.options.set"),
])
def test_writes_and_unlisted_calls_are_gameplay(body, needle):
    assert any(needle in r for r in lua_reasons(SDK + body))


def test_unknown_namespaces_fail_closed():
    # Anything not positively known to be client-only is gameplay.
    assert lua_reasons(SDK + "R.brand_new_thing.do_it()") != []


def test_aliasing_a_gameplay_namespace_is_caught():
    # `local s = R.stat` hides every later `s.modify(...)` from a name-based scan,
    # so aliasing a namespace that is not client-only as a whole is gameplay.
    assert any("R.stat" in r for r in lua_reasons(SDK + "local s = R.stat\ns.modify(1)"))


@pytest.mark.parametrize("body", [
    'R["give"].by_name("x")',
    'local f = R; f.give.by_name("x")',
    'helper(R)',
])
def test_dynamic_or_escaping_sdk_use_is_gameplay(body):
    assert lua_reasons(SDK + body) != []


def test_a_differently_named_sdk_alias_is_followed():
    src = 'local sdk = require("rsmm")\nsdk.give.by_name("x")'
    assert any("sdk.give" in r for r in lua_reasons(src))


CHEAT = '\nS.stat.modify(h, "move_speed", 2)'


@pytest.mark.parametrize("src", [
    # a require the scan cannot read the module name of
    'local S = require("rs" .. "mm")' + CHEAT,
    'local name = "rsmm"\nlocal S = require(name)' + CHEAT,
    'local ok, S = pcall(require, "rsmm")' + CHEAT,
    'local r = require\nlocal S = r "rsmm"' + CHEAT,
    'local S = require("\\114smm")' + CHEAT,
    # the SDK bound where the scan cannot follow it
    'local t = {}\nt.S = require "rsmm"\nt.S.stat.modify(h, "move_speed", 2)',
    'local a, S = 1, require "rsmm"' + CHEAT,
    'use(require "rsmm")',
    'return require "rsmm"',
    'local S = require "rsmm" or {}' + CHEAT,
    # the SDK reached through the environment or the module cache
    'require "rsmm"\nlocal S = package.loaded["rsmm"]' + CHEAT,
    'local S = _G["rsmm"]\nS.give_item(1)',
    'local S = _G.rsmm\nS.give_item(1)',
    'local S = _ENV.rsmm\nS.give_item(1)',
    # the native bindings without a dot after the name
    'local n = rsmm\nn.give_item(1)',
    # the SDK inside a table constructor, continued past a line break, or as
    # the environment itself
    'local S = { R = require "rsmm" }\nS.R.stat.modify(h, "move_speed", 2)',
    'local S = require "rsmm"\n.stat\nS.modify(h, "move_speed", 2)',
    'local _ENV = require "rsmm"\nstat.modify(h, "move_speed", 2)',
])
def test_obtaining_the_sdk_under_an_unchecked_name_is_gameplay(src):
    # Each of these calls a gameplay function through a name the scan never
    # learns. Before this was checked, every one was classified client-only,
    # which kept the mod out of the public-matchmaking gate.
    assert lua_reasons(src) != []


@pytest.mark.parametrize("src", [
    'local R = require "rsmm"\nR.log("x")',
    "local R = require('rsmm');\nR.log('x')",
    'local R = require("rsmm")\nlocal data = require "stats_gen"\nR.log(data)',
    'require "rsmm"\nlocal R = require "rsmm"\nR.log("x")',
    'local x = 1; local R = require "rsmm"\nR.log("x")',
    # text, not code
    'local R = require "rsmm"\nR.log("see _G or package.loaded or require(x)")',
])
def test_plain_sdk_bindings_stay_client_only(src):
    assert lua_reasons(src) == []


@pytest.mark.parametrize("binding", [
    'local S =\n    require "rsmm"',
    'local S\n=\nrequire\n"rsmm"',
    'S =\n  require("rsmm")',
])
def test_a_binding_wrapped_across_lines_registers_its_alias(binding):
    # Lua treats a line break as whitespace, so the alias must still be learned
    # and the gameplay call through it reported by name.
    reasons = lua_reasons(binding + CHEAT)
    assert any("S.stat.modify" in r for r in reasons), reasons


@pytest.mark.parametrize("src", [
    'do local R = require "rsmm" end',
    'R.on("x", function() local R = require "rsmm"; R.log(1) end)',
    # names that only look like the loader's globals
    'local R = require "rsmm"\nlocal label = { package = "HUD" }\nR.log(label.package)',
    'local R = require "rsmm"\nlocal package = "HUD"\nR.log(package)',
    'local R = require "rsmm"\nlocal t = { _G = 1, rsmm = 2 }\nR.log(t._G, t.rsmm)',
])
def test_bindings_in_blocks_and_lookalike_names_stay_client_only(src):
    assert lua_reasons(src) == []


def test_sdk_internals_and_native_bindings_are_gameplay():
    assert lua_reasons('local d = require "rsmm.damage"') != []
    assert lua_reasons('rsmm.hook(0x140000000, function() end)') != []


def test_comments_and_strings_are_not_code():
    src = SDK + '-- R.give.by_name("x")\n--[[ R.stat.modify ]]\nR.log("call R.hp.set later")'
    assert lua_reasons(src) == []


# --- assets ------------------------------------------------------------------

@pytest.mark.parametrize("path, ok", [
    ("3D/Characters/Heroes/Beowulf/Textures/T_Beowulf_ALB.tga.Texture.dxt", True),
    ("FX/Textures/Patterns\\Noise_B_NRM.png.Texture.nrm", True),
    ("Audio/Music.bank", True),
    ("Text/Refugees~GAM.xls.LocalText.gen", True),
    ("Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen", False),
    ("3D/Characters/Enemies\\X\\X_GEO.fbx.Geometry.gen", False),  # a model, not a texture
    ("Audio/Not/A/Bank.gen", False),
])
def test_asset_families(path, ok):
    assert asset_is_client_only(path) is ok


# --- whole mods --------------------------------------------------------------

def test_a_meter_with_an_overlay_is_client_only(tmp_path):
    mod = make_mod(tmp_path / "meter", manifest="[overlay]\ntitle = 'x'\n",
                   lua=SDK + "R.damage.enable()\nR.overlay.publish({})")
    assert classify_mod_dir(mod).client_only


def test_a_texture_swap_is_client_only(tmp_path):
    mod = make_mod(tmp_path / "skin", assets=("3D/X/T_A_ALB.tga.Texture.dxt",))
    assert classify_mod_dir(mod).client_only


@pytest.mark.parametrize("manifest", [
    '[[content]]\nkind = "item"\n',
    '[[patch]]\ntarget = "x"\n',
])
def test_content_and_patches_are_gameplay(tmp_path, manifest):
    assert not classify_mod_dir(make_mod(tmp_path / "m", manifest=manifest)).client_only


def test_a_data_override_is_gameplay(tmp_path):
    herodef = "Definitions/Heroes/Merlin.herodef.ot.DtHeroDefinition.gen"
    mod = make_mod(tmp_path / "m", assets=(herodef,))
    assert not classify_mod_dir(mod).client_only


def test_the_declared_scope_is_not_trusted(tmp_path):
    # The case that motivated deriving the verdict: a stat mod labelled local-only.
    mod = make_mod(tmp_path / "sprint", manifest='multiplayer_scope = "local-only"\n',
                   lua=SDK + 'R.stat.modify(h, "move_speed", 2)')
    verdict = classify_mod_dir(mod)
    assert not verdict.client_only
    assert any("R.stat.modify" in r for r in verdict.reasons)


def test_runtime_classification_reads_lua_and_decoded_assets(tmp_path):
    mod = make_mod(tmp_path / "m", lua=SDK + 'R.log("x")')
    assert classify_runtime(mod, ["Audio/Music.bank"]).client_only
    assert not classify_runtime(mod, ["Definitions/Enemies/X.enemydef.ot"]).client_only
