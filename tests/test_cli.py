"""Tests for CLI dispatch and subcommand modules."""

from __future__ import annotations

import json
import sys


def test_dispatch_help():
    from rsmm.cli._dispatch import main
    rc = main(["--help"])
    assert rc == 0


def test_dispatch_unknown():
    from rsmm.cli._dispatch import main
    rc = main(["nonexistent-subcommand"])
    assert rc == 2


def test_dispatch_gui():
    from rsmm.cli._dispatch import main
    rc = main(["gui"])
    assert rc == 2


def test_cmd_new_no_args():
    from rsmm.cli.cmd_new import main
    rc = main([])
    assert rc == 2


def test_cmd_pack_no_args():
    from rsmm.cli.cmd_pack import main
    rc = main([])
    assert rc == 2


def test_cmd_new_invalid_kind():
    from rsmm.cli.cmd_new import main
    rc = main(["--kind", "invalid", "TestMod"])
    assert rc == 2


def test_cmd_pack_nonexistent_mod(tmp_path, monkeypatch):
    from rsmm.cli.cmd_pack import main
    monkeypatch.setattr("rsmm.cli.cmd_pack.MODS_DIR", tmp_path / "mods")
    rc = main(["NonExistent"])
    assert rc == 1


def test_cmd_log_path(tmp_path):
    from rsmm.cli.cmd_log import main
    rc = main(["--path", "--game-dir", str(tmp_path)])
    assert rc == 0


def test_cmd_log_clear(tmp_path):
    from rsmm.cli.cmd_log import main
    log = tmp_path / "mods" / "_log.txt"
    log.parent.mkdir(parents=True)
    log.write_text("test content")
    rc = main(["--clear", "--game-dir", str(tmp_path)])
    assert rc == 0
    assert log.read_text() == ""


def test_cmd_log_no_file(tmp_path):
    from rsmm.cli.cmd_log import main
    rc = main(["--game-dir", str(tmp_path)])
    assert rc == 1


def test_dispatch_new(tmp_path, monkeypatch):
    from rsmm.cli._dispatch import main
    monkeypatch.setattr("rsmm.cli.cmd_new.MODS_DIR", tmp_path / "mods")
    rc = main(["new", "TestMod123"])
    assert rc == 0
    assert (tmp_path / "mods" / "TestMod123" / "manifest.toml").exists()


def test_dispatch_new_duplicate(tmp_path, monkeypatch):
    from rsmm.cli._dispatch import main
    monkeypatch.setattr("rsmm.cli.cmd_new.MODS_DIR", tmp_path / "mods")
    (tmp_path / "mods" / "Existing").mkdir(parents=True)
    rc = main(["new", "Existing"])
    assert rc == 1


def test_json_bridge_config_roundtrip(tmp_path, monkeypatch, capsys):
    from rsmm.cli import json_bridge
    from rsmm.cli._dispatch import main

    monkeypatch.setattr(json_bridge, "MODS_DIR", tmp_path)
    mod = tmp_path / "ConfigMod"
    mod.mkdir()
    (mod / "config_schema.toml").write_text(
        '[fields.enabled]\n'
        'type = "bool"\n'
        'default = true\n'
        '[fields.count]\n'
        'type = "int"\n'
        'default = 1\n',
        encoding="utf-8",
    )

    rc = json_bridge.cmd_config_get("ConfigMod")
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["schema"]["fields"]["enabled"]["type"] == "bool"
    assert payload["values"]["count"] == 1

    rc = json_bridge.cmd_config_set("ConfigMod", '{"enabled": false, "count": 7}')
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["values"]["enabled"] is False
    assert payload["values"]["count"] == 7
    assert "count = 7" in (mod / "config.toml").read_text(encoding="utf-8")

    rc = main(["json", "config", "get", "ConfigMod"])
    assert rc == 0


def test_json_bridge_zip_allows_python_hooks(tmp_path):
    import zipfile

    from rsmm.cli import json_bridge

    zpath = tmp_path / "mod.zip"
    target = tmp_path / "mods" / "PyMod"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("PyMod/manifest.toml", 'id = "PyMod"\n')
        zf.writestr("PyMod/on_disable.py", "print('ok')\n")

    err = json_bridge._extract_downloaded_zip(zpath, target, "PyMod")
    assert err is None
    assert (target / "on_disable.py").is_file()
