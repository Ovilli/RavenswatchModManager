"""`R.lobby.HERO_NAMES` follows the LiveOps versiondef's hero vector: a lobby
`RequestedHero` id is the hero's index there (observed in game on Update 6).
A content patch that reorders or grows the vector makes the table lie."""

from __future__ import annotations

import re

import pytest

from rsmm.engine import corpus
from rsmm.engine import versiondef as VD
from rsmm.engine.paths import REPO_ROOT

VD_REL = f"Definitions/Versions/{VD.VERSIONDEF_GEN_LEAF}"


def _lua_names() -> list[str]:
    src = (REPO_ROOT / "src/loader/lib/rsmm.lua").read_text(encoding="utf-8")
    body = re.search(r"R\.lobby\.HERO_NAMES = \{(.*?)\n\}", src, re.S).group(1)
    return re.findall(r'"([A-Za-z_]+)"', body)


@pytest.mark.skipif(corpus.read(VD_REL) is None, reason="no versiondef in the corpus")
def test_hero_names_follow_the_versiondef_hero_vector():
    raw = corpus.read(VD_REL)
    start, end, _n = VD._find_hero_vector(raw)
    stems = re.findall(rb"Heroes\\([A-Za-z0-9_]+)\.herodef\.ot", raw[start:end])
    want = [re.sub(r"_Update\d+$", "", s.decode()) for s in stems]
    assert _lua_names() == want
