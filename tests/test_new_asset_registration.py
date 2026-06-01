"""Tests for brand-new asset registration via UsedRscList.ot.

Vanilla asset overrides only touch files the engine already loads. A
*new* custom item / enemy / texture has no `asset_map` entry and is
never loaded unless its cipher-encoded path is appended to
`DarkTalesResources/UsedRscList.ot` (the engine's master manifest).

These tests cover the three pieces that make that work:

* `synthesize_encoded` — derive the `_Cooking` path for a new decoded
  asset by cloning an existing sibling's encoded prefix.
* `sync_usedrsclist` / `restore_usedrsclist` — register the new path in
  the manifest and roll it back cleanly.
* an end-to-end `cmd_apply` → `cmd_restore_all` roundtrip that places a
  brand-new file, registers it, then drops it and restores the manifest.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from rsmm.cli import apply_mods
from rsmm.engine.cipher import decode

# A minimal decoded->encoded map with one sibling already present in the
# `EntitySettings/Objects` directory so synthesize has a prefix to clone.
# The encoded form mirrors the real game's `\`-then-`!` collapse: the
# first two separators stay real directories, deeper ones fold into the
# filename as `!`.
_SIBLING_DECODED = "EntitySettings/Objects/Existing_Thing.entity.ot"
_SIBLING_ENCODED = "MzidisFqiidzyv\\Oacqbiv\\Mmtvitzy_Qatzy.qzidis.ri"


def _dec2enc() -> dict[str, str]:
    return {_SIBLING_DECODED: _SIBLING_ENCODED}


def test_synthesize_clones_sibling_prefix():
    new = "EntitySettings/Objects/My_New_Thing.entity.ot"
    enc = apply_mods.synthesize_encoded(new, _dec2enc())
    assert enc is not None
    # Shares the sibling's real-directory prefix.
    assert enc.startswith("MzidisFqiidzyv\\Oacqbiv\\")
    # Decoding the encoded path (un-collapsing `!`) returns the original.
    assert decode(enc.replace("!", "\\")) == new.replace("/", "\\")


def test_synthesize_no_sibling_returns_none():
    # No asset shares this parent dir, so there's no prefix to anchor.
    assert apply_mods.synthesize_encoded("Brand/New/Dir/x.bin", _dec2enc()) is None


def test_synthesize_toplevel_encodes_whole():
    # A bare top-level name has no separators and is encoded directly.
    assert apply_mods.synthesize_encoded("samples", {}) == "vgxjlqv"


def _write_usedrsc(game_dir: Path, lines: list[str]) -> Path:
    p = game_dir / apply_mods.USEDRSCLIST_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("1\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_usedrsclist_sync_and_restore_roundtrip(tmp_path):
    game_dir = tmp_path / "game"
    p = _write_usedrsc(game_dir, ["aaa", "bbb"])
    bak = p.with_name(p.name + apply_mods.BACKUP_SUFFIX)
    args_dry = False

    added = apply_mods.sync_usedrsclist(game_dir, {"ccc", "ddd"}, args_dry)
    assert added == 2
    assert bak.is_file(), "pristine backup must be kept"
    header, lines = apply_mods._read_usedrsclist(p)
    assert header == "1"
    assert lines == ["aaa", "bbb", "ccc", "ddd"]

    # Re-syncing with a different set is computed from the pristine backup,
    # so the previous registration is dropped, not stacked.
    apply_mods.sync_usedrsclist(game_dir, {"eee"}, args_dry)
    _, lines = apply_mods._read_usedrsclist(p)
    assert lines == ["aaa", "bbb", "eee"]

    # Empty set restores the pristine manifest and removes the backup.
    apply_mods.sync_usedrsclist(game_dir, set(), args_dry)
    _, lines = apply_mods._read_usedrsclist(p)
    assert lines == ["aaa", "bbb"]
    assert not bak.exists()


def test_sync_is_idempotent_when_already_registered(tmp_path):
    game_dir = tmp_path / "game"
    _write_usedrsc(game_dir, ["aaa"])
    apply_mods.sync_usedrsclist(game_dir, {"ccc"}, False)
    # Second identical sync adds nothing.
    assert apply_mods.sync_usedrsclist(game_dir, {"ccc"}, False) == 0


def _make_new_asset_repo(tmp_path: Path):
    """Fake repo whose mod ships a file that is NOT in the asset map but
    lives in the same decoded directory as a known sibling."""
    repo = tmp_path / "repo"
    mod_root = repo / "mods" / "NewItemMod"
    (mod_root / "assets" / "EntitySettings" / "Objects").mkdir(parents=True)
    new_decoded = "EntitySettings/Objects/My_New_Thing.entity.ot"
    (mod_root / "assets" / Path(new_decoded)).write_bytes(b"NEW ITEM BYTES")
    (mod_root / "manifest.toml").write_text(
        '[mod]\n'
        'id      = "NewItemMod"\n'
        'name    = "New Item"\n'
        'version = "1.0.0"\n'
        'enabled = true\n',
        encoding="utf-8",
    )
    asset_map = repo / "asset_map.json"
    asset_map.write_text(json.dumps({_SIBLING_ENCODED: _SIBLING_DECODED}),
                         encoding="utf-8")

    game_dir = tmp_path / "game"
    (game_dir / "DarkTalesResources" / "_Cooking").mkdir(parents=True)
    _write_usedrsc(game_dir, ["aaa", "bbb"])
    return repo, asset_map, game_dir, new_decoded


def test_apply_registers_new_asset_then_restore_drops_it(tmp_path, monkeypatch, capsys):
    repo, asset_map, game_dir, new_decoded = _make_new_asset_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    usedrsc = game_dir / apply_mods.USEDRSCLIST_REL

    import rsmm.engine.find_iyg as find_iyg

    monkeypatch.setattr(apply_mods, "MODS_DIR", repo / "mods")
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    # The first apply runs game-update recovery (no stored fingerprint yet),
    # which persists a fingerprint that the later restore relies on to NOT
    # treat this as a version change. Let recovery run, but stub the one
    # step that would rebuild — and clobber — the *real* data/asset_map.json
    # from the host's UsedRscList.
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)

    args = SimpleNamespace(dry_run=False)

    enc = apply_mods.synthesize_encoded(new_decoded, {_SIBLING_DECODED: _SIBLING_ENCODED})
    dest = apply_mods.encoded_to_dest(enc, cooking, game_dir)

    # --- apply: file placed + registered --------------------------------
    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert dest.is_file(), "new asset should be written into _Cooking"
    assert dest.read_bytes() == b"NEW ITEM BYTES"
    _, lines = apply_mods._read_usedrsclist(usedrsc)
    assert enc in lines, "new asset must be registered in UsedRscList.ot"
    assert usedrsc.with_name(usedrsc.name + apply_mods.BACKUP_SUFFIX).exists()

    # --- restore: file dropped + manifest reverted ----------------------
    rc = apply_mods.cmd_restore_all(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert not dest.exists(), "added file must be dropped on restore"
    _, lines = apply_mods._read_usedrsclist(usedrsc)
    assert lines == ["aaa", "bbb"], "manifest must return to pristine"
    assert not usedrsc.with_name(usedrsc.name + apply_mods.BACKUP_SUFFIX).exists()
