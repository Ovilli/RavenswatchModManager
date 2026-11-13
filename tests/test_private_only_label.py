"""The engine labels a mod that changes the game "Private games only" when it
is packed and published (`mod_scope.stamp_private_only` / `private_only_tags`),
so the registry gets the label without a moderator setting it by hand."""

from __future__ import annotations

import json
import os
import re
import tomllib
import zipfile
from pathlib import Path

import pytest

from rsmm.engine import mod_scope as MS


@pytest.mark.parametrize("text, tags", [
    ('[mod]\nid = "a"\ntags = ["heroes", "test"]\n\n[[content]]\nkind = "hero"\n',
     ["heroes", "test", "private-only"]),
    ('[mod]\nid = "a"\ntags = []\n', ["private-only"]),
    ('[mod]\nid = "a"\ntags = [\n  "x",\n  "y",\n]\n[other]\nk = 1\n', ["x", "y", "private-only"]),
    ('# about\n[mod]\nid = "a"\nname = "A"\n\n[x]\ntags = ["not the mod"]\n', ["private-only"]),
    ('[mod]\r\nid = "a"\r\n', ["private-only"]),
])
def test_the_label_lands_in_mod_tags_and_nothing_else_changes(text, tags):
    out = MS.stamp_private_only(text)
    assert out is not None
    before, after = tomllib.loads(text), tomllib.loads(out)
    assert after["mod"]["tags"] == tags
    assert {k: v for k, v in after.items() if k != "mod"} == \
        {k: v for k, v in before.items() if k != "mod"}
    assert {k: v for k, v in after["mod"].items() if k != "tags"} == \
        {k: v for k, v in before["mod"].items() if k != "tags"}


@pytest.mark.parametrize("text", [
    '[mod]\nid = "a"\ntags = ["Cheat"]\n',            # an alias of the label
    '[mod]\nid = "a"\ntags = ["private games only"]\n',
    'not toml [',
    'id = "no mod table"\n',
])
def test_nothing_is_stamped_when_labelled_or_unreadable(text):
    assert MS.stamp_private_only(text) is None


def test_the_verdict_decides_not_the_author():
    gameplay = MS.ScopeVerdict("m", ["has [[content]] blocks"])
    client = MS.ScopeVerdict("m", [])
    assert MS.private_only_tags(["heroes"], gameplay) == ["heroes", "private-only"]
    assert MS.private_only_tags(["cheat"], gameplay) == ["cheat"]          # already labelled
    assert MS.private_only_tags(["heroes"], client) == ["heroes"]
    assert MS.private_only_tags(["private-only"], client) == ["private-only"]  # author's own


def _pack(tmp_path, monkeypatch, manifest: str, files: dict[str, bytes]) -> str:
    from rsmm.cli import cmd_pack
    src = tmp_path / "mods" / "m"
    src.mkdir(parents=True)
    (src / "manifest.toml").write_text(manifest, encoding="utf-8")
    for rel, data in files.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    monkeypatch.setattr(cmd_pack, "MODS_DIR", tmp_path / "mods")
    monkeypatch.setattr(cmd_pack, "dist_out_dir", lambda: tmp_path / "dist")
    monkeypatch.setattr(cmd_pack, "_vanilla_offenders", lambda _d: [])
    assert cmd_pack.main(["m"]) == 0
    with zipfile.ZipFile(tmp_path / "dist" / "m.zip") as z:
        return z.read("m/manifest.toml").decode()


def test_pack_labels_a_gameplay_mod(tmp_path, monkeypatch, capsys):
    text = _pack(tmp_path, monkeypatch,
                 '[mod]\nid = "m"\nversion = "1.0.0"\ntags = ["heroes"]\n\n'
                 '[[content]]\nkind = "hero"\nid = "X"\n', {})
    assert tomllib.loads(text)["mod"]["tags"] == ["heroes", "private-only"]
    assert "Private games only" in capsys.readouterr().out


def test_pack_leaves_a_client_only_mod_alone(tmp_path, monkeypatch):
    manifest = '[mod]\nid = "m"\nversion = "1.0.0"\ntags = ["hud"]\n'
    text = _pack(tmp_path, monkeypatch, manifest,
                 {"init.lua": b'local R = require "rsmm"\nR.log("hi")\n'})
    assert text == manifest


def test_publish_metadata_carries_the_label(tmp_path, monkeypatch):
    from rsmm.cli import json_bridge
    mods = tmp_path / "mods"
    (mods / "m").mkdir(parents=True)
    (mods / "m" / "manifest.toml").write_text(
        '[mod]\nid = "m"\nversion = "1.0.0"\ntags = ["heroes"]\n\n'
        '[[patch]]\ntarget = "x"\n', encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "m.zip").write_bytes(b"PK")
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    monkeypatch.setattr(json_bridge, "dist_out_dir", lambda: dist)
    monkeypatch.setattr(json_bridge, "_collect_rsmm", lambda _a: {"ok": True})
    out = json_bridge.pack_mod_metadata("m")
    assert out["ok"] and out["privateOnly"] is True and out["privateOnlyReasons"]
    assert out["manifest"]["tags"] == ["heroes", "private-only"]


# ---- the store's copy of the check (packages/schemas/src/mod-scope.ts) --------
#
# The store runs a TypeScript copy on every upload, so a mod packed some other
# way still gets the label. It may only be STRICTER than the engine: these cases
# carry the engine's verdict into a fixture the TypeScript tests read
# (packages/schemas/src/__tests__/mod-scope.test.ts). Regenerate it with
# RSMM_REGEN=1 when a case or the engine's rules change.


_REPO = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO / "packages/schemas/src/__tests__/fixtures/mod-scope-cases.json"
_SDK = 'local R = require "rsmm"\n'
_CHEAT = '\nS.stat.modify(h, "move_speed", 2)'
LUA_CASES = [
    # client-only in the engine
    _SDK + 'R.log("hi")',
    _SDK + 'R.on("run_start", function() end)',
    _SDK + 'R.overlay.publish({rows = {}})',
    _SDK + 'R.damage.enable(); local t = R.damage.total()',
    _SDK + 'R.camera.set("Default", 1.5)',
    _SDK + 'R.config.get("x"); R.kv.set("a", 1); R.schedule.every(1, function() end)',
    _SDK + 'local h = R.entity.hero(); local hp = R.hp.get(h); local s = R.stat.get(h, "x")',
    _SDK + 'local peers = R.net.peers()',
    'local R = require "rsmm"\nR.log("x")',
    "local R = require('rsmm');\nR.log('x')",
    'local R = require("rsmm")\nlocal data = require "stats_gen"\nR.log(data)',
    'require "rsmm"\nlocal R = require "rsmm"\nR.log("x")',
    'local x = 1; local R = require "rsmm"\nR.log("x")',
    'local R = require "rsmm"\nR.log("see _G or package.loaded or require(x)")',
    'local S =\n    require "rsmm"\nS.log(1)',
    'S =\n  require("rsmm")\nS.log(1)',
    'R.on("x", function() local R = require "rsmm"; R.log(1) end)',
    '-- R.give.by_name("x")\n' + _SDK + 'R.log("R.give.by_name")',
    # gameplay in the engine
    _SDK + 'R.stat.modify(h, "move_speed", 2)',
    _SDK + 'R.give.by_name("x")',
    _SDK + 'R.engine.call("X")',
    _SDK + 'R["give"].by_name("x")',
    _SDK + 'local f = R; f.give.by_name("x")',
    _SDK + 'helper(R)',
    'local S = require("rs" .. "mm")' + _CHEAT,
    'local name = "rsmm"\nlocal S = require(name)' + _CHEAT,
    'local ok, S = pcall(require, "rsmm")' + _CHEAT,
    'local r = require\nlocal S = r "rsmm"' + _CHEAT,
    'local t = {}\nt.S = require "rsmm"\nt.S.stat.modify(h, "move_speed", 2)',
    'local a, S = 1, require "rsmm"' + _CHEAT,
    'use(require "rsmm")',
    'return require "rsmm"',
    'local S = require "rsmm" or {}' + _CHEAT,
    'require "rsmm"\nlocal S = package.loaded["rsmm"]' + _CHEAT,
    'local S = _G["rsmm"]\nS.give_item(1)',
    'local S = _G.rsmm\nS.give_item(1)',
    'local S = _ENV.rsmm\nS.give_item(1)',
    'local n = rsmm\nn.give_item(1)',
    'local S = { R = require "rsmm" }\nS.R.stat.modify(h, "move_speed", 2)',
    'local _ENV = require "rsmm"\nstat.modify(h, "move_speed", 2)',
    'local S = require "rsmm.engine"\nS.call(1)',
]
MANIFEST_CASES = [
    '[mod]\nid = "a"\n',
    '[mod]\nid = "a"\n\n[[content]]\nkind = "hero"\n',
    '[mod]\nid = "a"\n\n[[patch]]\ntarget = "x"\n',
    'content = [{ kind = "hero" }]\n[mod]\nid = "a"\n',
    '[mod]\nid = "a"\n\n[overlay]\ncontent = "hud"\n',
]
ASSET_CASES = [
    "3D/Characters/x.tga.Texture.dxt", "Audio/Music.bank", "Text/Common~GAM.xls.LocalText.gen",
    "EntitySettings/Heroes/Hero_X.entity.ot.EntitySettingsResource.gen",
    "Definitions/Heroes/X.herodef.ot.DtHeroDefinition.gen", "_root/DarkTalesResources/x.ot",
]


def _engine_cases() -> dict:
    return {
        "lua": [{"src": s, "gameplay": bool(MS.lua_reasons(s))} for s in LUA_CASES],
        "manifest": [{"src": s, "gameplay": bool(MS.manifest_reasons(tomllib.loads(s)))}
                     for s in MANIFEST_CASES],
        "asset": [{"path": p, "client_only": MS.asset_is_client_only(p)
                   and not p.startswith("_root/")} for p in ASSET_CASES],
        "client_namespaces": sorted(MS.CLIENT_NAMESPACES),
        "client_calls": sorted(MS.CLIENT_CALLS),
    }


def test_the_stores_case_fixture_carries_the_engines_verdicts():
    want = json.dumps(_engine_cases(), indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("RSMM_REGEN"):
        _FIXTURE.write_text(want, encoding="utf-8")
    assert _FIXTURE.read_text(encoding="utf-8") == want, (
        "the engine's scope rules or the cases changed: regenerate the store's fixture "
        "with RSMM_REGEN=1 pytest tests/test_private_only_label.py, then make "
        "packages/schemas/src/mod-scope.ts pass it")


def test_the_store_lists_the_same_client_only_sdk_calls():
    ts = (_REPO / "packages/schemas/src/mod-scope.ts").read_text(encoding="utf-8")

    def names(const: str) -> set[str]:
        block = re.search(rf"{const}: ReadonlySet<string> = new Set\(\[(.*?)\]\)", ts, re.S)
        assert block, const
        return set(re.findall(r"'([\w.]+)'", block.group(1)))
    assert names("CLIENT_NAMESPACES") == set(MS.CLIENT_NAMESPACES)
    assert names("CLIENT_CALLS") == set(MS.CLIENT_CALLS)
