"""Tests for CLI dispatch and subcommand modules."""

from __future__ import annotations

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
