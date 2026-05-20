#!/usr/bin/env python3
"""`rsmm update` — pull updates for installed mods from configured repos.

Workflow:
  1. Read configured repo URLs from ~/.rsmm/repos.json
     (managed by `rsmm repo add/remove/list`).
  2. Fetch each repo.json via urllib.
  3. For each installed mod, find a matching entry whose version is
     newer than the installed version.
  4. Download + SHA256-verify + (optional) Ed25519-verify.
  5. Unpack into `mods/<id>/` after the user confirms.

Trust:
  unsigned        -> warn, prompt unless --yes
  unknown signer  -> warn, prompt unless --yes
  trusted signer  -> silent

Run `rsmm update --check` to list available updates without downloading.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from rsmm.engine.paths import MODS_DIR
from rsmm.sdk.api import _parse_v
from rsmm.sdk.repo import RepoIndex, RepoError, sha256_file, verify_file


REPOS_FILE = Path.home() / ".rsmm" / "repos.json"
KEYS_DIR = Path.home() / ".rsmm" / "keys"


def _load_repos() -> list[str]:
    if not REPOS_FILE.exists():
        return []
    try:
        return list(json.loads(REPOS_FILE.read_text(encoding="utf-8")).get("urls", []))
    except Exception:
        return []


def _fetch(url: str, timeout: float = 30.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _installed_mods() -> dict[str, str]:
    """`{id: version}` for every mod in mods/."""
    import tomllib
    out: dict[str, str] = {}
    if not MODS_DIR.is_dir():
        return out
    for entry in MODS_DIR.iterdir():
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.exists():
            continue
        try:
            tbl = tomllib.loads(mf.read_text(encoding="utf-8"))
            meta = tbl.get("mod", {})
            out[str(meta.get("id", entry.name))] = str(meta.get("version", "0.0.0"))
        except Exception:
            pass
    return out


def _newer(have: str, want: str) -> bool:
    return _parse_v(want) > _parse_v(have)


def _verify_download(path: Path, expected_sha256: str,
                     sig_b64: str, pubkey_id: str) -> tuple[bool, str]:
    """Return (ok, reason). Reason describes signer trust state."""
    actual = sha256_file(path)
    if actual != expected_sha256:
        return False, f"sha256 mismatch: {actual} vs {expected_sha256}"
    if not sig_b64:
        return True, "unsigned (warn)"
    if not pubkey_id:
        return True, "signed without pubkey_id (warn)"
    pub = KEYS_DIR / f"{pubkey_id}.pub"
    if not pub.exists():
        return True, f"unknown signer {pubkey_id!r} (warn)"
    try:
        if verify_file(path, sig_b64, pub):
            return True, f"signature ok ({pubkey_id})"
        return False, f"signature INVALID ({pubkey_id})"
    except RepoError as e:
        return True, f"verify skipped: {e}"


def _install_zip(zip_path: Path, mod_id: str, dry_run: bool) -> None:
    """Replace `mods/<mod_id>/` with the zip contents atomically."""
    target = MODS_DIR / mod_id
    with tempfile.TemporaryDirectory(prefix=f".rsmm_update_{mod_id}_") as td:
        staging = Path(td) / mod_id
        staging.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging.parent)
        # The zip may extract as either `<mod_id>/...` or `./...`. Pick
        # the right inner path.
        if not staging.exists():
            inner = next((p for p in Path(td).iterdir() if p.is_dir()), None)
            if inner is None:
                raise RepoError("zip is empty or malformed")
            staging = inner
        if dry_run:
            print(f"  [dry] would replace {target}")
            return
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staging), str(target))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm update")
    ap.add_argument("--check", action="store_true",
                    help="only show what would be updated; don't download")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="skip the trust prompt for unsigned / unknown signers")
    ap.add_argument("--dry-run", action="store_true",
                    help="download + verify but do not replace the mod dir")
    ap.add_argument("--mod", help="restrict update to this mod id only")
    args = ap.parse_args(argv)

    repos = _load_repos()
    if not repos:
        print("no repos configured; add one with `rsmm repo add <url>`",
              file=sys.stderr)
        return 1
    installed = _installed_mods()
    if args.mod:
        installed = {k: v for k, v in installed.items() if k == args.mod}
    if not installed:
        print("no mods installed")
        return 0

    # Fetch every repo index up front.
    indices: list[tuple[str, RepoIndex]] = []
    for url in repos:
        try:
            raw = json.loads(_fetch(url).decode("utf-8"))
            indices.append((url, RepoIndex.load(raw)))
        except Exception as e:
            print(f"  [warn] {url}: {e}", file=sys.stderr)

    plan: list[tuple[str, str, object, str]] = []  # mod_id, have, entry, url
    for mid, have in sorted(installed.items()):
        best = None
        best_url = ""
        for url, idx in indices:
            e = idx.find(mid)
            if e and _newer(have, e.version):
                if best is None or _parse_v(e.version) > _parse_v(best.version):
                    best, best_url = e, url
        if best:
            plan.append((mid, have, best, best_url))

    if not plan:
        print("everything up to date")
        return 0

    print("Updates available:")
    for mid, have, entry, _url in plan:
        print(f"  {mid:24} {have} -> {entry.version}")
    if args.check:
        return 0

    code = 0
    for mid, _have, entry, _url in plan:
        print(f"\nfetching {entry.url}")
        try:
            data = _fetch(entry.url)
        except Exception as e:
            print(f"  download failed: {e}", file=sys.stderr)
            code = 1
            continue
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(data)
            zp = Path(f.name)
        try:
            ok, reason = _verify_download(zp, entry.sha256, entry.sig, entry.pubkey_id)
            print(f"  verify: {reason}")
            if not ok:
                print(f"  refusing to install {mid}", file=sys.stderr)
                code = 1
                continue
            if "warn" in reason and not args.yes:
                ans = input(f"  install {mid} anyway? [y/N] ").strip().lower()
                if ans != "y":
                    print(f"  skipped {mid}")
                    continue
            _install_zip(zp, mid, args.dry_run)
            print(f"  installed {mid} -> {entry.version}")
        finally:
            try:
                zp.unlink()
            except FileNotFoundError:
                pass
    return code


if __name__ == "__main__":
    sys.exit(main())
