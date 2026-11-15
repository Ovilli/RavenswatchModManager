"""`rsmm poi` reads chapter pools through engine.corpus.

`_pool_of` still treated `poi._MAPS_DIR` as a directory after it became a
corpus-relative string, so `rsmm poi`, `rsmm poi list --chapter` and
`rsmm poi show` raised TypeError on every install while `rsmm poi list` (the
one path that never asks for a pool) kept working.
"""

from __future__ import annotations

import pytest

from rsmm.cli import cmd_poi
from rsmm.engine import map_pool as MP
from rsmm.sdk.kinds import poi as P


def test_pool_of_reads_the_mapdef_through_the_corpus(monkeypatch):
    chapter = sorted(P.CHAPTERS)[0]
    asked = []

    def fake_read(rel):
        asked.append(rel)
        return b"mapdef"

    monkeypatch.setattr(cmd_poi.corpus, "read", fake_read)
    monkeypatch.setattr(MP, "read_pool", lambda raw: [
        "Tiles\\Avalon\\40x40_Avalon_Cauldron_T1.tiledef.ot",
        "too\\short",
    ])
    assert cmd_poi._pool_of(chapter) == {"Avalon/40x40_Avalon_Cauldron_T1"}
    assert asked == [f"{P._MAPS_DIR}/{P.CHAPTERS[chapter]}{MP.GEN_SUFFIX}"]


def test_pool_of_is_empty_when_the_mapdef_is_absent(monkeypatch):
    monkeypatch.setattr(cmd_poi.corpus, "read", lambda rel: None)
    assert cmd_poi._pool_of(sorted(P.CHAPTERS)[0]) == set()


@pytest.mark.parametrize("argv", [[], ["list", "--chapter", "Avalon"]])
def test_pool_commands_run_against_the_corpus(argv, capsys):
    tiles = P.known_tiles()
    if not tiles:
        pytest.skip("no tile corpus")
    assert cmd_poi.main(argv) == 0
    assert cmd_poi.main(["show", sorted(tiles)[0]]) == 0
    capsys.readouterr()
