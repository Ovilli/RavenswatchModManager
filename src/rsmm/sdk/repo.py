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
PINS_LOCK_NAME = "pins.lock"


@dataclass(frozen=True)
class Pin:
    """The signer a mod is pinned to: its key id and the SHA-256 of the key
    itself, so a key file swapped under the same name is not that signer.
    ``fpr`` is empty for a pin written before fingerprints were kept."""
    key: str
    fpr: str = ""


def pin_key(mod_id: str) -> str:
    """The pin-store key for a mod: the id case-folded, because ``Foo`` and
    ``foo`` are one folder on Windows and must not carry two pins."""
    return mod_id.casefold()


def _pins(keys_dir: Path) -> dict[str, Pin]:
    import json
    path = keys_dir / PINS_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # A pin file we cannot read must not quietly become "no pins": that is
        # exactly the state in which a swapped key installs.
        raise RepoError(f"unreadable key pins {path}: {e}") from None
    # The same holds for one that parses but is not a pin map (`[]` used to
    # read as "no pins", putting every pinned mod back on first-install
    # policy). Nothing is rewritten here, so the file stays for the user.
    if not isinstance(raw, dict):
        raise RepoError(f"key pins {path} is not a JSON object; fix or remove it")
    out: dict[str, Pin] = {}
    for k, v in raw.items():
        if isinstance(v, str) and v:
            pin = Pin(v)
        elif (isinstance(v, dict) and isinstance(v.get("key"), str) and v["key"]
              and isinstance(v.get("fpr", ""), str)):
            pin = Pin(v["key"], v.get("fpr", ""))
        else:
            raise RepoError(f"key pins {path}: bad entry for {k!r}; fix or remove it")
        out[pin_key(k)] = pin
    return out


def _write_pins(keys_dir: Path, pins: dict[str, Pin]) -> None:
    import json

    from rsmm.engine.safeio import atomic_write_text
    keys_dir.mkdir(parents=True, exist_ok=True)
    body = {k: {"key": v.key, "fpr": v.fpr} for k, v in sorted(pins.items())}
    atomic_write_text(keys_dir / PINS_NAME, json.dumps(body, indent=2) + "\n")


class pin_lock:
    """Hold ``<keys_dir>/pins.lock`` across a trust decision, the install it
    allows and the pin it records. Two installs reading the same pin map and
    each writing their own entry lost one of them; two first installs of one
    mod could each pin a different signer."""

    def __init__(self, keys_dir: Path) -> None:
        self.keys_dir = keys_dir
        self._fh = None

    def __enter__(self) -> pin_lock:
        import os
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        fh = open(self.keys_dir / PINS_LOCK_NAME, "a+b")  # held until __exit__
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                while True:
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:     # LK_LOCK gives up after ~10 s; keep waiting
                        continue
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except BaseException:
            fh.close()
            raise
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        import os
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


@dataclass
class Trust:
    """Outcome of :func:`check_entry`. ``ok`` False = refuse. ``warn`` = install
    only after the user confirms (unsigned, or a signer we hold no key for).
    ``pin``: ``(mod id, Pin)`` to record with :func:`record_pin` once the
    install succeeded; the check itself never writes."""
    ok: bool
    warn: bool
    reason: str
    pin: tuple[str, Pin] | None = None


def record_pin(keys_dir: Path, trust: Trust) -> None:
    """Persist ``trust.pin`` after a successful install. Call it inside the
    same :class:`pin_lock` as the check, so the store re-read here is the one
    the decision saw; a conflicting pin is still refused, not overwritten."""
    if trust.pin is None:
        return
    mod_id, pin = trust.pin
    pins = _pins(keys_dir)
    have = pins.get(pin_key(mod_id))
    if have is not None and have.key != pin.key:
        raise RepoError(f"{mod_id} is already pinned to {have.key!r}; not re-pinning "
                        f"it to {pin.key!r}")
    if have == pin:
        return
    pins[pin_key(mod_id)] = pin
    _write_pins(keys_dir, pins)


def check_unsigned(dest_id: str, keys_dir: Path, what: str) -> Trust:
    """Trust for an install with no signature to check (a direct archive URL,
    a registry download): allowed after consent, unless the mod it replaces
    is pinned to a signer, which it cannot prove it is."""
    have = _pins(keys_dir).get(pin_key(dest_id))
    if have is not None:
        return Trust(False, False, f"{what} cannot be verified, but {dest_id} is pinned "
                                   f"to signer {have.key!r}; refusing (install it from "
                                   f"a signed repo, or remove the pin in "
                                   f"{keys_dir / PINS_NAME})")
    return Trust(True, True, what)


def check_entry(digest_hex: str, entry: RepoEntry, keys_dir: Path, *,
                dest_id: str | None = None) -> Trust:
    """Decide whether a downloaded archive (``digest_hex`` = its SHA-256) may
    install, by the index entry's signature and the signer pinned for its mod.

    ``dest_id`` is the installed mod the archive will replace (its folder
    under ``mods/``); the pin consulted is that mod's, and the entry has to
    name the same mod. Trusting on ``entry.id`` while replacing whatever the
    archive's folder said let a mislabelled entry replace a different mod.

    Trust on first use: the first verified signature yields a pin for the
    mod (recorded by :func:`record_pin` once the install succeeds). After that
    a version signed by another key, not signed at all, or signed by a key
    whose file is missing or changed, is refused.
    """
    from .archive import safe_dir_name  # archive imports this module

    if digest_hex != entry.sha256:
        return Trust(False, False, f"sha256 mismatch: expected {entry.sha256}, got {digest_hex}")
    mod_id = entry.id if dest_id is None else dest_id
    if pin_key(entry.id) != pin_key(mod_id):
        return Trust(False, False, f"the index entry is for {entry.id!r} but the archive "
                                   f"replaces {mod_id!r}; refusing")
    pinned = _pins(keys_dir).get(pin_key(mod_id))
    if not entry.sig or not entry.pubkey_id:
        if pinned:
            return Trust(False, False, f"unsigned, but {mod_id} is pinned to signer "
                                       f"{pinned.key!r}; refusing (remove the pin in "
                                       f"{keys_dir / PINS_NAME} to accept it)")
        return Trust(True, True, "unsigned")
    # The id comes from the index. `../…` or an absolute path would reach a
    # .pub file anywhere, including one shipped inside an installed mod.
    try:
        safe_dir_name(entry.pubkey_id, what="signer id")
    except ValueError as e:
        return Trust(False, False, str(e))
    if pinned and pinned.key != entry.pubkey_id:
        return Trust(False, False, f"signed by {entry.pubkey_id!r}, but {mod_id} is pinned "
                                   f"to {pinned.key!r}; refusing (remove the pin in "
                                   f"{keys_dir / PINS_NAME} if the author changed keys)")
    pub = keys_dir / f"{entry.pubkey_id}.pub"
    if not pub.exists():
        if pinned:
            # The pinned signer's key is gone: this cannot be verified, and a
            # pinned mod never takes the unknown-signer consent path.
            return Trust(False, False, f"{mod_id} is pinned to {pinned.key!r}, but {pub} "
                                       f"is missing; refusing (restore the key)")
        return Trust(True, True, f"unknown signer {entry.pubkey_id!r} (no key in {keys_dir})")
    try:
        key_bytes = base64.b64decode(pub.read_text(encoding="utf-8").strip(), validate=True)
    except (OSError, ValueError) as e:
        return Trust(False, False, f"unreadable public key {pub}: {e}")
    fpr = hashlib.sha256(key_bytes).hexdigest()
    if pinned and pinned.fpr and pinned.fpr != fpr:
        return Trust(False, False, f"{pub} is not the key {mod_id} was pinned with "
                                   f"(fingerprint changed); refusing")
    # Can't verify is a refusal, not a pass.
    if len(key_bytes) != 32 or not _verify_digest(key_bytes, digest_hex, entry.sig):
        return Trust(False, False, f"signature INVALID ({entry.pubkey_id})")
    pin = Pin(entry.pubkey_id, fpr)
    if not pinned:
        return Trust(True, False, f"signature ok ({entry.pubkey_id}, pinned for {mod_id} "
                                  f"once installed)", pin=(mod_id, pin))
    # A pin from before fingerprints were kept gets one now.
    return Trust(True, False, f"signature ok ({entry.pubkey_id})",
                 pin=(mod_id, pin) if not pinned.fpr else None)


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
