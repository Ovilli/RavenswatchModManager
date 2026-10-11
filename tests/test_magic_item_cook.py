"""Unit tests for the length-preserving magical-object cooker.

Pure byte manipulation on a synthetic cooked-style blob (length-prefixed
strings interleaved with binary), so these run without a Ravenswatch install.
"""

import struct

import pytest
from _cooked_fixtures import END, entity, lstr, value_node

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
    found = {t: off for off, t in C.find_lstrings(_blob())}
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


def test_set_value_uses_node_layout_not_first_match():
    """The magnitude is the f32 before the node's END marker, not the first
    matching float after the label.

    `Power_Up_Armor` is the shipped case: a stray -2.0 sits between the
    "Armour Value" label and the node's real 6.0. Anchoring on the stray value
    overwrote four unrelated bytes and left the armour untouched, so a
    value_patch authored against it was a silent miss. The stale default is
    refused, and a patch against the real one lands on the node's own field.
    """
    blob = entity(value_node("Armour Value", 6.0,
                             prefix=struct.pack("<f", -2.0)))  # decoy, nearer

    assert dict(C.list_value_fields(blob)) == {"Armour Value": 6.0}

    with pytest.raises(ValueError, match="node holds"):
        C.set_value_after_label(blob, "Armour Value", -2.0, 3.0)

    out = C.set_value_after_label(blob, "Armour Value", 6.0, 3.0)
    assert len(out) == len(blob)
    assert struct.pack("<f", -2.0) in out      # decoy untouched
    assert struct.pack("<f", 3.0) + END in out
    assert struct.pack("<f", 6.0) not in out


def test_set_value_wrong_old_value_raises():
    blob = _lstr("Val") + struct.pack("<f", 2.0)
    with pytest.raises(ValueError, match="expected value"):
        C.set_value_after_label(blob, "Val", 9.0, 1.0)


def test_set_value_missing_label_raises():
    with pytest.raises(ValueError, match="not found"):
        C.set_value_after_label(_lstr("X"), "Nope", 1.0, 2.0)


def test_list_value_fields_filters_noise():
    blob = entity(
        value_node("Crit Chance Value", 0.1),
        # a scoped reference and a getter are wiring, not authored data
        lstr("[Value] Foo\\Crit Chance Value") + struct.pack("<f", 0.1),
        lstr("Entity Get Common Object Value") + struct.pack("<f", 5.0),
        # a name with no value node behind it is not a field at all
        lstr("Huge Value") + struct.pack("<f", 99999.0),
    )
    fields = dict(C.list_value_fields(blob))
    assert fields == {"Crit Chance Value": 0.1}


def test_find_and_set_icon_same_length():
    blob = _lstr("Objects\\UI_Object_GreenArmor.png")
    assert C.find_icon(blob) == "Objects\\UI_Object_GreenArmor.png"
    out = C.set_icon(blob, "Objects\\UI_Object_GreenArmer.png")  # same length
    assert C.find_icon(out) == "Objects\\UI_Object_GreenArmer.png"
    assert len(out) == len(blob)


def test_replace_lstr_any_variable_length():
    from rsmm.engine import cooked
    sec = cooked.Section(payload=_lstr("Objects\\UI_Object_GreenArmor.png"))
    cf = cooked.CookedFile(variant="B", hdr_a=1, flags=0, sections=[sec])
    data = cooked.emit(cf)
    out = C.replace_lstr_any(data, "Objects\\UI_Object_GreenArmor.png",
                             "Objects\\UI_Object_X.png")  # shorter
    assert b"GreenArmor" not in out
    re = cooked.parse(out)
    assert _lstr("Objects\\UI_Object_X.png") in re.sections[0].payload


def test_set_icon_no_icon_raises():
    with pytest.raises(ValueError, match="no icon"):
        C.set_icon(_lstr("not an image"), "Objects\\UI_Object_X.png")


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


def test_append_bank_keys_refuses_a_bank_with_no_value_files(tmp_path):
    # The uncooked mirror carries only the keys file. Appending keys with no
    # value file to match crashed the challenge screen on a -1 string pointer.
    from rsmm.engine.text_patches import append_bank_keys
    base = tmp_path / "Bank~GAM.xls.LocalText.gen"
    _write_bank(base, ["A", "B"])
    with pytest.raises(ValueError, match="no language value file"):
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


def test_sdk_custom_png_icon_cooks_texture(tmp_path):
    """A PNG shipped in the mod is cooked into a new oCTexture and the entity
    icon repointed at it."""
    pytest.importorskip("rsmm.sdk.content")
    from rsmm.engine.image import encode_png
    from rsmm.sdk.content import ContentRegistry, SchemaNotMined
    root = tmp_path / "mod"
    root.mkdir()
    (root / "myicon.png").write_bytes(encode_png(4, 4, bytes([0, 0, 200, 255]) * 16))
    cr = ContentRegistry(mod_id="IconMod")
    cr.register("item", id="Custom_Icon_Item", base="Armor_Per_Object",
                icon="myicon.png")
    try:
        written = cr.emit(root / "assets")
    except SchemaNotMined:
        pytest.skip("no game install or mirror to clone the base from")
    tex = [p for p in written if "Texture.dxt" in p.name]
    assert tex, "custom PNG should cook into a Texture.dxt"
    ent = next(p for p in written if "Custom_Icon_Item.entity" in p.name)
    assert C.find_icon(ent.read_bytes()) == "Objects\\UI_Object_Custom_Icon_Item.png"


def _blob_with_identity(guid: bytes, item_id: str) -> bytes:
    # Root node: <16-byte identity GUID><u32 namelen><id>, plus a self-reference
    # to the same GUID elsewhere (must be re-minted consistently), and an
    # unrelated sibling GUID that must be left untouched.
    sibling = bytes(range(0x20, 0x30))
    return (
        b"\x11\x11\xbb\xaa"
        + guid + _lstr(item_id)               # root identity node
        + sibling + _lstr("ChildNode")        # an unrelated node
        + b"REF:" + guid                       # an internal self-reference
        + b"\x22\x22\xbb\xaa"
    )


def test_find_identity_guid():
    guid = bytes(range(0x40, 0x50))
    blob = _blob_with_identity(guid, "Armor_Per_Object")
    assert C.find_identity_guid(blob, "Armor_Per_Object") == guid
    assert C.find_identity_guid(blob, "Nonexistent_Id") is None


def test_remint_identity_only_changes_root_identity():
    guid = bytes(range(0x40, 0x50))
    sibling = bytes(range(0x20, 0x30))
    blob = _blob_with_identity(guid, "Armor_Per_Object")
    out = C.remint_identity_guid(blob, "Armor_Per_Object", salt="Clone0")

    assert len(out) == len(blob)              # length-preserving
    assert guid not in out                    # old identity gone everywhere
    new = C.find_identity_guid(out, "Armor_Per_Object")
    assert new is not None and new != guid    # fresh identity
    assert out.count(new) == blob.count(guid)  # self-ref re-minted too
    assert sibling in out                     # unrelated GUID untouched


def test_remint_identity_deterministic():
    guid = bytes(range(0x40, 0x50))
    blob = _blob_with_identity(guid, "Armor_Per_Object")
    a = C.remint_identity_guid(blob, "Armor_Per_Object", salt="Clone0")
    b = C.remint_identity_guid(blob, "Armor_Per_Object", salt="Clone0")
    c = C.remint_identity_guid(blob, "Armor_Per_Object", salt="Clone1")
    assert a == b and a != c                  # stable per salt, distinct across


def test_remint_identity_noop_when_absent():
    blob = _blob_with_identity(bytes(range(0x40, 0x50)), "Armor_Per_Object")
    # id not present -> unchanged, never raises
    assert C.remint_identity_guid(blob, "Missing_Id", salt="x") == blob


def _text_ref(key: str, row: int) -> bytes:
    return (_lstr("Text") + _lstr("Magical_Objects~GAM.xls") + struct.pack("<I", row)
            + _lstr(key))


def _named_item(item_id: str) -> bytes:
    return (_node(_guid(0xAA), "oCEntitySettingsResource")
            + _node(_guid(0xB4), f"[Value] {item_id}\\X")
            + _node(_guid(0xB5), "Armor per Object Value")
            + struct.pack("<f", 2.0) + b"\x22\x22\xbb\xaa"
            + _text_ref(f"{item_id}_Name", 0) + _text_ref(f"{item_id}_Description", 1))


def _install_bank(tmp_path):
    from rsmm.engine.text_patches import lang_path_for
    base = tmp_path / "Magical_Objects~GAM.xls.LocalText.gen"
    _write_bank(base, ["Base_Item_Idxx_Name", "Base_Item_Idxx_Description"])
    _write_bank(lang_path_for(base, "EN"), ["Old Name", "Old Desc"])
    return base


def test_a_replacement_keeps_the_id_and_rewrites_the_bases_own_text(tmp_path):
    from rsmm.engine.text_patches import parse_text_bytes
    bank = _install_bank(tmp_path)
    ent = _named_item("Base_Item_Idxx")
    files = C.build_magic_item(
        new_id="Base_Item_Idxx", base_id="Base_Item_Idxx", base_cooked=ent, corpus=[],
        rarity="Epic", name="New Name",
        value_patches=[("Armor per Object Value", 2.0, 50.0)],
        bank_base_gen=bank, replace=True)
    out = files["EntitySettings/Objects/Magical_Objects/Epic/"
                "Base_Item_Idxx.entity.ot.EntitySettingsResource.gen"]
    assert out == ent.replace(struct.pack("<f", 2.0), struct.pack("<f", 50.0))
    # No key was added, so the keys file is not rewritten; the value is, in place.
    assert C.MAGIC_TEXT_BANK not in files
    en = parse_text_bytes(files[C.MAGIC_TEXT_BANK + ".LangEN"], bank)
    assert en.entries == ["New Name", "Old Desc"]


def test_a_replacement_refuses_a_new_id():
    with pytest.raises(ValueError, match="keeps the base"):
        C.build_magic_item(new_id="Other_Item_Idx", base_id="Base_Item_Idxx",
                           base_cooked=_named_item("Base_Item_Idxx"), corpus=[],
                           replace=True)


def test_a_second_item_builds_on_the_bank_the_first_wrote(tmp_path):
    # Two named items in one mod each rebuilt the bank from vanilla, so the
    # second one's file dropped the first one's name.
    from rsmm.engine.text_patches import parse_text_bytes
    bank = _install_bank(tmp_path)
    first = C.build_magic_item(
        new_id="Copy_Item_Idxx", base_id="Base_Item_Idxx",
        base_cooked=_named_item("Base_Item_Idxx"), corpus=[], name="Copy",
        bank_base_gen=bank)
    prior = {"__base__": first[C.MAGIC_TEXT_BANK],
             ".LangEN": first[C.MAGIC_TEXT_BANK + ".LangEN"]}
    second = C.build_magic_item(
        new_id="Base_Item_Idxx", base_id="Base_Item_Idxx",
        base_cooked=_named_item("Base_Item_Idxx"), corpus=[], name="Changed",
        bank_base_gen=bank, replace=True, bank_prior=prior)
    keys = parse_text_bytes(second[C.MAGIC_TEXT_BANK], bank)
    en = parse_text_bytes(second[C.MAGIC_TEXT_BANK + ".LangEN"], bank)
    assert keys.entries == ["Base_Item_Idxx_Name", "Base_Item_Idxx_Description",
                            "Copy_Item_Idxx_Name"]
    assert en.entries == ["Changed", "Old Desc", "Copy"]


def test_a_copys_text_rows_point_at_its_appended_keys(tmp_path):
    bank = _install_bank(tmp_path)
    files = C.build_magic_item(
        new_id="Copy_Item_Idxx", base_id="Base_Item_Idxx",
        base_cooked=_named_item("Base_Item_Idxx"), corpus=[], name="Copy",
        bank_base_gen=bank)
    ent = next(v for k, v in files.items() if k.endswith(".gen") and "Entity" in k)
    assert _text_ref("Copy_Item_Idxx_Name", 2) in ent


def test_text_keys_lists_every_key_the_item_reads():
    assert C.text_keys(_named_item("Base_Item_Idxx")) == [
        "Base_Item_Idxx_Name", "Base_Item_Idxx_Description"]


def test_the_bank_merge_keeps_a_row_rewritten_in_place(tmp_path, monkeypatch):
    from rsmm.engine import content_merge
    from rsmm.engine.text_patches import parse_text_file
    monkeypatch.setenv("RSMM_MODS_DIR", str(tmp_path / "mods"))
    vanilla, a, b = (tmp_path / n for n in ("van", "a", "b"))
    _write_bank(vanilla, ["one", "two"])
    _write_bank(a, ["one", "TWO"])                 # a replaced item's name
    _write_bank(b, ["one", "two", "three"])        # a copy's appended name
    out = content_merge._merge_text_bank("x", [a, b], vanilla)
    assert parse_text_file(out).entries == ["one", "TWO", "three"]


def test_find_identity_guid_from_magical_object_component():
    # Shipped items have no node named after their id: the identity is the GUID
    # of the "Dt Magical Object Data" component (the pool def), and before this
    # every shipped item came back None, so `unique_identity` did nothing.
    guid = bytes(range(0x40, 0x50))
    sibling = bytes(range(0x20, 0x30))
    blob = (b"\x11\x11\xbb\xaa" + sibling + _lstr("Child State Equiped")
            + guid + _lstr(C.MO_DATA_NODE) + b"\x22\x22\xbb\xaa")
    assert C.find_identity_guid(blob, "Damage_Attack") == guid
    out = C.remint_identity_guid(blob, "Damage_Attack", salt="Clone0")
    assert len(out) == len(blob) and guid not in out and sibling in out
    assert C.find_identity_guid(out, "Damage_Attack") not in (None, guid)


def test_every_shipped_item_has_one_unique_identity():
    from rsmm.engine import corpus
    rels = [r for r in corpus.rels("EntitySettings/Objects/Magical_Objects")
            if r.endswith(".EntitySettingsResource.gen")]
    node = _lstr(C.MO_DATA_NODE)
    found = {}
    for rel in rels:
        data = corpus.read(rel)
        if data is None or node not in data:
            continue  # templates / power-up models carry no MO component
        item = rel.rsplit("/", 1)[1].split(".")[0]
        g = C.find_identity_guid(data, item)
        assert g is not None, item
        assert data.count(g) == 1, f"{item}: identity occurs {data.count(g)}x"
        found[item] = g
    if not found:
        pytest.skip("no magical-object corpus reachable")
    assert len(set(found.values())) == len(found), "two items share an identity"
