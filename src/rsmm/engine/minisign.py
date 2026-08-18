"""Minisign signature verification — pure stdlib.

The loader update channel plants a DLL that gets injected into the game
process, so the payload is signed and verification is mandatory and
fail-closed (`rsmm.engine.loader_update`). The runtime CLI declares no
dependencies (`pyproject.toml`), so PyNaCl/cryptography are not options
and Ed25519 verification is implemented here from RFC 8032.

Verification only — this module can never produce a signature. Signing is
done by `tauri signer sign` in CI, with the same keypair that signs the
desktop bundles (pubkey in `apps/desktop/src-tauri/tauri.conf.json`).

Minisign wire format
--------------------
Public key file::

    untrusted comment: <text>
    base64( alg[2] || key_id[8] || public_key[32] )

Signature file::

    untrusted comment: <text>
    base64( alg[2] || key_id[8] || signature[64] )
    trusted comment: <text>
    base64( global_signature[64] )

``alg`` is ``Ed`` (sign the message as-is) or ``ED`` (sign its
BLAKE2b-512 hash). ``global_signature`` covers ``signature ||
trusted_comment`` and is what stops an attacker swapping the trusted
comment — which is where minisign users put version/filename metadata —
so it is verified too, not skipped.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

__all__ = ["MinisignError", "PublicKey", "Signature", "verify"]


class MinisignError(Exception):
    """Malformed key/signature, or a signature that does not verify."""


# --- Ed25519 (RFC 8032), verification half only ---------------------------

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _point_add(p, q):
    """Add two points in extended homogeneous coordinates (X, Y, Z, T)."""
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    dd = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


_G_Y = 4 * pow(5, _P - 2, _P) % _P
_G_X = pow((_G_Y * _G_Y - 1) * pow(_D * _G_Y * _G_Y + 1, _P - 2, _P), (_P + 3) // 8, _P)
if (_G_X * _G_X - ((_G_Y * _G_Y - 1) * pow(_D * _G_Y * _G_Y + 1, _P - 2, _P))) % _P != 0:
    _G_X = _G_X * _SQRT_M1 % _P
if _G_X % 2 != 0:
    _G_X = _P - _G_X
_B = (_G_X, _G_Y, 1, _G_X * _G_Y % _P)


def _scalar_mult(s: int, p):
    q = (0, 1, 1, 0)  # neutral element
    while s > 0:
        if s & 1:
            q = _point_add(q, p)
        p = _point_add(p, p)
        s >>= 1
    return q


def _point_equal(p, q) -> bool:
    # Projective coordinates: compare cross-multiplied affine values.
    if (p[0] * q[2] - q[0] * p[2]) % _P != 0:
        return False
    return (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _point_decompress(data: bytes):
    if len(data) != 32:
        raise MinisignError("Ed25519 point is not 32 bytes")
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        raise MinisignError("Ed25519 point y-coordinate out of range")

    # Recover x from the curve equation x^2 = (y^2 - 1) / (d*y^2 + 1).
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if x * x % _P != xx:
        x = x * _SQRT_M1 % _P
    if x * x % _P != xx:
        raise MinisignError("Ed25519 point is not on the curve")
    if x == 0 and sign:
        raise MinisignError("Ed25519 point has a non-canonical encoding")
    if x & 1 != sign:
        x = _P - x
    return (x, y, 1, x * y % _P)


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 Ed25519 verification. Returns False rather than raising on
    a signature that is merely wrong; raises only on malformed inputs."""
    if len(signature) != 64:
        raise MinisignError("Ed25519 signature is not 64 bytes")
    a = _point_decompress(public_key)
    r = _point_decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False  # non-canonical S — malleable, reject
    h = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(), "little"
    ) % _L
    return _point_equal(_scalar_mult(s, _B), _point_add(r, _scalar_mult(h, a)))


# --- Minisign container ---------------------------------------------------

_ALG_LEGACY = b"Ed"     # signature covers the raw message
_ALG_PREHASHED = b"ED"  # signature covers BLAKE2b-512(message)


def _b64(line: str, what: str) -> bytes:
    try:
        return base64.b64decode(line.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        raise MinisignError(f"{what}: not valid base64") from e


def _unwrap_b64(text: str, marker: str) -> str:
    """Undo the extra base64 layer Tauri wraps keys and signatures in.

    `tauri signer sign` writes its `.sig` as base64 of the whole minisign
    file, and `tauri.conf.json` stores the public key the same way. Plain
    minisign files pass through untouched.
    """
    stripped = text.strip()
    if not stripped or stripped.startswith(marker):
        return text
    try:
        inner = base64.b64decode(stripped, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return text
    return inner if inner.lstrip().startswith(marker) else text


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes
    key: bytes

    @classmethod
    def parse(cls, text: str) -> PublicKey:
        """Parse a minisign public-key file (comment line + base64 line).

        Also accepts the bare base64 line on its own, and the whole file
        wrapped in one more layer of base64 — which is how Tauri stores it
        in `tauri.conf.json`.
        """
        text = _unwrap_b64(text.strip(), "untrusted comment:")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise MinisignError("public key is empty")
        raw = _b64(lines[-1], "public key")
        if len(raw) != 42:
            raise MinisignError(f"public key payload is {len(raw)} bytes, expected 42")
        if raw[:2] != _ALG_LEGACY:
            raise MinisignError(f"unsupported public key algorithm: {raw[:2]!r}")
        return cls(key_id=raw[2:10], key=raw[10:])


@dataclass(frozen=True)
class Signature:
    alg: bytes
    key_id: bytes
    sig: bytes
    trusted_comment: str
    global_sig: bytes

    @classmethod
    def parse(cls, text: str) -> Signature:
        """Parse a minisign signature file.

        Also accepts the whole file wrapped in one more layer of base64,
        which is what `tauri signer sign` writes into its `.sig` — the
        same wrapping Tauri uses for public keys.
        """
        text = _unwrap_b64(text, "untrusted comment:")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 4:
            raise MinisignError(
                "signature file must have 4 lines "
                "(comment, signature, trusted comment, global signature)"
            )
        raw = _b64(lines[1], "signature")
        if len(raw) != 74:
            raise MinisignError(f"signature payload is {len(raw)} bytes, expected 74")
        alg = raw[:2]
        if alg not in (_ALG_LEGACY, _ALG_PREHASHED):
            raise MinisignError(f"unsupported signature algorithm: {alg!r}")
        prefix = "trusted comment:"
        if not lines[2].startswith(prefix):
            raise MinisignError("third line is not a trusted comment")
        global_sig = _b64(lines[3], "global signature")
        if len(global_sig) != 64:
            raise MinisignError("global signature is not 64 bytes")
        return cls(
            alg=alg,
            key_id=raw[2:10],
            sig=raw[10:],
            trusted_comment=lines[2][len(prefix):].lstrip(),
            global_sig=global_sig,
        )


def verify(message: bytes, signature_text: str, public_key_text: str) -> str:
    """Verify *message* against a minisign signature. Returns the trusted
    comment on success; raises `MinisignError` on any failure.

    There is deliberately no "skip" or "warn-only" path: the caller plants
    executable code, so a signature that does not verify must abort.
    """
    pk = PublicKey.parse(public_key_text)
    sg = Signature.parse(signature_text)

    if sg.key_id != pk.key_id:
        raise MinisignError(
            f"signature was made by key {sg.key_id[::-1].hex().upper()}, "
            f"expected {pk.key_id[::-1].hex().upper()}"
        )

    signed = (
        hashlib.blake2b(message, digest_size=64).digest()
        if sg.alg == _ALG_PREHASHED
        else message
    )
    if not ed25519_verify(pk.key, signed, sg.sig):
        raise MinisignError("signature does not match the payload")

    # The trusted comment is only trustworthy once the global signature over
    # (signature || comment) checks out; skipping it lets it be rewritten.
    if not ed25519_verify(
        pk.key, sg.sig + sg.trusted_comment.encode("utf-8"), sg.global_sig
    ):
        raise MinisignError("trusted comment signature does not match")
    return sg.trusted_comment
