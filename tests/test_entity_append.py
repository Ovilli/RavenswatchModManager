"""Unit tests for additive component append on cooked entity files.

`entity_append` is the entity-file analog of the versiondef MO-vector append
used for custom items; it had no direct coverage. These tests synthesize cooked
entities in-memory (no game assets) and exercise the directory/record grammar.

Note on fixtures: the cooked container splits sections on the ``MARK_END``
marker, so records fed through ``append_components`` (which re-parses bytes) use
marker-free payloads. The read-only helpers take an already-parsed
``CookedFile``, so those tests build one directly and skip the emit/parse trip.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import cooked
from rsmm.engine import entity_append as EA


def _lstr(s: str) -> bytes:
    b = s.encode("ascii")
    return struct.pack("<I", len(b)) + b


def _rec(cls: int, tag: str) -> bytes:
    """Marker-free component record (safe through cooked.parse)."""
    return struct.pack("<I", cls) + _lstr(tag) + b"\xde\xad\xbe\xef"


def _cf(records: list[bytes], n_classes: int = 3) -> cooked.CookedFile:
    """A CookedFile: directory + one section per record + a trailer."""
    idxs = [struct.unpack_from("<I", r, 0)[0] for r in records]
    directory = struct.pack("<I", len(idxs)) + struct.pack(f"<{len(idxs)}I", *idxs)
    sections = [cooked.Section(payload=directory)]
    sections += [cooked.Section(payload=r) for r in records]
    sections.append(cooked.Section(payload=b"TRLR"))
    return cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef(f"Class{i}", 0x1000 + i, 1, 0, 0)
                 for i in range(n_classes)],
        sections=sections,
    )


def test_validate_layout_accepts_wellformed_entity():
    cf = _cf([_rec(0, "Alpha"), _rec(1, "Beta")])
    assert EA.validate_layout(cf) == 2


def test_validate_layout_rejects_directory_record_mismatch():
    cf = _cf([_rec(0, "Alpha"), _rec(1, "Beta")])
    # Corrupt record 2 so its self-reported class disagrees with the directory.
    cf.sections[2].payload = struct.pack("<I", 2) + _lstr("Beta") + b"\xde\xad\xbe\xef"
    with pytest.raises(EA.EntityAppendError):
        EA.validate_layout(cf)


def test_append_components_grows_directory_and_stays_valid():
    raw = cooked.emit(_cf([_rec(0, "Alpha"), _rec(1, "Beta")]))
    out = EA.append_components(raw, [_rec(2, "Gamma")])
    cf = cooked.parse(out)
    count, idxs = EA._directory(cf)
    assert count == 3
    assert idxs == [0, 1, 2]
    assert EA.validate_layout(cf) == 3
    assert b"Gamma" in cf.sections[3].payload   # new record survived the roundtrip


def test_append_components_rejects_out_of_range_class():
    raw = cooked.emit(_cf([_rec(0, "Alpha")]))
    with pytest.raises(EA.EntityAppendError):
        EA.append_components(raw, [_rec(99, "Nope")])


def test_find_component_locates_unique_record():
    cf = _cf([_rec(0, "Alpha"), _rec(1, "Beta")])
    assert EA.find_component(cf, b"Beta") == 2
    with pytest.raises(EA.EntityAppendError):
        EA.find_component(cf, b"Missing")


def test_replace_blob_strings_swaps_whole_string():
    rec = _rec(0, "OldName")
    out = EA.replace_blob_strings(rec, {"OldName": "NewName"})
    assert _lstr("NewName") in out
    assert _lstr("OldName") not in out


def test_replace_blob_strings_rejects_absent_string():
    rec = _rec(0, "OldName")
    with pytest.raises(EA.EntityAppendError):
        EA.replace_blob_strings(rec, {"Absent": "X"})


def test_remint_guid_changes_identity_only():
    # remint operates on raw bytes and keys off the first inner END marker,
    # so this record intentionally carries one followed by a 16-byte GUID.
    rec = (struct.pack("<I", 0) + _lstr("Alpha") + cooked.MARK_END
           + b"\x11" * 16 + b"\x00\x00\x00\x00")
    out = EA.remint_guid(rec)
    assert len(out) == len(rec)
    pos = rec.find(cooked.MARK_END) + 4
    assert out[pos:pos + 16] != rec[pos:pos + 16]      # guid changed
    assert out[:pos] == rec[:pos]                       # everything before intact
    assert out[pos + 16:] == rec[pos + 16:]             # everything after intact
