"""One transport policy for everything rsmm fetches from the network.

Three commands pull bytes off the internet — `rsmm install`, `rsmm update`,
and the desktop bridge's `json install-mod` — and each had grown its own idea
of which URLs are acceptable and how much data to accept. Same reasoning as
`engine/hashing.py` and `sdk/archive.py`: a rule enforced in three places is
enforced at the strength of its weakest copy.

Two rules, both about mod archives specifically:

* **Transport must carry integrity.** The SHA-256 (and the Ed25519 signature,
  when there is one) that authenticate an archive are themselves read from the
  index over the same connection, so plaintext HTTP means an on-path attacker
  rewrites the bytes *and* the digest that would have caught them. `https` is
  required. `file://` is allowed where offline installs are a feature, and
  plain HTTP is allowed against loopback, where there is no path to be on.

* **Responses are bounded.** A download is buffered or written to disk before
  its digest can be checked, so a hostile or compromised index that streams
  forever exhausts memory or fills the disk before anything gets to reject it.

Stdlib only: the CLI ships frozen with no runtime dependencies.
"""

from __future__ import annotations

import urllib.parse
from typing import Protocol

#: Ceiling for a mod archive. The largest real mods are tens of MB of cooked
#: assets; this leaves room for an outlier without letting a stream run away.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

#: Ceiling for an index/metadata document. `repo.json` and the registry's
#: `/api/mods/<slug>` responses are kilobytes.
MAX_METADATA_BYTES = 32 * 1024 * 1024

#: Seconds before a connection that accepts but never sends is abandoned.
DEFAULT_TIMEOUT = 60.0

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class UnsafeURL(ValueError):
    """A URL was rejected before any connection was attempted."""


class TooLarge(ValueError):
    """A response exceeded its byte ceiling."""


class _Reader(Protocol):
    def read(self, n: int, /) -> bytes: ...


def is_loopback(host: str | None) -> bool:
    """True for hosts that cannot be reached from off-machine."""
    if not host:
        return False
    return host.lower().strip("[]") in _LOOPBACK_HOSTS


def require_safe_url(url: str, *, allow_file: bool = False) -> None:
    """Raise :class:`UnsafeURL` unless `url` is safe to fetch mod data from.

    `allow_file` enables `file://`, which `rsmm install` wants (installing a
    packed archive off disk, and the offline tests) but the registry client
    does not — a `file://` index base is never a real deployment.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as e:
        raise UnsafeURL(f"unparseable URL: {url}") from e
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return
    if scheme == "file" and allow_file:
        return
    if scheme == "http" and is_loopback(parsed.hostname):
        return
    raise UnsafeURL(
        f"refusing to fetch over {scheme or 'no'} scheme: {url}\n"
        "  mod data must come from https://"
        + (" (or file:// for local installs)" if allow_file else "")
    )


def read_capped(reader: _Reader, source: str, limit: int = MAX_DOWNLOAD_BYTES,
                chunk: int = 1 << 16) -> bytes:
    """Read `reader` fully, raising :class:`TooLarge` past `limit`.

    Fails rather than truncating: a silently short read turns a hostile
    response into a checksum mismatch, which reads like a corrupt mirror
    rather than the attack it is.
    """
    buf = bytearray()
    while True:
        block = reader.read(chunk)
        if not block:
            return bytes(buf)
        buf += block
        if len(buf) > limit:
            raise TooLarge(f"{source} exceeds the {limit}-byte limit")


def copy_capped(reader: _Reader, out, source: str,
                limit: int = MAX_DOWNLOAD_BYTES, chunk: int = 1 << 20,
                hasher=None) -> int:
    """Stream `reader` into the file object `out`; return bytes written.

    The streaming counterpart to :func:`read_capped`, for downloads that go
    straight to disk instead of being buffered. `hasher` (anything with
    ``update``) is fed each block, so a digest can be computed in the same
    pass rather than by re-reading the file.
    """
    total = 0
    while True:
        block = reader.read(chunk)
        if not block:
            return total
        total += len(block)
        if total > limit:
            raise TooLarge(f"{source} exceeds the {limit}-byte limit")
        if hasher is not None:
            hasher.update(block)
        out.write(block)
