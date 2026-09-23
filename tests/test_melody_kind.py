"""The `[[content]] kind="melody"` builder edits a retail melodydef in place
(override asset at the vanilla decoded path) — repoint the effect entity,
retune the game-modifier exclusion list.

Runs against the real vanilla melodies corpus (skipped if absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsmm.engine import corpus
from rsmm.sdk.content import KIND_CONFIDENCE, KINDS, ContentDef, ContentError, _load_kind
from rsmm.sdk.kinds import melodies

_BASE = "Fully_Heal"
_BASE_GEN = f"{melodies._MELODY_DIR}/{_BASE}{melodies.GEN_SUFFIX}"


def _retail_gens() -> list[str]:
    """Decoded paths of every retail melodydef (mirror or install)."""
    return [f"{melodies._MELODY_DIR}/{st}{melodies.GEN_SUFFIX}"
            for st in melodies.known_melodies()]


def _require_corpus():
    if not corpus.exists(_BASE_GEN):
        pytest.skip("vanilla melodies corpus not present")


def _decode(src: Path | str) -> dict:
    """Decode an emitted file (a Path) or a shipped def (a decoded path)."""
    raw = src.read_bytes() if isinstance(src, Path) else corpus.read(src)
    return json.loads(melodies.handler().decode_cooked(raw))


def _emit(tmp_path: Path, *, id: str = "Edit", **fields) -> list[Path]:
    defn = ContentDef(kind="melody", id=id, fields={"base": _BASE, **fields})
    return melodies.emit("TestMelodyMod", defn, tmp_path)


# --- registry wiring -------------------------------------------------------

def test_kind_is_registered_and_resolves_to_this_module():
    assert "melody" in KINDS
    assert _load_kind("melody") is melodies


def test_kind_confidence_is_honest():
    # No in-game proof exists for either lever; must not claim more.
    assert KIND_CONFIDENCE["melody"] == "guess"


# --- codec invariants (the evidence this kind rests on) --------------------

def test_all_retail_melodydefs_round_trip_byte_for_byte():
    _require_corpus()
    h = melodies.handler()
    gens = _retail_gens()
    assert len(gens) == 12, "retail corpus is exactly 12 melodies"
    for g in gens:
        raw = corpus.read(g)
        assert h.encode_container(h.decode_cooked(raw)) == raw, g


def test_field_a_is_a_dense_unique_enum_index():
    """The reason this kind is override-only: field_a covers {0..11} exactly,
    so there is no free index for a 13th melody."""
    _require_corpus()
    idx = sorted(_decode(g)["field_a"]
                 for g in _retail_gens())
    assert idx == list(range(12))


def test_exclusion_split_join_is_identity_on_whole_corpus():
    _require_corpus()
    for g in _retail_gens():
        tail = bytes.fromhex(_decode(g)["_tail_hex"])
        prefix, names, suffix = melodies.split_exclusions(tail)
        assert melodies.join_exclusions(prefix, names, suffix) == tail, g


def test_every_retail_exclusion_is_a_real_modifier_stem():
    _require_corpus()
    valid = set(melodies.known_modifiers())
    assert valid, "GameModifiers corpus should be present alongside melodies"
    seen: set[str] = set()
    for g in _retail_gens():
        _, names, _ = melodies.split_exclusions(bytes.fromhex(_decode(g)["_tail_hex"]))
        seen |= set(names)
    assert seen and seen <= valid


# --- emit ------------------------------------------------------------------

def test_emits_at_retail_decoded_path(tmp_path):
    _require_corpus()
    (out,) = _emit(tmp_path, exclude=[])
    assert out == tmp_path / "Definitions" / "Melodies" / f"{_BASE}{melodies.GEN_SUFFIX}"


def test_exclude_replaces_the_list(tmp_path):
    _require_corpus()
    _, before, _ = melodies.split_exclusions(bytes.fromhex(_decode(_BASE_GEN)["_tail_hex"]))
    assert before == ["NightOnly", "DayOnly", "NoFeathers"]
    edited = _decode(_emit(tmp_path, exclude=["OneChapter"])[0])
    _, after, _ = melodies.split_exclusions(bytes.fromhex(edited["_tail_hex"]))
    assert after == ["OneChapter"]


def test_exclude_empty_clears_all(tmp_path):
    _require_corpus()
    edited = _decode(_emit(tmp_path, exclude=[])[0])
    _, after, _ = melodies.split_exclusions(bytes.fromhex(edited["_tail_hex"]))
    assert after == []


def test_exclude_output_is_still_decodable_and_stable(tmp_path):
    _require_corpus()
    out = _emit(tmp_path, exclude=["NoMinimap", "NoBossTimer"])[0]
    h = melodies.handler()
    raw = out.read_bytes()
    assert h.encode_container(h.decode_cooked(raw)) == raw


def test_effect_repoints_entity_ref_only(tmp_path):
    _require_corpus()
    base = _decode(_BASE_GEN)
    edited = _decode(_emit(tmp_path, effect="Reveal_Map")[0])
    assert edited["entity_ref"] == ["EntitySettings", "Objects\\Melodies\\Reveal_Map.entity.ot"]
    # Identity fields are untouched — the melody keeps its index and GUID.
    assert edited["field_a"] == base["field_a"]
    assert edited["_tail_hex"] == base["_tail_hex"]


def test_unknown_modifier_stem_is_a_typo_guard(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="not a GameModifier stem"):
        _emit(tmp_path, exclude=["NoBossTimerr"])


def test_unknown_effect_melody_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="not a retail melody"):
        _emit(tmp_path, effect="Nope")


def test_no_edits_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="no edits"):
        _emit(tmp_path)


def test_missing_base_rejected(tmp_path):
    with pytest.raises(ContentError, match="needs a 'base'"):
        melodies.emit("M", ContentDef(kind="melody", id="X", fields={}), tmp_path)
