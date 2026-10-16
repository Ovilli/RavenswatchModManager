"""The `challenge` kind: a ChallengeDefinition clone with its own modifiers."""

from __future__ import annotations

import pytest

from rsmm.engine import challenge_cook as CK
from rsmm.engine import cooked, corpus
from rsmm.engine import rsc_cache as RC
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import challenges

_DIR = "Definitions/Challenges"
needs = pytest.mark.skipif(corpus.read(f"{_DIR}/DodgeIt{CK.GEN_SUFFIX}") is None,
                           reason="no challenge corpus")


def _defn(cid: str, **fields) -> ContentDef:
    return ContentDef(kind="challenge", id=cid, fields=fields)


@needs
@pytest.mark.parametrize("stem", ["DodgeIt", "MoonlightSonata", "PowerOfTheSun",
                                  "RushHour", "TerraIncognita"])
def test_every_retail_challenge_rebuilds_byte_exact(stem):
    raw = corpus.read(f"{_DIR}/{stem}{CK.GEN_SUFFIX}")
    d = CK.parse_tail(CK._tail(cooked.parse(raw)))
    assert CK.clone(raw, title_key=d["title"], modifiers=CK.modifiers_of(raw),
                    guid=d["guid"]) == raw


@needs
def test_a_cut_challenge_comes_back_with_its_own_modifiers_guid_and_cache(tmp_path):
    out = challenges.emit("M", _defn("AllIn", modifiers=["NoMinimap", "DayOnly"]), tmp_path)
    gen = next(p for p in out if p.name.endswith(CK.GEN_SUFFIX))
    raw = gen.read_bytes()
    d = CK.parse_tail(CK._tail(cooked.parse(raw)))
    assert d["title"] == "Challenge_AllIn_Title"
    assert CK.modifiers_of(raw) == ["NoMinimap", "DayOnly"]
    base = CK.parse_tail(CK._tail(cooked.parse(corpus.read(f"{_DIR}/DodgeIt{CK.GEN_SUFFIX}"))))
    assert d["guid"] != base["guid"]  # progress must not count as DodgeIt's

    cache = next(p for p in out if p.name.endswith(RC.CACHE_SUFFIX))
    lines = RC.parse(cache.read_bytes())
    assert lines == sorted(lines)
    assert "Definitions|Challenges\\AllIn.challengedef.ot|ChallengeDefinition" in lines
    assert "Definitions|GameModifiers\\NoMinimap.gamemodifierdef.ot|GameModifierDefinition" in lines


@needs
@pytest.mark.parametrize("fields, msg", [
    ({"modifiers": []}, "list of 1-5"),
    ({"modifiers": ["NoMinimap"] * 2}, "listed twice"),
    ({"modifiers": ["A", "B", "C", "D", "E", "F"]}, "at most 5"),
    ({"modifiers": ["NotAModifier"]}, "not a shipped modifier"),
])
def test_bad_modifier_lists_are_refused(tmp_path, fields, msg):
    with pytest.raises(ContentError, match=msg):
        challenges.emit("M", _defn("AllIn", **fields), tmp_path)


@needs
def test_a_new_id_needs_a_name(tmp_path):
    with pytest.raises(ContentError, match="needs a 'name'"):
        challenges.emit("M", _defn("Brand_New", modifiers=["NoMinimap"]), tmp_path)
