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
