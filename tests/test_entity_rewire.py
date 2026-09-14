"""Tests for the entity GUID-rewire + selector int32 edits (the "modified
Horde" / talent-logic-rewire capability) and the declarative ``talent`` kind
fields (``rewires`` / ``int_patches``) that drive them.

Synthetic legs build a minimal valid cooked container; the corpus leg runs the
full declarative emit against the shipped vanilla Piper entity (skipped when
``data/uncooked`` is absent).
"""

import struct
from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine.entity_edit import EntityEdit

_BEGIN = b"\x11\x11\xbb\xaa"
_END = b"\x22\x22\xbb\xaa"


def _lstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _picker(guid: bytes, label: str) -> bytes:
    """A class-66 oCEntityCpntPicker reference: BEGIN + classid 66 + 16B GUID
    + a [State] path lstring (the GUID sits 16 bytes before its label). The
    cooked container is depth-balanced, so the record is bracketed BEGIN..END."""
    return _BEGIN + struct.pack("<I", _PICKER_IDX) + guid + _lstr(label) + _END


def _int_entry(label: str, val: int) -> bytes:
    """A balanced value node: BEGIN + label + int32 just before its END."""
    return _BEGIN + _lstr(label) + struct.pack("<i", val) + _END


#: Class-table index the fixtures place ``oCEntityCpntPicker`` at. The u32 after
#: a BEGIN marker indexes the FILE'S OWN class table, so this is a per-file
#: value, not a constant: it is 0x42 in Red and Piper but 0x40 in Snow Queen.
#: The table below has to actually contain the class or `rewire_ref` cannot
#: check what it is rewriting.
_PICKER_IDX = 0x42


def _classes(picker_idx: int = _PICKER_IDX) -> list[cooked.ClassDef]:
    names = [f"oCFiller{i:03d}" for i in range(picker_idx + 1)]
    names[0] = "oCEntitySettingsResource"
    names[picker_idx] = "oCEntityCpntPicker"
    return [cooked.ClassDef(n, 0x1000 + i, 1, 0, 0) for i, n in enumerate(names)]


def _wrap(payload: bytes, *, picker_idx: int = _PICKER_IDX) -> bytes:
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=_classes(picker_idx),
        sections=[cooked.Section(payload=payload)],
    )
    return cooked.emit(cf)


def test_rewire_ref_repoints_picker_by_name():
    src = bytes(range(0x10, 0x20))           # the desired target node's GUID
    dst = bytes(range(0xA0, 0xB0))           # the trigger picker's current GUID
    payload = (
        _picker(dst, "[State] Hero\\Skill\\Trigger Proc")
        + _picker(src, "[State] Hero\\Trait\\Target State")
    )
    ed = EntityEdit(_wrap(payload))
    ed.rewire_ref("Trigger Proc", "Target State")
    out = EntityEdit(ed.emit())
    # the trigger picker now carries the target node's GUID
    o = [off for off, t in out.find_lstrings_containing("Trigger Proc")
         if t.startswith("[")][0] - 16
    assert out.concat[o:o + 16] == src


def test_rewire_ref_rejects_non_picker_classid():
    # a record whose classid is not 66 must be refused (guards a wrong match)
    bad = _BEGIN + struct.pack("<I", 0x09) + bytes(16) \
        + _lstr("[State] a\\b\\Trigger Proc") + _END
    good = _picker(bytes(range(16)), "[State] a\\b\\Target State")
    ed = EntityEdit(_wrap(bad + good))
    with pytest.raises(ValueError, match="classid"):
        ed.rewire_ref("Trigger Proc", "Target State")


def test_set_int_before_nth_end_targets_the_right_entry():
    # one labelled tier then three more — four successive value ENDs
    payload = (_int_entry("Selector", 7) + _int_entry("t1", 6)
               + _int_entry("t2", 5) + _int_entry("t3", 4))
    ed = EntityEdit(_wrap(payload))
    off = ed.set_int_before_nth_end("Selector", 2, 15, expect=5)
    out = EntityEdit(ed.emit()).concat
    # only END #2's int changed
    assert struct.unpack_from("<i", out, off)[0] == 15
    base = out.find(_lstr("Selector")) + len(_lstr("Selector"))
    vals, o = [], base
    for _ in range(4):
        e = out.find(_END, o)
        vals.append(struct.unpack_from("<i", out, e - 4)[0])
        o = e + 4
    assert vals == [7, 6, 15, 4]


def test_set_int_expect_mismatch_raises():
    payload = _int_entry("N", 3)
    ed = EntityEdit(_wrap(payload))
    with pytest.raises(ValueError, match="expected int"):
        ed.set_int_before_nth_end("N", 0, 10, expect=99)


# --- corpus leg: the real "modified Horde" emit -----------------------------

_PIPER = (Path(__file__).resolve().parents[1] / "data" / "uncooked"
          / "EntitySettings" / "Heroes" / "Hero_Piper"
          / "Hero_Piper.entity.ot.EntitySettingsResource.gen")


def _nth_int(concat: bytes, label: str, idx: int) -> int:
    pat = _lstr(label)
    o = concat.find(pat) + len(pat)
    end = -1
    for _ in range(idx + 1):
        end = concat.find(_END, o)
        o = end + 4
    return struct.unpack_from("<i", concat, end - 4)[0]


def test_piper_ghost_horde_emit_round_trips():
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    raw = _PIPER.read_bytes()
    defn = ContentDef(kind="talent", id="piper_ghost_horde", fields={
        "hero": "Piper",
        "file": "Hero_Piper.entity",
        "rewires": [{"trigger": "Event Skill Attack Ghost Notes Proc",
                     "action": "Event Trait Ability Spawn Pets"}],
        "int_patches": [
            {"label": "Skill Attack Ghost Notes Counter", "end_index": 5,
             "old": 3, "new": 10},
            {"label": "Skill Defense Spawn Pets Max Count Selector",
             "end_index": 3, "old": 7, "new": 15},
            {"label": "Skill Defense Spawn Pets Max Count Selector",
             "end_index": 9, "old": 6, "new": 15},
            {"label": "Skill Defense Spawn Pets Max Count Selector",
             "end_index": 15, "old": 5, "new": 15},
            {"label": "Skill Defense Spawn Pets Max Count Selector",
             "end_index": 20, "old": 4, "new": 15},
        ],
    })

    out_dir = Path(pytest.importorskip("tempfile").mkdtemp())
    written = talents.emit("PiperGhostHorde", defn, out_dir)
    assert len(written) == 1
    patched = written[0].read_bytes()
    # length-preserving (GUID swap + int writes only)
    assert len(patched) == len(raw)

    out = EntityEdit(patched)
    guid_off = [o for o, t in out.find_lstrings_containing(
        "Event Skill Attack Ghost Notes Proc") if t.startswith("[")][0] - 16
    assert out.concat[guid_off:guid_off + 16].hex() == \
        "db41bfd8eb24854988cee729faf22097"
    assert _nth_int(out.concat, "Skill Attack Ghost Notes Counter", 5) == 10
    assert [_nth_int(out.concat, "Skill Defense Spawn Pets Max Count Selector", i)
            for i in (3, 9, 15, 20)] == [15, 15, 15, 15]


def test_picker_classid_comes_from_the_files_own_class_table():
    """`oCEntityCpntPicker` sits at a different index in every file, so the
    class has to be resolved by NAME. Hardcoding one file's index refused a
    perfectly good rewire on any hero that laid its table out differently."""
    src = bytes(range(0x10, 0x20))
    dst = bytes(range(0xA0, 0xB0))
    payload = (_picker(dst, "[State] a\\b\\Trigger Proc")
               + _picker(src, "[State] a\\b\\Target State"))
    for idx in (0x40, 0x42):
        blob = _wrap(payload.replace(struct.pack("<I", _PICKER_IDX),
                                     struct.pack("<I", idx)), picker_idx=idx)
        ed = EntityEdit(blob)
        assert ed._picker_classid() == idx
        assert ed.rewire_ref("Trigger Proc", "Target State") == 1


def test_rewire_ref_can_move_every_matching_reference():
    """A tier-gated selector carries one condition reference per rarity, so
    moving only the first leaves the rest reading the dead node."""
    src = bytes(range(0x10, 0x20))
    dst = bytes(range(0xA0, 0xB0))
    payload = (_picker(dst, "[Dt Skill Controller] a\\Trigger Proc")
               + _picker(dst, "[Dt Skill Controller] a\\Trigger Proc")
               + _picker(dst, "[Dt Skill Controller] a\\Trigger Proc")
               + _picker(src, "[Dt Skill Controller] a\\Target State"))
    ed = EntityEdit(_wrap(payload))
    assert ed.rewire_ref("Trigger Proc", "Target State", count=None) == 3
    out = EntityEdit(ed.emit())
    assert out.concat.count(src) == 4      # three moved + the target itself
    assert out.concat.count(dst) == 0

    # the default still moves exactly one
    ed2 = EntityEdit(_wrap(payload))
    assert ed2.rewire_ref("Trigger Proc", "Target State") == 1
    assert EntityEdit(ed2.emit()).concat.count(dst) == 2


def test_exact_within_rewire_hits_the_controllers_own_reference():
    """A plain substring rewire picks the first label CONTAINING the text.

    Measured on Red: repointing Short Wick's controller state
    `[State] ...Skill Secondary Quick Bombs` hit
    `[Modifier] ...Skill Secondary Quick Bombs CD Reduction Modifier` instead,
    which comes earlier in the file, and left the controller untouched.
    `exact` + `within` must reach only the controller's own reference.
    """
    modifier = bytes(range(0x30, 0x40))
    own = bytes(range(0x50, 0x60))
    elsewhere = bytes(range(0x70, 0x80))
    target = bytes(range(0x90, 0xA0))
    state = "[State] a\\Quick Bombs\\Quick Bombs"
    payload = (_picker(modifier, "[Modifier] a\\Quick Bombs\\Quick Bombs CD Modifier")
               + _BEGIN + _lstr("Skill Controller Quick Bombs") + _END
               + _picker(own, state)
               + _BEGIN + _lstr("filler") + b"\x00" * 64 + _END
               + _picker(elsewhere, state)
               + _picker(target, "[State] a\\Finisher\\Finisher"))

    # the hazard, pinned: a loose rewire goes to the modifier
    loose = EntityEdit(_wrap(payload))
    loose.rewire_ref("Quick Bombs\\Quick Bombs", "Finisher\\Finisher")
    out = EntityEdit(loose.emit()).concat
    assert out.count(modifier) == 0 and out.count(own) == 1

    # the fix: exact + scoped reaches the controller's reference and only it
    ed = EntityEdit(_wrap(payload))
    n = ed.rewire_ref(state, "[State] a\\Finisher\\Finisher", exact=True,
                      within="Skill Controller Quick Bombs", within_span=80)
    out = EntityEdit(ed.emit()).concat
    assert n == 1
    assert out.count(own) == 0          # the controller's reference moved
    assert out.count(modifier) == 1     # the modifier was left alone
    assert out.count(elsewhere) == 1    # the same label outside the node too
    assert out.count(target) == 2


def test_within_scope_that_does_not_exist_is_an_error():
    payload = (_picker(bytes(16), "[State] a\\b")
               + _picker(bytes(range(16)), "[State] c\\d"))
    ed = EntityEdit(_wrap(payload))
    with pytest.raises(ValueError, match="scope"):
        ed.rewire_ref("[State] a\\b", "[State] c\\d", within="No Such Node")


_WUKONG = (Path(__file__).resolve().parent.parent / "data" / "uncooked" / "EntitySettings"
           / "Heroes" / "Hero_SunWukong" / "Hero_SunWukong.entity.ot.EntitySettingsResource.gen")


def _wukong_clone_emit(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    finisher = "[Anim Clip] Hero_SunWukong\\Skill Attack Finisher\\Skill Attack Finisher Clip"
    clip4 = "[Anim Clip] Hero_SunWukong\\Ability Basic\\Basic Attack Clip 4"
    defn = ContentDef(kind="talent", id="twirl_finisher", fields={
        "hero": "SunWukong",
        "file": "Hero_SunWukong.entity",
        "clone_nodes": [{
            "source": "Basic Attack Combo Selector",
            "name": "Skill Dash Attack Finisher Clip Selector",
            "retarget": [
                {"from": "[Dt Attack Combo] Hero_SunWukong\\Skill Attack Finisher"
                         "\\Skill Attack Finisher Combo", "to": finisher},
                {"from": "[Dt Attack Combo] Hero_SunWukong\\Ability Basic"
                         "\\Basic Attack Combo", "to": clip4},
            ],
        }],
        "rewires": [{
            "trigger": "[Anim Clip] Hero_SunWukong\\Skill Dash Attack\\Skill Dash Attack Clip",
            "action": "Skill Dash Attack Finisher Clip Selector",
            "exact": True, "within": "Basic Attack Clip Selector Step 1",
            "within_span": 600,
        }],
    })
    return talents.emit("wukong-twirl-finisher", defn, tmp_path)[0].read_bytes()


def test_clone_node_is_attached_retargeted_and_wired(tmp_path):
    """A cloned selector must land in the component VECTOR (not as an orphan),
    carry the retargeted GUIDs, and be what the rewired reference now names."""
    if not _WUKONG.is_file():
        pytest.skip("vanilla Hero_SunWukong entity corpus file not present")
    from rsmm.engine import entity_append as EA

    raw = _WUKONG.read_bytes()
    out = _wukong_clone_emit(tmp_path)
    before, after = cooked.parse(raw), cooked.parse(out)

    n = EA.validate_layout(before)
    assert EA.validate_layout(after) == n + 1
    _o, ids = EA.component_vector(after.sections[-1].payload)
    assert ids[-1] == n

    name = "Skill Dash Attack Finisher Clip Selector"
    clone = after.sections[EA.node_section(after, name)].payload
    for target in ("Skill Attack Finisher Clip", "Basic Attack Clip 4",
                   "Skill Attack Finisher"):           # the Pillar-owned condition
        assert EA.node_guid(after, target) in clone
    for gone in ("Skill Attack Finisher Combo", "Basic Attack Combo"):
        assert EA.node_guid(after, gone) not in clone

    step1 = after.sections[EA.node_section(after, "Basic Attack Clip Selector Step 1")].payload
    assert EA.node_guid(after, name) in step1
    assert EA.node_guid(after, "Skill Dash Attack Clip") not in step1

    # Deterministic identity: re-emitting a mod must not churn its bytes.
    assert _wukong_clone_emit(tmp_path / "again") == out


def test_clone_node_refuses_a_name_that_already_exists():
    if not _WUKONG.is_file():
        pytest.skip("vanilla Hero_SunWukong entity corpus file not present")
    from rsmm.engine import entity_append as EA

    with pytest.raises(EA.EntityAppendError, match="already exists"):
        EA.clone_component(_WUKONG.read_bytes(), "Basic Attack Combo Selector",
                           "Basic Attack Clip Selector Step 1")


_GN_STATE = "[State] Hero_Piper\\Skill Attack Ghost Notes\\Skill Attack Ghost Notes"
_CAN_FIGHT = "[State] Character_Common\\Base\\Child State Can Fight"


def test_subtest_of_moves_only_the_testers_condition():
    """The Ghost Notes state label sits on its CONTROLLER first and on the
    notify tester's sub-test second. `subtest_of` must move the second and
    leave the talent controller alone."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    ed = EntityEdit(_PIPER.read_bytes())
    gn = ed._node_guid("Skill Attack Ghost Notes")
    assert ed.rewire_ref(_GN_STATE, _CAN_FIGHT, exact=True,
                         subtest_of="Skill Attack Ghost Notes Notify Tester") == 1
    out = EntityEdit(ed.emit())
    refs = [o - 16 for o in out.find_lstrings(_GN_STATE)]
    assert [out.concat[o:o + 16] == gn for o in refs] == [True, False]


def test_subtest_of_refuses_a_node_without_a_combiner():
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    ed = EntityEdit(_PIPER.read_bytes())
    with pytest.raises(ValueError, match="has no combiner"):
        ed.rewire_ref(_GN_STATE, _CAN_FIGHT, exact=True,
                      subtest_of="Skill Attack Ghost Notes Counter")


def test_clone_retarget_moves_every_tier_reference():
    """A per-rarity selector names its controller once per tier; a retarget
    that moved only the first would leave two tiers keyed to the old talent."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.engine import entity_append as EA

    ctrl = "[Dt Skill Controller] Hero_Piper\\Skills\\Skill Controller "
    out = EA.clone_component(
        _PIPER.read_bytes(), "Skill Attack Ghost Notes Requirement Selector",
        "Horde Attacks Required Selector",
        [(ctrl + "Attack Ghost Notes", ctrl + "Trait More Controllable Pets")])
    cf = cooked.parse(out)
    clone = cf.sections[EA.node_section(cf, "Horde Attacks Required Selector")].payload
    assert clone.count(EA.node_guid(cf, "Skill Controller Trait More Controllable Pets")) == 3
    assert EA.node_guid(cf, "Skill Controller Attack Ghost Notes") not in clone


def test_clone_rename_gives_a_counter_its_own_event_name():
    """A counter listens by event NAME, so a copy that kept its source's name
    would count the source's events too. `rename` must replace the names in the
    copy and leave the source counter untouched."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.engine import entity_append as EA

    def lstr(s: str) -> bytes:
        return struct.pack("<I", len(s)) + s.encode()

    out = EA.clone_component(
        _PIPER.read_bytes(), "Skill Attack Ghost Notes Counter", "Horde Attacks Counter",
        rename=[("SKILL_ATTACK_GHOST_NOTES_COUNTER_INC", "HORDE_ATTACKS_COUNTER_INC")])
    cf = cooked.parse(out)
    clone = cf.sections[EA.node_section(cf, "Horde Attacks Counter")].payload
    source = cf.sections[EA.node_section(cf, "Skill Attack Ghost Notes Counter")].payload
    assert lstr("HORDE_ATTACKS_COUNTER_INC") in clone
    assert lstr("SKILL_ATTACK_GHOST_NOTES_COUNTER_INC") not in clone
    assert lstr("SKILL_ATTACK_GHOST_NOTES_COUNTER_INC") in source


def _accessor_after(payload: bytes, label: str) -> tuple[str, int]:
    """(accessor hex, union type) following the picker labelled ``label``."""
    lab = struct.pack("<I", len(label)) + label.encode()
    end = payload.index(lab) + len(lab)
    assert payload[end:end + 4] == _END
    return payload[end + 4:end + 8].hex(), struct.unpack_from("<I", payload, end + 16)[0]


def test_clone_retarget_switches_the_accessor_across_classes():
    """A value picker reads its target through an accessor tied to the target's
    class and type. Repointing a Value Operation reference at a Value Selector
    while keeping the operation accessor made the game read garbage — a cloned
    count switch spawned ~22 rats at once. The accessor must follow the target;
    a same-class retarget (per-tier skill-controller checks) must keep its own."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.engine import entity_append as EA

    op = ("[Value Operation] Hero_Piper\\Skill Trait More Controllable Pets"
          "\\Skill Trait More Controllable Pets Count Operation")
    sel = ("[Value Selector] Hero_Piper\\Skill Defense Spawn Pets"
           "\\Skill Defense Spawn Pets Max Count Selector")
    raw = _PIPER.read_bytes()
    src = cooked.parse(raw)
    switch = "Trait Ability Max Controllable Pets Selector"
    before = src.sections[EA.node_section(src, switch)].payload
    assert _accessor_after(before, op) == ("8686d20f", 1)       # value operation, int

    out = EA.clone_component(raw, switch, "Count Switch", [(op, sel)])
    cf = cooked.parse(out)
    clone = cf.sections[EA.node_section(cf, "Count Switch")].payload
    assert _accessor_after(clone, sel) == ("65c9d20f", 1)       # value selector, int

    ctrl = "[Dt Skill Controller] Hero_Piper\\Skills\\Skill Controller "
    out = EA.clone_component(raw, "Skill Attack Ghost Notes Requirement Selector",
                             "Tier Copy", [(ctrl + "Attack Ghost Notes",
                                            ctrl + "Trait More Controllable Pets")])
    cf = cooked.parse(out)
    clone = cf.sections[EA.node_section(cf, "Tier Copy")].payload
    lab = struct.pack("<I", len(ctrl) + len("Trait More Controllable Pets")) + (
        ctrl + "Trait More Controllable Pets").encode()
    accs, i = [], clone.find(lab)
    while i != -1:
        end = i + len(lab)
        accs.append(clone[end + 4:end + 8].hex())
        i = clone.find(lab, end)
    assert accs == ["f96bfc15", "f16bfc15", "f76bfc15"]         # one per tier, kept


def test_clone_retarget_gives_a_card_slot_the_format_of_its_new_value():
    """A talent-card slot prints through its own format type (0 decimal, 1
    integer). Sound Barrier's decimal slots, repointed at Horde's integer
    values, printed "For every 6.7263e-44 notes". The slot must take the new
    value's type; the display option comes from a shipped slot showing the
    same value when one exists."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.engine import entity_append as EA

    armor = "Hero_Piper\\Skill Defensive Armor Quest\\Skill Defensive Armor Quest "
    horde = "[Value Selector] Hero_Piper\\Skill Trait More Controllable Pets\\"
    out = EA.clone_component(
        _PIPER.read_bytes(), "Skill String Desc Defensive Armor Quest", "Card Copy",
        [("[Value] " + armor + "Armor Per Proc",                      # decimal slot
          horde + "Skill Trait More Controllable Pets Per Spawn Amount Selector"),
         ("[Value] " + armor + "Complete Shield Duration",            # decimal slot
          horde + "Skill Trait More Controllable Pets Amount Selector")])
    cf = cooked.parse(out)
    acc = EA._Accessors(cf)
    card = cf.sections[EA.node_section(cf, "Card Copy")].payload
    pat = cooked.MARK_BEGIN + struct.pack("<I", acc.picker)
    slots, i = [], card.find(pat)
    while i != -1:
        entry = EA.format_slot_at(card, i, acc)
        if entry is not None:
            n = struct.unpack_from("<I", card, i + 24)[0]
            off = EA._accessor_off(card, i + 28 + n, acc.union)
            slots.append((struct.unpack_from("<I", card, entry + 8)[0],
                          struct.unpack_from("<I", card, off + 32)[0]))
        i = card.find(pat, i + 1)
    # slots 1 and 4 now read Horde's integers: integer format, and the display
    # option Horde's own card uses for those two values (1 and 0)
    assert slots[1] == (1, 1)
    assert slots[4] == (1, 0)
    assert slots[0][0] == 1 and slots[3][0] == 0     # untouched slots keep theirs


_BEOWULF = (Path(__file__).resolve().parents[1] / "data" / "uncooked" / "EntitySettings"
            / "Heroes" / "Hero_Beowulf" / "Hero_Beowulf.entity.ot.EntitySettingsResource.gen")


def _owned_refs(cf, node):
    from rsmm.engine import entity_append as EA
    names = [c.name for c in cf.classes]
    count, _ = EA._directory(cf)
    _o, vector = EA.component_vector(cf.sections[-1].payload)
    payload = cf.sections[EA.node_section(cf, node)].payload
    return [struct.unpack_from("<I", payload, o)[0]
            for o in EA._carrier_refs(payload, names, set(range(count)) - set(vector))]


def test_clone_gives_the_copy_its_own_subobjects():
    """No shipped file points two references at one sub-object (0 of 529), so
    a copied event sender must own a fresh copy of its collector — appended as
    a sub-object, not as a component of the entity."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.engine import entity_append as EA

    out = EA.clone_component(_PIPER.read_bytes(),
                             "SKILL_ATTACK_GHOST_NOTES_COUNTER_INC Event Sender", "Copy Sender")
    cf = cooked.parse(out)
    src = _owned_refs(cf, "SKILL_ATTACK_GHOST_NOTES_COUNTER_INC Event Sender")
    copy = _owned_refs(cf, "Copy Sender")
    assert len(src) == len(copy) == 1 and src != copy
    assert cf.sections[1 + src[0]].payload == cf.sections[1 + copy[0]].payload
    _o, vector = EA.component_vector(cf.sections[-1].payload)
    assert copy[0] not in vector
    assert EA.node_section(cf, "Copy Sender") - 1 in vector


def test_clone_can_give_a_modifier_another_heroes_stat():
    """Stats are a shared enum (TRAIT cooldown is 8a5db415 on Beowulf and
    Geppetto), so a copied Wukong modifier can take Beowulf's."""
    if not (_WUKONG.is_file() and _BEOWULF.is_file()):
        pytest.skip("vanilla hero entity corpus files not present")
    from rsmm.engine import entity_append as EA

    stat = EA.modifier_stat(_BEOWULF.read_bytes(),
                            "Skill Trait Quest Complete CD Reduction Modifier")
    assert stat.hex() == "8a5db415"
    raw = _WUKONG.read_bytes()
    out = EA.clone_component(raw, "Skill Power Hold AP Modifier", "CD Copy", stat=stat)
    assert EA.modifier_stat(out, "CD Copy") == stat
    assert EA.modifier_stat(out, "Skill Power Hold AP Modifier") == \
        EA.modifier_stat(raw, "Skill Power Hold AP Modifier")
    with pytest.raises(EA.EntityAppendError, match="not a modifier"):
        EA.clone_component(raw, "Skill Power Hold", "Not A Modifier", stat=stat)


def test_two_talent_blocks_on_one_entity_stack(tmp_path):
    """Each block used to rebuild the entity from vanilla, so the second one in
    a mod silently erased the first. The second must build on the first."""
    if not _PIPER.is_file():
        pytest.skip("vanilla Hero_Piper entity corpus file not present")
    from rsmm.engine import entity_append as EA
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import talents

    def emit(cid, clone_name):
        defn = ContentDef(kind="talent", id=cid, fields={
            "hero": "Piper", "file": "Hero_Piper.entity",
            "clone_nodes": [{"source": "Skill Attack Ghost Notes", "name": clone_name}],
        })
        return talents.emit("stack-test", defn, tmp_path)[0]

    emit("first", "First Copy")
    path = emit("second", "Second Copy")
    cf = cooked.parse(path.read_bytes())
    assert EA.node_section(cf, "First Copy") and EA.node_section(cf, "Second Copy")
