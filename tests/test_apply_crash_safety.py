"""Crash safety for `rsmm apply`: nothing lost, nothing torn, one writer.

The failure this file is really about: apply writes the state file ONCE, at
the end. Everything applied before a crash is live but unrecorded — and for a
mod-*added* file there is no `.rsmm.bak` for `restore --all` to sweep either,
so it used to stay in the install forever with nothing tracking it.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rsmm.cli import apply_mods
from rsmm.engine.safeio import LOCK_NAME, TMP_PREFIX


def _fake_install(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """repo + game install with one vanilla asset and one mod that adds a file."""
    repo = tmp_path / "repo"
    mods_dir = repo / "mods"
    mod_root = mods_dir / "TestMod"
    (mod_root / "assets" / "foo").mkdir(parents=True)
    (mod_root / "assets" / "foo" / "bar.bin").write_bytes(b"MOD CONTENT")
    (mod_root / "manifest.toml").write_text(
        '[mod]\n'
        'id      = "TestMod"\n'
        'name    = "Test"\n'
        'version = "1.0.0"\n'
        'author  = "t"\n'
        'enabled = true\n',
        encoding="utf-8",
    )
    asset_map = repo / "asset_map.json"
    asset_map.write_text(json.dumps({"a\\b.bin": "foo/bar.bin"}), encoding="utf-8")

    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    (cooking / "a").mkdir(parents=True)
    (cooking / "a" / "b.bin").write_bytes(b"VANILLA CONTENT")
    return repo, mods_dir, asset_map, game_dir


@pytest.fixture
def install(tmp_path, monkeypatch):
    repo, mods_dir, asset_map, game_dir = _fake_install(tmp_path)
    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    import rsmm.engine.find_iyg as find_iyg
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    return SimpleNamespace(repo=repo, game_dir=game_dir, cooking=cooking)


def test_apply_clears_its_journal_on_success(install, capsys):
    args = SimpleNamespace(dry_run=False)
    assert apply_mods.cmd_apply(args, install.repo, install.cooking, install.game_dir) == 0
    capsys.readouterr()
    assert not (install.cooking / apply_mods.JOURNAL_FILE_NAME).exists()


def test_a_crash_before_the_state_write_is_recovered(install, capsys):
    """Simulate dying after the writes but before `state.save()`.

    The journal is the only record; the next run must adopt it so the file is
    tracked and `restore --all` can undo it.
    """
    cooking = install.cooking
    dest = cooking / "a" / "b.bin"

    # The apply happened: file written, backup taken, journal recorded...
    dest.write_bytes(b"MOD CONTENT")
    (cooking / "a" / "b.bin.rsmm.bak").write_bytes(b"VANILLA CONTENT")
    apply_mods.Journal(cooking).record("a\\b.bin", "TestMod", added=False)
    # ...but the state file was never written.
    assert not (cooking / apply_mods.STATE_FILE_NAME).exists()

    state = apply_mods.State(cooking)
    adopted = apply_mods.reconcile_journal(cooking, state)
    capsys.readouterr()

    assert adopted == 1
    assert "a\\b.bin" in state.active
    assert not (cooking / apply_mods.JOURNAL_FILE_NAME).exists()


def test_restore_drops_an_added_file_a_crashed_apply_left_behind(install, capsys):
    """The case with no backup to sweep — the one that used to be permanent."""
    cooking = install.cooking
    added = cooking / "a" / "added.bin"
    added.write_bytes(b"NEW ASSET")
    apply_mods.Journal(cooking).record("a\\added.bin", "TestMod", added=True)

    args = SimpleNamespace(dry_run=False)
    assert apply_mods.cmd_restore_all(args, install.repo, cooking, install.game_dir) == 0
    capsys.readouterr()

    assert not added.exists(), "orphaned added file should be dropped by restore"


def test_journal_survives_a_torn_final_line(install):
    cooking = install.cooking
    journal = apply_mods.Journal(cooking)
    journal.record("a\\one.bin", "TestMod", added=True)
    # Power loss mid-append leaves a partial line.
    with open(journal.path, "a", encoding="utf-8") as f:
        f.write('{"enc": "a\\\\two.bin", "add')

    pending = journal.pending()
    assert [p["enc"] for p in pending] == ["a\\one.bin"]


def test_apply_refuses_when_another_process_holds_the_lock(install, capsys):
    """Two writers can capture a MODDED file as the "original" backup —
    the one corruption no restore can undo."""
    from rsmm.engine.safeio import install_lock

    with install_lock(install.cooking, "apply"):
        with apply_mods._install_lock_or_fail(install.cooking, "apply") as held:
            assert held is False
    out = capsys.readouterr()
    assert "another rsmm process" in out.err


def test_apply_leaves_no_temp_files_and_sweeps_stale_ones(install, capsys):
    cooking = install.cooking
    stale = cooking / "a" / f"{TMP_PREFIX}b.bin.999"
    stale.write_bytes(b"leftover")

    args = SimpleNamespace(dry_run=False)
    assert apply_mods.cmd_apply(args, install.repo, cooking, install.game_dir) == 0
    capsys.readouterr()

    assert not stale.exists()
    assert list(cooking.rglob(f"{TMP_PREFIX}*")) == []
    assert not (cooking / LOCK_NAME).exists()


def test_apply_fails_loudly_if_the_written_bytes_do_not_match(install, monkeypatch, capsys):
    """A short write (full disk, failing drive) must not be recorded as applied."""
    real_copy = apply_mods.atomic_copy

    def truncating_copy(src: Path, dest: Path) -> int:
        # Emulate a drive that accepts the write but stores less than asked.
        if dest.name == "b.bin":
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"TRUNC")
            return 5
        return real_copy(src, dest)

    monkeypatch.setattr(apply_mods, "atomic_copy", truncating_copy)
    args = SimpleNamespace(dry_run=False)
    with pytest.raises(OSError, match="did not land intact"):
        apply_mods.cmd_apply(args, install.repo, install.cooking, install.game_dir)
