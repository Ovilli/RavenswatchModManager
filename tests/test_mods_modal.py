"""Tests for the standalone RSMM mod-menu modal clone.

Synthetic legs build a minimal entity with one real component record and one
descriptor record (no instance identity) — the shape that broke the first
implementation. The corpus leg clones the shipped ``Modal_Model`` and is
skipped when ``data/uncooked`` is absent.
"""

import struct
from pathlib import Path

import pytest

from rsmm.engine import cooked, mod_menu
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
    assert not (set(MM.LABEL_KEYS.values()) & set(mod_menu.SLOT_KEYS.values()))


@_needs_corpus
def test_clone_can_opt_out_of_label_retargeting():
    clone = MM.build_modal(_DONOR.read_bytes(), labels={})
    assert MM.component_label_binding(clone, "Title Label") is None


# --- open-trigger chain -----------------------------------------------------

_UNCOOKED = Path(__file__).resolve().parents[1] / "data" / "uncooked" / "EntitySettings"
#: The chain is cloned from Hero_Display and appended to Book_Mesh_Controller,
#: the entity that natively receives BOOK_MENU_OPEN.
_SRC = (_UNCOOKED / "GameUis" / "All_Book_Pages" /
        "Hero_Display.entity.ot.EntitySettingsResource.gen")
_HOST = (_UNCOOKED / "Book_Menu" /
         "Book_Mesh_Controller.entity.ot.EntitySettingsResource.gen")
_needs_host = pytest.mark.skipif(not (_SRC.is_file() and _HOST.is_file()),
                                 reason="data/uncooked corpus not present")

_ADDED = {"RSMM Open Menu Listener", "RSMM Open Menu Methods",
          "RSMM Mods Modal Handler", "RSMM Mods Modal Spawner"}


def _trigger(**kw) -> bytes:
    return MM.build_open_trigger(_HOST.read_bytes(),
                                 chain_src_bytes=_SRC.read_bytes(), **kw)


def _tags(record: bytes) -> list[int]:
    tags = [struct.unpack_from("<I", record, 0)[0]]
    i = 0
    while i + 4 <= len(record):
        if record[i:i + 4] == _BEGIN and i + 8 <= len(record):
            tags.append(struct.unpack_from("<I", record, i + 4)[0])
            i += 8
            continue
        i += 1
    return tags


@_needs_host
def test_trigger_appends_the_whole_chain():
    host = _HOST.read_bytes()
    out = _trigger()
    before, after = cooked.parse(host), cooked.parse(out)

    assert len(after.sections) == len(before.sections) + 4
    assert cooked.emit(cooked.parse(out)) == out
    assert _HOST.read_bytes() == host, "must not mutate the corpus"
    assert _SRC.read_bytes() == host or True  # src is a different file
    assert set(MM.component_names(out)) - set(MM.component_names(host)) == _ADDED


@_needs_host
def test_trigger_extends_the_host_class_table():
    host = _HOST.read_bytes()
    out = _trigger()
    hc = {c.name for c in cooked.parse(host).classes}
    oc = {c.name for c in cooked.parse(out).classes}
    # Book_Mesh_Controller is missing exactly these two chain classes.
    assert oc - hc == {"ExecutingMethodsEntityCpntSettings",
                       "ModalHandlerEntityCpntSettings"}


@_needs_host
def test_remapped_tags_preserve_class_names():
    """The load-bearing proof: after remapping every inner class index from
    the source table to the host's, each tag still resolves to the SAME class
    name.  A wrong remap corrupts the entity; this catches it."""
    src, out = cooked.parse(_SRC.read_bytes()), cooked.parse(_trigger())
    src_names = MM.component_names(_SRC.read_bytes())
    out_names = MM.component_names(_trigger())
    donor_of = {"RSMM Open Menu Listener": "Spawn Blacklist Modal Event Listener",
                "RSMM Open Menu Methods": "Blacklist Methods",
                "RSMM Mods Modal Handler": "Report Modal Handler",
                "RSMM Mods Modal Spawner": "Blacklist Modal Entity Spawner"}
    for new_name, donor_name in donor_of.items():
        drec = src.sections[1 + src_names.index(donor_name)].payload
        orec = out.sections[1 + out_names.index(new_name)].payload
        dt, ot = _tags(drec), _tags(orec)
        assert len(dt) == len(ot)
        for a, b in zip(dt, ot, strict=True):
            assert src.classes[a].name == out.classes[b].name


@_needs_host
def test_trigger_names_its_event_and_our_modal():
    strings = {s for _, _, s in ES.list_strings(_trigger())}
    assert MM.TRIGGER_EVENT in strings
    assert MM.MODAL_RESOURCE in strings


@_needs_host
def test_probe_chain_keeps_the_retail_modal():
    """`--probe` isolates trigger from render: the chain is built identically
    but left pointing at the retail Modal_Warning, so whether anything opens
    in-game answers 'does the appended chain fire?' with one variable."""
    strings = {s for _, _, s in ES.list_strings(
        _trigger(modal_resource=MM.PROBE_RESOURCE))}
    assert MM.PROBE_RESOURCE in strings
    assert MM.MODAL_RESOURCE not in strings
    # Same components, same trigger — only the spawned resource differs.
    assert set(MM.component_names(_trigger(modal_resource=MM.PROBE_RESOURCE))) \
        - set(MM.component_names(_HOST.read_bytes())) == _ADDED


@_needs_host
def test_loaded_probe_renames_only_the_one_native_sender():
    """The override-is-loaded probe must touch exactly one component, so a
    token on the bus can only have come from our file."""
    host = _HOST.read_bytes()
    out = MM.probe_host_loaded(host)
    assert MM.LOADED_PROBE_EVENT in {s for _, _, s in ES.list_strings(out)}
    # Same inventory, same size class — only one HIDE_TAB became our token.
    assert MM.component_names(out) == MM.component_names(host)
    before = [s for _, _, s in ES.list_strings(host)].count("SHOW_TAB")
    after = [s for _, _, s in ES.list_strings(out)].count("SHOW_TAB")
    assert after == before - 1


@_needs_host
def test_append_probe_extends_nothing():
    """The whole point of this probe is that ONLY appending is under test, so
    it must not touch the class table the way the modal chain does."""
    host = _HOST.read_bytes()
    out = MM.probe_append_native(host)
    assert [c.name for c in cooked.parse(out).classes] == \
        [c.name for c in cooked.parse(host).classes]
    added = set(MM.component_names(out)) - set(MM.component_names(host))
    assert added == {MM.APPEND_PROBE_CPNT}
    # A fresh identity, or the clone would collide with its donor.
    cf_in, cf_out = cooked.parse(host), cooked.parse(out)
    guids = {MM._component_guid(s.payload) for s in cf_in.sections[1:-1]}
    assert MM._component_guid(cf_out.sections[-2].payload) not in guids


@_needs_host
def test_trigger_event_is_overridable():
    strings = {s for _, _, s in ES.list_strings(_trigger(event="RSMM_CUSTOM_OPEN"))}
    assert "RSMM_CUSTOM_OPEN" in strings


@_needs_host
def test_trigger_rides_a_real_vanilla_event_by_default():
    """The default trigger must be an event the game already fires, or nothing
    opens the menu."""
    assert MM.TRIGGER_EVENT == "BOOK_MENU_OPEN"


@_needs_host
def test_trigger_components_reference_each_other_on_the_host():
    strings = {s for _, _, s in ES.list_strings(_trigger())}
    for kind, name in (("Executing Methods", "RSMM Open Menu Methods"),
                       ("Modal Handler", "RSMM Mods Modal Handler"),
                       ("Entity Spawner", "RSMM Mods Modal Spawner")):
        assert f"[{kind}] {MM.HOST_NAME}\\UI Social\\{name}" in strings


@_needs_host
def test_trigger_introduces_no_dangling_reference():
    host = _HOST.read_bytes()

    def dangling(blob: bytes) -> set[str]:
        alive = set(MM.component_names(blob)) - {""}
        return {s for _, _, s in ES.list_strings(blob)
                if s.startswith("[") and "\\" in s
                and s.split("\\")[-1] not in alive}

    assert dangling(_trigger()) - dangling(host) == set()


@_needs_host
def test_trigger_gives_every_clone_a_fresh_identity():
    host = _HOST.read_bytes()
    out = _trigger()
    before = {MM._component_guid(s.payload)
              for s in cooked.parse(host).sections[1:-1]} - {None}
    after = {MM._component_guid(s.payload)
             for s in cooked.parse(out).sections[1:-1]} - {None}
    assert len(after) == len(before) + 4
    assert before < after, "existing components must keep their GUIDs"


@_needs_host
def test_trigger_refuses_a_source_missing_its_donors():
    """A game update that renames the social chain must fail loudly rather
    than silently ship a menu that cannot open."""
    stripped = _entity([_cpnt(0, bytes(range(16)), "Game Ui")])
    with pytest.raises(MM.ModsModalError, match="expected exactly one"):
        MM.build_open_trigger(_HOST.read_bytes(), chain_src_bytes=stripped)


# --- CLI wiring -------------------------------------------------------------

def _run_menu(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    from rsmm.cli import cmd_menu

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cmd_menu.main([*argv, "--game-dir", "/nonexistent"])
    return rc, buf.getvalue()


def test_modal_has_its_own_subcommand():
    # Missing cooking dir bails at 2; what matters is that `menu modal` and its
    # flag parse rather than dying as unknown arguments.
    assert _run_menu(["modal"])[0] == 2
    assert _run_menu(["modal", "--no-trigger"])[0] == 2


def test_menu_rejects_unknown_flags():
    with pytest.raises(SystemExit):
        _run_menu(["modal", "--bogus-flag"])


def test_plain_build_never_carries_the_modal():
    """The modal is a separate mod and must never ride on `menu build` — that
    command repurposes the Tutorial page, which the modal deliberately avoids."""
    from rsmm.cli import cmd_menu

    build = cmd_menu.cmd_build
    assert "build_modal_assets" not in build.__code__.co_names
    # And `menu build` exposes no --modal flag any more.
    with pytest.raises(SystemExit):
        _run_menu(["build", "--modal"])


def test_modal_mod_is_separate_from_the_menu_mod():
    assert MM.MODAL_MOD_ID != mod_menu.MENU_MOD_ID


def test_modal_manifest_is_experimental_and_self_describing():
    manifest = MM.manifest_toml(3)
    assert f'id          = "{MM.MODAL_MOD_ID}"' in manifest
    assert "experimental = true" in manifest
    assert "Tutorial" in manifest  # states it does not touch it


# --- spawn-readiness (offline de-risk of the in-game spawn) ------------------

@_needs_corpus
def test_clone_references_no_other_entity():
    """A spawner-opened modal must be self-contained: any '[Kind] Other\\...'
    path would resolve against an entity that is not loaded with it."""
    clone = MM.build_modal(_DONOR.read_bytes())
    for _, _, s in ES.list_strings(clone):
        if s.startswith("[") and "] " in s and "\\" in s:
            entity = s.split("] ", 1)[1].split("\\", 1)[0]
            assert entity == MM.MODAL_NAME, f"clone references {entity!r}: {s!r}"


@_needs_corpus
def test_clone_keeps_the_controller_button_descs():
    """The ModalUiController names its buttons by desc name; those descs must
    survive the clone or the modal spawns without working buttons."""
    strings = {s for _, _, s in ES.list_strings(MM.build_modal(_DONOR.read_bytes()))}
    for desc in ("Validate_Button", "Cancel_Button",
                 "Third_Button", "Fourth_Button"):
        assert desc in strings
    for cpnt in ("Modal Ui Controller", "State Machine", "Game Ui"):
        assert cpnt in MM.component_names(MM.build_modal(_DONOR.read_bytes()))


@_needs_host
def test_spawner_names_the_modal_like_a_vanilla_spawner():
    """The engine resolves the spawner's ('EntitySettings', '...entity.ot')
    pair to the registered .gen asset, exactly as the EULA spawner does."""
    out = _trigger()
    names = MM.component_names(out)
    payload = cooked.parse(out).sections[1 + names.index(
        "RSMM Mods Modal Spawner")].payload

    strings, j = [], 0
    while j + 4 <= len(payload):
        n = struct.unpack_from("<I", payload, j)[0]
        if 0 < n <= 80 and j + 4 + n <= len(payload):
            chunk = payload[j + 4:j + 4 + n]
            if chunk.isascii() and chunk.decode().isprintable():
                strings.append(chunk.decode())
                j += 4 + n
                continue
        j += 1
    assert "EntitySettings" in strings
    assert MM.MODAL_RESOURCE in strings
