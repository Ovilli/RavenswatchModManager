"""A resource cache must stay in ascending line order.

All 575 shipped `*.UsedRscCache.ot` files are sorted, with no exceptions. The
engine looks a resource up in here rather than scanning, so a line appended
past the end is a line the lookup never reaches — and both symptoms that
produces point somewhere else entirely (a pooled tile that is silently never
placed; an access violation in the engine's cleanup after a level load fails).
Pinned here because nothing else catches it.
"""

from __future__ import annotations

import pytest

from rsmm.engine import rsc_cache as RC
from rsmm.engine.paths import DATA_DIR

CACHES = sorted((DATA_DIR / "uncooked").rglob("*.UsedRscCache.ot"))

needs_corpus = pytest.mark.skipif(not CACHES, reason="uncooked corpus absent")


@needs_corpus
def test_every_shipped_cache_is_sorted():
    unsorted = [p.name for p in CACHES
                if RC.parse(p.read_bytes()) != sorted(RC.parse(p.read_bytes()))]
    assert not unsorted


@needs_corpus
def test_extend_keeps_the_result_sorted():
    donor = CACHES[0].read_bytes()
    # Names chosen to sort before, inside and after the donor's range.
    out = RC.extend(donor, [
        "3D/Scenery/DarkHills/aaa_mod_thing.fbx.Geometry.gen",
        "Ui/MiniMap/Icons/zzz_mod_thing.png.Texture.dxt",
        "EntitySettings/DarkHills/SceneryObjects_DarkHills/mmm_mod.entity.ot"
        ".EntitySettingsResource.gen",
    ])
    lines = RC.parse(out)
    assert lines == sorted(lines)


@needs_corpus
def test_extend_is_still_additive_and_deduplicated():
    donor = CACHES[0].read_bytes()
    before = set(RC.parse(donor))
    new = "3D/Scenery/DarkHills/aaa_mod_thing.fbx.Geometry.gen"
    out = RC.parse(RC.extend(donor, [new, new]))
    assert before < set(out)                      # nothing dropped
    assert len(out) == len(set(out))              # no duplicate line
    assert len(out) == len(before) + 1            # the repeat added nothing


@needs_corpus
def test_extending_with_nothing_new_only_reorders_nothing():
    # A donor that is already sorted must survive a no-op extend byte-for-byte,
    # so re-applying a mod cannot churn the file.
    donor = CACHES[0].read_bytes()
    assert RC.extend(donor, []) == donor
