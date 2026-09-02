"""`rsmm assets` — readable-path search over the shipped asset map.

The install is 43k cipher-encoded filenames, so "where does the wolf enemy
live" cannot be answered with `ls` or `grep`. These tests pin the matching
rules (the part with logic) against a fixture index rather than the real map,
so they hold with no corpus and no game present.
"""

from __future__ import annotations

import pytest

from rsmm.cli import cmd_assets

_INDEX = {
    "Definitions/Enemies/Standard_Wolf_Dire.enemydef.ot.DtEnemyDefinition.gen": "A\\B",
    "Definitions/Enemies/Elite_Wolf_Alpha.enemydef.ot.DtEnemyDefinition.gen": "A\\C",
    "Entities/Wolves/Standard_Wolf_Dire.entity.ot": "D\\E",
    "Ui/Objects/Icon_Wolf.png": "F\\G",
    "Ui/Objects/Icon_Crab.png": "F\\H",
}


def test_terms_are_anded_so_adding_one_narrows():
    assert len(cmd_assets.search_paths(_INDEX, ["wolf"])) == 4
    hits = cmd_assets.search_paths(_INDEX, ["wolf", "enemies"])
    assert len(hits) == 2
    assert all("Enemies" in h for h in hits)


def test_matching_ignores_case_and_slash_direction():
    assert cmd_assets.search_paths(_INDEX, ["ui/objects"]) == \
        cmd_assets.search_paths(_INDEX, ["UI\\Objects"])
    assert len(cmd_assets.search_paths(_INDEX, ["ICON_wolf"])) == 1


def test_a_wildcard_term_matches_the_whole_path_as_a_glob():
    assert cmd_assets.search_paths(_INDEX, ["ui/*.png"]) == [
        "Ui/Objects/Icon_Crab.png",
        "Ui/Objects/Icon_Wolf.png",
    ]
    # ...and a glob that only matches a fragment does NOT match, because the
    # pattern is anchored to the whole path.
    assert cmd_assets.search_paths(_INDEX, ["icon_*"]) == []


def test_shortest_path_first_so_the_definition_beats_its_textures():
    hits = cmd_assets.search_paths(_INDEX, ["standard_wolf_dire"])
    assert hits[0] == "Entities/Wolves/Standard_Wolf_Dire.entity.ot"


def test_empty_query_matches_nothing_rather_than_everything():
    assert cmd_assets.search_paths(_INDEX, []) == []
    assert cmd_assets.search_paths(_INDEX, [""]) == []


def test_search_exits_nonzero_when_nothing_matches(monkeypatch, capsys):
    monkeypatch.setattr(cmd_assets, "_index", lambda: _INDEX)
    assert cmd_assets.main(["search", "definitely_not_an_asset"]) == 1
    assert cmd_assets.main(["search", "wolf"]) == 0
    out = capsys.readouterr().out
    assert "4 match(es)" in out


def test_json_output_carries_both_spellings(monkeypatch, capsys):
    import json

    monkeypatch.setattr(cmd_assets, "_index", lambda: _INDEX)
    cmd_assets.main(["search", "icon_wolf", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert rows == [{"decoded": "Ui/Objects/Icon_Wolf.png", "encoded": "F\\G"}]


def test_missing_asset_map_is_reported_not_an_empty_result(monkeypatch, capsys):
    monkeypatch.setattr(cmd_assets, "_index", dict)
    assert cmd_assets.main(["search", "wolf"]) == 1
    assert "rebuild-asset-map" in capsys.readouterr().err


@pytest.mark.parametrize("path", [
    "Audio/Music.bank",
    "Definitions/Enemies/Gnoll_Hunter.enemydef.UsedRscCache.ot",
])
def test_show_resolves_the_families_absent_from_the_asset_map(path, capsys):
    """Sound banks and resource caches are ciphered by convention and appear in
    no manifest — `show` must still answer for them, or it teaches that a file
    the game plainly loads does not exist."""
    from rsmm.engine.asset_map import decoded_to_encoded

    if not decoded_to_encoded():
        pytest.skip("no asset map")
    assert cmd_assets.main(["show", path]) == 0
    out = capsys.readouterr().out
    assert "by convention" in out
