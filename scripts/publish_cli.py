#!/usr/bin/env python3
"""Publish the frozen CLI to the rolling, signed `cli` release.

`rsmm json update-cli` (src/rsmm/engine/cli_update.py) consumes it, so a Python
change reaches users without a desktop release. Run from
.github/workflows/publish-cli.yml:

    python scripts/build-sidecar.py --onedir --require-loader   # per platform
    python scripts/publish_cli.py pack --out <dir>              # per platform
    python scripts/publish_cli.py publish --archives <dir> --notes "..." [--dry-run]

`publish` bumps data/cli_version.json; commit the bump, or the next app build
embeds a stamp lower than the channel and keeps preferring the channel copy.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from rsmm.engine.cli_update import (  # noqa: E402
    MANIFEST_NAME,
    SIGNATURE_NAME,
    platform_key,
    validate_manifest,
)
from rsmm.engine.loader_update import public_key  # noqa: E402
from rsmm.engine.minisign import verify  # noqa: E402

ONEDIR = REPO / "dist" / "cli-onedir" / "rsmm"
STAMP = REPO / "data" / "cli_version.json"
TAG = "cli"


def archive_name(key: str) -> str:
    return f"rsmm-cli-{key}.tar.gz"


def pack(out: Path) -> None:
    if not ONEDIR.is_dir():
        sys.exit(f"missing {ONEDIR}: run scripts/build-sidecar.py --onedir first")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / archive_name(platform_key())

    def norm(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        ti.mtime = 0
        return ti

    # dereference: PyInstaller's onedir symlinks some shared libs, and the
    # client refuses links outright (cli_update.extract_archive).
    with tarfile.open(dest, "w:gz", dereference=True) as tf:
        for p in sorted(ONEDIR.rglob("*")):
            tf.add(p, arcname=p.relative_to(ONEDIR).as_posix(), recursive=False, filter=norm)
    print(f"packed {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sign(manifest: Path) -> Path:
    """Same key and the same unwrap as scripts/publish_loader.sh."""
    sig = manifest.with_name(SIGNATURE_NAME)
    key = os.environ.get("TAURI_SIGNING_PRIVATE_KEY")
    if not key:
        sys.exit("no signing key: set TAURI_SIGNING_PRIVATE_KEY (+ _PASSWORD)")
    env = {**os.environ, "TAURI_PRIVATE_KEY": key,
           "TAURI_PRIVATE_KEY_PASSWORD": os.environ.get("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")}
    subprocess.run(["pnpm", "--silent", "--filter", "desktop", "exec", "tauri", "signer",
                    "sign", str(manifest)], env=env, check=True, cwd=REPO)
    wrapped = manifest.with_name(manifest.name + ".sig").read_bytes()
    try:
        text = base64.b64decode(wrapped, validate=True).decode()
    except ValueError:
        text = wrapped.decode()
    if not text.startswith("untrusted comment"):
        sys.exit("signature is not in minisign format")
    sig.write_text(text, encoding="utf-8")
    return sig


def publish(archives: Path, notes: str, dry_run: bool) -> None:
    stamp = json.loads(STAMP.read_text(encoding="utf-8"))
    nxt = int(stamp["cli_version"]) + 1
    platforms = {}
    for key in ("linux-x86_64", "windows-x86_64"):
        p = archives / archive_name(key)
        if not p.is_file():
            sys.exit(f"missing {p}")
        platforms[key] = {"name": p.name, "sha256": sha256(p), "size": p.stat().st_size}

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=REPO).stdout.strip() or None
    manifest = {
        "abi": int(stamp["abi"]),
        "cli_version": nxt,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rsmm_version": json.loads((REPO / "apps/desktop/package.json").read_text())["version"],
        "commit": commit,
        "notes": notes or None,
        "platforms": platforms,
    }
    stage = Path(tempfile.mkdtemp(prefix="rsmm-cli-publish-"))
    mpath = stage / MANIFEST_NAME
    mpath.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    sig = sign(mpath)

    # The client's own checks, before anything is uploaded.
    verify(mpath.read_bytes(), sig.read_text(encoding="utf-8"), public_key())
    validate_manifest(json.loads(mpath.read_text(encoding="utf-8")))
    print(f"ok: cli v{nxt} (abi {manifest['abi']}) signed and accepted by the client validator")

    if dry_run:
        print(f"dry run: not uploading. Artifacts in {stage}")
        return

    if subprocess.run(["gh", "release", "view", TAG], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", TAG, "--title", "CLI (rolling)",
                        "--latest=false", "--notes",
                        "Rolling, signed frozen CLI consumed by the desktop app "
                        "(`rsmm json update-cli`). Assets are replaced in place; do not pin."],
                       check=True)
    # Archives first: a manifest must never name an archive that is not up yet.
    subprocess.run(["gh", "release", "upload", TAG, "--clobber",
                    *(str(archives / p["name"]) for p in platforms.values())], check=True)
    subprocess.run(["gh", "release", "upload", TAG, "--clobber", str(mpath), str(sig)], check=True)

    stamp["cli_version"] = nxt
    STAMP.write_text(json.dumps(stamp, indent=1) + "\n", encoding="utf-8")
    print(f"published cli v{nxt}; COMMIT {STAMP.relative_to(REPO)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_pack = sub.add_parser("pack")
    p_pack.add_argument("--out", type=Path, required=True)
    p_pub = sub.add_parser("publish")
    p_pub.add_argument("--archives", type=Path, required=True)
    p_pub.add_argument("--notes", default="")
    p_pub.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "pack":
        pack(a.out)
    else:
        publish(a.archives, a.notes, a.dry_run)
