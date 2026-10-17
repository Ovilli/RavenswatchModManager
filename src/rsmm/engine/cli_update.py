"""Out-of-band update channel for the frozen CLI itself.

The desktop app used to carry the only copy of the CLI, so every Python change
cost an app release. Now a rolling ``cli`` GitHub release carries a signed
manifest plus one PyInstaller ``--onedir`` archive per platform, and
``rsmm json update-cli --dest <dir>`` stages the newest one into
``<dir>/staged``. The app promotes ``staged`` to ``current`` on its next start,
before any CLI process runs, so a running copy is never replaced (Windows
cannot replace files a process holds open).

The app runs ``current`` only when its ``abi`` equals the app's and its
``cli_version`` is higher than the copy bundled in the app; otherwise it keeps
the bundled sidecar. Same key, same fail-closed verification as the loader
channel (`rsmm.engine.loader_update`).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

from rsmm.engine.loader_update import (
    ChannelNotPublishedError,
    LoaderUpdateError,
    _fetch,
    _sha256,
    public_key,
)
from rsmm.engine.minisign import MinisignError
from rsmm.engine.minisign import verify as minisign_verify
from rsmm.engine.paths import DATA_DIR

MANIFEST_NAME = "cli.manifest.json"
SIGNATURE_NAME = "cli.manifest.json.minisig"
VERSION_FILE = "cli_version.json"
STAMP_NAME = "channel.json"
DEFAULT_REMOTE_BASE = "https://github.com/Ovilli/RavenswatchModManager/releases/download/cli"
_MAX_ARCHIVE_BYTES = 300 * 1024 * 1024


class CliUpdateError(LoaderUpdateError):
    pass


def remote_base() -> str:
    return os.environ.get("RSMM_CLI_UPDATE_BASE", "").strip() or DEFAULT_REMOTE_BASE


def platform_key() -> str:
    return "windows-x86_64" if sys.platform == "win32" else "linux-x86_64"


def exe_name() -> str:
    return "rsmm.exe" if sys.platform == "win32" else "rsmm"


def own_stamp() -> tuple[int, int]:
    """(cli_version, abi) of the CLI that is running right now."""
    try:
        d = json.loads((DATA_DIR / VERSION_FILE).read_text(encoding="utf-8"))
        return int(d.get("cli_version", 0)), int(d.get("abi", 0))
    except (OSError, ValueError, TypeError):
        return 0, 0


def _stamp_version(d: Path) -> int:
    try:
        return int(json.loads((d / STAMP_NAME).read_text(encoding="utf-8"))["cli_version"])
    except (OSError, ValueError, TypeError, KeyError):
        return 0


def validate_manifest(m: dict) -> None:
    if not isinstance(m.get("abi"), int) or not isinstance(m.get("cli_version"), int):
        raise CliUpdateError("manifest has no integer 'abi' / 'cli_version'")
    plats = m.get("platforms")
    if not isinstance(plats, dict) or not plats:
        raise CliUpdateError("manifest lists no platforms")
    for key, p in plats.items():
        if not (isinstance(p, dict) and isinstance(p.get("name"), str)
                and isinstance(p.get("sha256"), str) and "/" not in p["name"]):
            raise CliUpdateError(f"manifest platform entry {key!r} is malformed")


def fetch_manifest(base: str) -> dict:
    raw = _fetch(f"{base}/{MANIFEST_NAME}", limit=1 << 20)
    sig = _fetch(f"{base}/{SIGNATURE_NAME}", limit=1 << 16)
    try:
        minisign_verify(raw, sig.decode("utf-8", "replace"), public_key())
    except MinisignError as e:
        raise CliUpdateError(f"manifest signature rejected: {e}") from e
    try:
        m = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CliUpdateError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(m, dict):
        raise CliUpdateError("manifest is not a JSON object")
    validate_manifest(m)
    return m


def _safe_member(name: str) -> str:
    name = name[2:] if name.startswith("./") else name
    if (not name or name.startswith("/") or "\\" in name or ":" in name
            or ".." in name.split("/") or any(ord(c) < 32 for c in name)):
        raise CliUpdateError(f"archive member escapes the payload root: {name!r}")
    return name


def extract_archive(archive: Path, dest: Path) -> None:
    """Regular files and directories only; links, devices and traversal refused."""
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            if member.name in (".", "./"):
                continue
            rel = _safe_member(member.name)
            target = dest.joinpath(*rel.split("/"))
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isreg():
                raise CliUpdateError(f"archive member {rel!r} is not a regular file")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            assert src is not None
            with src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if sys.platform != "win32":
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def run(dest: Path, check_only: bool = False,
        on_progress: Callable[[int, int], None] | None = None) -> dict:
    own_version, own_abi = own_stamp()
    have = max(own_version, _stamp_version(dest / "current"), _stamp_version(dest / "staged"))
    base = remote_base()
    state: dict = {"installed_version": have, "abi": own_abi}
    try:
        m = fetch_manifest(base)
    except ChannelNotPublishedError:
        return {**state, "status": "not_published"}

    remote = m["cli_version"]
    state.update(remote_version=remote, notes=m.get("notes"), generated=m.get("generated"))
    if m["abi"] != own_abi:
        # Higher abi: this app cannot drive that CLI. Lower: the app outgrew it.
        return {**state, "status": "needs_app_update" if m["abi"] > own_abi else "up_to_date"}
    if remote <= have:
        return {**state, "status": "up_to_date"}
    entry = m["platforms"].get(platform_key())
    if entry is None:
        return {**state, "status": "up_to_date"}
    if check_only:
        return {**state, "status": "update_available"}

    data = _fetch(f"{base}/{entry['name']}", limit=_MAX_ARCHIVE_BYTES, on_progress=on_progress)
    if _sha256(data) != entry["sha256"]:
        raise CliUpdateError("downloaded CLI archive does not match the signed manifest")

    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / f"staging-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        archive = tmp / entry["name"]
        archive.write_bytes(data)
        payload = tmp / "payload"
        payload.mkdir()
        extract_archive(archive, payload)
        if not (payload / exe_name()).is_file():
            raise CliUpdateError(f"archive has no top-level {exe_name()}")
        (payload / STAMP_NAME).write_text(json.dumps(
            {"cli_version": remote, "abi": m["abi"], "generated": m.get("generated")}),
            encoding="utf-8")
        staged = dest / "staged"
        shutil.rmtree(staged, ignore_errors=True)
        payload.rename(staged)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {**state, "status": "staged", "installed_version": remote}
