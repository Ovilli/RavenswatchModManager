"""The desktop/store JSON bridge must derive a {mod_id: range} dependency map
from the manifest's `requires` array — the store schema wants a dict, the
manifest carries an array, and the two were never connected (deps always
shipped empty).
"""

from __future__ import annotations

from rsmm.cli.json_bridge import _deps_map


def test_requires_array_becomes_range_map():
    m = {"requires": ["core >=1.2 <2.0", "loot ^1.0", "bare"]}
    assert _deps_map(m) == {"core": ">=1.2 <2.0", "loot": "^1.0", "bare": "*"}


def test_no_requires_is_empty():
    assert _deps_map({"name": "x"}) == {}


def test_legacy_dependencies_table_merged_under_requires():
    m = {"requires": ["core >=1.0"], "dependencies": {"core": "9.9.9", "old": "1.0.0"}}
    out = _deps_map(m)
    assert out["core"] == ">=1.0"      # requires wins
    assert out["old"] == "1.0.0"       # legacy-only entry kept
