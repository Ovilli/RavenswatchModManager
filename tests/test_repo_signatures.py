"""Repo-index signature checks (`rsmm update` / `rsmm install` from a repo).

Two holes, both reachable from a hostile repo index:

* ``verify_file`` needed the optional ``cryptography`` package, which the
  frozen CLI never bundles, so it raised on every call — and ``rsmm update``
  read that as ``(True, "verify skipped")`` with no trust prompt. A forged
  signature installed silently in every released build.
* ``pubkey_id`` came straight from the index and was joined onto the key
  directory, so ``../…`` or an absolute path could name a ``.pub`` shipped in
  an already-installed mod and pass an attacker's key off as trusted.

These tests run without ``cryptography`` on purpose (the dev venv and the
frozen build both lack it). The signer below is textbook RFC 8032 built on the
curve arithmetic ``rsmm.engine.minisign`` already verifies with.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from rsmm.engine import minisign as ms
from rsmm.sdk import repo


def _encode(point) -> bytes:
    x, y, z, _t = point
    zi = pow(z, ms._P - 2, ms._P)
    x, y = x * zi % ms._P, y * zi % ms._P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _keypair(seed: bytes) -> tuple[bytes, bytes, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a.to_bytes(32, "little"), h[32:], _encode(ms._scalar_mult(a, ms._B))


def _sign(seed: bytes, message: bytes) -> bytes:
    a_bytes, prefix, pub = _keypair(seed)
    a = int.from_bytes(a_bytes, "little")
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % ms._L
    big_r = _encode(ms._scalar_mult(r, ms._B))
    k = int.from_bytes(hashlib.sha512(big_r + pub + message).digest(), "little") % ms._L
    return big_r + ((r + k * a) % ms._L).to_bytes(32, "little")


@pytest.fixture
def no_crypto(monkeypatch):
    """Exactly what a frozen build sees."""
    monkeypatch.setattr(repo, "_load_crypto", lambda: None)


@pytest.fixture
def signed(tmp_path: Path):
    seed = b"\x07" * 32
    blob = tmp_path / "mod.zip"
    blob.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    digest = hashlib.sha256(blob.read_bytes()).hexdigest().encode("ascii")
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "official.pub").write_text(
        base64.b64encode(_keypair(seed)[2]).decode("ascii"), encoding="utf-8")
    sig = base64.b64encode(_sign(seed, digest)).decode("ascii")
    return blob, keys, sig


def test_verify_file_works_without_cryptography(no_crypto, signed):
    blob, keys, sig = signed
    assert repo.verify_file(blob, sig, keys / "official.pub") is True


def test_verify_file_rejects_tampering_and_garbage(no_crypto, signed):
    blob, keys, sig = signed
    pub = keys / "official.pub"
    assert repo.verify_file(blob, base64.b64encode(b"\x00" * 64).decode(), pub) is False
    assert repo.verify_file(blob, "not base64!!", pub) is False
    blob.write_bytes(b"tampered")
    assert repo.verify_file(blob, sig, pub) is False


def _check(blob: Path, keys: Path, sig: str, pubkey_id: str, mod: str = "m"):
    sha = hashlib.sha256(blob.read_bytes()).hexdigest()
    entry = repo.RepoEntry(id=mod, version="1", url="", sha256=sha, sig=sig, pubkey_id=pubkey_id)
    t = repo.check_entry(sha, entry, keys)
    return t.ok and not t.warn, t.reason


def test_update_refuses_a_forged_signature_from_a_known_signer(
        no_crypto, signed, monkeypatch):
    blob, keys, _sig = signed
    forged = base64.b64encode(b"\x01" * 64).decode()
    ok, reason = _check(blob, keys, forged, "official")
    assert not ok, reason


def test_update_accepts_a_genuine_signature(no_crypto, signed, monkeypatch):
    blob, keys, sig = signed
    ok, reason = _check(blob, keys, sig, "official")
    assert ok and reason.startswith("signature ok"), reason


@pytest.mark.parametrize("pubkey_id", ["../planted", "..", "sub/official"])
def test_update_refuses_a_signer_id_that_is_a_path(no_crypto, signed, monkeypatch,
                                                  tmp_path, pubkey_id):
    blob, keys, sig = signed
    # The attacker's key sits OUTSIDE the key directory, e.g. inside a mod.
    (tmp_path / "planted.pub").write_text(
        (keys / "official.pub").read_text(encoding="utf-8"), encoding="utf-8")
    (keys / "sub").mkdir()
    (keys / "sub" / "official.pub").write_text(
        (keys / "official.pub").read_text(encoding="utf-8"), encoding="utf-8")
    ok, reason = _check(blob, keys, sig, pubkey_id)
    assert not ok, reason


def test_update_refuses_an_absolute_signer_id(no_crypto, signed, monkeypatch, tmp_path):
    blob, keys, sig = signed
    planted = tmp_path / "elsewhere" / "k"
    planted.parent.mkdir()
    planted.with_suffix(".pub").write_text(
        (keys / "official.pub").read_text(encoding="utf-8"), encoding="utf-8")
    ok, reason = _check(blob, keys, sig, str(planted))
    assert not ok, reason


def test_first_verified_signer_is_pinned_and_a_swap_is_refused(no_crypto, signed):
    """Any key in ~/.rsmm/keys used to verify any mod, so whoever controlled
    the index could re-sign a mod with another trusted key, or strip the
    signature, and it installed. The first verified signer is now pinned."""
    blob, keys, sig = signed
    assert _check(blob, keys, sig, "official")[0]
    assert (keys / repo.PINS_NAME).is_file()
    # Another key the user trusts, signing the same mod: refused.
    (keys / "other.pub").write_text((keys / "official.pub").read_text(), encoding="utf-8")
    ok, reason = _check(blob, keys, sig, "other")
    assert not ok and "pinned" in reason
    # The signature dropped: refused, not merely a warning.
    sha = hashlib.sha256(blob.read_bytes()).hexdigest()
    t = repo.check_entry(sha, repo.RepoEntry(id="m", version="2", url="", sha256=sha), keys)
    assert not t.ok and "pinned" in t.reason
    # A different mod is unaffected by m's pin.
    assert _check(blob, keys, sig, "other", mod="n")[0]


def test_unsigned_and_unknown_signer_warn(no_crypto, signed):
    blob, keys, sig = signed
    sha = hashlib.sha256(blob.read_bytes()).hexdigest()
    t = repo.check_entry(sha, repo.RepoEntry(id="m", version="1", url="", sha256=sha), keys)
    assert t.ok and t.warn
    t = repo.check_entry(sha, repo.RepoEntry(id="m", version="1", url="", sha256=sha,
                                             sig=sig, pubkey_id="stranger"), keys)
    assert t.ok and t.warn
    assert not (keys / repo.PINS_NAME).exists(), "an unverified signer must not be pinned"


def test_unattended_install_of_unverified_needs_yes(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert repo.confirm_untrusted("m", yes=False) is False
    assert repo.confirm_untrusted("m", yes=True) is True
