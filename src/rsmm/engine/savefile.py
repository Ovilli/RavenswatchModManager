"""Ravenswatch profile save (`Profile_*.ob`) container reader/writer.

Container layout (verified 2026-07-19 against a real 69 KB `Profile_1.ob`:
checksum, magic and class registry all parse and the CRC re-computes exactly):

    0x00 u32  header size (0x10)
    0x04 u32  reserved (0)
    0x08 u32  format version (1)
    0x0c u32  CRC32 of bytes [0x10 .. EOF]      <- rejected by the game if wrong
    0x10 u32  magic 0xAABB1111
    0x14 u32  class count N
    0x18      class registry, N entries of:
                u32 name length, ASCII name,
                u32 type hash, u32 reserved (always 1), u32 schema version,
                u32 parent hash
    ...       data section: instance records delimited by
              0xAABB1111 (open) / 0xAABB2222 (close)

SCOPE — deliberately container-only. The registry (names, hashes, schema
versions) is fully parsed; the **data section is left opaque**. Each record's
field layout is driven by the engine's per-class serializers, so decoding it
means RE'ing every `*ProfileData` class — that work is not done, and guessing
offsets here would corrupt real saves.

The class names in the registry match the `*ProfileData` RTTI classes found
independently in the vtable dump (`oCDtHeroProfileData`, `SkillProfileData`,
`oCDtCurrentRunProfileData`, ...), which is what cross-validates this layout.

Credit: the container format was first published by the `just-maik/rwedit`
project. That repository carries no license, so nothing is copied from it —
this is an independent implementation of the same on-disk facts, re-verified
against a real save before being written.
"""

from __future__ import annotations

import shutil
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

HEADER_SIZE = 0x10
CRC_OFFSET = 0x0C
MAGIC_OFFSET = 0x10
MAGIC = 0xAABB1111
MARKER_OPEN = 0xAABB1111
MARKER_CLOSE = 0xAABB2222
REGISTRY_OFFSET = 0x18


class SaveFormatError(ValueError):
    """The file is not a Ravenswatch profile save (or is truncated)."""


@dataclass(frozen=True)
class ClassEntry:
    """One row of the save's class registry.

    NOTE on the third u32 (`version`): it was initially read as an instance
    count. It is not. Corrected 2026-07-19 on three independent signals:
    the engine's per-class deserializers gate on it (`oCDtHeroProfileData`
    FUN_140321450 accepts up to 0x12 = 18, and the registry says 18); across
    two saves five weeks apart exactly TWO classes changed (10->11, 18->19)
    while a game patch added MelodyProfileData — schema bumps, not player
    data; and the real record count for hero is 12, not the 18 stored here.

    `reserved` is the second u32 and is 1 for all 27 classes in both saves —
    it carries no observed information.
    """

    name: str
    hash: int
    reserved: int
    version: int
    parent_hash: int


@dataclass
class Save:
    path: Path
    data: bytearray
    stored_crc: int
    format_version: int
    classes: list[ClassEntry]
    data_start: int

    @property
    def computed_crc(self) -> int:
        return zlib.crc32(bytes(self.data[MAGIC_OFFSET:])) & 0xFFFFFFFF

    @property
    def crc_ok(self) -> bool:
        return self.computed_crc == self.stored_crc

    def by_name(self, name: str) -> ClassEntry | None:
        return next((c for c in self.classes if c.name == name), None)


def load(path: str | Path) -> Save:
    """Parse a profile save. Raises SaveFormatError on anything unexpected."""
    p = Path(path)
    data = bytearray(p.read_bytes())
    if len(data) < REGISTRY_OFFSET:
        raise SaveFormatError(f"{p}: too small to be a save ({len(data)} bytes)")

    stored_crc = struct.unpack_from("<I", data, CRC_OFFSET)[0]
    magic = struct.unpack_from("<I", data, MAGIC_OFFSET)[0]
    if magic != MAGIC:
        raise SaveFormatError(
            f"{p}: bad magic 0x{magic:08x} at 0x{MAGIC_OFFSET:02x} "
            f"(expected 0x{MAGIC:08x})"
        )
    version = struct.unpack_from("<I", data, 0x08)[0]
    count = struct.unpack_from("<I", data, 0x14)[0]

    classes: list[ClassEntry] = []
    off = REGISTRY_OFFSET
    for i in range(count):
        try:
            (slen,) = struct.unpack_from("<I", data, off)
            off += 4
            name = bytes(data[off:off + slen]).decode("ascii", "replace")
            off += slen
            chash, reserved, ver, parent = struct.unpack_from("<IIII", data, off)
            off += 16
        except struct.error as e:
            raise SaveFormatError(f"{p}: truncated class registry at entry {i}") from e
        classes.append(ClassEntry(name, chash, reserved, ver, parent))

    return Save(p, data, stored_crc, version, classes, off)


def resign(save: Save) -> int:
    """Rewrite the header CRC from the current bytes. Returns the new value.

    Any edit to `save.data` invalidates the checksum and the game will reject
    the file, so this must run before writing.
    """
    crc = save.computed_crc
    struct.pack_into("<I", save.data, CRC_OFFSET, crc)
    save.stored_crc = crc
    return crc


def write(save: Save, path: str | Path | None = None, *, backup: bool = True) -> Path:
    """Re-sign and write the save out, backing up any file being replaced.

    `backup` defaults to True on purpose: a bad save is unrecoverable for the
    player, and this writes to a real profile.
    """
    out = Path(path) if path is not None else save.path
    resign(save)
    if backup and out.exists():
        shutil.copy2(out, out.with_suffix(out.suffix + ".rsmm.bak"))
    out.write_bytes(bytes(save.data))
    return out


def find_saves(game_dir: str | Path) -> list[Path]:
    """Profile saves under `<game>/_Save` (includes `*_Temp.ob` autosaves)."""
    save_dir = Path(game_dir) / "_Save"
    if not save_dir.is_dir():
        return []
    return sorted(p for p in save_dir.glob("Profile_*.ob") if p.is_file())
