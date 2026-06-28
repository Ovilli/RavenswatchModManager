"""Re-sequence a run's chapters (custom map order, Heredos #10).

Corpus-gated on the shipped ``All_Chapters`` game-mode def.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import game_mode_cook as GMC

_DIR = Path("data/uncooked/Definitions/GameModes")
_BASE = "All_Chapters"
_BASE_GEN = _DIR / f"{_BASE}{GMC.GEN_SUFFIX}"

requires_corpus = pytest.mark.skipif(
    not _BASE_GEN.exists(), reason="vanilla game-mode corpus not present"
)


@requires_corpus
def test_vanilla_sequence_is_four_biomes():
    assert GMC.read_sequence(_BASE_GEN.read_bytes()) == [0, 1, 2, 3]


@requires_corpus
def test_reorder_roundtrips():
    out = GMC.set_chapter_sequence(_BASE_GEN.read_bytes(), [2, 0, 1, 3])
    assert GMC.read_sequence(out) == [2, 0, 1, 3]


@requires_corpus
def test_repeat_and_shorten():
    blob = _BASE_GEN.read_bytes()
    assert GMC.read_sequence(GMC.set_chapter_sequence(blob, [0, 0, 0])) == [0, 0, 0]
    assert GMC.read_sequence(GMC.set_chapter_sequence(blob, [3])) == [3]


@requires_corpus
def test_out_of_range_index_rejected():
    with pytest.raises(GMC.GameModeCookError):
        GMC.set_chapter_sequence(_BASE_GEN.read_bytes(), [0, 9])


@requires_corpus
def test_empty_sequence_rejected():
    with pytest.raises(GMC.GameModeCookError):
        GMC.set_chapter_sequence(_BASE_GEN.read_bytes(), [])
