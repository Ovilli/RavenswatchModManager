"""Convention-over-configuration content discovery.

The point of this layer is that a manifest stops growing as a mod gains
content. These tests pin the two properties that makes it safe to rely on:
discovery produces exactly the dict a hand-written block would, and a
hand-written block always wins.
"""

from __future__ import annotations

import pytest

from rsmm.sdk import discovery
from rsmm.sdk.content import KINDS, ContentError


def test_returns_nothing_for_a_mod_with_no_content_dirs(tmp_path):
    assert discovery.discover(tmp_path) == []


def test_every_kind_dir_maps_to_a_real_kind():
    """A typo here silently disables a whole directory convention."""
    assert set(discovery.KIND_DIRS.values()) <= set(KINDS)


def test_folder_becomes_a_block_with_id_from_the_folder_name(tmp_path):
    d = tmp_path / "items" / "ember_charm"
    d.mkdir(parents=True)
    (d / "item.toml").write_text('name = "Ember Charm"\nrarity = "rare"\n')
    assert discovery.discover(tmp_path) == [
        {"kind": "item", "id": "ember_charm", "name": "Ember Charm", "rarity": "rare"}]


def test_explicit_id_overrides_the_folder_name(tmp_path):
    d = tmp_path / "modifiers" / "whatever"
    d.mkdir(parents=True)
    (d / "def.toml").write_text('id = "DoubleTrouble"\n')
    assert discovery.discover(tmp_path)[0]["id"] == "DoubleTrouble"


def test_both_config_filenames_are_accepted(tmp_path):
    for folder, fname in (("a", "item.toml"), ("b", "def.toml")):
        d = tmp_path / "items" / folder
        d.mkdir(parents=True)
        (d / fname).write_text("rarity = 'common'\n")
    assert [b["id"] for b in discovery.discover(tmp_path)] == ["a", "b"]


def test_discovery_is_deterministic_across_kinds_and_folders(tmp_path):
    for kind_dir, names in (("items", ("zeta", "alpha")), ("enemies", ("wolf",))):
        for n in names:
            d = tmp_path / kind_dir / n
            d.mkdir(parents=True)
            (d / "def.toml").write_text("x = 1\n")
    got = [(b["kind"], b["id"]) for b in discovery.discover(tmp_path)]
    assert got == [("enemy", "wolf"), ("item", "alpha"), ("item", "zeta")]


def test_a_folder_with_no_config_is_an_error_not_a_silent_skip(tmp_path):
    (tmp_path / "items" / "empty").mkdir(parents=True)
    with pytest.raises(ContentError, match="has no item.toml"):
        discovery.discover(tmp_path)


def test_invalid_toml_names_the_file(tmp_path):
    d = tmp_path / "items" / "broken"
    d.mkdir(parents=True)
    (d / "item.toml").write_text("this is not = = toml\n")
    with pytest.raises(ContentError, match="not valid TOML"):
        discovery.discover(tmp_path)


def test_manifest_block_wins_over_a_same_id_folder():
    declared = [{"kind": "item", "id": "foo", "name": "HAND WRITTEN"}]
    discovered = [{"kind": "item", "id": "foo", "name": "from folder"},
                  {"kind": "item", "id": "bar"}]
    merged = discovery.merge_with_manifest(declared, discovered)
    assert [b["id"] for b in merged] == ["foo", "bar"]
    assert merged[0]["name"] == "HAND WRITTEN"


def test_same_id_in_different_kinds_do_not_shadow_each_other():
    declared = [{"kind": "item", "id": "foo"}]
    discovered = [{"kind": "enemy", "id": "foo"}]
    merged = discovery.merge_with_manifest(declared, discovered)
    assert len(merged) == 2, "an item and an enemy may share a name"


def test_poi_uses_its_own_discover_hook(tmp_path):
    """`poi` resolves presets and matches art by filename, so the generic scan
    must not shadow it — a poi.toml with only `chapters` would otherwise emit a
    block missing every donor field."""
    d = tmp_path / "pois" / "shrine"
    d.mkdir(parents=True)
    (d / "poi.toml").write_text('chapters = ["Dark_Hills"]\n')
    block = discovery.discover(tmp_path)[0]
    assert block["kind"] == "poi"
    assert "base" in block and "weight" in block, "preset fields were not applied"
