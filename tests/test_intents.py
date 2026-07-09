"""Unit tests for the `rsmm intents` host-side consumer."""

from __future__ import annotations

import json

import pytest

from rsmm.cli import cmd_intents as CI


@pytest.fixture()
def game_dir(tmp_path):
    cooking = tmp_path / "game" / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    return tmp_path / "game"


@pytest.fixture()
def mods_dir(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    return d


def _write_manifest(mods_dir, mod_id, enabled=True, with_flag=True):
    root = mods_dir / mod_id
    root.mkdir()
    lines = ["[mod]", f'id = "{mod_id}"', 'name = "T"', 'version = "0.1.0"']
    if with_flag:
        lines.append(f"enabled = {'true' if enabled else 'false'}")
    (root / "manifest.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _queue(game_dir, *intents):
    path = CI.intents_path(game_dir)
    with path.open("a", encoding="utf-8") as f:
        for it in intents:
            f.write(json.dumps(it) + "\n")
    return path


def test_read_intents_filters_garbage(game_dir):
    path = _queue(
        game_dir,
        {"op": "disable", "mod": "GoodMod", "ts": 1},
        {"op": "rm -rf", "mod": "GoodMod"},          # bad op
        {"op": "uninstall", "mod": "../escape"},      # bad id
        {"op": "enable", "mod": "Other_Mod-2"},
    )
    path.write_text(path.read_text(encoding="utf-8") + "not json\n", encoding="utf-8")
    intents, rejected = CI.read_intents(path)
    assert [(i["op"], i["mod"]) for i in intents] == [
        ("disable", "GoodMod"), ("enable", "Other_Mod-2")]
    assert len(rejected) == 3


def test_set_mod_enabled_flips_existing_flag(mods_dir):
    _write_manifest(mods_dir, "M", enabled=True)
    assert CI.set_mod_enabled(mods_dir, "M", False) == "ok"
    text = (mods_dir / "M" / "manifest.toml").read_text(encoding="utf-8")
    assert "enabled = false" in text and "enabled = true" not in text
    # idempotent
    assert CI.set_mod_enabled(mods_dir, "M", False) == "unchanged"


def test_set_mod_enabled_inserts_when_missing(mods_dir):
    _write_manifest(mods_dir, "M", with_flag=False)
    assert CI.set_mod_enabled(mods_dir, "M", False) == "ok"
    text = (mods_dir / "M" / "manifest.toml").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "[mod]"
    assert "enabled = false" in text


def test_uninstall_mod_removes_dir_and_rejects_escape(mods_dir):
    _write_manifest(mods_dir, "M")
    assert CI.uninstall_mod(mods_dir, "M") == "ok"
    assert not (mods_dir / "M").exists()
    assert CI.uninstall_mod(mods_dir, "M") == "missing"
    assert CI.uninstall_mod(mods_dir, "..") == "invalid"


def test_apply_executes_and_clears(game_dir, mods_dir, capsys):
    _write_manifest(mods_dir, "KeepMe", enabled=True)
    _write_manifest(mods_dir, "DropMe", enabled=True)
    path = _queue(
        game_dir,
        {"op": "disable", "mod": "KeepMe", "ts": 1},
        {"op": "enable", "mod": "KeepMe", "ts": 2},   # last one wins
        {"op": "uninstall", "mod": "DropMe", "ts": 3},
    )
    rc = CI.main(["apply", "--game-dir", str(game_dir),
                  "--mods-dir", str(mods_dir), "--no-apply"])
    assert rc == 0
    assert not path.exists()
    assert "enabled = true" in (mods_dir / "KeepMe" / "manifest.toml").read_text(
        encoding="utf-8")
    assert not (mods_dir / "DropMe").exists()


def test_apply_keeps_file_on_failure(game_dir, mods_dir):
    path = _queue(game_dir, {"op": "disable", "mod": "NoSuchMod", "ts": 1})
    rc = CI.main(["apply", "--game-dir", str(game_dir),
                  "--mods-dir", str(mods_dir), "--no-apply"])
    assert rc == 1
    assert path.exists()


def test_list_and_clear(game_dir, capsys):
    _queue(game_dir, {"op": "disable", "mod": "M", "ts": 1})
    assert CI.main(["list", "--game-dir", str(game_dir)]) == 0
    assert "disable" in capsys.readouterr().out
    assert CI.main(["clear", "--game-dir", str(game_dir)]) == 0
    assert not CI.intents_path(game_dir).exists()


def test_apply_rebuilds_menu_then_applies(game_dir, mods_dir, monkeypatch):
    _write_manifest(mods_dir, "SomeMod", enabled=True)
    (mods_dir / "RSMMMenu").mkdir()
    _queue(game_dir, {"op": "disable", "mod": "SomeMod", "ts": 1})

    calls = []

    class _Ret:
        returncode = 0

    monkeypatch.setattr(CI.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or _Ret())
    monkeypatch.setattr(CI.P, "self_cmd", lambda args: ["rsmm", *args])

    rc = CI.main(["apply", "--game-dir", str(game_dir), "--mods-dir", str(mods_dir)])
    assert rc == 0
    assert ["rsmm", "menu", "build", "--game-dir", str(game_dir),
            "--mods-dir", str(mods_dir)] in calls
    assert ["rsmm", "apply"] in calls
    # menu rebuild must run BEFORE the final apply
    assert calls.index(["rsmm", "menu", "build", "--game-dir", str(game_dir),
                        "--mods-dir", str(mods_dir)]) < calls.index(["rsmm", "apply"])
