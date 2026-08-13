"""Cloned entity resources must carry their own component identity GUIDs.

An `oCEntitySettingsResource` is one section per component, and each component
carries a 16-byte identity GUID. A clone that keeps the donor's is a second
resource claiming the donor's identity: it cooks, installs, registers and
resolves, every static check passes, and the engine still cannot instantiate
it. That cost several playtests, so it is pinned here.
"""

from __future__ import annotations

import pytest

from rsmm.engine import cooked
from rsmm.engine import entity_strings as ES
from rsmm.engine import prop_cook as PC
from rsmm.engine.paths import DATA_DIR

DONOR = (DATA_DIR / "uncooked/EntitySettings/DarkHills/SceneryObjects_DarkHills"
         / "Wall_Ruins_Block_Small_A.entity.ot.EntitySettingsResource.gen")

needs_corpus = pytest.mark.skipif(
    not DONOR.is_file(),
    reason="uncooked corpus absent (run scripts/extract_uncooked.py)",
)

MESH = "Scenery\\DarkHills\\Wall_Ruins_Block_Small_A.fbx"
NEW_REF = "DarkHills\\SceneryObjects_DarkHills\\testmod_thing_Prop.entity.ot"


def _clone(seed=NEW_REF):
    return PC.clone_prop_entity(DONOR.read_bytes(), {MESH: "Scenery\\DarkHills\\x.fbx"}, seed)


@needs_corpus
def test_the_clone_shares_no_component_guid_with_its_donor():
    donor = set(PC.component_guids(DONOR.read_bytes()))
    assert donor, "donor has no component GUIDs — the locator stopped working"
    assert donor.isdisjoint(set(PC.component_guids(_clone())))


@needs_corpus
def test_no_donor_guid_survives_anywhere_in_the_clone():
    # Not just in the identity slot: components reference each other by GUID,
    # and a leftover byte-sequence is a link back into the donor.
    out = _clone()
    assert not any(g in out for g in PC.component_guids(DONOR.read_bytes()))


@needs_corpus
def test_internal_links_are_carried_across_not_severed():
    # Two of this donor's component GUIDs appear twice: once as the component's
    # own identity, once as another component's link to it. Both occurrences
    # have to move together or the component tree breaks.
    donor_raw = DONOR.read_bytes()
    blob = b"".join(s.payload for s in cooked.parse(donor_raw).sections)
    linked = [g for g in PC.component_guids(donor_raw) if blob.count(g) > 1]
    assert linked, "donor has no cross-component links — pick another donor"

    out = _clone()
    new_blob = b"".join(s.payload for s in cooked.parse(out).sections)
    for old, new in zip(PC.component_guids(donor_raw), PC.component_guids(out),
                        strict=True):
        if blob.count(old) > 1:
            assert new_blob.count(new) == blob.count(old)


@needs_corpus
def test_guids_that_are_not_this_files_own_are_left_alone():
    # A picker pointing at another entity's component must keep pointing there.
    donor_raw = DONOR.read_bytes()
    own = set(PC.component_guids(donor_raw))
    external = bytes.fromhex("f43ebb9e1db9914fa1edcb4710e5542b")
    assert external not in own
    assert external in donor_raw
    assert external in _clone()


@needs_corpus
def test_restamping_is_derived_not_random():
    # Every peer in a lobby cooks these bytes independently.
    assert _clone() == _clone()


@needs_corpus
def test_different_clones_of_one_donor_do_not_collide():
    a = PC.component_guids(_clone("DarkHills\\SceneryObjects_DarkHills\\a.entity.ot"))
    b = PC.component_guids(_clone("DarkHills\\SceneryObjects_DarkHills\\b.entity.ot"))
    assert set(a).isdisjoint(set(b))


@needs_corpus
def test_string_rewrites_still_happen_and_the_container_still_parses():
    out = _clone()
    strings = [s for _sec, _off, s in ES.list_strings(out)]
    assert "Scenery\\DarkHills\\x.fbx" in strings
    assert MESH not in strings
    assert len(cooked.parse(out).sections) == len(cooked.parse(DONOR.read_bytes()).sections)


@needs_corpus
def test_omitting_the_seed_leaves_the_bytes_untouched():
    # The low-level "rewrite these strings" use has to stay available.
    assert PC.clone_prop_entity(DONOR.read_bytes(), {}) == DONOR.read_bytes()
