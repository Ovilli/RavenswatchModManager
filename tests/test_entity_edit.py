"""Unit tests for the variable-length entity re-emit API.

Builds a synthetic cooked container (no Ravenswatch install needed) and checks
that EntityEdit round-trips byte-stably, renames strings across the section
split with correct length bookkeeping, and swaps fixed-size refs in place.
"""

import struct

from rsmm.engine import cooked
from rsmm.engine.entity_edit import EntityEdit


def _lstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _sample() -> bytes:
    # Two sections; the second holds a value node ("... Value" + f32 before END)
    # plus two 16-byte refs to swap. A node name is split across the section
    # boundary to exercise concat-based editing.
    name = _lstr("Damage Value")
    s0 = name[:6]                       # node name straddles the section split
    s1 = (name[6:]
          + b"\x11\x11\xbb\xaa" + struct.pack("<f", 0.2) + b"\x22\x22\xbb\xaa"
          + b"A" * 16 + b"B" * 16)
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef("oCEntitySettingsResource", 0x16f5f7a3, 1, 0, 0)],
        sections=[cooked.Section(payload=s0), cooked.Section(payload=s1)],
    )
    return cooked.emit(cf)


def test_noop_roundtrip_byte_stable():
    raw = _sample()
    assert EntityEdit(raw).emit() == raw


def test_rename_variable_length_reparses():
    raw = _sample()
    ed = EntityEdit(raw)
    n = ed.replace_lstring("Damage Value", "Attack Speed Value")
    out = ed.emit()
    assert n == 1
    assert len(out) - len(raw) == len("Attack Speed Value") - len("Damage Value")
    cf = cooked.parse(out)
    concat = b"".join(s.payload for s in cf.sections)
    assert b"Attack Speed Value" in concat
    # the renamed file must itself re-emit stably (idempotent)
    assert EntityEdit(out).emit() == out


def test_set_value_before_end_length_preserving():
    raw = _sample()
    ed = EntityEdit(raw)
    ed.set_value_before_end("Damage Value", 0.5)
    out = ed.emit()
    assert len(out) == len(raw)
    cf = cooked.parse(out)
    concat = b"".join(s.payload for s in cf.sections)
    i = concat.find(b"\x22\x22\xbb\xaa")
    assert struct.unpack_from("<f", concat, i - 4)[0] == 0.5


def test_swap_refs():
    raw = _sample()
    cf = cooked.parse(raw)
    concat = b"".join(s.payload for s in cf.sections)
    a = concat.index(b"A" * 16)
    b = concat.index(b"B" * 16)
    ed = EntityEdit(raw)
    ed.swap_refs(a, b, 16)
    out = ed.emit()
    cf2 = cooked.parse(out)
    c2 = b"".join(s.payload for s in cf2.sections)
    assert c2[a:a + 16] == b"B" * 16
    assert c2[b:b + 16] == b"A" * 16
