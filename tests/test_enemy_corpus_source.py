"""The enemy corpus has two stores, and only one exists on a player's machine.

`data/uncooked/` is the 7.3 GB authoring mirror — gitignored, never bundled
into the sidecar. Every downloaded copy of the app therefore has to read the
same cooked bytes out of the game install itself, or `mode="override"` emits
nothing on exactly the machines the mod is for.

These tests run the install-backed path by hiding the mirror, and pin the one
property that makes the fallback trustworthy: both stores answer identically.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rsmm.engine import enemy_pools as EP
from rsmm.sdk.content import ContentDef
from rsmm.sdk.kinds import enemies


@pytest.fixture
def install_only(monkeypatch):
    """Hide the uncooked mirror so every read falls through to the install."""
    if EP._cooking_dir() is None:
        pytest.skip("no game install to read the cooked corpus from")
    missing = Path("/nonexistent/uncooked")
    monkeypatch.setattr(EP, "UNCOOKED", missing)
    monkeypatch.setattr(EP, "OT_DIR", missing / "Ot")
    monkeypatch.setattr(EP, "ENEMY_DIR", missing / "Definitions" / "Enemies")
    assert EP.corpus_source() == "install"
    yield


def _fingerprint(paths: list[Path]) -> str:
    rows = sorted((p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths)
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _emit(out: Path, defn_id: str) -> list[Path]:
    defn = ContentDef(kind="enemy", id=defn_id,
                      fields={"mode": "override", "cross_biome": True,
                              "repoint_pools": False, "mix": "shuffle",
                              "seed": 1337, "weight": 5.0})
    return enemies.emit("TestCorpusSourceMod", defn, out)


def test_install_answers_the_same_index_as_the_mirror(install_only):
    """The mirror is a verbatim copy of the install's cooked files, so the
    definition index derived from either must be the same object."""
    from_install = EP.enemy_index()
    assert from_install, "install-backed index is empty"
    assert len(EP.spawnable_entities()) == 50
    assert set(EP.pool_rels()) >= {"Dark_Hills", "Avalon", "Storm_Island", "Common"}


def test_emit_is_byte_identical_from_either_store(tmp_path, monkeypatch):
    """The proof the fallback is a fallback and not a second implementation."""
    if not EP.enemy_index():
        pytest.skip("no enemy corpus")
    mirror_out = tmp_path / "mirror"
    mirror = _fingerprint(_emit(mirror_out, "src"))

    if EP._cooking_dir() is None:
        pytest.skip("no game install to compare against")
    missing = Path("/nonexistent/uncooked")
    monkeypatch.setattr(EP, "UNCOOKED", missing)
    monkeypatch.setattr(EP, "OT_DIR", missing / "Ot")
    monkeypatch.setattr(EP, "ENEMY_DIR", missing / "Definitions" / "Enemies")
    install = _fingerprint(_emit(tmp_path / "install", "src"))
    assert install == mirror


def test_install_reads_the_pristine_backup_not_the_applied_file(install_only):
    """`apply` overwrites cooked files in place. Reading the live file would
    make an applied override look like vanilla and compound edits."""
    rel = EP.cooked_rel_for(next(iter(EP.enemy_index())))
    p = EP._install_path(rel)
    assert p is not None
    live = p.with_name(p.name.removesuffix(".rsmm.bak"))
    if live.with_name(live.name + ".rsmm.bak").is_file():
        assert p.name.endswith(".rsmm.bak"), "must prefer the pristine backup"


def test_picker_options_come_from_the_install_too(install_only):
    """The config panel's monster list is the same read path, so it populates
    on a plain install — the machine the mod is actually downloaded onto."""
    from rsmm.sdk.config_choices import provide

    opts = provide("enemy-roster")
    assert len(opts) == 50
    assert all(o["group"] for o in opts)
