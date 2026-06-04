"""Shared file-hashing util."""

import hashlib

from rsmm.engine.hashing import sha256_file


def test_sha256_file_matches_hashlib(tmp_path):
    data = b"the quick brown fox" * 5000  # spans multiple 64 KiB chunks
    p = tmp_path / "blob.bin"
    p.write_bytes(data)
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()


def test_sha256_file_empty(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert sha256_file(p) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_accepts_str_path(tmp_path):
    p = tmp_path / "s.bin"
    p.write_bytes(b"abc")
    assert sha256_file(str(p)) == hashlib.sha256(b"abc").hexdigest()
