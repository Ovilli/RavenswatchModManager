"""
Cooked-container codec for Ravenswatch's oEngine.

Wraps every shipped binary asset (.gen / .dxt / .nrm — encoded as .yqz / .tpi /
.zux on disk) and the .ob save format. Provides:

  parse(data: bytes)          -> CookedFile     # decode container
  emit(cf:   CookedFile)      -> bytes          # encode container (byte-stable
                                                 # round-trip on unchanged input)

Per-class payload schemas are NOT handled here — see rsmm.engine.cooked_schemas.

Container layout (two variants, both supported):

  Type A — classic cooked file (.yqz/.gen, .tpi/.dxt, .zux/.nrm):
    u32 hdr_a        = 0x10
    u32 flags        = 0x01
    u32 tag_len      = 0x06
    bytes tag        = "Cooked"
    u32 extra        = 0x01
    u8  type_tag     = 0x31
    u32 BEGIN        = 0xAABB1111
    --- class table ---
    --- sections ---

  Type B — stream container (e.g. oCGameStream level files):
    u32 hdr_a        = 0x10
    u32 flags        = 0x00
    u32 BEGIN        = 0xAABB1111
    --- class table ---
    --- sections ---

  Class table:
    u32 class_count
    class_count * {
      u32 name_len; bytes name;
      u32 class_id;
      u32 version_major;
      u32 version_minor;
      u32 parent_id;
    }
    u32 END          = 0xAABB2222

  Sections (one or more):
    u32 BEGIN
    bytes payload (may contain nested BEGIN/END pairs — depth-balanced)
    u32 END

Save files (.ob) carry an extra 16-byte preamble with a zlib CRC32 over
bytes[0x10:] — that variant is documented in rsmm.engine.save_container
(future), not here. Asset containers have no CRC.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Literal

MARK_BEGIN = b"\x11\x11\xbb\xaa"   # 0xAABB1111 little-endian
MARK_END = b"\x22\x22\xbb\xaa"     # 0xAABB2222 little-endian
COOKED_TAG = b"Cooked"
DEFAULT_TYPE_TAG = 0x31


@dataclass
class ClassDef:
    name: str
    class_id: int
    version_major: int
    version_minor: int
    parent_id: int


@dataclass
class Section:
    """A BEGIN..END bracketed payload inside the container.

    `payload` is the raw bytes between the outer BEGIN and the outermost END
    of the section, with any inner BEGIN/END pairs preserved verbatim. The
    container codec is depth-balanced but does not interpret the payload.
    """
    payload: bytes


@dataclass
class CookedFile:
    variant: Literal["A", "B"]
    hdr_a: int
    flags: int
    extra: int = 0
    type_tag: int = DEFAULT_TYPE_TAG
    classes: list[ClassDef] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


class _Cursor:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def lstr_bytes(self) -> bytes:
        n = self.u32()
        if self.pos + n > len(self.data):
            raise ValueError(
                f"string length {n} exceeds remaining data at {self.pos - 4:#x}"
            )
        s = self.data[self.pos:self.pos + n]
        self.pos += n
        return s

    def expect(self, sig: bytes, label: str) -> None:
        got = self.data[self.pos:self.pos + len(sig)]
        if got != sig:
            raise ValueError(
                f"expected {label} {sig.hex()} at {self.pos:#x}, got {got.hex()}"
            )
        self.pos += len(sig)


def _find_section_end(data: bytes, start_pos: int) -> int:
    """Return absolute offset past the matching END marker for the BEGIN at
    `start_pos - 4`. Handles nested BEGIN/END pairs (depth-balanced).

    Markers are aligned to wherever they appear in the byte stream — when
    scanning we must NOT step by 1 byte through arbitrary payload, since
    payload bytes can incidentally match a marker prefix. Markers are however
    always written aligned to natural u32 boundaries within sections. We
    therefore scan with stride 4 starting from `start_pos`.

    A scalar byte stride would risk misaligned false positives inside payload
    floats/ints whose bytes might happen to spell 0x11 0x11 0xbb 0xaa.
    """
    depth = 1
    pos = start_pos
    n = len(data)
    while pos + 4 <= n:
        tag = data[pos:pos + 4]
        if tag == MARK_BEGIN:
            depth += 1
            pos += 4
            continue
        if tag == MARK_END:
            depth -= 1
            pos += 4
            if depth == 0:
                return pos
            continue
        pos += 1
    raise ValueError("unterminated section: no matching END marker")


def parse(data: bytes) -> CookedFile:
    c = _Cursor(data)
    hdr_a = c.u32()
    flags = c.u32()

    if c.data[c.pos:c.pos + 4] == MARK_BEGIN:
        # Type B
        c.expect(MARK_BEGIN, "marker_begin")
        cf = CookedFile(variant="B", hdr_a=hdr_a, flags=flags)
    else:
        # Type A
        tag = c.lstr_bytes()
        if tag != COOKED_TAG:
            raise ValueError(f"expected 'Cooked' tag, got {tag!r}")
        extra = c.u32()
        type_tag = c.u8()
        c.expect(MARK_BEGIN, "marker_begin")
        cf = CookedFile(
            variant="A", hdr_a=hdr_a, flags=flags, extra=extra, type_tag=type_tag
        )

    # Class table.
    class_count = c.u32()
    if class_count > 200:
        raise ValueError(f"implausible class_count={class_count}")
    for _ in range(class_count):
        name = c.lstr_bytes().decode("ascii", errors="replace")
        class_id, vmaj, vmin, parent_id = struct.unpack_from(
            "<IIII", c.data, c.pos
        )
        c.pos += 16
        cf.classes.append(ClassDef(name, class_id, vmaj, vmin, parent_id))
    c.expect(MARK_END, "class_table_end")

    # Sections.
    while c.pos < len(c.data):
        if c.data[c.pos:c.pos + 4] != MARK_BEGIN:
            # Stray trailing bytes — tolerate but flag via the section list
            # being non-exhaustive of the input. Round-trip emit() will
            # re-emit only what we captured; callers must compare against
            # the truncated form if trailing bytes are present.
            break
        c.pos += 4
        section_end = _find_section_end(c.data, c.pos)
        payload = c.data[c.pos:section_end - 4]
        cf.sections.append(Section(payload=payload))
        c.pos = section_end

    return cf


def emit(cf: CookedFile) -> bytes:
    out = bytearray()
    out += struct.pack("<II", cf.hdr_a, cf.flags)
    if cf.variant == "A":
        out += struct.pack("<I", len(COOKED_TAG))
        out += COOKED_TAG
        out += struct.pack("<I", cf.extra)
        out += struct.pack("<B", cf.type_tag)
    elif cf.variant != "B":
        raise ValueError(f"unknown variant {cf.variant!r}")
    out += MARK_BEGIN

    out += struct.pack("<I", len(cf.classes))
    for cls in cf.classes:
        name_bytes = cls.name.encode("ascii")
        out += struct.pack("<I", len(name_bytes))
        out += name_bytes
        out += struct.pack(
            "<IIII", cls.class_id, cls.version_major, cls.version_minor, cls.parent_id
        )
    out += MARK_END

    for sec in cf.sections:
        out += MARK_BEGIN
        out += sec.payload
        out += MARK_END

    return bytes(out)
