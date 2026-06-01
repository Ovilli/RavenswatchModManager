"""Unit tests for the length-preserving magical-object cooker.

Pure byte manipulation on a synthetic cooked-style blob (length-prefixed
strings interleaved with binary), so these run without a Ravenswatch install.
"""

import struct

import pytest

from rsmm.engine import magic_item_cook as C


def _lstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _blob() -> bytes:
    # Mimics a cooked entity: float, a scoped node label embedding the id,
    # the debug name, the icon path, and a text key — all length-prefixed.
    return (
        b"\x11\x11\xbb\xaa"                     # a marker-ish prefix (binary)
        + struct.pack("<f", 2.0)               # a value float
        + _lstr("[Value] Armor_Per_Object\\Armor per Object Value")
        + _lstr("Green_Armor")                 # debug name
        + _lstr("Objects\\UI_Object_GreenArmor.png")  # icon
        + _lstr("Armor_Per_Object_Name")       # text-bank key (embeds id)
        + b"\x22\x22\xbb\xaa"
    )


def test_rename_id_same_length():
    out = C.rename_id(_blob(), "Armor_Per_Object", "Test_Clone_Item0")
    assert len(out) == len(_blob())
    assert b"Armor_Per_Object" not in out
    # Renamed inside the scoped label AND the text key in one pass.
    assert b"[Value] Test_Clone_Item0\\Armor per Object Value" in out
    assert b"Test_Clone_Item0_Name" in out


def test_rename_id_variable_length_via_container():
    from rsmm.engine import cooked
    # Build a minimal valid cooked container (type B) with one section whose
    # payload holds an id-bearing length-prefixed string.
    sec = cooked.Section(payload=_lstr("[Value] Armor_Per_Object\\X"))
    cf = cooked.CookedFile(variant="B", hdr_a=1, flags=0, sections=[sec])
    data = cooked.emit(cf)
    out = C.rename_id(data, "Armor_Per_Object", "A_Much_Longer_Item_Id")
    assert b"Armor_Per_Object" not in out
    assert b"A_Much_Longer_Item_Id" in out
    # still a valid, re-parseable cooked file with a fixed-up string prefix
    re = cooked.parse(out)
    assert _lstr("[Value] A_Much_Longer_Item_Id\\X") in re.sections[0].payload


def test_rename_id_missing_raises():
    with pytest.raises(ValueError, match="not found"):
        C.rename_id(_blob(), "Nonexistent_Item", "Nonexistent_Itez")


def test_replace_lstr_anchored():
    out = C.replace_lstr(_blob(), "Green_Armor", "RSMMClone_X", what="debug name")
    assert b"Green_Armor" not in out
    assert _lstr("RSMMClone_X") in out
    assert len(out) == len(_blob())


def test_replace_lstr_length_mismatch_raises():
    with pytest.raises(ValueError, match="byte length"):
        C.replace_lstr(_blob(), "Green_Armor", "TooLongReplacement")


def test_replace_lstr_unanchored_substring_not_matched():
    # "Armor" appears inside other strings but never as its own length-prefixed
    # slot, so an anchored replace must fail rather than corrupt a substring.
    with pytest.raises(ValueError, match="not found"):
        C.replace_lstr(_blob(), "Armor", "Armer")


def test_find_lstrings():
    found = dict((t, off) for off, t in C.find_lstrings(_blob()))
    assert "Green_Armor" in found
    assert "Objects\\UI_Object_GreenArmor.png" in found
    icons = C.find_lstrings(_blob(), contains="png")
    assert len(icons) == 1 and icons[0][1].endswith(".png")


def test_set_value_after_label():
    blob = (_lstr("Armor per Object Value")
            + b"\x01\x02\x03\x04" + struct.pack("<f", 2.0) + b"\x22\x22\xbb\xaa")
    out = C.set_value_after_label(blob, "Armor per Object Value", 2.0, 50.0)
    assert len(out) == len(blob)
    assert struct.pack("<f", 2.0) not in out
    assert struct.pack("<f", 50.0) in out


def test_set_value_wrong_old_value_raises():
    blob = _lstr("Val") + struct.pack("<f", 2.0)
    with pytest.raises(ValueError, match="expected value"):
        C.set_value_after_label(blob, "Val", 9.0, 1.0)


def test_set_value_missing_label_raises():
    with pytest.raises(ValueError, match="not found"):
        C.set_value_after_label(_lstr("X"), "Nope", 1.0, 2.0)


def _guid(seed: int) -> bytes:
    return bytes([seed]) * 16


def _node(guid: bytes, name: str) -> bytes:
    return guid + _lstr(name)


def test_own_node_guids_splits_unique_from_shared():
    shared = _guid(0xAA)   # class-table-like, in every item
    own_a = _guid(0xB1)    # unique to item A
    own_b = _guid(0xB2)
    item_a = (_node(shared, "oCEntitySettingsResource")
              + _node(own_a, "Node A1") + _node(own_b, "Node A2"))
    item_b = _node(shared, "oCEntitySettingsResource") + _node(_guid(0xC1), "Node B1")
    own = C.own_node_guids(item_a, [item_a, item_b])
    assert shared not in own
    assert own_a in own and own_b in own


def test_remint_changes_only_own_guids_and_preserves_length():
    shared = _guid(0xAA)
    own = _guid(0xB1)
    item = _node(shared, "oCEntitySettingsResource") + _node(own, "My Node")
    other = _node(shared, "oCEntitySettingsResource") + _node(_guid(0xC1), "Other")
    out = C.remint_guids(item, [item, other], salt="New_Item")
    assert len(out) == len(item)
    assert shared in out          # external/class guid preserved
    assert own not in out         # own guid re-minted away
    # deterministic
    assert out == C.remint_guids(item, [item, other], salt="New_Item")
    # salt-dependent (different clone => different identity)
    assert out != C.remint_guids(item, [item, other], salt="Other_Item")


def test_remint_keeps_internal_references_consistent():
    # Own guid appears twice: as a node definition and as an internal reference.
    shared = _guid(0xAA)
    own = _guid(0xB7)
    item = (_node(shared, "oCEntitySettingsResource")
            + _node(own, "Def Node") + b"\x99\x99" + own + b"\x88\x88")
    other = _node(shared, "x")
    out = C.remint_guids(item, [item, other], salt="Z")
    minted = C._mint_guid(own, b"Z")
    # both the definition and the reference were rewritten to the same new guid
    assert out.count(minted) == 2
    assert own not in out


def _write_bank(path, entries):
    from rsmm.engine.text_patches import TextFile, write_text_file
    tf = TextFile(path=path, header=b"\x14\x00\x00\x00" + b"\x00" * 0x10,
                  entries=list(entries), footer=b"")
    path.write_bytes(write_text_file(tf))


def test_append_bank_keys_aligns_base_and_siblings(tmp_path):
    from rsmm.engine.text_patches import (
        append_bank_keys,
        lang_path_for,
        parse_text_file,
    )
    base = tmp_path / "Bank~GAM.xls.LocalText.gen"
    _write_bank(base, ["Old_Name", "Old_Desc"])
    _write_bank(lang_path_for(base, "EN"), ["Old EN Name", "Old EN Desc"])
    _write_bank(lang_path_for(base, "DE"), ["Alt", "Beschr"])

    out = append_bank_keys(base, {"New_Name": "Hello", "New_Desc": "World"})
    # base gets the keys
    base.write_bytes(out["__base__"])
    keys = parse_text_file(base)
    assert keys.entries[-2:] == ["New_Name", "New_Desc"]
    # each sibling got the same display values at matching indices
    en = lang_path_for(base, "EN")
    en.write_bytes(out[".LangEN"])
    vals = parse_text_file(en)
    assert len(vals.entries) == len(keys.entries)
    assert vals.entries[-2:] == ["Hello", "World"]
    assert ".LangDE" in out


def test_append_bank_keys_rejects_misaligned(tmp_path):
    from rsmm.engine.text_patches import append_bank_keys, lang_path_for
    base = tmp_path / "Bank~GAM.xls.LocalText.gen"
    _write_bank(base, ["A", "B"])
    _write_bank(lang_path_for(base, "EN"), ["only one"])  # 1 != 2
    with pytest.raises(ValueError, match="misaligned"):
        append_bank_keys(base, {"C": "c"})


def test_build_magic_item_entity_and_text(tmp_path):
    # cooked entity blob: each lstr is a proper node (preceded by its own GUID)
    # so remint's GUID heuristic never grabs the id string or the value float.
    shared = _guid(0xAA)
    ent = (_node(shared, "oCEntitySettingsResource")
           + _node(_guid(0xB4), "[Value] Base_Item_Idxx\\X")
           + _node(_guid(0xB5), "Armor per Object Value")
           + struct.pack("<f", 2.0) + b"\x22\x22\xbb\xaa")
    other = _node(shared, "oCEntitySettingsResource") + _node(_guid(0xC9), "y")
    base = tmp_path / "Bank~GAM.xls.LocalText.gen"
    _write_bank(base, ["X"])
    from rsmm.engine.text_patches import lang_path_for
    _write_bank(lang_path_for(base, "EN"), ["x"])

    files = C.build_magic_item(
        new_id="New_Item_Idxxx", base_id="Base_Item_Idxx",  # same length (14)
        base_cooked=ent, corpus=[ent, other], rarity="Epic",
        name="My Item", description="Desc",
        value_patches=[("Armor per Object Value", 2.0, 50.0)],
        bank_base_gen=base,
    )
    ent_key = ("EntitySettings/Objects/Magical_Objects/Epic/"
               "New_Item_Idxxx.entity.ot.EntitySettingsResource.gen")
    assert ent_key in files
    assert b"Base_Item_Idxx" not in files[ent_key]
    assert struct.pack("<f", 50.0) in files[ent_key]
    assert C.MAGIC_TEXT_BANK in files
    assert any(k.endswith(".LangEN") for k in files)


def test_item_edit_swaps_track_id_rename():
    # An lstr swap whose strings embed the base id must still match after the
    # id rename rewrote that token in the blob.
    edit = C.ItemEdit(
        base_id="Armor_Per_Object", new_id="Test_Clone_Item0",
        lstr_swaps=[("Armor_Per_Object_Name", "Test_Clone_Item0_Name")],
    )
    out = edit.apply(_blob())
    assert b"Armor_Per_Object" not in out
    assert b"Test_Clone_Item0" in out
    assert len(out) == len(_blob())
