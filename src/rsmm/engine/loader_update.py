"""Out-of-band update channel for the loader DLL and the Lua SDK.

Why this exists
---------------
`winhttp.dll` and `src/loader/lib/*.lua` are baked into the PyInstaller
sidecar, which is baked into the Tauri desktop bundle. That made a
one-line `rsmm.lua` change cost a full desktop release *and* a reinstall
on every user's machine — even though the SDK is disk-loaded and a plain
file copy would have done it.

This is the same shape as `rsmm.engine.data_update` (the pattern DB
channel), one tier up: a rolling GitHub release tagged ``loader`` carries
a signed manifest plus a tarball, and `rsmm update-loader` plants it into
the game install. The Python CLI and the desktop UI stay on the Tauri
updater — they are the things doing the planting.

Payload layout (inside ``loader-bundle.tar.gz``)::

    winhttp.dll     -> <game>/winhttp.dll
    lib/*.lua       -> <game>/rsmm/lib/*.lua

That mapping is an allowlist, not a hint: any other member aborts the
update, so a hostile tarball cannot write outside those two destinations.

Security
--------
This channel plants code that is injected into the game process. The
manifest is signed with the same minisign key that signs the desktop
bundles, every payload file is hashed in the manifest, and verification
is **mandatory and fail-closed** — there is no unsigned path, no
hash-only fallback and no override flag. If anything fails to verify, the
already-planted loader is left exactly as it was.

Compatibility
-------------
The manifest declares an integer ``abi``. When a loader change also needs
new *planting* logic on this side, the abi is bumped and older CLIs
refuse the update and report that the app itself must be updated, rather
than planting a DLL they do not know how to install.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from rsmm.engine.hashing import sha256_file
from rsmm.engine.minisign import MinisignError
from rsmm.engine.minisign import verify as minisign_verify
from rsmm.engine.paths import DATA_DIR, REPO_ROOT

MANIFEST_NAME = "loader.manifest.json"
SIGNATURE_NAME = "loader.manifest.json.minisig"
BUNDLE_NAME = "loader-bundle.tar.gz"
VERSION_FILE = "loader_version.json"

# Highest payload layout this CLI knows how to plant. A remote manifest
# above this is refused (see module docstring).
SUPPORTED_ABI = 1

DEFAULT_REMOTE_BASE = (
    "https://github.com/Ovilli/RavenswatchModManager/releases/download/loader"
)

# Same minisign key that signs the desktop bundles — the pubkey in
# apps/desktop/src-tauri/tauri.conf.json. Embedded rather than read from
# that file because tauri.conf.json is not bundled into the frozen
# sidecar. tests/test_loader_update.py asserts the two stay identical.
PUBLIC_KEY = (
    "untrusted comment: minisign public key: C2FF9DF953A0E966\n"
    "RWRm6aBT+Z3/wpi/ys0CTprsRAFvzG+zsYddJUHzlqak/Krvwy4AmeTG\n"
)

# Destination prefixes inside the bundle -> path under the game dir.
# Longest prefix wins, so "lib/" is matched before the bare-file rule.
_DESTINATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lib/", ("rsmm", "lib")),
    ("winhttp.dll", ()),
)

_TIMEOUT = 60.0
_MAX_BUNDLE_BYTES = 64 * 1024 * 1024


class LoaderUpdateError(Exception):
    pass


class ChannelNotPublishedError(LoaderUpdateError):
    """The rolling release has no manifest yet.

    Distinct from a transport failure: until the first
    `scripts/publish_loader.sh` run the assets legitimately 404, and every
    build shipped before then would otherwise report a hard error on each
    launch for a channel that simply is not live.
    """


class AbiTooNewError(LoaderUpdateError):
    """The published payload needs a newer rsmm to plant it.

    A distinct type because it is a real answer, not a transport failure:
    `check()` turns it into a "needs_app_update" status so the UI can say
    "update the app". Matching on the message text instead also caught
    "manifest has no integer 'abi'", which told the user to update the app
    when the actual fault was a malformed manifest.
    """


# --- locations ------------------------------------------------------------

def remote_base() -> str:
    return os.environ.get("RSMM_LOADER_UPDATE_BASE", "").strip() or DEFAULT_REMOTE_BASE


def public_key() -> str:
    """The key every payload is verified against.

    `RSMM_LOADER_UPDATE_PUBKEY` substitutes one, but **only in a source
    checkout**. In a frozen build — which is what every end user runs —
    the embedded key is the only key, because an env var that swaps the
    trust root is an env var that installs an arbitrary DLL into the game
    process. Devs and tests need the override; users must not have it.

    It was never a way to *disable* verification: an empty or invalid
    override still goes through `minisign.verify`.
    """
    if not getattr(sys, "frozen", False):
        override = os.environ.get("RSMM_LOADER_UPDATE_PUBKEY", "").strip()
        if override:
            return override
    return PUBLIC_KEY


def cache_dir(game_dir: Path) -> Path:
    """Where a downloaded bundle is kept so `install-loader` can replant it."""
    return game_dir / "rsmm" / "cache" / "loader"


def planted_manifest_path(game_dir: Path) -> Path:
    return game_dir / "rsmm" / MANIFEST_NAME


def bundled_version() -> int:
    """Loader version shipped inside this rsmm build (0 when unstamped)."""
    try:
        data = json.loads((DATA_DIR / VERSION_FILE).read_text(encoding="utf-8"))
        return int(data.get("loader_version", 0))
    except (OSError, ValueError, TypeError):
        return 0


def planted_manifest(game_dir: Path) -> dict | None:
    try:
        data = json.loads(planted_manifest_path(game_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def planted_manifest_version(game_dir: Path) -> int | None:
    """What the game dir ACTUALLY holds, or None if nothing is planted.

    Unlike `planted_version` this does not fold in the bundled stamp, so it
    answers the question the running game answers: which SDK will load?
    """
    m = planted_manifest(game_dir)
    if not m:
        return None
    v = m.get("loader_version")
    return v if isinstance(v, int) else None


def bundled_loader_dll() -> Path:
    """The winhttp.dll this build carries. Same relative path in a source
    checkout and in a frozen bundle (REPO_ROOT resolves to _MEIPASS)."""
    return REPO_ROOT / "dist" / "winhttp.dll"


def plant_matches_bundle(game_dir: Path) -> bool | None:
    """Does the game dir hold the same loader binary this build carries?

    True / False / None when it cannot be told (either file missing, or the
    bundle has no DLL — a source checkout that has never built one).

    This is the only signal available when the game dir has NO planted
    manifest, which is the normal state after `install-loader`: that path
    plants the bundled copy and writes no manifest, so `planted_version` falls
    back to the bundled stamp and every version comparison says "current" no
    matter how old the files on disk actually are.
    """
    src, dst = bundled_loader_dll(), game_dir / "winhttp.dll"
    try:
        if not src.is_file() or not dst.is_file():
            return None
        # Size first: a mismatch settles it without hashing 5 MB on a path
        # that runs at every launch check.
        if src.stat().st_size != dst.stat().st_size:
            return False
        return sha256_file(src) == sha256_file(dst)
    except OSError:
        return None


def planted_version(game_dir: Path) -> int:
    """Highest loader version present in the game dir — planted or bundled.

    `install-loader` plants the bundled copy, so a game dir with no
    manifest is at `bundled_version()`, not at zero.

    ⚠ This is the UPDATE-ELIGIBILITY figure, not "what is installed". The max
    is what stops the channel re-planting a payload this build already
    carries, but it also hides an OLDER planted copy behind a newer bundled
    stamp — and the older copy is the one the game loads. On 2026-08-24 that
    read "loader is up to date (v7)" while `<game>/rsmm` held v6 and the SDK
    fix under test was not in the process at all. Use
    `planted_manifest_version` for anything a user reads, and see the
    `plant_stale` flag on `check()`.
    """
    m = planted_manifest(game_dir)
    planted = int(m.get("loader_version", 0)) if m else 0
    return max(planted, bundled_version())


# --- fetch + verify -------------------------------------------------------

def _allowed_schemes() -> tuple[str, ...]:
    """HTTPS always; ``file://`` only in a source checkout.

    Tests and local dry-runs serve a channel off the filesystem. A frozen
    build — what every user runs — has no reason to read one, so it cannot.
    The signature already makes transport untrusted, so this narrows the
    surface rather than providing the guarantee.
    """
    if getattr(sys, "frozen", False):
        return ("https://",)
    return ("https://", "file://")


def _fetch(url: str, limit: int | None = None,
           on_progress: Callable[[int, int], None] | None = None) -> bytes:
    """Fetch a payload, optionally reporting (received, total) as it arrives.

    The bundle is a few MB over a link nobody can predict, and without progress
    the desktop can only show a spinner that says nothing — the same download
    the app's own updater draws a bar for. `total` is 0 when the server sends
    no Content-Length, which the caller must render as "unknown", never as 0%.
    """
    if not url.startswith(_allowed_schemes()):
        raise LoaderUpdateError(f"refusing to fetch non-HTTPS URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "rsmm-update-loader"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            if on_progress is None:
                data = r.read(limit + 1) if limit else r.read()
            else:
                try:
                    total = int(r.headers.get("Content-Length") or 0)
                except ValueError:
                    total = 0
                cap = (limit + 1) if limit else None
                chunks: list[bytes] = []
                got = 0
                on_progress(0, total)
                while True:
                    want = 1 << 16
                    if cap is not None:
                        want = min(want, cap - got)
                        if want <= 0:
                            break
                    chunk = r.read(want)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    got += len(chunk)
                    on_progress(got, total)
                data = b"".join(chunks)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ChannelNotPublishedError(
                "the loader update channel has nothing published yet"
            ) from e
        raise LoaderUpdateError(f"fetch failed: {url}: {e}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LoaderUpdateError(f"fetch failed: {url}: {e}") from e
    if limit and len(data) > limit:
        raise LoaderUpdateError(f"payload exceeds {limit} bytes: {url}")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_manifest(manifest: dict) -> None:
    abi = manifest.get("abi")
    if not isinstance(abi, int):
        raise LoaderUpdateError("manifest has no integer 'abi'")
    if abi > SUPPORTED_ABI:
        raise AbiTooNewError(
            f"this loader bundle needs a newer rsmm (payload abi {abi}, "
            f"this build supports {SUPPORTED_ABI}) — update the app first"
        )
    if not isinstance(manifest.get("loader_version"), int):
        raise LoaderUpdateError("manifest has no integer 'loader_version'")
    if not isinstance(manifest.get("bundle_sha256"), str):
        raise LoaderUpdateError("manifest has no 'bundle_sha256'")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise LoaderUpdateError("manifest lists no files")
    seen: set[str] = set()
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) \
                or not isinstance(f.get("sha256"), str):
            raise LoaderUpdateError("manifest file entry missing path/sha256")
        resolve_destination(f["path"])  # raises on anything outside the allowlist
        # A repeated path means two hashes for one destination, and which one
        # wins would depend on dict ordering. Refuse instead of picking.
        if f["path"] in seen:
            raise LoaderUpdateError(f"manifest lists {f['path']!r} twice")
        seen.add(f["path"])


# Bundle members are plain relative POSIX paths. Anything else — a drive
# letter, an NTFS alternate data stream ("x.lua:evil"), a control character,
# a trailing dot or space that Windows silently strips — is refused rather
# than reasoned about. The manifest is signed, so this is defence in depth
# against a compromised publish, not against the network.
_MEMBER_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*$")


def resolve_destination(member: str) -> tuple[str, ...]:
    """Map a bundle member path to its game-relative destination parts.

    Raises for anything outside the allowlist — absolute paths, ``..``,
    Windows separators and unknown prefixes all land here.
    """
    if member != member.strip() or not member:
        raise LoaderUpdateError(f"bundle member has a suspicious name: {member!r}")
    if member.startswith("/") or "\\" in member or ".." in member.split("/"):
        raise LoaderUpdateError(f"bundle member escapes the payload root: {member!r}")
    for segment in member.split("/"):
        if not _MEMBER_RE.match(segment) or segment.endswith("."):
            raise LoaderUpdateError(
                f"bundle member has an illegal path segment {segment!r}: {member!r}"
            )
    for prefix, dest in _DESTINATIONS:
        if prefix.endswith("/"):
            if member.startswith(prefix):
                tail = member[len(prefix):]
                if not tail or tail.endswith("/"):
                    raise LoaderUpdateError(f"bundle member is not a file: {member!r}")
                return (*dest, *tail.split("/"))
        elif member == prefix:
            return (*dest, member)
    raise LoaderUpdateError(
        f"bundle member {member!r} is not one of the destinations this "
        f"rsmm plants ({', '.join(p for p, _ in _DESTINATIONS)})"
    )


def fetch_manifest(base: str | None = None) -> dict:
    """Fetch the remote manifest and its signature; verify before parsing use.

    The signature is checked against the raw bytes, so a manifest that
    fails verification is never acted on in any form.
    """
    base = base or remote_base()
    raw = _fetch(f"{base}/{MANIFEST_NAME}", limit=1 << 20)
    sig = _fetch(f"{base}/{SIGNATURE_NAME}", limit=1 << 16)
    try:
        minisign_verify(raw, sig.decode("utf-8", "replace"), public_key())
    except MinisignError as e:
        raise LoaderUpdateError(f"manifest signature rejected: {e}") from e
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise LoaderUpdateError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(manifest, dict):
        raise LoaderUpdateError("manifest is not a JSON object")
    _validate_manifest(manifest)
    manifest["_raw"] = raw
    manifest["_signature"] = sig.decode("utf-8", "replace")
    return manifest


def _plant_stale(game_dir: Path) -> bool:
    """Shared by `check`'s early returns; see the comment in `check`."""
    planted = planted_manifest_version(game_dir)
    if planted is not None:
        return planted < bundled_version()
    return plant_matches_bundle(game_dir) is False


def check(game_dir: Path) -> dict:
    """Compare the remote manifest against what is installed. Manifest fetch
    only — the bundle itself is not downloaded here."""
    base = remote_base()
    have = planted_version(game_dir)
    try:
        manifest = fetch_manifest(base)
    except ChannelNotPublishedError:
        return {
            "status": "not_published",
            "remote_base": base,
            "installed_version": have,
            "planted_version": planted_manifest_version(game_dir),
            "bundled_version": bundled_version(),
            "plant_stale": _plant_stale(game_dir),
        }
    except AbiTooNewError as e:
        # A real answer, not a transport failure: report it as a status so
        # the UI can say "update the app" rather than showing an error.
        return {
            "status": "needs_app_update",
            "remote_base": base,
            "installed_version": have,
            "planted_version": planted_manifest_version(game_dir),
            "bundled_version": bundled_version(),
            "plant_stale": _plant_stale(game_dir),
            "error": str(e),
        }

    remote_version = int(manifest["loader_version"])
    planted_now = planted_manifest_version(game_dir)
    # A plant that is not what this build carries. `install-loader` fixes it;
    # `update-loader` cannot, because the channel is not what is behind.
    #
    # Two ways to be behind, and the second is the one that bit on 2026-08-24:
    #   * a manifest with an older version — the plain case; or
    #   * NO manifest, because `install-loader` planted and wrote none, while
    #     the bytes on disk are not the ones this build ships. Version
    #     comparison is blind to that (planted_version falls back to the
    #     bundled stamp), so `update-loader` said "up to date (v8)" over a game
    #     dir running an SDK from an older desktop build.
    if planted_now is not None:
        plant_stale = planted_now < bundled_version()
    else:
        plant_stale = plant_matches_bundle(game_dir) is False
    if remote_version > have:
        status = "update_available"
    elif remote_version == have:
        status = "up_to_date"
    else:
        status = "ahead"  # local build is newer than the channel

    return {
        "status": status,
        "remote_base": base,
        "installed_version": have,
        "planted_version": planted_now,
        "bundled_version": bundled_version(),
        "plant_stale": plant_stale,
        "remote_version": remote_version,
        "rsmm_version": manifest.get("rsmm_version"),
        "generated": manifest.get("generated"),
        "notes": manifest.get("notes"),
        "file_count": len(manifest["files"]),
        "_manifest": manifest,
    }


# --- extract + plant ------------------------------------------------------

def _extract_bundle(raw: bytes, manifest: dict, dest: Path) -> list[tuple[str, Path]]:
    """Unpack the tarball into *dest* and check every member against the
    manifest. Returns (member, extracted_path) pairs.

    Members are read one at a time and written by hand rather than via
    ``TarFile.extractall``: symlinks, hardlinks, devices and directory
    traversal are all rejected instead of merely being unlikely.
    """
    expected = {f["path"]: f for f in manifest["files"]}
    written: list[tuple[str, Path]] = []
    seen: set[str] = set()

    with tempfile.TemporaryDirectory() as td:
        blob = Path(td) / BUNDLE_NAME
        blob.write_bytes(raw)
        with tarfile.open(blob, "r:gz") as tf:
            for member in tf:
                name = member.name
                if name in (".", "./"):
                    continue
                name = name[2:] if name.startswith("./") else name
                if member.isdir():
                    continue
                if not member.isreg():
                    raise LoaderUpdateError(
                        f"bundle member {name!r} is not a regular file"
                    )
                spec = expected.get(name)
                if spec is None:
                    raise LoaderUpdateError(
                        f"bundle member {name!r} is not listed in the manifest"
                    )
                parts = resolve_destination(name)
                fh = tf.extractfile(member)
                if fh is None:
                    raise LoaderUpdateError(f"bundle member {name!r} is unreadable")
                data = fh.read()
                if _sha256(data) != spec["sha256"]:
                    raise LoaderUpdateError(f"bundle member {name!r} failed its hash")
                out = dest.joinpath(*parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
                written.append((name, out))
                seen.add(name)

    missing = sorted(set(expected) - seen)
    if missing:
        raise LoaderUpdateError(f"bundle is missing manifest files: {missing[:4]}")
    return written


# A plant is a multi-file, non-atomic operation. Two of them interleaving
# (the desktop's launch check racing a hand-run CLI, or two app windows) can
# mix files from different versions into one install. The lock is advisory
# and best-effort — losing it costs one skipped update, never a broken one.
_LOCK_NAME = ".loader-update.lock"
_LOCK_STALE_SECONDS = 15 * 60


@contextmanager
def _update_lock(game_dir: Path):
    """Serialise planting per game directory.

    Uses O_CREAT|O_EXCL, which is atomic on Windows and POSIX alike. A lock
    older than `_LOCK_STALE_SECONDS` is assumed to be from a process that
    died mid-update and is reclaimed — otherwise one crash would wedge
    updates permanently, which is worse than the race it prevents.
    """
    lock = game_dir / "rsmm" / _LOCK_NAME
    lock.parent.mkdir(parents=True, exist_ok=True)

    def _acquire() -> int:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    try:
        fd = _acquire()
    except FileExistsError:
        try:
            stale = (time.time() - lock.stat().st_mtime) > _LOCK_STALE_SECONDS
        except OSError:
            stale = True
        if not stale:
            raise LoaderUpdateError(
                "another rsmm loader update is already running — "
                "wait for it to finish, or delete "
                f"{lock} if nothing is"
            ) from None
        lock.unlink(missing_ok=True)
        try:
            fd = _acquire()
        except FileExistsError:  # lost the reclaim race; the winner proceeds
            raise LoaderUpdateError(
                "another rsmm loader update is already running"
            ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _plant_file(src: Path, dst: Path) -> None:
    """Atomically replace *dst* with *src*'s bytes.

    Windows refuses to replace a DLL the game has mapped, which is the
    common case for `winhttp.dll` — surface that as "close the game"
    rather than a bare PermissionError.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    # PID-qualified: two planters sharing one staging name means the first
    # one's os.replace consumes the second's file, and the second fails with
    # a bewildering ENOENT on a path it just wrote.
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.rsmm-new")
    shutil.copyfile(src, tmp)
    try:
        os.replace(tmp, dst)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise LoaderUpdateError(
            f"{dst.name} is in use — close Ravenswatch and run this again"
        ) from e
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise LoaderUpdateError(f"could not write {dst}: {e}") from e


def _cache_bundle(game_dir: Path, manifest: dict, payload: Path) -> Path:
    """Keep the verified payload so `install-loader` can replant it.

    `restore --all` wipes the loader out of the game dir, and
    `install-loader` replants the copy bundled in this rsmm build. Without
    a cache every restore would silently roll users back to the shipped
    loader and this whole channel would be undone by a routine command.
    """
    cache = cache_dir(game_dir)
    staging = cache.with_name(cache.name + ".new")
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(payload, staging / "payload")
    (staging / MANIFEST_NAME).write_bytes(manifest["_raw"])
    (staging / SIGNATURE_NAME).write_text(manifest["_signature"], encoding="utf-8")
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    staging.replace(cache)
    return cache


def _preflight_writable(game_dir: Path, manifest: dict) -> None:
    """Fail before planting anything if a destination cannot be replaced.

    The DLL is locked for as long as Ravenswatch is running, and Windows
    refuses to replace a mapped image. Discovering that *after* the Lua SDK
    has been planted leaves a new SDK against an old DLL — and the SDK calls
    into the DLL, so a call the old build does not export is a runtime error
    inside every mod. Probing first makes the running-game case plant
    nothing at all, which is the only state that is trivially correct.

    Only an outright "cannot write here" aborts. Anything the probe cannot
    determine is allowed through to the real plant, which is itself guarded.
    """
    for f in manifest["files"]:
        dst = game_dir.joinpath(*resolve_destination(f["path"]))
        try:
            if dst.exists():
                # Opening for write is what actually fails on a mapped DLL;
                # existence and permission bits do not.
                with open(dst, "r+b"):
                    pass
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise LoaderUpdateError(
                f"{dst.name} is in use — close Ravenswatch and run this again"
            ) from e
        except OSError as e:
            raise LoaderUpdateError(f"cannot write {dst}: {e}") from e


def _plant_payload(game_dir: Path, manifest: dict, payload: Path) -> list[str]:
    """Copy the verified payload into the game dir, DLL last.

    `_preflight_writable` has already established that every destination is
    replaceable, so this should not fail — but the DLL is still planted last
    so that losing a race with a game launched in between leaves the old DLL
    with the old SDK's *entry points* still resolvable, rather than a new DLL
    under an old SDK.
    """
    _preflight_writable(game_dir, manifest)
    entries = [f["path"] for f in manifest["files"]]
    entries.sort(key=lambda p: (p == "winhttp.dll", p))
    planted = []
    for name in entries:
        parts = resolve_destination(name)
        _plant_file(payload.joinpath(*parts), game_dir.joinpath(*parts))
        planted.append("/".join(parts))
    return planted


def apply_update(game_dir: Path, state: dict | None = None,
                 on_progress: Callable[[int, int], None] | None = None) -> dict:
    """Download, verify and plant the remote bundle.

    `on_progress(received, total)` is called as the bundle downloads, so a UI
    can draw a real meter instead of an indeterminate spinner.
    """
    if state is None:
        state = check(game_dir)
    if state["status"] == "needs_app_update":
        raise LoaderUpdateError(state["error"])

    manifest = state.get("_manifest") or fetch_manifest(state["remote_base"])
    raw = _fetch(f"{state['remote_base']}/{BUNDLE_NAME}", limit=_MAX_BUNDLE_BYTES,
                 on_progress=on_progress)
    if _sha256(raw) != manifest["bundle_sha256"]:
        raise LoaderUpdateError(
            "bundle hash does not match the signed manifest — refusing to plant"
        )

    with _update_lock(game_dir), tempfile.TemporaryDirectory() as td:
        payload = Path(td) / "payload"
        _extract_bundle(raw, manifest, payload)
        planted = _plant_payload(game_dir, manifest, payload)
        _cache_bundle(game_dir, manifest, payload)

        # Stamped LAST, and only once every file is in place: an interrupted
        # plant then still reads as the old version and is simply redone,
        # rather than claiming a version it only partly installed.
        path = planted_manifest_path(game_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(manifest["_raw"])
        os.replace(tmp, path)

    out = {k: v for k, v in state.items() if not k.startswith("_")}
    out["status"] = "updated"
    out["installed_version"] = int(manifest["loader_version"])
    out["planted"] = planted
    return out


def replant_cached(game_dir: Path) -> dict | None:
    """Re-plant a cached bundle that is newer than this build's bundled one.

    Called by `install-loader` after the platform script has planted the
    bundled loader, so a `restore --all` / `install-loader` cycle does not
    downgrade a user who already pulled a newer loader. Re-verifies the
    cached manifest signature — the cache lives in the game directory and
    is not a trusted store. Returns None when there is nothing to do.
    """
    cache = cache_dir(game_dir)
    raw_path, sig_path, payload = (
        cache / MANIFEST_NAME, cache / SIGNATURE_NAME, cache / "payload",
    )
    if not (raw_path.exists() and sig_path.exists() and payload.is_dir()):
        return None
    raw = raw_path.read_bytes()
    try:
        minisign_verify(raw, sig_path.read_text(encoding="utf-8"), public_key())
        manifest = json.loads(raw.decode("utf-8"))
        _validate_manifest(manifest)
    except (MinisignError, ValueError, LoaderUpdateError) as e:
        raise LoaderUpdateError(f"cached loader bundle rejected: {e}") from e

    if int(manifest["loader_version"]) <= bundled_version():
        return None

    for f in manifest["files"]:
        parts = resolve_destination(f["path"])
        src = payload.joinpath(*parts)
        # Check the declared size before reading: the cache is on disk in a
        # directory anyone can write, and hashing an arbitrarily large file
        # to discover it is wrong is a needless way to run out of memory.
        size = f.get("size")
        if not src.is_file() or (isinstance(size, int) and src.stat().st_size != size):
            raise LoaderUpdateError(
                f"cached loader payload is corrupt at {f['path']} — "
                f"run `rsmm update-loader` to re-download it"
            )
        if _sha256(src.read_bytes()) != f["sha256"]:
            raise LoaderUpdateError(
                f"cached loader payload is corrupt at {f['path']} — "
                f"run `rsmm update-loader` to re-download it"
            )

    with _update_lock(game_dir):
        planted = _plant_payload(game_dir, manifest, payload)
        shutil.copyfile(raw_path, planted_manifest_path(game_dir))
    return {"loader_version": int(manifest["loader_version"]), "planted": planted}
