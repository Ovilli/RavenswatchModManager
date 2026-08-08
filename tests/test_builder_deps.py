"""The SDK builder must emit dependency declarations in the [mod]-level array
form the dependency graph + apply gate actually read.

Regression guard: an earlier builder wrote a `[dependencies]` table that both
readers silently ignored, so `Mod.requires(...)` had no effect.
"""

from __future__ import annotations

from pathlib import Path

from rsmm.manifest_graph import _load_one, validate_graph
from rsmm.sdk import Mod
from rsmm.sdk.builder import ModBuilder


def _render(mb: ModBuilder, tmp_path: Path) -> Path:
    mb._write_manifest(tmp_path)
    return tmp_path / "manifest.toml"


def test_all_dep_tiers_round_trip_through_reader(tmp_path):
    mb = ModBuilder("MyMod", version="1.0.0", author="me", name="My Mod",
                    load_order=90)
    mb.requires("Core", ">=1.2 <2.0")
    mb.recommends("BetterLoot", "^1.0")
    mb.suggests("SoundPack")
    mb.conflicts("OldMod")
    mb.replaces("LegacyMod")

    rec = _load_one(_render(mb, tmp_path), "MyMod")
    assert rec.requires == ["Core >=1.2 <2.0"]
    assert rec.recommends == ["BetterLoot ^1.0"]
    assert rec.suggests == ["SoundPack"]
    assert rec.conflicts == ["OldMod"]
    assert rec.replaces == ["LegacyMod"]
    assert rec.load_order == 90


def test_no_deps_emits_no_arrays(tmp_path):
    mb = ModBuilder("Plain", version="1.0.0", author="me", name="Plain")
    text = _render(mb, tmp_path).read_text()
    for key in ("requires", "recommends", "suggests", "conflicts", "replaces",
                "load_order", "[dependencies]"):
        assert key not in text


def test_emitted_requires_validates_in_graph(tmp_path):
    """A built mod's requires range must drive the graph the same as the
    hand-written form."""
    core = ModBuilder("Core", version="1.5.0", author="me", name="Core")
    user = ModBuilder("User", version="1.0.0", author="me", name="User")
    user.requires("Core", ">=1.2 <2.0")

    cdir = tmp_path / "Core"
    udir = tmp_path / "User"
    cdir.mkdir()
    udir.mkdir()
    recs = {
        "Core": _load_one(_render(core, cdir), "Core"),
        "User": _load_one(_render(user, udir), "User"),
    }
    codes = {i.code for i in validate_graph(recs)}
    assert "missing-dep" not in codes and "version-mismatch" not in codes

    # Bump Core out of range -> version-mismatch error.
    core_bad = ModBuilder("Core", version="2.1.0", author="me", name="Core")
    recs["Core"] = _load_one(_render(core_bad, cdir), "Core")
    assert "version-mismatch" in {i.code for i in validate_graph(recs)}


def test_public_wrapper_exposes_dep_methods(tmp_path, monkeypatch):
    """sdk.Mod (the wrapper authors use) must forward every dep tier +
    load_order, and commit them to disk."""
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path))
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path)
    with Mod("WrapMod", version="1.0.0", author="me", name="Wrap",
             load_order=80) as m:
        m.requires("Core", ">=1.0")
        m.recommends("Extra")
        m.suggests("Nice")
        m.conflicts("Bad")
        m.replaces("Old")

    rec = _load_one(tmp_path / "WrapMod" / "manifest.toml", "WrapMod")
    assert rec.requires == ["Core >=1.0"]
    assert rec.recommends == ["Extra"]
    assert rec.suggests == ["Nice"]
    assert rec.conflicts == ["Bad"]
    assert rec.replaces == ["Old"]
    assert rec.load_order == 80
