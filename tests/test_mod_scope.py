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
