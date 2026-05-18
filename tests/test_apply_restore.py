"""End-to-end test for `rsmm apply` + `rsmm restore`.

Builds a self-contained fake repo (mods + asset_map) and a fake game
install in tmp_path, runs apply_mods.cmd_apply against it, asserts the
override took and the .rsmm.bak sibling preserves the original bytes.
Then runs cmd_restore_all and asserts the file is byte-identical to
the original and that .rsmm_state.json's active map is empty.

This is the regression contract: nothing in the apply path should
ever fail to roundtrip a clean install."""

import json
from pathlib import Path
from types import SimpleNamespace


def _make_fake_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Return (repo, mods_dir, asset_map_json, game_dir).

    Layout:
      repo/mods/TestMod/manifest.toml
      repo/mods/TestMod/assets/foo/bar.bin     ('MOD CONTENT')
      repo/asset_map.json                      {'a\\\\b.bin': 'foo/bar.bin'}
      game/DarkTalesResources/_Cooking/a/b.bin ('VANILLA CONTENT')
    """
    repo = tmp_path / "repo"
    mods_dir = repo / "mods"
    mod_root = mods_dir / "TestMod"
    (mod_root / "assets" / "foo").mkdir(parents=True)
    (mod_root / "assets" / "foo" / "bar.bin").write_bytes(b"MOD CONTENT")
    (mod_root / "manifest.toml").write_text(
        '[mod]\n'
        'id          = "TestMod"\n'
        'name        = "Test"\n'
        'version     = "1.0.0"\n'
        'author      = "t"\n'
        'enabled     = true\n',
        encoding="utf-8",
    )

    asset_map = repo / "asset_map.json"
    asset_map.write_text(json.dumps({"a\\b.bin": "foo/bar.bin"}), encoding="utf-8")

    game_dir = tmp_path / "game"
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    (cooking / "a").mkdir(parents=True)
    (cooking / "a" / "b.bin").write_bytes(b"VANILLA CONTENT")

    return repo, mods_dir, asset_map, game_dir


def test_apply_then_restore_roundtrips(tmp_path, monkeypatch, capsys):
    from rsmm.cli import apply_mods

    repo, mods_dir, asset_map, game_dir = _make_fake_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    vanilla = cooking / "a" / "b.bin"
    bak = vanilla.parent / (vanilla.name + ".rsmm.bak")
    state_path = cooking / ".rsmm_state.json"

    monkeypatch.setattr(apply_mods, "MODS_DIR", mods_dir)
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)

    args = SimpleNamespace(dry_run=False)

    # --- apply -----------------------------------------------------
    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert vanilla.read_bytes() == b"MOD CONTENT"
    assert bak.is_file()
    assert bak.read_bytes() == b"VANILLA CONTENT"
    assert state_path.is_file()
    state = json.loads(state_path.read_text())
    assert "a\\b.bin" in state["active"], state

    # --- restore ---------------------------------------------------
    rc = apply_mods.cmd_restore_all(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert vanilla.read_bytes() == b"VANILLA CONTENT"
    assert not bak.exists(), "backup should be moved back, not left behind"
    state = json.loads(state_path.read_text())
    assert state.get("active") == {}, state
