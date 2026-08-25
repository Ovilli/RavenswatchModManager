"""A mod deleted while still enabled can never run its `on_disable.py`.

`on_disable.py` is the only way a mod undoes what it wrote at RUNTIME — a
`[Debug]` key in `_Save/GameSettings.ini`, a profile flag — because the
loader is gone by the time the mod is turned off. If the user deletes
`mods/<id>/` instead of disabling it, there is no directory left to read the
hook from, so that cleanup silently never happens and the leftover state
outlives every trace of the mod that wrote it. Apply cannot fix it, but it
must not stay quiet about it.
"""

from pathlib import Path

from rsmm.cli import apply_mods


def _mod(mods_dir: Path, mod_id: str, *, enabled: bool,
         on_disable: bool = False) -> apply_mods.Mod:
    root = mods_dir / mod_id
    root.mkdir(parents=True)
    (root / "manifest.toml").write_text(
        f'[mod]\n'
        f'id      = "{mod_id}"\n'
        f'name    = "{mod_id}"\n'
        f'version = "1.0.0"\n'
        f'enabled = {str(enabled).lower()}\n',
        encoding="utf-8",
    )
    if on_disable:
        (root / "on_disable.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    return apply_mods.Mod(root)


def _state(cooking: Path, enabled_ids: list[str]) -> apply_mods.State:
    cooking.mkdir(parents=True, exist_ok=True)
    state = apply_mods.State(cooking)
    state.set_enabled_mods(enabled_ids)
    return state


def test_vanished_enabled_mod_warns(tmp_path, capsys):
    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()

    # "ghost" was enabled last apply and its directory is now gone.
    state = _state(cooking, ["ghost"])
    ran, missing = apply_mods._run_deactivation_hooks(
        [], state, game_dir, cooking, dry_run=False)

    assert ran == []
    assert missing == ["ghost"]
    err = capsys.readouterr().err
    assert "ghost" in err
    assert "[WARN]" in err
    # Points at the file the canonical leak (a pinned Forced seed) lands in.
    assert "GameSettings.ini" in err


def test_disabled_mod_without_hook_stays_silent(tmp_path, capsys):
    """Still on disk, declared no cleanup — nothing to report."""
    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()

    mod = _mod(mods_dir, "quiet", enabled=False)
    state = _state(cooking, ["quiet"])
    ran, missing = apply_mods._run_deactivation_hooks(
        [mod], state, game_dir, cooking, dry_run=False)

    assert ran == []
    assert missing == ["quiet"]
    assert capsys.readouterr().err == ""


def test_still_enabled_mod_is_not_a_flip(tmp_path, capsys):
    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()

    mod = _mod(mods_dir, "live", enabled=True, on_disable=True)
    state = _state(cooking, ["live"])
    ran, missing = apply_mods._run_deactivation_hooks(
        [mod], state, game_dir, cooking, dry_run=False)

    assert (ran, missing) == ([], [])
    assert capsys.readouterr().err == ""
