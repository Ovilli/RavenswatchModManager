"""Tests for brand-new asset registration in UsedRscList.ot.

Vanilla asset overrides only touch files the engine already loads. A
*new* custom item / enemy / texture has no `asset_map` entry and is
never loaded unless it is registered in
`DarkTalesResources/UsedRscList.ot` (the engine's master manifest).

The engine parses that file in fixed groups of THREE lines per resource
(reverse-engineered from FUN_140488f50): line 1 is the type root, line 2
the logical resource name, line 3 the cooked file path. Appending fewer
than three lines desyncs the reader and crashes the game — so a new
asset must be registered as a full cloned 3-line record.

These tests cover:
* `synthesize_encoded` — derive the cooked `_Cooking` path for a new asset.
* `build_usedrsc_record` — clone a same-kind sibling's 3-line record.
* `sync_usedrsclist` / `restore_usedrsclist` — append records / roll back.
* an end-to-end `cmd_apply` -> `cmd_restore_all` roundtrip.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from rsmm.cli import apply_mods
from rsmm.engine.cipher import decode, encode

# ---------------------------------------------------------------------------
# A self-consistent sibling resource modelled on the real game's records.
# Because the cipher is a per-character homomorphism, encode(a+b) ==
# encode(a)+encode(b), so encode(<id>) is always a contiguous substring of
# encode(<path containing id>) — which is exactly what record-cloning relies on.
# ---------------------------------------------------------------------------
_ROOT = "EntitySettings"
_PARENT = "Objects/Magical_Objects/Common"
_SIB_ID = "Existing_Item"
_LOGICAL_SUFFIX = ".entity.ot"
_COOK_SUFFIX = ".EntitySettingsResource.gen"

_SIB_LOGICAL_DEC = f"{_PARENT}/{_SIB_ID}{_LOGICAL_SUFFIX}".replace("/", "\\")
_SIB_COOKED_DEC = f"{_ROOT}/{_PARENT}/{_SIB_ID}{_LOGICAL_SUFFIX}{_COOK_SUFFIX}"

# The sibling's three encoded manifest lines (line3 uses the `\`-then-`!`
# collapse the real game emits for EntitySettings cooked paths).
_LINE1 = encode(_ROOT)
_LINE2 = encode(_SIB_LOGICAL_DEC)
_LINE3 = (
    encode(_ROOT) + "\\" + encode("Objects") + "\\" + encode("Magical_Objects")
    + "!" + encode("Common") + "!" + encode(f"{_SIB_ID}{_LOGICAL_SUFFIX}{_COOK_SUFFIX}")
)


def _dec2enc() -> dict[str, str]:
    # asset_map maps decoded (forward-slash) -> encoded cooked path (line3).
    return {_SIB_COOKED_DEC: _LINE3}


def _new_cooked(new_id: str) -> str:
    return f"{_ROOT}/{_PARENT}/{new_id}{_LOGICAL_SUFFIX}{_COOK_SUFFIX}"


# ---------------------------------------------------------------------------
# synthesize_encoded
# ---------------------------------------------------------------------------
def test_synthesize_clones_sibling_prefix():
    new = _new_cooked("My_New_Thing")
    enc = apply_mods.synthesize_encoded(new, _dec2enc())
    assert enc is not None
    assert decode(enc.replace("!", "\\")) == new.replace("/", "\\")


def test_synthesize_no_sibling_returns_none():
    assert apply_mods.synthesize_encoded("Brand/New/Dir/x.bin", _dec2enc()) is None


def test_synthesize_toplevel_encodes_whole():
    assert apply_mods.synthesize_encoded("samples", {}) == "vgxjlqv"


# ---------------------------------------------------------------------------
# build_usedrsc_record
# ---------------------------------------------------------------------------
def test_build_record_clones_sibling_triple():
    base_lines = [_LINE1, _LINE2, _LINE3]
    new = _new_cooked("Brand_New_Item")
    rec = apply_mods.build_usedrsc_record(new, base_lines, _dec2enc())
    assert rec is not None and len(rec) == 3
    # line 1 (type root) is unchanged.
    assert rec[0] == _LINE1
    # line 2 decodes to the logical path with the id swapped.
    assert decode(rec[1].replace("!", "\\")) == \
        f"{_PARENT}/Brand_New_Item{_LOGICAL_SUFFIX}".replace("/", "\\")
    # line 3 decodes to the full cooked path with the id swapped.
    assert decode(rec[2].replace("!", "\\")) == new.replace("/", "\\")
    # line 3 matches what synthesize_encoded produces for the same asset.
    assert rec[2] == apply_mods.synthesize_encoded(new, _dec2enc())


def test_build_record_no_sibling_returns_none():
    # Sibling exists in dec2enc but its line3 isn't in the manifest lines.
    assert apply_mods.build_usedrsc_record(_new_cooked("X"), [], _dec2enc()) is None
    # Different kind/suffix in a different dir -> no structural sibling.
    assert apply_mods.build_usedrsc_record(
        "Other/Dir/Thing.png.Texture.dxt", [_LINE1, _LINE2, _LINE3], _dec2enc()
    ) is None


# ---------------------------------------------------------------------------
# sync / restore
# ---------------------------------------------------------------------------
def _write_usedrsc(game_dir: Path, lines: list[str]) -> Path:
    p = game_dir / apply_mods.USEDRSCLIST_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("1\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_sync_appends_full_record_and_restores(tmp_path):
    game_dir = tmp_path / "game"
    p = _write_usedrsc(game_dir, [_LINE1, _LINE2, _LINE3])
    bak = p.with_name(p.name + apply_mods.BACKUP_SUFFIX)

    new = _new_cooked("Brand_New_Item")
    enc = apply_mods.synthesize_encoded(new, _dec2enc())
    added = apply_mods.sync_usedrsclist(game_dir, {enc: new}, _dec2enc(), False)
    assert added == 1
    assert bak.is_file()
    header, lines = apply_mods._read_usedrsclist(p)
    assert header == "1"
    # Original triple preserved, plus a full new triple (6 lines total).
    assert lines[:3] == [_LINE1, _LINE2, _LINE3]
    assert len(lines) == 6
    assert lines[5] == enc  # cooked path is the 3rd line of the new record

    # Re-sync identical -> idempotent no-op.
    assert apply_mods.sync_usedrsclist(game_dir, {enc: new}, _dec2enc(), False) == 0

    # Empty registrations -> pristine restored, backup removed.
    apply_mods.sync_usedrsclist(game_dir, {}, _dec2enc(), False)
    _, lines = apply_mods._read_usedrsclist(p)
    assert lines == [_LINE1, _LINE2, _LINE3]
    assert not bak.exists()


# ---------------------------------------------------------------------------
# end-to-end apply / restore
# ---------------------------------------------------------------------------
def _make_new_asset_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    mod_root = repo / "mods" / "NewItemMod"
    new_decoded = _new_cooked("My_New_Thing")
    (mod_root / "assets" / Path(new_decoded)).parent.mkdir(parents=True)
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
    asset_map.write_text(json.dumps({_LINE3: _SIB_COOKED_DEC}), encoding="utf-8")

    game_dir = tmp_path / "game"
    (game_dir / "DarkTalesResources" / "_Cooking").mkdir(parents=True)
    _write_usedrsc(game_dir, [_LINE1, _LINE2, _LINE3])
    return repo, asset_map, game_dir, new_decoded


def test_apply_registers_new_asset_then_restore_drops_it(tmp_path, monkeypatch, capsys):
    repo, asset_map, game_dir, new_decoded = _make_new_asset_repo(tmp_path)
    cooking = game_dir / "DarkTalesResources" / "_Cooking"
    usedrsc = game_dir / apply_mods.USEDRSCLIST_REL

    import rsmm.engine.find_iyg as find_iyg

    monkeypatch.setattr(apply_mods, "MODS_DIR", repo / "mods")
    monkeypatch.setattr(apply_mods, "ASSET_MAP_JSON", asset_map)
    # Let game-update recovery run (it persists the fingerprint restore relies
    # on) but stub the step that would clobber the real data/asset_map.json.
    monkeypatch.setattr(find_iyg, "main", lambda *a, **k: 0)

    args = SimpleNamespace(dry_run=False)
    enc = apply_mods.synthesize_encoded(new_decoded, _dec2enc())
    dest = apply_mods.encoded_to_dest(enc, cooking, game_dir)

    rc = apply_mods.cmd_apply(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert dest.is_file() and dest.read_bytes() == b"NEW ITEM BYTES"
    _, lines = apply_mods._read_usedrsclist(usedrsc)
    # A full 3-line record was appended (6 lines: original triple + new triple).
    assert len(lines) == 6
    assert lines[5] == enc
    assert usedrsc.with_name(usedrsc.name + apply_mods.BACKUP_SUFFIX).exists()

    rc = apply_mods.cmd_restore_all(args, repo, cooking, game_dir)
    capsys.readouterr()
    assert rc == 0
    assert not dest.exists()
    _, lines = apply_mods._read_usedrsclist(usedrsc)
    assert lines == [_LINE1, _LINE2, _LINE3]
    assert not usedrsc.with_name(usedrsc.name + apply_mods.BACKUP_SUFFIX).exists()
