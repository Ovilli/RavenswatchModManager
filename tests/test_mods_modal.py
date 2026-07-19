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


# --- label text binding -----------------------------------------------------

# Deliberately NOT the values Modal_Model uses: inner BEGIN tags index the
# file's own class table, so the code must resolve them by class name rather
# than assume one donor's numbering.
_T_PICKER, _T_BOUND, _T_UNION = 0x07, 0x08, 0x09


def _label_record(name: str) -> bytes:
    """A label whose text union is bound to a picker (the donor's shape)."""
    text_union = (_BEGIN + struct.pack("<I", _T_UNION)
                  + struct.pack("<I", 5) + b"\0" * 8 + struct.pack("<I", 3)
                  + b"\0" * 8 + b"\xff\xff\xff\xff" + b"\0" * 4 + _END)
    bound = (_BEGIN + struct.pack("<I", _T_BOUND) + b"\x01\x00"
             + _BEGIN + struct.pack("<I", _T_PICKER) + bytes(range(16))
             + _lstr("[Value] Modal_Model\\Title Value") + _END
             + b"\xde\xad\xbe\xef" + text_union + _END)
    # A float union either side: only the type-5 one may ever be matched.
    other = (_BEGIN + struct.pack("<I", _T_BOUND) + b"\x00"
             + _BEGIN + struct.pack("<I", _T_UNION) + struct.pack("<I", 0)
             + b"\0" * 8 + _END + _END)
    return _cpnt(0, bytes(range(32, 48)), name, other + bound + other)


def _binding(record: bytes):
    return MM.label_text_binding(record, bound=_T_BOUND, union_tag=_T_UNION)


def _retarget(record: bytes, key: str, bank_file: str = "Common~GAM.xls"):
    return MM.set_label_text(record, bound=_T_BOUND, union_tag=_T_UNION,
                             bank_dir="Text", bank_file=bank_file, key=key)


def test_label_binding_reads_none_when_controller_driven():
    assert _binding(_label_record("Title Label")) is None


def test_label_retarget_replaces_the_picker_with_a_bank_key():
    out = _retarget(_label_record("Title Label"), "RSMM_Menu_Title")
    assert _binding(out) == ("Text", "Common~GAM.xls", "RSMM_Menu_Title")
    assert b"Title Value" not in out, "the value picker must be dropped"


def test_label_retarget_is_idempotent():
    once = _retarget(_label_record("Title Label"), "K")
    assert _retarget(once, "K") == once


def test_label_retarget_rejects_non_ascii_keys():
    with pytest.raises(MM.ModsModalError, match="ASCII"):
        _retarget(_label_record("Title Label"), "Ünicode")


def test_label_retarget_needs_exactly_one_text_union():
    with pytest.raises(MM.ModsModalError, match="text union"):
        _retarget(_cpnt(0, bytes(range(16)), "No Text Here"), "K")


def test_block_tags_are_resolved_from_the_class_table():
    """oCEntityCpntValuePicker is 0x14 in Modal_Model but 0x13 in
    System_Book_Page — hardcoding either number corrupts the other file."""
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef("oCEntityValueUnion", 1, 1, 0, 0),
                 cooked.ClassDef("oCEntityCpntValuePicker", 2, 1, 0, 0)],
        sections=[cooked.Section(payload=b"")],
    )
    assert MM.class_index(cf, "oCEntityCpntValuePicker") == 1
    assert MM.class_index(cf, "oCEntityValueUnion") == 0
    with pytest.raises(MM.ModsModalError, match="class table"):
        MM.class_index(cf, "oCNotHere")


@_needs_corpus
def test_rewriting_a_bank_label_with_its_own_values_is_byte_identical():
    """The strongest check on the union schema: a no-op rewrite must not
    disturb a single byte of a label the game itself authored."""
    donor = _DONOR.read_bytes()
    cf = cooked.parse(donor)
    names = MM.component_names(donor)
    record = cf.sections[1 + names.index("Cancel Button Label")].payload
    binding = MM.component_label_binding(donor, "Cancel Button Label")
    assert binding == ("Text", "Common~GAM.xls", "Common_Back")
    bank_dir, bank_file, key = binding
    assert MM.set_label_text(
        record, bound=MM.class_index(cf, "oCEntityCpntValuePicker"),
        union_tag=MM.class_index(cf, "oCEntityValueUnion"),
        bank_dir=bank_dir, bank_file=bank_file, key=key) == record


@_needs_corpus
def test_clone_labels_render_from_our_own_bank_keys():
    """Controller-driven labels render empty under a plain spawner, so the
    clone must carry its own text."""
    donor = _DONOR.read_bytes()
    clone = MM.build_modal(donor)
    for cpnt, key in MM.LABEL_KEYS.items():
        assert MM.component_label_binding(clone, cpnt) == (MM.BANK_DIR,
                                                           MM.BANK_FILE, key)
    # The donor's own button labels must be left exactly as they were.
    for cpnt in ("Cancel Button Label", "Validate Button Label"):
        assert (MM.component_label_binding(clone, cpnt)
                == MM.component_label_binding(donor, cpnt))


def test_modal_texts_cover_every_retargeted_label():
    texts = MM.modal_texts([{"id": "a", "name": "Alpha", "version": "1.0"}])
    assert set(texts) == set(MM.LABEL_KEYS.values())
    assert all(v for v in texts.values())


def test_modal_texts_mark_disabled_mods_and_count_them():
    texts = MM.modal_texts([
        {"id": "a", "name": "Alpha", "version": "1.0", "enabled": True},
        {"id": "b", "name": "Beta", "version": "0.2", "enabled": False},
    ])
    body = texts[MM.LABEL_KEYS["Description Label"]]
    assert "2 installed, 1 enabled." in body
    assert "Alpha 1.0" in body
    assert "[disabled]" in body.split("Beta")[1]


def test_modal_texts_handle_an_empty_mod_list():
    body = MM.modal_texts([])[MM.LABEL_KEYS["Description Label"]]
    assert "0 installed, 0 enabled." in body
    assert "(no mods installed)" in body


def test_modal_keys_do_not_collide_with_the_page_menu():
    """The page menu owns RSMM_Menu_* in Tutorials~GAM.xls; sharing a key
    across banks would make the two builders fight over one string."""
    from rsmm.engine import mod_menu

    assert not (set(MM.LABEL_KEYS.values()) & set(mod_menu.SLOT_KEYS.values()))


@_needs_corpus
def test_clone_can_opt_out_of_label_retargeting():
    clone = MM.build_modal(_DONOR.read_bytes(), labels={})
    assert MM.component_label_binding(clone, "Title Label") is None
