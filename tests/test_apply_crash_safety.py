"""Crash safety for `rsmm apply`: nothing lost, nothing torn, one writer.

The failure this file is really about: apply writes the state file ONCE, at
the end. Everything applied before a crash is live but unrecorded — and for a
mod-*added* file there is no `.rsmm.bak` for `restore --all` to sweep either,
so it used to stay in the install forever with nothing tracking it.
"""

import json
import os
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


def test_apply_fails_loudly_if_the_written_bytes_do_not_match(install, monkeypatch):
    """A short write (full disk, failing drive) must not be recorded as applied.

    Emulated at the staging layer: the batch commits, so the truncated bytes
    reach the destination and the post-commit verification is what has to
    catch them.
    """
    from rsmm.sdk.transaction import ApplyTransaction

    class TruncatingTx(ApplyTransaction):
        def stage_write(self, encoded, src, dest):
            w = super().stage_write(encoded, src, dest)
            if dest.name == "b.bin":
                w.stage.write_bytes(b"TRUNC")
            return w

    monkeypatch.setattr(apply_mods, "ApplyTransaction", TruncatingTx)
    args = SimpleNamespace(dry_run=False)
    with pytest.raises(OSError, match="did not land intact"):
        apply_mods.cmd_apply(args, install.repo, install.cooking, install.game_dir)


def test_a_failed_batch_rolls_the_whole_apply_back(install, capsys):
    """One bad file must not leave the other overrides half-installed."""
    cooking = install.cooking
    # A second mod file so the batch has two writes.
    second = install.repo / "mods" / "TestMod" / "assets" / "foo" / "two.bin"
    second.write_bytes(b"SECOND MOD CONTENT")
    asset_map = install.repo / "asset_map.json"
    asset_map.write_text(json.dumps({
        "a\\b.bin": "foo/bar.bin",
        "a\\c.bin": "foo/two.bin",
    }))
    vanilla_b = cooking / "a" / "b.bin"
    vanilla_c = cooking / "a" / "c.bin"
    vanilla_c.write_bytes(b"VANILLA TWO")

    from rsmm.sdk.transaction import ApplyTransaction

    class FailingTx(ApplyTransaction):
        def commit(self):
            # Make the SECOND replace fail inside commit — the way a file
            # that vanished or is locked would — so the transaction's own
            # rollback has to undo the first one.
            if len(self.pending) > 1:
                self.pending[1].stage.unlink()
            return super().commit()

    import pytest as _pytest
    args = SimpleNamespace(dry_run=False)
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(apply_mods, "ApplyTransaction", FailingTx)
        with _pytest.raises(OSError):
            apply_mods.cmd_apply(args, install.repo, cooking, install.game_dir)
    capsys.readouterr()

    # Both originals are intact — the committed one was rolled back.
    assert vanilla_b.read_bytes() == b"VANILLA CONTENT"
    assert vanilla_c.read_bytes() == b"VANILLA TWO"
    # And nothing was recorded as an active override.
    state_path = cooking / apply_mods.STATE_FILE_NAME
    if state_path.exists():
        assert json.loads(state_path.read_text()).get("active") == {}


def test_apply_refuses_while_the_game_is_running(install, monkeypatch, capsys):
    """Cooked assets must not be rewritten under a live engine."""
    monkeypatch.setattr(apply_mods, "is_game_running", lambda: True)
    assert apply_mods._refuse_if_game_running("apply mods", force=False) is True
    err = capsys.readouterr().err
    assert "Ravenswatch is running" in err

    # --force is an explicit override, and warns rather than blocking.
    assert apply_mods._refuse_if_game_running("apply mods", force=True) is False
    assert "continuing anyway" in capsys.readouterr().err


def test_game_probe_failure_never_blocks_an_apply(install, monkeypatch):
    """The probe fails open: an unknown state must not make rsmm unusable."""
    from rsmm.engine import game_proc

    monkeypatch.setattr(game_proc, "_run", lambda cmd: None)
    monkeypatch.setattr(game_proc.os, "listdir", _raise_oserror)
    assert game_proc.is_game_running() is False


def _raise_oserror(*_a, **_kw):
    raise OSError("probe unavailable")


@pytest.mark.skipif(os.name == "nt", reason="the /proc scan is the POSIX path")
def test_game_probe_ignores_launcher_scaffolding(monkeypatch, tmp_path):
    """A command line that MENTIONS the exe is not the exe.

    Under Proton the launcher chain — reaper, steam-runtime-launch-client,
    bwrap, pv-adverb, proton, steam.exe — all carry the full exe path in their
    arguments, and they outlive the game. The old probe was `pgrep -f`, which
    matches any command line, so every apply after the first launch of a Steam
    session was refused with "Ravenswatch is running" while nothing ran (it
    even matched a shell script waiting for the game to exit). Measured
    2026-08-23: 9 matching processes, none of them the game.
    """
    from rsmm.engine import game_proc

    procs = {
        # /proc/<pid>/cmdline is NUL-separated, so argv[0] is the FIRST field —
        # the wrapper binary. The exe path is just one of its arguments.
        "101": ("reaper", b"/steam/reaper\0SteamLaunch\0AppId=2071280\0--\0"
                          b"/games/Ravenswatch/Ravenswatch.exe\0"),
        "102": ("bwrap", b"bwrap\0--args\094\0--\0/proton\0waitforexitandrun\0"
                         b"/games/Ravenswatch/Ravenswatch.exe\0"),
        "103": ("bash", b"/bin/bash\0/tmp/wait_for_Ravenswatch.exe.sh\0"),
    }
    for pid, (comm, cmdline) in procs.items():
        d = tmp_path / pid
        d.mkdir()
        (d / "comm").write_text(comm + "\n")
        (d / "cmdline").write_bytes(cmdline)
    (tmp_path / "not-a-pid").mkdir()

    monkeypatch.setattr(game_proc.os, "listdir",
                        lambda p: sorted(x.name for x in tmp_path.iterdir()))
    monkeypatch.setattr(game_proc, "_run", lambda cmd: None)
    real_open = open

    def fake_open(path, *a, **kw):
        text = str(path)
        if text.startswith("/proc/"):
            return real_open(str(tmp_path / text[len("/proc/"):]), *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    assert game_proc.is_game_running() is False

    # The real thing IS detected — by comm, and by argv[0] when comm is
    # truncated differently.
    game = tmp_path / "104"
    game.mkdir()
    (game / "comm").write_text("Ravenswatch.exe\n")
    (game / "cmdline").write_bytes(b"Z:\\games\\Ravenswatch\\Ravenswatch.exe\0")
    assert game_proc.is_game_running() is True

    (game / "comm").write_text("wine-preloader\n")
    (game / "cmdline").write_bytes(b"/games/Ravenswatch/Ravenswatch.exe\0-arg\0")
    assert game_proc.is_game_running() is True


# --- corrupt state file ----------------------------------------------------

def _state_path(cooking):
    from rsmm.cli.apply_mods import STATE_FILE_NAME
    return cooking / STATE_FILE_NAME


def test_corrupt_state_file_is_preserved_not_overwritten(tmp_path, capsys):
    """Regression: an unreadable state file was warned about and then silently
    replaced by an empty one on the next save.

    Replaced assets survive that — `restore --all` sweeps orphan `.rsmm.bak`
    files — but *added* files have no backup and no state entry, so nothing
    would ever know they existed. Keep the bytes so the record can be
    reconstructed.
    """
    from rsmm.cli.apply_mods import State

    cooking = tmp_path / "cooking"
    cooking.mkdir()
    _state_path(cooking).write_text("{not json", encoding="utf-8")

    st = State(cooking)
    st.save()   # would have clobbered the original

    assert st.active == {}
    kept = list(cooking.glob(".rsmm_state.json.corrupt-*"))
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8") == "{not json"
    assert "state file is unreadable" in capsys.readouterr().err


def test_state_file_of_the_wrong_shape_is_quarantined(tmp_path, capsys):
    """Parsing is not the same as being a state file: a bare list used to sail
    through and die later on `.setdefault` with an AttributeError."""
    from rsmm.cli.apply_mods import State

    cooking = tmp_path / "cooking"
    cooking.mkdir()
    _state_path(cooking).write_text('["not", "a", "state"]', encoding="utf-8")

    st = State(cooking)
    assert st.active == {}          # usable, not an AttributeError
    assert list(cooking.glob(".rsmm_state.json.corrupt-*"))
    assert "not a state object" in capsys.readouterr().err


def test_valid_state_file_is_left_alone(tmp_path):
    from rsmm.cli.apply_mods import State

    cooking = tmp_path / "cooking"
    cooking.mkdir()
    _state_path(cooking).write_text(
        json.dumps({"version": 1, "active": {"a": {"mod": "m"}}}), encoding="utf-8")

    st = State(cooking)
    assert st.active == {"a": {"mod": "m"}}
    assert not list(cooking.glob(".rsmm_state.json.corrupt-*"))


# --- malformed manifests ---------------------------------------------------

def _mod(mods_dir, name: str, manifest: str):
    d = mods_dir / name
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(manifest, encoding="utf-8")


def test_one_malformed_manifest_does_not_block_every_other_mod(
        tmp_path, monkeypatch, capsys):
    """Regression: `discover_mods` skips-and-warns on TOMLDecodeError/OSError/
    ValueError, but valid TOML of the wrong shape (`mod = 5`) reached `m.get`
    and raised AttributeError, which nothing caught. One bad manifest anywhere
    in mods/ therefore aborted the whole apply and silently stopped every other
    mod from being applied.
    """
    from rsmm.cli import apply_mods

    mods_dir = tmp_path / "mods"
    _mod(mods_dir, "BadShape", "mod = 5\n")
    # `content` must precede [mod]; after it, TOML nests it inside that table.
    _mod(mods_dir, "BadContent", 'content = "oops"\n[mod]\nid = "BadContent"\n')
    _mod(mods_dir, "BadName", '[mod]\nid = "BadName"\nname = ["a", "b"]\n')
    _mod(mods_dir, "GoodMod", '[mod]\nid = "GoodMod"\n')
    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)

    found = apply_mods.discover_mods(tmp_path)

    assert [m.id for m in found] == ["GoodMod"]
    err = capsys.readouterr().err
    assert "[mod] must be a table" in err
    assert "[[content]] must be a list of tables" in err
    assert "mod.name must be a single value" in err


def test_manifest_scalars_are_coerced_not_stringified_containers(tmp_path, monkeypatch):
    """A number is a fine version; a list is a manifest error, not `"['a']"`."""
    from rsmm.cli import apply_mods

    mods_dir = tmp_path / "mods"
    _mod(mods_dir, "Coerce", "[mod]\nid = 42\nversion = 1\n")
    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)

    (mod,) = apply_mods.discover_mods(tmp_path)
    assert mod.id == "42" and mod.version == "1"
