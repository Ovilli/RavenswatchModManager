"""Profile save container tests.

Everything runs against a synthetic save built in-process — never a real
`Profile_*.ob`. A bad write to a player's profile is unrecoverable, so the
test suite must not be able to touch one even by accident.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from rsmm.engine import savefile


def build_save(classes=(("oCDtHeroProfileData", 0x131E8BD7, 1, 18, 0x17C4CD9C),),
               # tuple order = wire order: name, hash, reserved, version, parent
               payload: bytes = b"\xaa\xbb\x11\x11payload\xaa\xbb\x22\x22",
               *, version: int = 1, magic: int = savefile.MAGIC) -> bytes:
    """Assemble a minimal but structurally faithful save."""
    body = struct.pack("<I", magic) + struct.pack("<I", len(classes))
    for name, chash, reserved, ver, parent in classes:
        raw = name.encode("ascii")
        body += struct.pack("<I", len(raw)) + raw
        body += struct.pack("<IIII", chash, reserved, ver, parent)
    body += payload
    head = struct.pack("<III", savefile.HEADER_SIZE, 0, version)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return head + struct.pack("<I", crc) + body


def write_save(tmp_path, **kw):
    p = tmp_path / "Profile_1.ob"
    p.write_bytes(build_save(**kw))
    return p


def test_parses_header_registry_and_crc(tmp_path):
    s = savefile.load(write_save(tmp_path))
    assert s.format_version == 1
    assert s.crc_ok
    assert [c.name for c in s.classes] == ["oCDtHeroProfileData"]
    entry = s.by_name("oCDtHeroProfileData")
    assert entry is not None
    assert entry.version == 18          # schema version, NOT an instance count
    assert entry.reserved == 1
    assert entry.hash == 0x131E8BD7
    # data section begins right after the registry
    assert s.data_start == 0x18 + 4 + len("oCDtHeroProfileData") + 16


def test_rejects_non_save(tmp_path):
    p = tmp_path / "not.ob"
    p.write_bytes(build_save(magic=0xDEADBEEF))
    with pytest.raises(savefile.SaveFormatError, match="bad magic"):
        savefile.load(p)


def test_rejects_truncated_file(tmp_path):
    p = tmp_path / "short.ob"
    p.write_bytes(b"\x10\x00\x00\x00")
    with pytest.raises(savefile.SaveFormatError, match="too small"):
        savefile.load(p)


def test_rejects_truncated_registry(tmp_path):
    """A count that overruns the buffer must raise, not read garbage."""
    p = tmp_path / "bad.ob"
    raw = bytearray(build_save())
    struct.pack_into("<I", raw, 0x14, 99)  # claim 99 classes
    p.write_bytes(bytes(raw))
    with pytest.raises(savefile.SaveFormatError, match="truncated class registry"):
        savefile.load(p)


def test_edit_invalidates_crc_until_resigned(tmp_path):
    """The core safety property: the game rejects a stale checksum, so an edit
    must show as invalid until it is re-signed."""
    s = savefile.load(write_save(tmp_path))
    s.data[-1] ^= 0xFF
    assert not s.crc_ok
    new = savefile.resign(s)
    assert s.crc_ok
    assert new == s.stored_crc


def test_write_roundtrip_and_backup(tmp_path):
    p = write_save(tmp_path)
    original = p.read_bytes()
    s = savefile.load(p)
    s.data[-1] ^= 0xFF
    out = savefile.write(s)

    assert out == p
    # backup preserves the pre-edit bytes
    bak = p.with_suffix(p.suffix + ".rsmm.bak")
    assert bak.read_bytes() == original
    # and the file on disk reloads clean
    assert savefile.load(p).crc_ok


def test_write_without_backup(tmp_path):
    p = write_save(tmp_path)
    s = savefile.load(p)
    savefile.write(s, backup=False)
    assert not p.with_suffix(p.suffix + ".rsmm.bak").exists()


def test_write_to_new_path_leaves_source_untouched(tmp_path):
    p = write_save(tmp_path)
    before = p.read_bytes()
    s = savefile.load(p)
    s.data[-1] ^= 0xFF
    out = savefile.write(s, tmp_path / "copy.ob")
    assert p.read_bytes() == before
    assert savefile.load(out).crc_ok


def test_find_saves(tmp_path):
    sd = tmp_path / "_Save"
    sd.mkdir()
    for n in ("Profile_1.ob", "Profile_1_Temp.ob", "notes.txt"):
        (sd / n).write_bytes(b"")
    assert [p.name for p in savefile.find_saves(tmp_path)] == [
        "Profile_1.ob",
        "Profile_1_Temp.ob",
    ]
    assert savefile.find_saves(tmp_path / "nope") == []
