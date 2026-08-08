"""Fabric-style dependency ranges + soft tiers in `rsmm.manifest_graph`.

`requires`/`recommends`/`suggests`/`conflicts` mirror fabric.mod.json's
`depends`/`recommends`/`suggests`/`breaks`, and version constraints accept the
npm/Fabric semver grammar (compound, wildcard, caret, tilde).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.manifest_graph import (
    ManifestRecord,
    split_dep,
    validate_graph,
    version_satisfies,
)

# --- split_dep -------------------------------------------------------------

@pytest.mark.parametrize("spec,name,rng", [
    ("fabric", "fabric", None),
    ("fabric >=1.2", "fabric", ">=1.2"),
    ("fabric>=1.2", "fabric", ">=1.2"),               # glued single-op
    ("fabric >=1.2 <2.0", "fabric", ">=1.2 <2.0"),    # compound
    ("fabric ^1.2.3", "fabric", "^1.2.3"),
    ("fabric ~1.2", "fabric", "~1.2"),
    ("fabric 1.2.x", "fabric", "1.2.x"),
    ("my-mod:core *", "my-mod:core", "*"),
])
def test_split_dep(spec, name, rng):
    assert split_dep(spec) == (name, rng)


# --- version_satisfies -----------------------------------------------------

@pytest.mark.parametrize("have,rng,ok", [
    # bare / any
    ("1.0.0", None, True),
    ("1.0.0", "*", True),
    ("9.9.9", "any", True),
    # single op
    ("1.2.0", ">=1.2", True),
    ("1.1.9", ">=1.2", False),
    ("1.2.0", "<=1.2.0", True),
    ("2.0.0", "!=2.0.0", False),
    # compound AND (the headline Fabric pattern)
    ("1.5.0", ">=1.2 <2.0", True),
    ("2.0.0", ">=1.2 <2.0", False),
    ("1.2.0", ">=1.2 <2.0", True),
    ("1.5.0", ">=1.2, <2.0", True),          # comma separator
    # wildcard window
    ("1.2.9", "1.2.x", True),
    ("1.3.0", "1.2.x", False),
    ("1.9.9", "1.x", True),
    ("2.0.0", "1.x", False),
    # partial bare == window
    ("1.2.5", "1.2", True),
    ("1.3.0", "1.2", False),
    # caret (npm semantics)
    ("1.5.0", "^1.2.3", True),
    ("2.0.0", "^1.2.3", False),
    ("1.2.2", "^1.2.3", False),
    ("0.2.9", "^0.2.3", True),               # 0.x caret pins the minor
    ("0.3.0", "^0.2.3", False),
    # tilde
    ("1.2.9", "~1.2.3", True),
    ("1.3.0", "~1.2.3", False),
    ("1.2.0", "~1.2", True),
    ("1.3.0", "~1.2", False),
    # full bare == exact
    ("1.2.3", "1.2.3", True),
    ("1.2.4", "1.2.3", False),
])
def test_version_satisfies(have, rng, ok):
    assert version_satisfies(have, rng) is ok


# --- validate_graph: requires range + soft tiers ---------------------------

def _rec(id, **kw):
    from pathlib import Path
    return ManifestRecord(id=id, path=Path(f"/x/{id}/manifest.toml"), **kw)


def _codes(records):
    return {(i.code, i.severity) for i in validate_graph({r.id: r for r in records})}


def test_requires_compound_range_pass_and_fail():
    lib_ok = _rec("lib", version="1.5.0")
    lib_bad = _rec("lib", version="2.1.0")
    user = _rec("user", requires=["lib >=1.2 <2.0"])

    assert ("version-mismatch", "error") not in _codes([user, lib_ok])
    assert ("version-mismatch", "error") in _codes([user, lib_bad])


def test_recommends_is_warn_not_error():
    user = _rec("user", recommends=["sidekick >=1.0"])
    codes = _codes([user])  # sidekick absent
    assert ("missing-recommend", "warn") in codes
    assert not any(sev == "error" for _, sev in codes)


def test_recommends_version_warn_when_out_of_range():
    side = _rec("sidekick", version="0.9.0")
    user = _rec("user", recommends=["sidekick >=1.0"])
    codes = _codes([user, side])
    assert ("recommend-version", "warn") in codes
    assert not any(sev == "error" for _, sev in codes)


def test_suggests_is_info_only():
    user = _rec("user", suggests=["extras"])
    codes = _codes([user])
    assert ("suggest", "info") in codes
    assert not any(sev in ("error", "warn") for _, sev in codes)


def test_missing_hard_requires_still_errors():
    user = _rec("user", requires=["lib >=1.0"])
    assert ("missing-dep", "error") in _codes([user])


# --- malformed manifests must not take the graph down ----------------------

def _mod(mods: Path, name: str, body: str) -> None:
    d = mods / name
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(body, encoding="utf-8")


def test_load_manifests_is_total(tmp_path):
    """`load_manifests` has no per-entry guard, so `_load_one` must never raise.

    Regression: `mod = 5` reached `meta.get` (AttributeError) and
    `load_order = "soon"` reached `int()` (ValueError). Either one aborted the
    whole scan, so `rsmm doctor`'s compat graph and the desktop's dependency
    view showed nothing at all — including for every well-formed mod.
    """
    from rsmm.manifest_graph import load_manifests

    mods = tmp_path / "mods"
    _mod(mods, "BadMeta", "mod = 5\n")
    _mod(mods, "BadOrder", '[mod]\nid = "BadOrder"\nload_order = "soon"\n')
    _mod(mods, "Good", '[mod]\nid = "Good"\n')

    recs = load_manifests(mods)

    assert sorted(recs) == ["BadMeta", "BadOrder", "Good"]
    assert recs["Good"].parse_error is None
    assert "must be a table" in recs["BadMeta"].parse_error
    assert "whole number" in recs["BadOrder"].parse_error
    # A record that failed to parse must not be treated as an active mod.
    assert not recs["BadMeta"].enabled and not recs["BadOrder"].enabled


def test_string_dependency_is_an_error_not_four_phantom_deps(tmp_path):
    """`requires = "core"` is an easy typo; `list("core")` made it four deps.

    The author got `missing-dep` errors naming 'c', 'o', 'r' and 'e', with
    nothing pointing at the actual mistake.
    """
    from rsmm.manifest_graph import load_manifests

    mods = tmp_path / "mods"
    _mod(mods, "StrRequires", '[mod]\nid = "StrRequires"\nrequires = "core"\n')

    rec = load_manifests(mods)["StrRequires"]

    assert rec.requires == []
    assert "must be an array of strings" in rec.parse_error
    assert "did you mean ['core']" in rec.parse_error


def test_dependency_entries_are_coerced_to_strings(tmp_path):
    from rsmm.manifest_graph import load_manifests

    mods = tmp_path / "mods"
    _mod(mods, "NumDep", '[mod]\nid = "NumDep"\nrequires = [1, 2]\n')

    rec = load_manifests(mods)["NumDep"]
    assert rec.parse_error is None
    assert rec.requires == ["1", "2"]
