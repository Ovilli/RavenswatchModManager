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
    return _BEGIN + struct.pack("<I", 0x42) + guid + _lstr(label) + _END


def _int_entry(label: str, val: int) -> bytes:
    """A balanced value node: BEGIN + label + int32 just before its END."""
    return _BEGIN + _lstr(label) + struct.pack("<i", val) + _END


def _wrap(payload: bytes) -> bytes:
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef("oCEntitySettingsResource", 0x16f5f7a3, 1, 0, 0)],
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
