"""The mined enemy catalog (data/enemy_catalog.json) and its generated docs page.

Game-derived but committed, on the same terms as data/stat_keys.json: names,
tags and a handful of floats rather than game content, and it is what the
encyclopedia page in the docs is rendered from. These tests need no game exe
and no cooked corpus — they check the shape of what was mined, and that the
page and the JSON have not drifted apart.
"""

import json
import re

from rsmm.engine.paths import REPO_ROOT

CATALOG = REPO_ROOT / "data" / "enemy_catalog.json"
PAGE = REPO_ROOT / "apps" / "docs" / "src" / "content" / "docs" / "reference" / "enemy-catalog.md"

# Spot values cross-checked by hand against the cooked entities they come from.
# A parser that picks the wrong mark reads adjacent marker bytes and these go
# absurd (~1e30) or vanish, so they are the first thing to break.
ANCHORS = {
    "Gnoll_Hunter": 125.0,
    "Standard_Mud_Crab": 70.0,
    "Ogre_Cyclop": 300.0,
    "Baba_Yaga_Boss": 1000.0,
    "Boss_Crab": 180.0,
}


def _rows():
    return json.loads(CATALOG.read_text())["enemies"]


def _by_id():
    return {r["id"]: r for r in _rows()}


def test_catalog_is_well_formed():
    rows = _rows()
    assert len(rows) > 60, "suspiciously small catalog"
    seen = set()
    for r in rows:
        assert r["id"] and r["id"] not in seen, f"duplicate enemy id {r['id']!r}"
        seen.add(r["id"])
        assert isinstance(r["flags"], list)
        assert isinstance(r["stats"], dict)


def test_anchor_health_values():
    rows = _by_id()
    for enemy_id, want in ANCHORS.items():
        assert enemy_id in rows, f"{enemy_id} is gone from the catalog"
        health = rows[enemy_id]["stats"].get("health")
        assert health, f"{enemy_id} lost its mined health"
        assert health["value"] == want, f"{enemy_id}: {health['value']} != {want}"


def test_stats_are_plausible_numbers():
    """A misparse reads marker bytes as a float and lands around 1e30."""
    for r in _rows():
        for field, rec in r["stats"].items():
            val = rec["value"]
            assert isinstance(val, (int, float))
            assert val == val, f"{r['id']}.{field} is NaN"
            assert 0 <= val <= 1e7, f"{r['id']}.{field} = {val} is not an authored number"
            assert rec["from"], f"{r['id']}.{field} has no source entity"


def test_most_enemies_resolve_health():
    rows = _rows()
    with_hp = sum(1 for r in rows if "health" in r["stats"])
    # 63/81 at the time of mining; the rest inherit the Character_Common
    # default. A drop here means the inheritance walk broke, which is exactly
    # how this started out (2 of 81) before the mark-position fix.
    assert with_hp >= len(rows) * 0.7, f"only {with_hp}/{len(rows)} resolved health"


def test_docs_page_matches_the_catalog():
    """Every catalogued enemy appears on the generated page, and the count agrees."""
    text = PAGE.read_text()
    rows = _rows()

    m = re.search(r"\*\*(\d+) enemy definitions\*\*", text)
    assert m, "the page lost its headline count"
    assert int(m.group(1)) == len(rows), "the page count disagrees with the catalog"

    assert "Do not edit this page by hand" in text, "the generated-file banner is gone"

    for r in rows:
        name = r["id"]
        for prefix in ("Standard_", "Elite_", "Boss_"):
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break
        display = name.replace("_", " ")
        assert f"| {display} |" in text, f"{r['id']} is missing from the docs page"
