"""The mined entity-value catalog (data/stat_keys.json) and its generated Lua.

The catalog is game-derived but committed, like data/symbols.json: it is small,
it is names and 32-bit ids rather than game content, and the SDK's stat table is
built on it. These tests need no game exe — they check the shape of what was
mined and that the loader-facing table stays in step with it.
"""

import json
import re

from rsmm.engine.paths import REPO_ROOT

CATALOG = REPO_ROOT / "data" / "stat_keys.json"
LUA = REPO_ROOT / "src" / "loader" / "lib" / "stats_gen.lua"

# Verified against the engine's own display names by tools/mine_stat_keys.py
# --verify. A parser that drifts by one registration breaks these first.
ANCHORS = {
    0x15A486C4: "Attack power",
    0x188671A6: "Vitality",
    0x044DADDE: "Move Speed Ratio",
    0x15C7D482: "Crit chance",
    0x173FCDAA: "Poison",
}


def _catalog():
    return json.loads(CATALOG.read_text())


def test_catalog_is_well_formed():
    recs = _catalog()
    assert len(recs) > 150, "suspiciously small catalog"
    for r in recs:
        assert isinstance(r["key"], int) and 0 <= r["key"] <= 0xFFFFFFFF
        assert r["name"] and r["name"].strip() == r["name"]
        # a name/key pairing that slipped by one registration shows up here
        assert "length_mismatch" not in r, f"staged length disagrees for {r['name']!r}"


def test_keys_are_unique():
    keys = [r["key"] for r in _catalog()]
    assert len(keys) == len(set(keys)), "a key was mined twice"


def test_known_names_match_the_engine():
    by_key = {r["key"]: r["name"] for r in _catalog()}
    for key, name in ANCHORS.items():
        assert by_key.get(key) == name, f"0x{key:08x} should be {name!r}, got {by_key.get(key)!r}"


def test_armour_is_registered_but_unaddressable():
    """Armour has a definition and NO key, which is why R.stat cannot move it."""
    unkeyed = [r["name"] for r in _catalog() if r["key"] == 0]
    assert "Armour" in unkeyed


def test_generated_lua_matches_the_catalog():
    lua = LUA.read_text()
    assert "DO NOT EDIT" in lua
    entries = dict(re.findall(r'\["(\w+)"\] = \{ key = (0x[0-9a-f]+)', lua))
    assert entries, "no entries generated"
    keyed = {r["key"] for r in _catalog() if r["key"]}
    for ident, key in entries.items():
        assert int(key, 16) in keyed, f"{ident} is not in the catalog"
    # key 0 is never emitted: it cannot be looked up
    assert "0x00000000" not in lua


def test_every_generated_table_is_planted_and_published():
    """A generated lib/*.lua reaches the game only if each list names it.

    rsmm.lua loads these with `pcall(require, ...)`, so a table nobody plants is
    silently absent: the SDK degrades instead of failing, which is how
    events_gen went unplanted once. Four lists have to agree — both installers,
    the loader-update bundle and doctor's planted-file check.
    """
    generated = sorted(p.name for p in (REPO_ROOT / "src" / "loader" / "lib").glob("*_gen.lua"))
    assert generated, "no generated tables found"
    sources = {
        "install_loader.sh": (REPO_ROOT / "src/rsmm/cli/install_loader.sh").read_text(),
        "install_loader.ps1": (REPO_ROOT / "src/rsmm/cli/install_loader.ps1").read_text(),
        "publish_loader.sh": (REPO_ROOT / "scripts/publish_loader.sh").read_text(),
        "doctor.py": (REPO_ROOT / "src/rsmm/cli/doctor.py").read_text(),
    }
    for name in generated:
        for where, text in sources.items():
            assert name in text, f"{name} is not listed in {where}"
