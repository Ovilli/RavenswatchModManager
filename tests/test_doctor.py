"""Tests for rsmm doctor health checks."""

from __future__ import annotations

import json

from rsmm.cli.doctor import (
    Result,
    check_asset_map,
    check_compat_graph,
    check_exe_hash,
    check_game_install,
    check_mods,
    check_patch_conflicts,
    check_state,
)


def test_result_kind_must_be_valid():
    r = Result("OK", "test")
    assert r.kind == "OK"
    r = Result("WARN", "test", "detail")
    assert r.detail == "detail"


def test_check_game_install_missing_dir(tmp_path):
    fake = tmp_path / "nonexistent"
    results = check_game_install(fake)
    assert any(r.kind == "FAIL" for r in results)


def test_check_game_install_ok(tmp_path):
    cooking = tmp_path / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    results = check_game_install(tmp_path)
    assert all(r.kind == "OK" for r in results)


def test_check_asset_map_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.cli.doctor.ASSET_MAP_JSON", tmp_path / "missing.json")
    results = check_asset_map(tmp_path)
    assert any(r.kind == "FAIL" for r in results)


def test_check_state_corrupt(tmp_path):
    cooking = tmp_path / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    state = cooking / ".rsmm_state.json"
    state.write_text("not json", encoding="utf-8")
    results = check_state(tmp_path)
    assert any(r.kind == "FAIL" for r in results)


def test_check_state_no_state_file(tmp_path):
    results = check_state(tmp_path)
    assert any("no applier state" in r.label for r in results)


def test_check_state_has_active(tmp_path):
    cooking = tmp_path / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    state = cooking / ".rsmm_state.json"
    state.write_text(json.dumps({"active": {"a\\b.bin": "TestMod"}}), encoding="utf-8")
    results = check_state(tmp_path)
    assert any("1 active override" in r.label for r in results)


def test_check_exe_hash_no_patterns(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.cli.doctor.DATA_DIR", tmp_path)
    results = check_exe_hash(tmp_path)
    assert any("function_patterns.json missing" in r.label for r in results)


def test_check_mods_no_mods_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.cli.doctor.MODS_DIR", tmp_path / "mods")
    results = check_mods()
    assert any("mods/ missing" in r.label for r in results)


def test_check_patch_conflicts_no_patches():
    results = check_patch_conflicts()
    assert not results or all(r.kind != "FAIL" for r in results)


def _write_mod(mods: object, mod_id: str, body: str) -> None:
    from pathlib import Path
    d = Path(mods) / mod_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(
        f'[mod]\nid = "{mod_id}"\nname = "{mod_id}"\nversion = "1.0.0"\n{body}',
        encoding="utf-8",
    )


def test_compat_graph_no_mods(tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.engine.paths.MODS_DIR", tmp_path / "mods")
    rs = check_compat_graph()
    assert len(rs) == 1 and rs[0].kind == "OK"


def test_compat_graph_clean(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    _write_mod(mods, "core", "")
    _write_mod(mods, "user", 'requires = ["core >=1.0 <2.0"]\n')
    monkeypatch.setattr("rsmm.engine.paths.MODS_DIR", mods)
    rs = check_compat_graph()
    assert all(r.kind == "OK" for r in rs)


def test_compat_graph_recommend_warns_not_fails(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    _write_mod(mods, "user", 'recommends = ["sidekick >=1.0"]\n')  # sidekick absent
    monkeypatch.setattr("rsmm.engine.paths.MODS_DIR", mods)
    rs = check_compat_graph()
    assert any(r.kind == "WARN" and "missing-recommend" in r.label for r in rs)
    assert all(r.kind != "FAIL" for r in rs)


def test_compat_graph_missing_requires_fails(tmp_path, monkeypatch):
    mods = tmp_path / "mods"
    _write_mod(mods, "user", 'requires = ["missing-lib >=2.0"]\n')
    monkeypatch.setattr("rsmm.engine.paths.MODS_DIR", mods)
    rs = check_compat_graph()
    assert any(r.kind == "FAIL" and "missing-dep" in r.label for r in rs)
