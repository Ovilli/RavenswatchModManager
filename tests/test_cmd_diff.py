"""`rsmm diff <mod>`: what applying one mod changes, and who else touches it.

The view must agree with `plan_apply`, so these build real mods on disk and
resolve them against the shipped asset map rather than a stub.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsmm.cli import apply_mods as A
from rsmm.cli import cmd_diff as D
from rsmm.cli import merge as M

ENTITY = "EntitySettings/Heroes/Hero_Juliet/Ghost_Hero_Juliet.entity.ot.EntitySettingsResource.gen"
TEXT_BANK = "Text/Refugees~GAM.xls.LocalText.gen"
NEW_FILE = "Characters/Rsmm_Diff_Test_New.mat.ot"       # sibling dir exists
ORPHAN = "No_Such_Top/Nested/orphan.bin"                # nothing to anchor it


def _mod(root: Path, folder: str, files: dict[str, bytes], *, enabled=True,
         extra: str = "", load_order: int = 100) -> Path:
    d = root / folder
    (d / "assets").mkdir(parents=True)
    (d / "manifest.toml").write_text(
        f'[mod]\nid = "{folder}"\nname = "{folder}"\nversion = "1.0.0"\n'
        f"enabled = {'true' if enabled else 'false'}\nload_order = {load_order}\n"
        + extra, encoding="utf-8")
    for rel, data in files.items():
        p = d / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return d


@pytest.fixture
def mods_dir(tmp_path, monkeypatch):
    root = tmp_path / "mods"
    root.mkdir()
    monkeypatch.setattr(A, "MODS_DIR", root)
    monkeypatch.setattr(M, "MODS_DIR", root)
    return root


def _report(mods_dir: Path, mod_id: str, active=None, game_dir=None):
    mods = A.discover_mods(mods_dir.parent)
    mod = D._find(mods, mod_id)
    return D.build_report(mod, mods, A.load_asset_map(), active, game_dir)


def _by_path(rep):
    return {f.decoded: f for f in rep.files}


def test_classifies_replace_add_and_skip(mods_dir):
    _mod(mods_dir, "solo", {ENTITY: b"e", NEW_FILE: b"n", ORPHAN: b"o"})
    files = _by_path(_report(mods_dir, "solo"))
    assert files[ENTITY].action == "replace"
    assert files[NEW_FILE].action == "add"
    assert files[ORPHAN].action == "skip" and files[ORPHAN].encoded is None


def test_unmerged_overlap_names_the_mod_whose_copy_lands(mods_dir):
    # plan_apply keeps the LAST writer in discovery (folder) order.
    _mod(mods_dir, "alpha", {ENTITY: b"a"})
    _mod(mods_dir, "beta", {ENTITY: b"b"})
    a = _by_path(_report(mods_dir, "alpha"))[ENTITY]
    b = _by_path(_report(mods_dir, "beta"))[ENTITY]
    assert a.others == ["beta"] and a.winner == "beta"
    assert b.others == ["alpha"] and b.winner == "beta"
    assert "LOST to beta" in D.render(_report(mods_dir, "alpha"))


def test_additive_families_are_merged_not_conflicts(mods_dir):
    _mod(mods_dir, "alpha", {TEXT_BANK: b"a"})
    _mod(mods_dir, "beta", {TEXT_BANK: b"b"})
    f = _by_path(_report(mods_dir, "alpha"))[TEXT_BANK]
    assert f.merged_as == "text bank" and f.winner == ""


def test_disabled_mods_neither_conflict_nor_hide_themselves(mods_dir):
    _mod(mods_dir, "alpha", {ENTITY: b"a"})
    _mod(mods_dir, "beta", {ENTITY: b"b"}, enabled=False)
    assert _by_path(_report(mods_dir, "alpha"))[ENTITY].others == []
    # The disabled mod itself is still inspectable before enabling it.
    rep = _report(mods_dir, "beta")
    assert not rep.enabled and rep.files[0].others == ["alpha"]


def test_patch_overlap_only_on_a_different_value(mods_dir):
    stat = '[[patch]]\nkind = "stat"\nname = "Foo"\nvalue = {v}\n'
    _mod(mods_dir, "alpha", {}, extra=stat.format(v=1), load_order=200)
    _mod(mods_dir, "beta", {}, extra=stat.format(v=2))
    _mod(mods_dir, "gamma", {}, extra=stat.format(v=1))
    (p,) = _report(mods_dir, "beta").patches
    assert p.key == "foo.value" and p.others == {"alpha": 1, "gamma": 1}
    # alpha's higher load_order sorts it last, so it wins.
    assert p.winner == "alpha"
    (a,) = _report(mods_dir, "alpha").patches
    assert a.others == {"beta": 2} and a.winner == "alpha"


def test_install_status_from_the_state_file(mods_dir):
    _mod(mods_dir, "alpha", {ENTITY: b"current", NEW_FILE: b"n", TEXT_BANK: b"t"})
    dec2enc = A.load_asset_map()
    src = mods_dir / "alpha" / "assets" / ENTITY
    active = {
        dec2enc[ENTITY]: {"mod": "alpha", "src_sha256": A.sha256(src)},
        dec2enc[TEXT_BANK]: {"mod": "someone-else", "src_sha256": "x"},
    }
    files = _by_path(_report(mods_dir, "alpha", active))
    assert files[ENTITY].status == "installed"
    assert files[NEW_FILE].status == "pending"
    assert files[TEXT_BANK].status == "owned:someone-else"
    active[dec2enc[ENTITY]]["src_sha256"] = "stale"
    assert _by_path(_report(mods_dir, "alpha", active))[ENTITY].status == "outdated"


def test_read_active_never_touches_a_corrupt_state_file(tmp_path):
    state = tmp_path / A.STATE_FILE_NAME
    state.write_text("{not json", encoding="utf-8")
    assert D.read_active(tmp_path) is None
    assert state.read_text(encoding="utf-8") == "{not json"   # not quarantined
    assert list(tmp_path.iterdir()) == [state]
    assert D.read_active(tmp_path / "missing") == {}


def test_long_sections_are_capped_but_conflicts_always_print(mods_dir):
    many = {f"Characters/Rsmm_Diff_{i:03}.mat.ot": b"x" for i in range(40)}
    _mod(mods_dir, "alpha", {**many, ENTITY: b"a"})
    _mod(mods_dir, "beta", {ENTITY: b"b"})
    text = D.render(_report(mods_dir, "alpha"))
    assert "more (--all" in text and "LOST to beta" in text
    assert "more (--all" not in D.render(_report(mods_dir, "alpha"), show_all=True)


def test_cli_json_and_unknown_mod(mods_dir, monkeypatch, capsys):
    monkeypatch.setenv("RSMM_GAME_DIR", str(mods_dir / "no-game"))
    _mod(mods_dir, "alpha", {ENTITY: b"a"})
    assert D.main(["alpha", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mod"] == "alpha" and out["game_found"] is False
    assert out["files"][0]["action"] == "replace"
    assert D.main(["nope"]) == 1
    assert "installed: alpha" in capsys.readouterr().err
    assert D.main(["alpah"]) == 1
    assert "did you mean alpha?" in capsys.readouterr().err
