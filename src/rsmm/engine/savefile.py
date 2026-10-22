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

SCOPE. The registry (names, hashes, schema versions) is fully parsed. In the
data section, the object table and the record boundaries are read (see
`records`), and ONE record layout is decoded: `oCDtMagicalObjectProfileData`,
a fixed 40-byte record per item (`item_records`). Every other record's layout
is driven by an engine serializer nobody has decoded, so those are walked past
and never changed — guessing offsets would corrupt real saves.

An item record names its item by a 16-byte GUID that sits in the item's own
EntitySettingsResource file (not the identity GUID `magic_item_cook` reads).
The game writes a record only for items whose entity it loaded that session:
some retired items keep theirs (their entity still loads), but an item missing
from the LiveOps catalog for one session (an item ban, a disabled mod's item)
loses its record at the next save. `save_item_ledger` puts those back.
The meaning of each flag is NOT known; what is known
is the two states the game itself writes (`ITEM_STATES`), read from
`oCDtMagicalObjectProfileData`'s vtable on build b9c3642884a8 (serializer
FUN_1402cc730, "grant" slot 15 FUN_1402ccbf0, "reset" slot 13 FUN_1402ccb90).
Editing is therefore limited to putting a record into one of those states.

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

from rsmm.engine.paths import BACKUP_SUFFIX

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
        shutil.copy2(out, out.with_suffix(out.suffix + BACKUP_SUFFIX))
    out.write_bytes(bytes(save.data))
    return out


def find_saves(game_dir: str | Path) -> list[Path]:
    """Profile saves under `<game>/_Save` (includes `*_Temp.ob` autosaves)."""
    save_dir = Path(game_dir) / "_Save"
    if not save_dir.is_dir():
        return []
    return sorted(p for p in save_dir.glob("Profile_*.ob") if p.is_file())


# --- records ----------------------------------------------------------------
_OPEN = struct.pack("<I", MARKER_OPEN)
_CLOSE = struct.pack("<I", MARKER_CLOSE)


@dataclass(frozen=True)
class Record:
    """One top-level object in the data section: ``start`` is its open marker,
    ``end`` is just past its close marker, ``cls`` its registry index."""

    start: int
    end: int
    cls: int


def object_table(save: Save) -> list[int]:
    """The class index of every object, as the data section's header lists it:
    ``close open u32 n  n x u32 close``, right after the registry."""
    d, o = save.data, save.data_start
    if bytes(d[o:o + 8]) != _CLOSE + _OPEN:
        raise SaveFormatError(f"{save.path}: no object table after the registry")
    (n,) = struct.unpack_from("<I", d, o + 8)
    if o + 12 + 4 * n + 4 > len(d):
        raise SaveFormatError(f"{save.path}: object table runs past the end")
    return list(struct.unpack_from(f"<{n}I", d, o + 12))


def records(save: Save) -> list[Record]:
    """Every top-level record, by walking the open/close markers.

    Records nest (a record may hold sub-objects in their own markers), so a
    record ends when the depth returns to zero. Payload bytes are not decoded;
    a payload that happened to contain a marker's bytes would throw the walk
    off, which is why callers that edit check the walk against the object
    table before trusting it (see `item_records`).
    """
    d = bytes(save.data)
    table = object_table(save)
    i = save.data_start + 12 + 4 * len(table)
    if d[i:i + 4] != _CLOSE:
        raise SaveFormatError(f"{save.path}: object table is not closed")
    i += 4
    out: list[Record] = []
    depth, start = 0, -1
    while i + 4 <= len(d):
        w = d[i:i + 4]
        if w == _OPEN:
            if depth == 0:
                start = i
            depth += 1
            i += 4
        elif w == _CLOSE:
            if depth == 0:
                raise SaveFormatError(f"{save.path}: unbalanced close marker at 0x{i:x}")
            depth -= 1
            i += 4
            if depth == 0:
                (cls,) = struct.unpack_from("<I", d, start + 4)
                out.append(Record(start, i, cls))
        else:
            i += 1
    if depth:
        raise SaveFormatError(f"{save.path}: the last record is not closed")
    return out


ITEM_CLASS = "oCDtMagicalObjectProfileData"
#: After the open marker and class index: GUID, u32, u8 +0x60, u8 +0x61,
#: u8 +0x62, i32 +0x64, u8 +0x68 (schema v5 order, FUN_1402cc730).
_ITEM_BODY = struct.Struct("<16sIBBBiB")
_ITEM_SIZE = 8 + _ITEM_BODY.size + 4                 # 40 bytes, markers included

#: The states the game itself puts an item record in, and nothing else. The
#: flags' meanings are not decoded, so the editor offers these whole rather
#: than letting a field be set to a value the game may never write. Both occur
#: naturally in real saves (every Common/Rare/Epic item a player has is in the
#: "granted" one). None = leave that field as it is.
ITEM_STATES: dict[str, dict[str, int | None]] = {
    # vtable slot 15 (FUN_1402ccbf0): u16 +0x60 = 0x0101, i32 +0x64 = 3.
    "granted": {"f60": 1, "f61": 1, "f62": None, "f64": 3, "f68": None},
    # vtable slot 13 (FUN_1402ccb90): +0x60/+0x61/+0x62 = 0, +0x64 = -1, +0x68 = 1.
    "reset": {"f60": 0, "f61": 0, "f62": 0, "f64": -1, "f68": 1},
}


@dataclass(frozen=True)
class ItemRecord:
    offset: int          # of the record's open marker
    guid: bytes
    word: int            # u32 after the GUID (0 in every record seen)
    f60: int
    f61: int
    f62: int
    f64: int
    f68: int

    def state(self) -> str:
        """The ITEM_STATES name this record is in, or "other"."""
        for name, want in ITEM_STATES.items():
            if all(v is None or getattr(self, k) == v for k, v in want.items()):
                return name
        return "other"


def item_records(save: Save) -> list[ItemRecord]:
    """Every magic-object record. Raises SaveFormatError unless the walk found
    exactly as many as the object table declares, each exactly 40 bytes: the
    one check that a marker-shaped payload byte did not mislead the walk."""
    try:
        cls = next(i for i, c in enumerate(save.classes) if c.name == ITEM_CLASS)
    except StopIteration:
        return []
    if save.classes[cls].version != 5:
        raise SaveFormatError(f"{save.path}: {ITEM_CLASS} is schema v{save.classes[cls].version}; "
                              "only v5 is decoded")
    want = object_table(save).count(cls)
    found = [r for r in records(save) if r.cls == cls]
    d = save.data
    if len(found) != want or any(r.end - r.start != _ITEM_SIZE for r in found):
        raise SaveFormatError(f"{save.path}: found {len(found)} item records where the "
                              f"object table lists {want}; not editing a save the walk "
                              "does not account for")
    return [ItemRecord(r.start, *_ITEM_BODY.unpack_from(d, r.start + 8)) for r in found]


def item_body(rec: ItemRecord) -> bytes:
    """The record's bytes between class index and close marker, as stored."""
    return _ITEM_BODY.pack(rec.guid, rec.word, rec.f60, rec.f61, rec.f62, rec.f64, rec.f68)


def append_item_records(save: Save, bodies: list[bytes]) -> None:
    """Add item records (each an `item_body`) to the save, in place.

    The game writes a record only for items whose entity it loaded that
    session, so an item missing from the catalog for one session (a ban, a
    disabled mod) loses its record for good. This puts records back: each new
    object takes the next object id, goes in the object table and just before
    the profile record, and the profile lists its id. Existing ids do not
    move. Re-sign before writing."""
    if not bodies:
        return
    if any(len(b) != _ITEM_BODY.size for b in bodies):
        raise ValueError(f"an item record body is {_ITEM_BODY.size} bytes")
    item_records(save)                       # refuses a save the walk does not account for
    cls = next(i for i, c in enumerate(save.classes) if c.name == ITEM_CLASS)
    d, o = bytes(save.data), save.data_start
    n = len(object_table(save))
    root = records(save)[-1]
    if save.classes[root.cls].name != "oCDtGameProfile":
        raise SaveFormatError(f"{save.path}: the last record is not the profile")
    k = len(bodies)
    tend = o + 12 + 4 * n
    (m,) = struct.unpack_from("<I", d, root.start + 8)
    refs_end = root.start + 12 + 4 * m
    head = struct.pack("<I", cls)
    save.data[:] = (d[:o + 8] + struct.pack("<I", n + k) + d[o + 12:tend]
                    + head * k + d[tend:root.start]
                    + b"".join(_OPEN + head + b + _CLOSE for b in bodies)
                    + d[root.start:root.start + 8] + struct.pack("<I", m + k)
                    + d[root.start + 12:refs_end]
                    + struct.pack(f"<{k}I", *range(n, n + k)) + d[refs_end:])


def set_item_state(save: Save, rec: ItemRecord, state: str) -> ItemRecord:
    """Put one item record into an ITEM_STATES state, in place. The record keeps
    its size, so nothing else in the file moves. Re-sign before writing."""
    want = ITEM_STATES[state]
    vals = {k: (getattr(rec, k) if want[k] is None else want[k]) for k in want}
    new = ItemRecord(rec.offset, rec.guid, rec.word, **vals)
    _ITEM_BODY.pack_into(save.data, rec.offset + 8, new.guid, new.word,
                         new.f60, new.f61, new.f62, new.f64, new.f68)
    return new
