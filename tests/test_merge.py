"""Tests for the [[patch]] merge layer."""

from __future__ import annotations

from pathlib import Path

from rsmm.cli.merge import _ranked, _toml_fallback, _toml_load, build_merged_mod, collect_patches


def test_toml_fallback_basic(tmp_path):
    f = tmp_path / "test.toml"
    f.write_text(
        '[mod]\nid = "Test"\nname = "Test"\nversion = "1.0.0"\n'
        'enabled = true\n\n'
        '[[patch]]\nkind = "stat"\nname = "Health"\nvalue = 100\n',
        encoding="utf-8",
    )
    data = _toml_fallback(f)
    assert data["mod"]["id"] == "Test"
    assert len(data["patch"]) == 1
    assert data["patch"][0]["kind"] == "stat"
    assert data["patch"][0]["value"] == 100


def test_toml_fallback_boolean():
    from rsmm.cli.merge import _toml_fallback
    f = Path(__file__).parent / "data" / "test_bool.toml"
    f.parent.mkdir(exist_ok=True)
    f.write_text('[mod]\nenabled = true\ndisabled = false\n', encoding="utf-8")
    data = _toml_fallback(f)
    assert data["mod"]["enabled"] is True
    assert data["mod"]["disabled"] is False
    f.unlink()


def test_toml_load_fallback_on_failure(tmp_path):
    f = tmp_path / "test.toml"
    f.write_text('[mod]\nid = "Test"\n', encoding="utf-8")
    # tomllib can parse this fine, but if we corrupt it...
    f2 = tmp_path / "bad.toml"
    f2.write_text("not toml {{{", encoding="utf-8")
    # On corrupt toml, _toml_load uses fallback which also fails -> {}
    data = _toml_load(f2)
    assert isinstance(data, dict)


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
