"""A stale asset map must never let apply/restore treat game files as mod-added.

Measured 2026-10-18: a frozen CLI still held its pre-Update-6 copy of the map,
so the Update 5 backport's ``*_Update6`` herodefs and ``LiveOps6`` versiondef
looked mod-added. Apply overwrote them with no backup, restore deleted them,
and hero select was left with only Random. Same day: the versiondef patcher
restored its "pristine" copy over the backport's versiondef on the second
apply, so the backport never reached the game.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rsmm.cli import apply_mods as A
from rsmm.engine import asset_map as AM
from rsmm.engine import cipher
from rsmm.engine import versiondef as V
from rsmm.engine.paths import BACKUP_SUFFIX, COOKING_REL, USEDRSCLIST_REL


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A game whose manifest ships ``old\\a`` and ``new\\b``, and a map that
    only knows ``old\\a`` (built before the patch that added ``new\\b``)."""
    game = tmp_path / "game"
    (game / COOKING_REL / "new").mkdir(parents=True)
    (game / COOKING_REL / "new" / "b").write_bytes(b"VANILLA")
    manifest = game / USEDRSCLIST_REL
    manifest.write_text("2\nold\\a\nnew\\b\n", encoding="utf-8")
    amap = tmp_path / "asset_map.json"
    amap.write_text(json.dumps({"old\\a": "Old/a"}), encoding="utf-8")
    monkeypatch.setattr(AM, "ASSET_MAP_JSON", amap)
    monkeypatch.setattr(A, "ASSET_MAP_JSON", amap)
    for f in (AM.encoded_to_decoded, AM.decoded_to_encoded, A._shipped_cache_paths):
        f.cache_clear()
    yield game, amap
    for f in (AM.encoded_to_decoded, AM.decoded_to_encoded, A._shipped_cache_paths):
        f.cache_clear()


def _rebuild_into(amap, calls):
    def rebuild(path=None):
        calls.append(path)
        amap.write_text(json.dumps({"old\\a": "Old/a", "new\\b": "New/b"}),
                        encoding="utf-8")
        return 0
    return rebuild


def test_a_map_that_covers_the_install_is_left_alone(game, monkeypatch):
    g, amap = game
    amap.write_text(json.dumps({"old\\a": "Old/a", "new\\b": "New/b"}), encoding="utf-8")
    import rsmm.engine.find_iyg as F
    monkeypatch.setattr(F, "main", lambda *a, **k: pytest.fail("rebuilt a fresh map"))
    assert A._refresh_stale_asset_map(g)


def test_a_stale_map_is_rebuilt_and_the_new_file_counts_as_vanilla(game, monkeypatch):
    g, amap = game
    import rsmm.engine.find_iyg as F
    calls: list = []
    monkeypatch.setattr(F, "main", _rebuild_into(amap, calls))
    assert not A.is_vanilla_encoded("new\\b")
    assert A._refresh_stale_asset_map(g)
    assert calls == [str(g / USEDRSCLIST_REL)]
    assert A.is_vanilla_encoded("new\\b")


def test_mod_records_in_the_live_manifest_do_not_count_as_stale(game, monkeypatch):
    g, amap = game
    amap.write_text(json.dumps({"old\\a": "Old/a", "new\\b": "New/b"}), encoding="utf-8")
    live = g / USEDRSCLIST_REL
    live.with_name(live.name + BACKUP_SUFFIX).write_text(live.read_text())
    live.write_text(live.read_text() + "mod\\c\n", encoding="utf-8")
    import rsmm.engine.find_iyg as F
    monkeypatch.setattr(F, "main", lambda *a, **k: pytest.fail("read mod records"))
    assert A._refresh_stale_asset_map(g)


def test_restore_refuses_when_the_map_cannot_be_fixed(game, monkeypatch, capsys):
    g, _amap = game
    import rsmm.engine.find_iyg as F
    monkeypatch.setattr(F, "main", lambda *a, **k: 1)
    cooking = g / COOKING_REL
    (cooking / ".rsmm_state.json").write_text(json.dumps(
        {"active": {"new\\b": {"mod": "m", "src_sha256": "x", "orig_sha256": ""}}}))
    rc = A.cmd_restore_all(SimpleNamespace(dry_run=False), g, cooking, g)
    assert rc == 1
    assert (cooking / "new" / "b").read_bytes() == b"VANILLA"
    assert "Not restoring" in capsys.readouterr().err


# --- the versiondef patcher vs a mod that replaces the versiondef ----------

def test_patcher_leaves_a_mod_owned_versiondef_and_its_backup_alone(tmp_path, capsys):
    cooking = tmp_path / COOKING_REL
    cooking.mkdir(parents=True)
    gen = cooking / cipher.encode(V.VERSIONDEF_GEN_LEAF)
    assert cipher.decode(gen.name) == V.VERSIONDEF_GEN_LEAF
    gen.write_bytes(b"BACKPORT VERSIONDEF")
    bak = gen.with_name(gen.name + BACKUP_SUFFIX)
    bak.write_bytes(b"VANILLA VERSIONDEF")       # the override's own backup

    assert V.sync_versiondef(tmp_path, {}, dry_run=False, gen_owner="backport") == 0
    assert gen.read_bytes() == b"BACKPORT VERSIONDEF"
    assert bak.read_bytes() == b"VANILLA VERSIONDEF"

    V.sync_versiondef(tmp_path, {}, dry_run=False, bans={"Some_Item"},
                      gen_owner="backport")
    assert gen.read_bytes() == b"BACKPORT VERSIONDEF"
    assert "backport replaces the LiveOps versiondef" in capsys.readouterr().err
