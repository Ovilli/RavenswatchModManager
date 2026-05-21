#!/usr/bin/env python3
"""
oCTextSaver binary decoder.

Ravenswatch ships content in two forms:

  * Uncooked text  — `.ot` files starting with `//OPROJECT oCTextSaver`. These
    are the engine's native, human-readable serialization format. A few of
    these ship alongside the game executable (e.g. ApplicationSettings.ot).

  * Cooked binary  — `.gen` files (decoded extension; on disk encoded via the
    substitution cipher) inside DarkTalesResources/_Cooking/. Same data,
    packed binary. The actual runtime assets — Ravenswatch *only* probes
    these at runtime, never the text source.

Binary layout (reverse-engineered, confirmed 2026-05-14):

  [0x00] u32   header_size       = 0x10
  [0x04] u32   flags             = 0x01
  [0x08] str4  "Cooked"          (length-prefixed)
  [..]   u32   extra             = 0x01
  [..]   u8    tag               = 0x31
  [..]   u32   marker_begin      = 0xAABB1111
  [..]   u32   class_count
  [..]   N * { u32 name_len; bytes name; u32 class_id;
                u32 v_major; u32 v_minor; u32 parent_id }
  [..]   u32   marker_end        = 0xAABB2222
  [..]   --- object table section, bracketed by AABB1111/AABB2222 ---
  [..]   --- data section(s),    bracketed by AABB1111/AABB2222 ---

Section markers act as BEGIN/END brackets, not just inline magic.

Body decoding requires the per-class serialization schema, which lives in
Ravenswatch.exe — we don't have it. This decoder therefore parses the
structural skeleton and dumps the data sections as labelled hex; that's
enough to support targeted byte-level overrides of known files.

Usage:
    tools/ot_decoder.py <path-to-cooked-file>          # structural dump
    tools/ot_decoder.py <path> --raw                   # include raw hex
"""

from __future__ import annotations

import argparse
import struct
import sys
import uuid
from dataclasses import dataclass, field

MARK_BEGIN = bytes.fromhex("1111bbaa")   # 0xAABB1111 (little-endian on disk)
MARK_END   = bytes.fromhex("2222bbaa")   # 0xAABB2222


@dataclass
class ClassDef:
    name: str
    class_id: int
    version_major: int
    version_minor: int
    parent_id: int = 0


@dataclass
class Section:
    begin_off: int
    end_off: int
    payload: bytes


@dataclass
class CookedFile:
    header_size: int
    flags: int
    project_tag: str       # "Cooked"
    extra: int
    classes: list[ClassDef] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    body_offset: int = 0


class Cursor:
    def __init__(self, data: bytes):
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

    def lstr(self) -> str:
        n = self.u32()
        s = self.data[self.pos:self.pos + n].decode("ascii", errors="replace")
        self.pos += n
        return s

    def expect(self, sig: bytes, label: str) -> None:
        got = self.data[self.pos:self.pos + len(sig)]
        if got != sig:
            raise ValueError(
                f"expected {label} {sig.hex()} at {self.pos:#x}, got {got.hex()}"
            )
        self.pos += len(sig)


def parse_header(c: Cursor) -> CookedFile:
    """Two observed header variants:

      Type A (direct cooked):
        u32 header_size = 0x10
        u32 flags       = 0x01
        lstr "Cooked"
        u32 extra       = 0x01
        u8  tag         = 0x31
        u32 BEGIN marker

      Type B (stream container, e.g. oCGameStream level files):
        u32 header_size = 0x10
        u32 flags       = 0x00
        u32 BEGIN marker            (no "Cooked" string, no extra/tag)

    Distinguish by peeking at offset 8: if it's AABB1111 we're in Type B.
    """
    header_field_0 = c.u32()
    flags = c.u32()
    if c.data[c.pos:c.pos + 4] == MARK_BEGIN:
        # Type B: no Cooked string. Move straight into class table.
        tag = "<stream>"
        extra = 0
        c.expect(MARK_BEGIN, "marker_begin")
    else:
        # Type A: classic Cooked header.
        tag = c.lstr()
        extra = c.u32()
        c.u8()   # tag byte 0x31
        c.expect(MARK_BEGIN, "marker_begin")
    return CookedFile(header_size=header_field_0, flags=flags,
                      project_tag=tag, extra=extra)


def parse_class_table(c: Cursor, cf: CookedFile) -> None:
    class_count = c.u32()
    for _ in range(class_count):
        name      = c.lstr()
        class_id  = c.u32()
        v_major   = c.u32()
        v_minor   = c.u32()
        parent_id = c.u32()
        cf.classes.append(ClassDef(name, class_id, v_major, v_minor, parent_id))
    c.expect(MARK_END, "class_table_end")


def parse_sections(c: Cursor, cf: CookedFile) -> None:
    """After the class table, the file contains a series of BEGIN/END-
    bracketed sections. We capture each section's raw payload + its file
    offsets. Schema-aware decoding of the payload requires per-class layout
    knowledge that isn't in the file.
    """
    def find_balanced_end(data: bytes, start_pos: int) -> int:
        # start_pos is after the first BEGIN marker for this section.
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
        return -1

    while c.pos < len(c.data):
        # Tolerate trailing zero padding or unexpected ends.
        if c.data[c.pos:c.pos + 4] != MARK_BEGIN:
            break
        begin_off = c.pos
        c.pos += 4
        section_end = find_balanced_end(c.data, c.pos)
        if section_end == -1:
            # Unterminated — store remainder for debugging.
            payload = c.data[c.pos:]
            cf.sections.append(Section(begin_off, len(c.data), payload))
            c.pos = len(c.data)
            return
        payload = c.data[c.pos:section_end - 4]
        cf.sections.append(Section(begin_off, section_end, payload))
        c.pos = section_end


def hex_dump(buf: bytes, indent: str = "    ") -> str:
    out = []
    for i in range(0, len(buf), 16):
        chunk = buf[i:i + 16]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{indent}{i:06x}  {h:<48s}  {a}")
    return "\n".join(out)


def maybe_decode_payload(payload: bytes) -> list[str]:
    """Best-effort labelling of common patterns in a data-section payload.

    We don't have class schemas yet, so this just picks out plausible
    field-shaped runs (floats, ints, length-prefixed strings).
    """
    notes = []
    n = len(payload)

    # length-prefixed ascii strings inside the payload
    i = 0
    while i + 4 <= n:
        L = struct.unpack_from("<I", payload, i)[0]
        if 1 <= L <= 256 and i + 4 + L <= n:
            s = payload[i + 4:i + 4 + L]
            if all(32 <= b < 127 for b in s):
                notes.append(f'    @{i:04x}  str(len={L})  "{s.decode("ascii")}"')
                i += 4 + L
                continue
        i += 1

    # trailing floats (small heuristic: last 4-byte aligned runs)
    if n >= 8:
        tail = payload[-8:]
        f1, f2 = struct.unpack("<ff", tail)
        if 1e-6 < abs(f1) < 1e9 and 1e-6 < abs(f2) < 1e9:
            notes.append(f"    tail floats: ({f1}, {f2})")

    # Common in oCEntitySettingsResource: length(0x10) + 16-byte GUID blob.
    for i in range(0, n - 20):
        if payload[i:i + 4] != b"\x10\x00\x00\x00":
            continue
        raw = payload[i + 4:i + 20]
        if len(raw) != 16:
            continue
        if MARK_BEGIN in raw or MARK_END in raw:
            continue
        if i + 24 <= n:
            tail_u32 = struct.unpack_from("<I", payload, i + 20)[0]
            if tail_u32 not in (0x00000000, 0xFFFFFFFF):
                continue
        if raw == b"\x00" * 16 or raw == b"\xff" * 16:
            continue
        try:
            gid = str(uuid.UUID(bytes=raw))
        except ValueError:
            continue
        notes.append(f"    @{i+4:04x}  guid(raw16) {gid}")
    return notes


def emit(cf: CookedFile, full_path: str, show_raw: bool = False) -> str:
    out = []
    out.append("//OPROJECT oCTextSaver (decoded from cooked .gen)")
    out.append(f"//SOURCE {full_path}")
    out.append(f"//HEADER tag={cf.project_tag} flags={cf.flags:#x} hdr_size={cf.header_size}")
    out.append(f"*Classes={len(cf.classes)}")
    for i, k in enumerate(cf.classes):
        parent = f"<[{k.parent_id}]" if k.parent_id and k.parent_id != 0xFFFFFFFF else ""
        out.append(f"*Class{i}={k.name}[{k.class_id}]({k.version_major}.{k.version_minor}){parent}")
    out.append(f"*Sections={len(cf.sections)}")
    for i, s in enumerate(cf.sections):
        out.append(
            f"*Section{i}=range[{s.begin_off:#x}..{s.end_off:#x}] "
            f"payload_len={len(s.payload)}")
        for note in maybe_decode_payload(s.payload):
            out.append(note)
        if show_raw:
            out.append(hex_dump(s.payload))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--raw", action="store_true", help="dump section payloads as hex")
    args = ap.parse_args()

    with open(args.path, "rb") as f:
        data = f.read()
    c = Cursor(data)
    cf = parse_header(c)
    parse_class_table(c, cf)
    parse_sections(c, cf)
    cf.body_offset = c.pos
    sys.stdout.write(emit(cf, args.path, show_raw=args.raw))


if __name__ == "__main__":
    main()
