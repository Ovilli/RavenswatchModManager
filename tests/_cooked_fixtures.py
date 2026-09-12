"""Builders for synthetic cooked entity containers used by several suites.

A value node can only be identified by resolving the class index after each
``1111bbaa`` BEGIN marker through *the file's own class table*, so a fixture
has to be a real container — a bare byte fragment carries no class table and
is correctly unreadable. See :mod:`rsmm.engine.talent_values`.
"""

from __future__ import annotations

import struct

from rsmm.engine import cooked

BEGIN = b"\x11\x11\xbb\xaa"
END = b"\x22\x22\xbb\xaa"

#: ``oCEntityValueUnion`` type codes.
T_F32 = 0
T_INT32 = 1
T_BOOL = 2

#: Class-table indices the builders place the picker/union at by default. Any
#: pair works — that is the point — these just mirror a small shipped file.
PICKER_IDX = 0x0E
UNION_IDX = 0x0F


def lstr(s: str) -> bytes:
    b = s.encode("ascii")
    return struct.pack("<I", len(b)) + b


def begin(idx: int) -> bytes:
    return BEGIN + struct.pack("<I", idx)


def class_table(picker_idx: int = PICKER_IDX,
                union_idx: int = UNION_IDX) -> list[cooked.ClassDef]:
    """A plausible class table with the picker/union at the given indices."""
    n = max(picker_idx, union_idx) + 1
    names = [f"oCFiller{i:03d}" for i in range(n)]
    names[0] = "oCEntitySettingsResource"
    for i, nm in enumerate(("oCEntityCpntTimerSettings",
                            "oCEntityCpnt3dNodeSettings",
                            "oIEntityCpntSettings",
                            "oCEntityCpntPicker"), start=1):
        if i < n:
            names[i] = nm
    names[picker_idx] = "oCEntityCpntValuePicker"
    names[union_idx] = "oCEntityValueUnion"
    return [cooked.ClassDef(nm, 0x1000 + i, 1, 0, 0) for i, nm in enumerate(names)]


def value_node(label: str, value, *, type_code: int = T_F32,
               shadowed: bool = False, picker_idx: int = PICKER_IDX,
               union_idx: int = UNION_IDX, prefix: bytes = b"") -> bytes:
    """One value node: label, optional filler, then the picker/union pair.

    ``prefix`` is inserted between the label and the picker, for fixtures that
    need a decoy float sitting nearer the label than the real field.
    """
    if type_code == T_INT32:
        raw = struct.pack("<i", int(value))
    elif type_code == T_BOOL:
        raw = bytes([1 if value else 0])
    else:
        raw = struct.pack("<f", value)
    flag = b"\x01\xde\xad\xbe" if shadowed else b"\x00"
    return (lstr(label) + prefix
            + begin(picker_idx) + flag
            + begin(union_idx) + struct.pack("<II", type_code, 0) + raw
            + END    # closes the union
            + END)   # closes the picker


def container(payload: bytes, *, picker_idx: int = PICKER_IDX,
              union_idx: int = UNION_IDX) -> bytes:
    """Wrap a node payload in a valid cooked container with a class table."""
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=class_table(picker_idx, union_idx),
        sections=[cooked.Section(payload=payload)],
    )
    return cooked.emit(cf)


def entity(*nodes: bytes, picker_idx: int = PICKER_IDX,
           union_idx: int = UNION_IDX) -> bytes:
    """A whole cooked entity file holding ``nodes``."""
    return container(b"".join(nodes), picker_idx=picker_idx, union_idx=union_idx)


def name_list(*names: str) -> bytes:
    """A balanced node holding nothing but a list of names.

    Real containers END-terminate every node, so a stray name can never run
    straight into the next node's picker; a fixture has to do the same or it
    tests a layout the format cannot produce.
    """
    body = b"".join(lstr(n) + b"\x00" * 8 for n in names)
    return begin(1) + body + END
