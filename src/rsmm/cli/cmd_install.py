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
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from rsmm.engine.paths import MODS_DIR
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


def _fetch(url_or_path: str) -> bytes:
    """Read bytes from an http(s)/file URL or a bare local path."""
    if "://" not in url_or_path:
        return Path(url_or_path).read_bytes()
    with urllib.request.urlopen(url_or_path) as r:  # noqa: S310 (intended)
        return r.read()


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


def _safe_extract(data: bytes, dest_root: Path) -> str:
    """Extract a packed-mod zip into ``dest_root`` (which becomes
    ``dest_root/<id>/``). Returns the mod id. Rejects zip-slip and archives
    that aren't a single top-level dir."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        tops = {n.replace("\\", "/").split("/", 1)[0] for n in names}
        if len(tops) != 1:
            raise RepoError(
                f"archive must contain exactly one top-level mod dir, got {sorted(tops)}")
        mod_id = tops.pop()
        dest_root.mkdir(parents=True, exist_ok=True)
        root_res = dest_root.resolve()
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = (dest_root / member.filename).resolve()
            if not str(target).startswith(str(root_res)):
                raise RepoError(f"unsafe path in archive: {member.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as out:
                out.write(src.read())
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
    if target.endswith(".zip"):
        try:
            data = _fetch(target)
        except OSError as e:
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
    try:
        data = _fetch(entry.url)
    except OSError as e:
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
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        tops = {n.replace("\\", "/").split("/", 1)[0]
                for n in zf.namelist() if n.strip("/")}
    mod_id = next(iter(tops)) if len(tops) == 1 else None
    if mod_id and (MODS_DIR / mod_id).exists() and not force:
        print(f"{mod_id} already installed at {MODS_DIR / mod_id}; "
              f"use --force to overwrite", file=sys.stderr)
        return 1
    if mod_id and force:
        import shutil
        shutil.rmtree(MODS_DIR / mod_id, ignore_errors=True)

    try:
        installed = _safe_extract(data, MODS_DIR)
    except (RepoError, zipfile.BadZipFile) as e:
        print(f"install failed: {e}", file=sys.stderr)
        return 1
    print(f"installed {installed} -> {MODS_DIR / installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
