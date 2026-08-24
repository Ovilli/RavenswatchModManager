"""`restore --all` must not destroy the log it is about to be blamed for.

The loader archives the PREVIOUS run's `_log.txt` at the start of the next
launch: it copies it into `<game>/rsmm/logs/<stamp>_<session>.log`, mirrors it
to `_log.prev.txt`, and only then truncates. That whole chain needs `_log.txt`
to still be on disk when the game starts.

`clear_runtime_mods` used to `rmtree` the entire `<game>/mods/` directory, and
it runs on every `restore --all` — which is the first step of the iterate loop
this project documents. So the input to the archive was deleted before every
launch, and both `_log.prev.txt` and the dated archive were permanently empty:
"the previous run log never gets written".
"""
from __future__ import annotations

from pathlib import Path

from rsmm.cli.apply_mods import clear_runtime_mods


def _game(tmp_path: Path) -> Path:
    mods = tmp_path / "mods"
    (mods / "damage-meter").mkdir(parents=True)
    (mods / "damage-meter" / "manifest.toml").write_text("[mod]\nid='x'\n", encoding="utf-8")
    (mods / "damage-meter" / "init.lua").write_text("-- x", encoding="utf-8")
    (mods / "_log.txt").write_text("== SESSION abcd  the run that just ended\n", encoding="utf-8")
    (mods / "_log.prev.txt").write_text("the run before that\n", encoding="utf-8")
    (mods / "_health.json").write_text('{"canary":{"open":false},"mods":{}}', encoding="utf-8")
    return tmp_path


def test_restore_keeps_the_loader_log_and_health(tmp_path):
    game = _game(tmp_path)
    assert clear_runtime_mods(game) == 1

    mods = game / "mods"
    assert (mods / "_log.txt").read_text(encoding="utf-8").startswith("== SESSION abcd")
    assert (mods / "_log.prev.txt").is_file()
    # The crash canary and three-strike history exist to survive a bad run;
    # wiping them re-enables a mod that bricks startup.
    assert (mods / "_health.json").is_file()


def test_restore_still_removes_every_mod(tmp_path):
    """The point of the clear is that a vanilla launch loads nothing."""
    game = _game(tmp_path)
    assert clear_runtime_mods(game) == 1
    assert not (game / "mods" / "damage-meter").exists()
    assert [p.name for p in sorted((game / "mods").iterdir())] == [
        "_health.json", "_log.prev.txt", "_log.txt",
    ]


def test_clear_is_a_noop_without_a_mods_dir(tmp_path):
    assert clear_runtime_mods(tmp_path) == 1


def test_dry_run_touches_nothing(tmp_path):
    game = _game(tmp_path)
    assert clear_runtime_mods(game, dry_run=True) == 1
    assert (game / "mods" / "damage-meter" / "init.lua").is_file()
