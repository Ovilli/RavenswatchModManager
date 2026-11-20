"""Distribution: `repo.json` schema + SHA256/Ed25519 sign + verify.

Open spec. No central host. Anyone can publish a `repo.json` at a URL of
their choice; users add it with `rsmm repo add <url>`.

Signing is optional but recommended. We use Ed25519 from `cryptography`
when available and fall back to "unsigned mode" otherwise. Keys live in
`~/.rsmm/keys/`:

    <id>.pub        # base64 Ed25519 public key
    <id>.key        # base64 Ed25519 private key (mode 0600)
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .api import sdk_export

REPO_SCHEMA = "rsmm.repo.v1"


class RepoError(ValueError):
    pass


# ---------------------------------------------------------------------------
# repo.json model
# ---------------------------------------------------------------------------


@dataclass
class RepoEntry:
    id: str
    version: str
    url: str
    sha256: str
    size: int = 0
    sdk_version: str = ""
    target_game_build: str = ""
    sig: str = ""              # base64
    pubkey_id: str = ""        # which key in ~/.rsmm/keys/ to verify with

    @classmethod
    def from_dict(cls, raw: dict) -> RepoEntry:
        return cls(
            id=str(raw["id"]),
            version=str(raw["version"]),
            url=str(raw["url"]),
            sha256=str(raw["sha256"]),
            size=int(raw.get("size", 0)),
            sdk_version=str(raw.get("sdk_version", "")),
            target_game_build=str(raw.get("target_game_build", "")),
            sig=str(raw.get("sig", "")),
            pubkey_id=str(raw.get("pubkey_id", "")),
        )

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "version": self.version, "url": self.url,
            "sha256": self.sha256, "size": self.size,
        }
        if self.sdk_version:
            d["sdk_version"] = self.sdk_version
        if self.target_game_build:
            d["target_game_build"] = self.target_game_build
        if self.sig:
            d["sig"] = self.sig
        if self.pubkey_id:
            d["pubkey_id"] = self.pubkey_id
        return d


@dataclass
class RepoIndex:
    name: str
    updated_at: str = ""
    mods: list[RepoEntry] = field(default_factory=list)

    @classmethod
    def load(cls, raw: dict) -> RepoIndex:
        if raw.get("schema") != REPO_SCHEMA:
            raise RepoError(f"unknown repo schema: {raw.get('schema')!r}")
        return cls(
            name=str(raw.get("name", "")),
            updated_at=str(raw.get("updated_at", "")),
            mods=[RepoEntry.from_dict(m) for m in raw.get("mods", [])],
        )

    def dump(self) -> dict:
        return {
            "schema": REPO_SCHEMA,
            "name": self.name,
            "updated_at": self.updated_at,
            "mods": [m.to_dict() for m in self.mods],
        }

    def find(self, mod_id: str, version_spec: str = "") -> RepoEntry | None:
        from .api import satisfies
        candidates = [m for m in self.mods if m.id == mod_id]
        if version_spec:
            candidates = [m for m in candidates if satisfies(m.version, version_spec)]
        if not candidates:
            return None
        # Newest version wins.
        from .api import _parse_v  # type: ignore[attr-defined]
        candidates.sort(key=lambda e: _parse_v(e.version), reverse=True)
        return candidates[0]


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


@sdk_export("repo.sha256_file")
def sha256_file(path: Path) -> str:
    """Hex SHA256 of a file, streamed (no full-file buffering).

    The integrity primitive behind `repo.json` manifests and
    :func:`sign_file` / :func:`verify_file`.
    """
    from rsmm.engine.hashing import sha256_file as _impl
    return _impl(path)


# ---------------------------------------------------------------------------
# Ed25519 sign / verify (optional dep on `cryptography`)
# ---------------------------------------------------------------------------


def _load_crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        return Ed25519PrivateKey, Ed25519PublicKey, serialization
    except Exception:  # noqa: BLE001
        return None


@sdk_export("repo.sign_file")
def sign_file(path: Path, private_key_path: Path) -> str:
    """Return base64 Ed25519 signature of `path`'s SHA256 digest.

    Signing the digest (not the whole file) lets verifiers stream-hash
    without buffering the file.
    """
    crypto = _load_crypto()
    if crypto is None:
        raise RepoError(
            "Signing requires the 'cryptography' package "
            "(`pip install cryptography`). Or ship unsigned + accept the warning."
        )
    Ed25519PrivateKey, _Pub, _ser = crypto
    key_bytes = base64.b64decode(private_key_path.read_text(encoding="utf-8").strip())
    key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    digest_hex = sha256_file(path)
    sig = key.sign(digest_hex.encode("ascii"))
    return base64.b64encode(sig).decode("ascii")


@sdk_export("repo.verify_file")
def verify_file(path: Path, sig_b64: str, public_key_path: Path) -> bool:
    """Verify a base64 Ed25519 signature over `path`'s SHA256 digest.

    Returns ``True`` if ``sig_b64`` (from :func:`sign_file`) matches under
    ``public_key_path``, ``False`` otherwise — a malformed signature is simply
    one that does not verify. Raises ``RepoError`` only for a malformed or
    unreadable public key.

    Verification must not depend on ``cryptography``: the CLI ships frozen
    with no runtime dependencies, so every released build lacked it and this
    raised on every call — which ``rsmm update`` then read as "verify skipped"
    and installed the archive without checking the signature at all. Without
    the package it uses the stdlib Ed25519 verifier the signed loader channel
    already relies on (:mod:`rsmm.engine.minisign`).
    """
    try:
        key_bytes = base64.b64decode(
            public_key_path.read_text(encoding="utf-8").strip(), validate=True)
    except (OSError, ValueError) as e:
        raise RepoError(f"unreadable public key {public_key_path}: {e}") from None
    if len(key_bytes) != 32:
        raise RepoError(f"public key {public_key_path} is not a raw 32-byte Ed25519 key")
    return _verify_digest(key_bytes, sha256_file(path), sig_b64)


def _verify_digest(key_bytes: bytes, digest_hex: str, sig_b64: str) -> bool:
    message = digest_hex.encode("ascii")
    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except (ValueError, TypeError):
        return False

    crypto = _load_crypto()
    if crypto is None:
        from rsmm.engine.minisign import MinisignError, ed25519_verify
        try:
            return ed25519_verify(key_bytes, message, signature)
        except MinisignError:
            return False
    _Priv, Ed25519PublicKey, _ser = crypto
    try:
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, message)
        return True
    except Exception:  # noqa: BLE001 — verify() raises InvalidSignature
        return False


def keygen() -> tuple[str, str]:
    """Generate an Ed25519 keypair. Returns (priv_b64, pub_b64)."""
    crypto = _load_crypto()
    if crypto is None:
        raise RepoError("keygen requires the 'cryptography' package")
    Ed25519PrivateKey, _Pub, ser = crypto
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=ser.Encoding.Raw,
        format=ser.PrivateFormat.Raw,
        encryption_algorithm=ser.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=ser.Encoding.Raw, format=ser.PublicFormat.Raw,
    )
    return base64.b64encode(priv_raw).decode("ascii"), base64.b64encode(pub_raw).decode("ascii")


# ---------------------------------------------------------------------------
# Install trust: signature + per-mod key pinning
# ---------------------------------------------------------------------------

PINS_NAME = "pins.json"


def _pins(keys_dir: Path) -> dict[str, str]:
    import json
    try:
        raw = json.loads((keys_dir / PINS_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # A pin file we cannot read must not quietly become "no pins": that is
        # exactly the state in which a swapped key installs.
        raise RepoError(f"unreadable key pins {keys_dir / PINS_NAME}: {e}") from None
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _pin(keys_dir: Path, mod_id: str, pubkey_id: str) -> None:
    import json

    from rsmm.engine.safeio import atomic_write_text
    pins = _pins(keys_dir)
    pins[mod_id] = pubkey_id
    keys_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(keys_dir / PINS_NAME, json.dumps(pins, indent=2, sort_keys=True) + "\n")


@dataclass
class Trust:
    """Outcome of :func:`check_entry`. ``ok`` False = refuse. ``warn`` = install
    only after the user confirms (unsigned, or a signer we hold no key for)."""
    ok: bool
    warn: bool
    reason: str


def check_entry(digest_hex: str, entry: RepoEntry, keys_dir: Path) -> Trust:
    """Decide whether a downloaded archive (``digest_hex`` = its SHA-256) may
    install, by the index entry's signature and the signer pinned for its mod.

    Trust on first use: the first verified signature pins ``entry.pubkey_id``
    to ``entry.id`` in ``<keys_dir>/pins.json``. After that a version signed by
    another key, or not signed at all, is refused: any key in ``keys_dir`` used
    to verify any mod, so whoever controlled the index could re-sign a mod with
    a different trusted key, or drop the signature, and it installed.
    """
    from .archive import safe_dir_name  # archive imports this module

    if digest_hex != entry.sha256:
        return Trust(False, False, f"sha256 mismatch: expected {entry.sha256}, got {digest_hex}")
    pinned = _pins(keys_dir).get(entry.id)
    if not entry.sig or not entry.pubkey_id:
        if pinned:
            return Trust(False, False, f"unsigned, but {entry.id} is pinned to signer "
                                       f"{pinned!r}; refusing (remove the pin in "
                                       f"{keys_dir / PINS_NAME} to accept it)")
        return Trust(True, True, "unsigned")
    # The id comes from the index. `../…` or an absolute path would reach a
    # .pub file anywhere, including one shipped inside an installed mod.
    try:
        safe_dir_name(entry.pubkey_id, what="signer id")
    except ValueError as e:
        return Trust(False, False, str(e))
    if pinned and pinned != entry.pubkey_id:
        return Trust(False, False, f"signed by {entry.pubkey_id!r}, but {entry.id} is pinned "
                                   f"to {pinned!r}; refusing (remove the pin in "
                                   f"{keys_dir / PINS_NAME} if the author changed keys)")
    pub = keys_dir / f"{entry.pubkey_id}.pub"
    if not pub.exists():
        return Trust(True, True, f"unknown signer {entry.pubkey_id!r} (no key in {keys_dir})")
    try:
        key_bytes = base64.b64decode(pub.read_text(encoding="utf-8").strip(), validate=True)
    except (OSError, ValueError) as e:
        return Trust(False, False, f"unreadable public key {pub}: {e}")
    # Can't verify is a refusal, not a pass.
    if len(key_bytes) != 32 or not _verify_digest(key_bytes, digest_hex, entry.sig):
        return Trust(False, False, f"signature INVALID ({entry.pubkey_id})")
    if not pinned:
        _pin(keys_dir, entry.id, entry.pubkey_id)
        return Trust(True, False, f"signature ok ({entry.pubkey_id}, now pinned for {entry.id})")
    return Trust(True, False, f"signature ok ({entry.pubkey_id})")


def confirm_untrusted(what: str, yes: bool) -> bool:
    """Ask before installing something unverified. ``--yes`` answers for the
    user; with no terminal to ask and no ``--yes`` the answer is no."""
    import sys
    if yes:
        return True
    if not sys.stdin.isatty():
        print(f"  {what}: not verified; pass --yes to install it anyway", file=sys.stderr)
        return False
    return input(f"  {what}: not verified. Install anyway? [y/N] ").strip().lower() == "y"
