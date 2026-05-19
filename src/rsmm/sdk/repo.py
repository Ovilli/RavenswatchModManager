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
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    def from_dict(cls, raw: dict) -> "RepoEntry":
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
    def load(cls, raw: dict) -> "RepoIndex":
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

    def find(self, mod_id: str, version_spec: str = "") -> Optional[RepoEntry]:
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
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Ed25519 sign / verify (optional dep on `cryptography`)
# ---------------------------------------------------------------------------


def _load_crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey, Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives import serialization
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
    Ed25519PrivateKey, _Pub, ser = crypto
    key_bytes = base64.b64decode(private_key_path.read_text(encoding="utf-8").strip())
    key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    digest_hex = sha256_file(path)
    sig = key.sign(digest_hex.encode("ascii"))
    return base64.b64encode(sig).decode("ascii")


@sdk_export("repo.verify_file")
def verify_file(path: Path, sig_b64: str, public_key_path: Path) -> bool:
    crypto = _load_crypto()
    if crypto is None:
        raise RepoError(
            "Verification requires the 'cryptography' package "
            "(`pip install cryptography`)."
        )
    _Priv, Ed25519PublicKey, ser = crypto
    key_bytes = base64.b64decode(public_key_path.read_text(encoding="utf-8").strip())
    pub = Ed25519PublicKey.from_public_bytes(key_bytes)
    digest_hex = sha256_file(path)
    try:
        pub.verify(base64.b64decode(sig_b64), digest_hex.encode("ascii"))
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
