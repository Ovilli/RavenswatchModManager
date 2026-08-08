"""rsmm install — fetch, verify, and unpack a packed mod.

Closes the distribution loop opened by ``rsmm pack`` + the ``repo.json``
spec (:mod:`rsmm.sdk.repo`): mods were packable and indexable but not
installable. Resolution order:

    rsmm install <id> [version-spec]   # search configured repos
    rsmm install <url-to.zip>          # direct archive
    rsmm install <id> --from <repo.json-url-or-path>

The archive is the ``shutil.make_archive`` zip ``rsmm pack`` writes (a
single top-level ``<id>/`` dir). It is downloaded, its SHA256 checked
against the repo entry (unless ``--no-verify``), its Ed25519 signature
verified when the entry carries one and the pubkey is in ``~/.rsmm/keys``,
then extracted into ``mods/``. ``file://`` and bare local paths work, so
this is fully testable offline.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from rsmm.engine.paths import MODS_DIR
from rsmm.sdk.archive import require_single_top_dir, safe_extract, scan_dangerous
from rsmm.sdk.repo import RepoError, RepoIndex, verify_file

# Reuse the same locations the `repo`/`sign` commands use.
from .repo_cmd import KEYS_DIR, _load_repos

_USAGE = (
    "usage: rsmm install <id|url.zip> [version-spec] [--from REPO] "
    "[--no-verify] [--force]\n"
    "\n"
    "Fetch + verify + unpack a packed mod into mods/.\n"
    "  <id>           resolve from configured repos (`rsmm repo add`)\n"
    "  <url.zip>      install a packed archive directly\n"
    "  version-spec   semver constraint, e.g. '>=1.2,<2'\n"
    "  --from REPO    repo.json url/path to resolve from (skips config)\n"
    "  --no-verify    skip the SHA256/signature check (not recommended)\n"
    "  --force        overwrite an already-installed mod\n"
)


#: Downloads are buffered in memory (the SHA256 and the signature both cover
#: the whole archive), so the transfer needs its own ceiling independent of
#: the uncompressed-size cap enforced during extraction.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

#: Seconds. A repo that accepts the connection and then never sends a byte
#: would otherwise hang `rsmm install` forever.
FETCH_TIMEOUT = 60.0

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _check_url(url: str) -> None:
    """Refuse fetch schemes that give no integrity guarantee.

    The checksum and signature that authenticate an archive are themselves
    read from ``repo.json`` over the same transport, so plaintext HTTP means
    an on-path attacker rewrites both and the verification proves nothing.
    ``file://`` is allowed (offline installs, tests) and plain HTTP is allowed
    only against loopback, where there is no path to be on.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in ("https", "file"):
        return
    if parsed.scheme == "http" and (parsed.hostname or "") in _LOCAL_HOSTS:
        return
    raise RepoError(
        f"refusing to fetch over {parsed.scheme or 'no'} scheme: {url}\n"
        "  mod archives must come from https:// (or file:// for local installs)"
    )


def _read_capped(reader, source: str) -> bytes:
    """Read at most :data:`MAX_DOWNLOAD_BYTES`, then fail rather than truncate.

    Silently truncating would turn a hostile response into a checksum
    mismatch, which reads like a corrupt mirror instead of an attack.
    """
    buf = bytearray()
    while True:
        chunk = reader.read(1 << 16)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > MAX_DOWNLOAD_BYTES:
            raise RepoError(
                f"{source} exceeds the {MAX_DOWNLOAD_BYTES}-byte download limit")


def _fetch(url_or_path: str) -> bytes:
    """Read bytes from an https/file URL or a bare local path."""
    if "://" not in url_or_path:
        with open(url_or_path, "rb") as f:
            return _read_capped(f, url_or_path)
    _check_url(url_or_path)
    with urllib.request.urlopen(  # noqa: S310 — scheme checked by _check_url
        url_or_path, timeout=FETCH_TIMEOUT
    ) as r:
        return _read_capped(r, url_or_path)


def _load_index(repo: str) -> RepoIndex:
    import json
    return RepoIndex.load(json.loads(_fetch(repo).decode("utf-8")))


def _resolve(mod_id: str, version: str, repos: list[str]):
    """Return (RepoEntry, repo_url) for the first repo that has the id."""
    for repo in repos:
        try:
            entry = _load_index(repo).find(mod_id, version)
        except (RepoError, OSError, ValueError) as e:
            print(f"  [warn] skipping repo {repo}: {e}", file=sys.stderr)
            continue
        if entry:
            return entry, repo
    return None, None


def _peek_mod_id(data: bytes) -> str:
    """Validated mod id of a packed archive, without extracting anything.

    The id names a directory that ``--force`` deletes, so it must never be
    taken from the archive unchecked: a zip whose members all start with
    ``../`` yields ``..``, and ``mods/..`` is the repo root.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return require_single_top_dir(zf)


def _safe_extract(data: bytes, dest_root: Path) -> str:
    """Unpack a packed-mod zip so it lands at ``dest_root/<id>/``.

    Returns the mod id. Extraction runs in a staging directory alongside the
    destination and is moved into place only once every member is written, so
    a rejected entry or a truncated stream cannot leave a half-installed mod
    that ``rsmm apply`` would then happily walk.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        mod_id = require_single_top_dir(zf)
        for rel in scan_dangerous(zf, mod_id):
            print(f"  [WARN] {mod_id} overwrites game install root file: {rel}",
                  file=sys.stderr)
        dest_root.mkdir(parents=True, exist_ok=True)
        final = dest_root / mod_id   # mod_id validated as a plain dir name
        with tempfile.TemporaryDirectory(
            prefix=f".rsmm_install_{mod_id}_", dir=dest_root
        ) as td:
            staging = Path(td) / mod_id
            safe_extract(zf, staging, strip_prefix=f"{mod_id}/", label=mod_id)
            if final.is_dir():
                shutil.rmtree(final)
            elif final.exists():
                final.unlink()
            shutil.move(str(staging), str(final))
    return mod_id


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0 if argv else 2

    pos: list[str] = []
    repo_override: str | None = None
    no_verify = force = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--from":
            i += 1
            repo_override = argv[i] if i < len(argv) else None
        elif a == "--no-verify":
            no_verify = True
        elif a == "--force":
            force = True
        else:
            pos.append(a)
        i += 1

    if not pos:
        print(_USAGE, file=sys.stderr)
        return 2
    target = pos[0]
    version = pos[1] if len(pos) > 1 else ""

    # --- direct archive url -------------------------------------------
    # Match on the URL path so a cache-busting query string (registry asset
    # URLs carry one) doesn't hide the .zip suffix.
    if urllib.parse.urlparse(target).path.endswith(".zip"):
        try:
            data = _fetch(target)
        except (OSError, RepoError) as e:
            print(f"download failed: {e}", file=sys.stderr)
            return 1
        return _finish(data, None, no_verify, force)

    # --- resolve id from repos ----------------------------------------
    repos = [repo_override] if repo_override else _load_repos()
    if not repos:
        print("no repos configured; `rsmm repo add <url>` or pass --from REPO",
              file=sys.stderr)
        return 1
    entry, repo = _resolve(target, version, repos)
    if not entry:
        print(f"mod {target!r}{' ' + version if version else ''} not found in "
              f"{len(repos)} repo(s)", file=sys.stderr)
        return 1
    print(f"resolving {entry.id} {entry.version} from {repo}")
    if entry.size and entry.size > MAX_DOWNLOAD_BYTES:
        print(f"refusing {entry.id}: repo declares {entry.size} bytes, over the "
              f"{MAX_DOWNLOAD_BYTES}-byte limit", file=sys.stderr)
        return 1
    try:
        data = _fetch(entry.url)
    except (OSError, RepoError) as e:
        print(f"download failed: {e}", file=sys.stderr)
        return 1
    return _finish(data, entry, no_verify, force)


def _finish(data: bytes, entry, no_verify: bool, force: bool) -> int:
    # SHA256 + optional signature.
    if entry is not None and not no_verify:
        got = hashlib.sha256(data).hexdigest()
        if got != entry.sha256:
            print(f"checksum mismatch: expected {entry.sha256}, got {got}",
                  file=sys.stderr)
            return 1
        if entry.sig and entry.pubkey_id:
            pub = KEYS_DIR / f"{entry.pubkey_id}.pub"
            if not pub.exists():
                print(f"signed mod but pubkey {entry.pubkey_id!r} not in "
                      f"{KEYS_DIR}; install the key or use --no-verify",
                      file=sys.stderr)
                return 1
            with tempfile.NamedTemporaryFile() as tf:
                tf.write(data)
                tf.flush()
                if not verify_file(Path(tf.name), entry.sig, pub):
                    print("signature verification FAILED", file=sys.stderr)
                    return 1
            print("  signature ok")

    # Peek the mod id without extracting, to honor --force / collisions.
    try:
        mod_id = _peek_mod_id(data)
    except (RepoError, zipfile.BadZipFile) as e:
        print(f"install failed: {e}", file=sys.stderr)
        return 1
    if (MODS_DIR / mod_id).exists() and not force:
        print(f"{mod_id} already installed at {MODS_DIR / mod_id}; "
              f"use --force to overwrite", file=sys.stderr)
        return 1

    # The old code deleted the destination here, before extracting. Deleting
    # is now _safe_extract's last step, after a full staged unpack succeeded,
    # so a bad archive can no longer remove a working install.
    try:
        installed = _safe_extract(data, MODS_DIR)
    except (RepoError, zipfile.BadZipFile) as e:
        print(f"install failed: {e}", file=sys.stderr)
        return 1
    print(f"installed {installed} -> {MODS_DIR / installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
