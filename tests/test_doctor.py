"""Tests for rsmm doctor health checks."""

from __future__ import annotations

import json

from rsmm.cli.doctor import (
    Result,
    check_asset_map,
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
