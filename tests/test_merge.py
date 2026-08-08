"""Tests for the [[patch]] merge layer."""

from __future__ import annotations

import tomllib

import pytest

from rsmm.cli.merge import _ranked, _toml_load, build_merged_mod, collect_patches


def test_toml_load_reads_a_manifest(tmp_path):
    f = tmp_path / "test.toml"
    f.write_text(
        '[mod]\nid = "Test"\nname = "Test"\nversion = "1.0.0"\n'
        'enabled = true\n\n'
        '[[patch]]\nkind = "stat"\nname = "Health"\nvalue = 100\n',
        encoding="utf-8",
    )
    data = _toml_load(f)
    assert data["mod"]["id"] == "Test"
    assert len(data["patch"]) == 1
    assert data["patch"][0]["kind"] == "stat"
    assert data["patch"][0]["value"] == 100


def test_toml_load_raises_on_malformed_input(tmp_path):
    """No lenient re-parse: `collect_patches` skips the mod instead.

    A regex fallback used to accept whatever it could scrape from a manifest
    tomllib had already rejected, using different semantics into the bargain,
    so `merge` applied patches from a mod `apply_mods` refused to load.
    """
    f = tmp_path / "bad.toml"
    f.write_text("not toml {{{", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        _toml_load(f)


def test_collect_patches_skips_a_mod_apply_would_also_reject(
        tmp_path, monkeypatch, capsys):
    """merge and apply must agree on which manifests are valid."""
    mods = tmp_path / "mods"
    good = mods / "Good"
    good.mkdir(parents=True)
    good.joinpath("manifest.toml").write_text(
        '[mod]\nid = "Good"\n[[patch]]\nkind = "stat"\nname = "Health"\nvalue = 1\n',
        encoding="utf-8")
    bad = mods / "Sneaky"
    bad.mkdir(parents=True)
    bad.joinpath("manifest.toml").write_text(
        '[mod]\nid = "Sneaky"\n[[patch]]\nkind = "stat"\nbroken = = =\n',
        encoding="utf-8")
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", mods)

    patches = collect_patches()

    assert [p.mod_id for p in patches] == ["Good"]
    assert "skip Sneaky" in capsys.readouterr().err


def test_collect_patches_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", tmp_path / "mods")
    assert collect_patches() == []


def test_ranked_stable():
    from rsmm.cli.merge import _Patch
    patches = [
        _Patch("B", 1, "stat", {"name": "X"}),
        _Patch("A", 1, "stat", {"name": "X"}),
        _Patch("C", 0, "stat", {"name": "X"}),
    ]
    ranked = _ranked(patches)
    assert ranked[0].mod_id == "C"  # load_order 0 first
    assert ranked[-1].mod_id == "B"  # load_order 1, then alphabetical


def test_build_merged_mod_no_patches(monkeypatch, tmp_path):
    monkeypatch.setattr("rsmm.cli.merge.MODS_DIR", tmp_path / "mods")
    monkeypatch.setattr("rsmm.cli.merge.COOKING_SUBDIR", "_Cooking")
    game = tmp_path / "game"
    (game / "_Cooking").mkdir(parents=True)
    out, conflicts = build_merged_mod(game)
    assert out is None
    assert conflicts == []
