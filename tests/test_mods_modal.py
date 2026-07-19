"""Tests for the standalone RSMM mod-menu modal clone.

Synthetic legs build a minimal entity with one real component record and one
descriptor record (no instance identity) — the shape that broke the first
implementation. The corpus leg clones the shipped ``Modal_Model`` and is
skipped when ``data/uncooked`` is absent.
"""

import struct
from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine import entity_strings as ES
from rsmm.engine import mods_modal as MM

_BEGIN = cooked.MARK_BEGIN
_END = cooked.MARK_END

_DONOR = (Path(__file__).resolve().parents[1] / "data" / "uncooked" /
          "EntitySettings" / "GameUis" / "Modal" /
          "Modal_Model.entity.ot.EntitySettingsResource.gen")
_needs_corpus = pytest.mark.skipif(not _DONOR.is_file(),
                                   reason="data/uncooked corpus not present")


def _lstr(s: str) -> bytes:
    b = s.encode("ascii")
    return struct.pack("<I", len(b)) + b


def _cpnt(cls: int, guid: bytes, name: str, tail: bytes = b"") -> bytes:
    """A component record: class + header + instance GUID + name + tail."""
    return (struct.pack("<I", cls) + _BEGIN + struct.pack("<I", 0x13)
            + b"\0" * 20 + _END + guid + _lstr(name) + tail)


def _desc(cls: int) -> bytes:
    """A descriptor record — no instance GUID, and its first END sits in
    structural bytes that contain section markers."""
    return (struct.pack("<I", cls) + _BEGIN + struct.pack("<I", 0x2c)
            + _BEGIN + struct.pack("<I", 0x15) + _END + _lstr("Some_Desc")
            + _END)


def _entity(records: list[bytes]) -> bytes:
    directory = (struct.pack("<I", len(records))
                 + b"".join(struct.pack("<I", struct.unpack_from("<I", r, 0)[0])
                            for r in records))
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef("oCEntitySettingsResource", 0x16f5f7a3, 1, 0, 0)],
        sections=([cooked.Section(payload=directory)]
                  + [cooked.Section(payload=r) for r in records]
                  + [cooked.Section(payload=b"\0" * 4)]),
    )
    return cooked.emit(cf)


@pytest.fixture
def synthetic() -> bytes:
    guid_ui = bytes(range(16))
    guid_state = bytes(range(16, 32))
    return _entity([
        _cpnt(0, guid_ui, "Game Ui"),
        # A picker: the referenced component's GUID sits next to its path.
        _cpnt(0, guid_state, "State Ready",
              guid_ui + _lstr("[Game Ui] Modal_Model\\Game Ui")),
        _desc(0),
    ])


def test_rename_rewrites_reference_paths(synthetic):
    out = MM.rename_entity(synthetic, "Modal_Model", "RSMM_Mods_Modal")
    strings = {s for _, _, s in ES.list_strings(out)}
    assert "[Game Ui] RSMM_Mods_Modal\\Game Ui" in strings
    assert not [s for s in strings if "Modal_Model" in s]


def test_rename_rejects_absent_donor_name(synthetic):
    with pytest.raises(MM.ModsModalError, match="not present"):
        MM.rename_entity(synthetic, "Modal_Nope", "RSMM_Mods_Modal")


def test_descriptor_records_have_no_instance_guid(synthetic):
    cf = cooked.parse(synthetic)
    guids = [MM._component_guid(s.payload) for s in cf.sections[1:-1]]
    assert guids[0] is not None and guids[1] is not None
    # The descriptor must be refused: its structural bytes contain markers,
    # and reminting them merges sections.
    assert guids[2] is None
    assert MM.component_names(synthetic) == ["Game Ui", "State Ready", ""]


def test_remint_keeps_references_pointing_at_their_component(synthetic):
    out = MM.remint_all(synthetic)
    cf_in, cf_out = cooked.parse(synthetic), cooked.parse(out)
    assert len(cf_out.sections) == len(cf_in.sections)

    old_ui = MM._component_guid(cf_in.sections[1].payload)
    new_ui = MM._component_guid(cf_out.sections[1].payload)
    assert new_ui != old_ui
    # The picker in "State Ready" must have moved to the new GUID in lockstep.
    picker = cf_out.sections[2].payload
    assert new_ui in picker and old_ui not in picker
    assert old_ui not in out


def test_remint_leaves_no_donor_guid_behind(synthetic):
    out = MM.remint_all(synthetic)
    before = {MM._component_guid(s.payload)
              for s in cooked.parse(synthetic).sections[1:-1]} - {None}
    after = {MM._component_guid(s.payload)
             for s in cooked.parse(out).sections[1:-1]} - {None}
    assert len(after) == len(before)
    assert not (before & after)


@_needs_corpus
def test_donor_clone_is_structurally_intact():
    donor = _DONOR.read_bytes()
    clone = MM.build_modal(donor)
    cf_d, cf_c = cooked.parse(donor), cooked.parse(clone)

    assert len(cf_c.sections) == len(cf_d.sections)
    assert cooked.emit(cooked.parse(clone)) == clone
    assert [c.name for c in cf_c.classes] == [c.name for c in cf_d.classes]
    assert _DONOR.read_bytes() == donor, "clone must not mutate the corpus"


@_needs_corpus
def test_donor_clone_has_no_dangling_component_references():
    clone = MM.build_modal(_DONOR.read_bytes())
    names = set(MM.component_names(clone)) - {""}
    refs = {s for _, _, s in ES.list_strings(clone)
            if s.startswith("[") and "\\" in s}
    assert refs, "clone should carry component references"
    assert not [r for r in refs if r.split("\\", 1)[1] not in names]


@_needs_corpus
def test_donor_clone_shares_no_identity_with_the_donor():
    donor = _DONOR.read_bytes()
    clone = MM.build_modal(donor)
    guids_d = {MM._component_guid(s.payload)
               for s in cooked.parse(donor).sections[1:-1]} - {None}
    guids_c = {MM._component_guid(s.payload)
               for s in cooked.parse(clone).sections[1:-1]} - {None}
    assert len(guids_c) == len(guids_d)
    assert not (guids_d & guids_c)
    assert not [s for _, _, s in ES.list_strings(clone) if MM.DONOR_NAME in s]


@_needs_corpus
def test_donor_clone_keeps_the_controller_buttons():
    """The four declared buttons are what make this a usable custom menu."""
    clone = MM.build_modal(_DONOR.read_bytes())
    strings = {s for _, _, s in ES.list_strings(clone)}
    for button in ("Validate_Button", "Cancel_Button",
                   "Third_Button", "Fourth_Button"):
        assert button in strings
