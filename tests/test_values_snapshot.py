"""`rsmm values`: a patch's values backed up, and an update's changes listed."""

from __future__ import annotations

import pytest

from rsmm.engine import corpus
from rsmm.engine import values_snapshot as VS

ICE_CLONE = ("EntitySettings/Heroes/Hero_Snow_Queen/"
             "Hero_Snow_Queen_Ice_Clone.entity.ot.EntitySettingsResource.gen")


def test_diff_lists_changed_added_and_removed_values():
    a = {"entities": {"E/x.gen": {"Timer": {"duration": "f32 3"}, "Gone": {"v": "f32 1"}},
                      "E/old.gen": {}},
         "items": {"E/i.gen": {"values": {"Damage": 10.0}, "modifiers": []}}}
    b = {"entities": {"E/x.gen": {"Timer": {"duration": "f32 5"}}, "E/new.gen": {}},
         "items": {"E/i.gen": {"values": {"Damage": 12.0}, "modifiers": []}}}
    got = {(c.rel, c.where, c.old, c.new) for c in VS.diff(a, b)}
    assert got == {
        ("E/x.gen", "Timer.duration", "f32 3", "f32 5"),
        ("E/x.gen", "Gone", "part", None),
        ("E/old.gen", "", "file", None),
        ("E/new.gen", "", None, "file"),
        ("E/i.gen", "item value Damage", "10.0", "12.0"),
    }
    assert list(VS.diff(a, a)) == []


@pytest.mark.skipif(corpus.cooking_dir() is None, reason="no game install")
def test_snapshot_round_trips_the_installed_bytes(tmp_path, monkeypatch):
    # Only the Snow Queen's folder, so the test stays fast.
    read, rels = VS._install_reader()
    monkeypatch.setattr(VS, "_install_reader", lambda: (
        read, lambda prefix: [r for r in rels(prefix) if "Hero_Snow_Queen/" in r]))
    snap = VS.snapshot("t", out_dir=tmp_path)
    assert snap.meta["entities"] > 10 and snap.meta["files"] >= snap.meta["entities"]
    loaded = VS.load(str(tmp_path / "t"))
    parts = loaded.values["entities"][ICE_CLONE]          # keyed Group\\Name
    assert any(k.endswith("Lifetime Timer") for k in parts)
    assert VS.restore_file(str(tmp_path / "t"), ICE_CLONE) == read(ICE_CLONE)
    with pytest.raises(VS.SnapshotError, match="already exists"):
        VS.snapshot("t", out_dir=tmp_path)
