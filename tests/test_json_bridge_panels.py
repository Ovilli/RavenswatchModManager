"""The desktop panels backed by the JSON bridge: conflicts, loader flags, the
vanilla-launch cleanup and the item ban list.

Each test pins what the UI shows or what the command writes into the game
folder, against a fake install and mods folder.
"""

from __future__ import annotations

import json

import pytest

from rsmm.cli import compat, json_bridge, merge


def _out(capsys):
    return json.loads(capsys.readouterr().out)


# --- conflicts -------------------------------------------------------------

@pytest.fixture
def mods(tmp_path, monkeypatch):
    root = tmp_path / "mods"
    root.mkdir()
    for mod in (json_bridge, merge, compat):
        monkeypatch.setattr(mod, "MODS_DIR", root)
    return root


def _mod(root, mod_id, *, enabled=True, assets=(), extra=""):
    d = root / mod_id
    (d / "assets").mkdir(parents=True)
    (d / "manifest.toml").write_text(
        f'[mod]\nid = "{mod_id}"\nname = "{mod_id}"\nversion = "1.0.0"\n'
        f'enabled = {"true" if enabled else "false"}\n{extra}')
    for rel in assets:
        p = d / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return d


def test_two_mods_writing_one_asset_conflict(mods, capsys):
    _mod(mods, "a", assets=["3D/Characters/Hero.fbx.Geometry.gen"])
    _mod(mods, "b", assets=["3D/Characters/Hero.fbx.Geometry.gen"])
    json_bridge.cmd_conflicts()
    files = [c for c in _out(capsys) if c["type"] == "file"]
    assert files == [{"type": "file", "path": "3D/Characters/Hero.fbx.Geometry.gen",
                      "modIds": ["a", "b"]}]


@pytest.mark.parametrize("rel", [
    # apply MERGES these, so two mods shipping one is not a conflict. The
    # alias table is the case two custom heroes (Nyx + Gretel) both hit.
    "_root/DarkTalesResources/ApplicationSettings.ot",
    "Text/Hero_Piper_Common~GAM.xls.LocalText.gen.LangEN",
    "Definitions/Maps/X.mapdef.ot.DtMapDefinition.gen",
    "EntitySettings/Heroes/Hero_Piper/Hero_Nyx.entity.UsedRscCache.ot",
    # ...and never installs these at all.
    "_pending_bans/ban.json",
    "3D/Model.glb.rsmmcook",
])
def test_files_apply_merges_or_skips_are_not_conflicts(mods, capsys, rel):
    _mod(mods, "nyx", assets=[rel])
    _mod(mods, "gretel", assets=[rel])
    json_bridge.cmd_conflicts()
    assert [c for c in _out(capsys) if c["type"] == "file"] == []


def test_a_disabled_mod_cannot_conflict(mods, capsys):
    _mod(mods, "a", assets=["x/y.gen"])
    _mod(mods, "b", enabled=False, assets=["x/y.gen"])
    json_bridge.cmd_conflicts()
    assert _out(capsys) == []


def test_a_declared_hard_conflict_is_listed(mods, capsys):
    _mod(mods, "a", extra='conflicts = ["b"]\n')
    _mod(mods, "b")
    json_bridge.cmd_conflicts()
    manifest = [c for c in _out(capsys) if c["type"] == "manifest"]
    assert manifest and sorted(manifest[0]["modIds"]) == ["a", "b"]


def test_no_mods_folder_is_no_conflicts(tmp_path, monkeypatch, capsys):
    for mod in (json_bridge, merge, compat):
        monkeypatch.setattr(mod, "MODS_DIR", tmp_path / "missing")
    json_bridge.cmd_conflicts()
    assert _out(capsys) == []


# --- loader flags ----------------------------------------------------------

@pytest.fixture
def game(tmp_path, monkeypatch):
    g = tmp_path / "Ravenswatch"
    g.mkdir()
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: g)
    monkeypatch.setattr(json_bridge, "_loader_status",
                        lambda _g: {"loaderInstalled": False, "launchOptionsPresent": None})
    return g


SAFE = sorted(json_bridge._SAFE_FLAG_NAMES)
LOCKED = sorted(json_bridge._KNOWN_FLAG_NAMES - json_bridge._SAFE_FLAG_NAMES)


def test_only_safe_flags_can_be_enabled_from_the_ui(game, capsys):
    assert SAFE, "no safe loader flags defined"
    want = [SAFE[0], *LOCKED[:1], "NOT_A_FLAG"]
    json_bridge.cmd_loader_flags_set(json.dumps(want))
    out = _out(capsys)
    assert out["ok"] is True and out["enabled"] == [SAFE[0]]
    written = json.loads((game / json_bridge._LOADER_FLAGS_FILE).read_text())
    assert written == [SAFE[0]]                  # a locked flag never reaches the file


def test_clearing_every_flag_removes_the_file(game, capsys):
    path = game / json_bridge._LOADER_FLAGS_FILE
    path.write_text(json.dumps([SAFE[0]]))
    json_bridge.cmd_loader_flags_set("[]")
    assert _out(capsys)["enabled"] == [] and not path.exists()


@pytest.mark.parametrize("payload, message", [
    ("{not json", "invalid JSON"),
    ('{"a": 1}', "JSON array"),
    ("[1, 2]", "JSON array"),
])
def test_a_malformed_flag_payload_is_refused(game, capsys, payload, message):
    json_bridge.cmd_loader_flags_set(payload)
    out = _out(capsys)
    assert out["ok"] is False and message in out["error"]
    assert not (game / json_bridge._LOADER_FLAGS_FILE).exists()


def test_setting_flags_without_an_install_is_an_error(monkeypatch, capsys):
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: None)
    json_bridge.cmd_loader_flags_set(json.dumps(SAFE[:1]))
    assert _out(capsys)["ok"] is False


@pytest.mark.parametrize("content, want", [
    (None, []),                                   # no file
    ("garbage{", []),                             # unreadable
    ('{"a": 1}', []),                             # not a list
])
def test_reading_flags_tolerates_a_bad_file(tmp_path, content, want):
    path = tmp_path / "flags.json"
    if content is not None:
        path.write_text(content)
    assert json_bridge._read_loader_flags(path) == want


def test_reading_flags_drops_unknown_names(tmp_path):
    path = tmp_path / "flags.json"
    path.write_text(json.dumps([SAFE[0], "NOT_A_FLAG", 3]))
    assert json_bridge._read_loader_flags(path) == [SAFE[0]]


def test_flags_get_reports_the_enabled_set(game, capsys):
    (game / json_bridge._LOADER_FLAGS_FILE).write_text(json.dumps([SAFE[0]]))
    json_bridge.cmd_loader_flags_get()
    out = _out(capsys)
    assert out["enabled"] == [SAFE[0]] and out["gameDir"] == str(game)


# --- vanilla launch: removing the loader -----------------------------------

def test_uninstall_restores_the_stock_winhttp(tmp_path):
    (tmp_path / "winhttp.dll").write_bytes(b"rsmm loader")
    (tmp_path / "winhttp_real.dll").write_bytes(b"stock")
    (tmp_path / "asset_map.json").write_text("{}")
    (tmp_path / "rsmm" / "lib").mkdir(parents=True)
    ok, notes = json_bridge._uninstall_loader_runtime(tmp_path)
    assert ok and "restored stock winhttp.dll" in notes
    assert (tmp_path / "winhttp.dll").read_bytes() == b"stock"
    assert not (tmp_path / "winhttp_real.dll").exists()
    assert not (tmp_path / "asset_map.json").exists()
    assert not (tmp_path / "rsmm").exists()


def test_uninstall_without_a_stock_copy_just_removes_the_loader(tmp_path):
    (tmp_path / "winhttp.dll").write_bytes(b"rsmm loader")
    ok, notes = json_bridge._uninstall_loader_runtime(tmp_path)
    assert ok and "removed rsmm winhttp.dll" in notes
    assert not (tmp_path / "winhttp.dll").exists()


def test_uninstall_on_a_clean_install_says_so(tmp_path):
    assert json_bridge._uninstall_loader_runtime(tmp_path) == (
        True, "loader artifacts already absent")


# --- item bans -------------------------------------------------------------

@pytest.mark.parametrize("payload, message", [
    ("nope", "invalid JSON"),
    ('{"x": 1}', "JSON array of item ids"),
    ('["a", 2]', "JSON array of item ids"),
])
def test_a_malformed_ban_list_is_refused(capsys, payload, message):
    json_bridge.cmd_item_bans_set(payload)
    out = _out(capsys)
    assert out["ok"] is False and message in out["error"]


# --- dispatch --------------------------------------------------------------

def test_an_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        json_bridge.main(["no-such-command"])
    assert e.value.code == 2


def test_dispatch_reaches_the_command(mods, capsys):
    _mod(mods, "a", assets=["x/y.gen"])
    _mod(mods, "b", assets=["x/y.gen"])
    json_bridge.main(["conflicts"])
    assert [c["type"] for c in _out(capsys)] == ["file"]
