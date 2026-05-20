#!/usr/bin/env python3
"""`rsmm repo`, `rsmm sign`, `rsmm verify`, `rsmm keygen`.

Distribution lives in `rsmm.sdk.repo`; this is the thin CLI wrapper.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rsmm.sdk.repo import (
    RepoError, RepoIndex, sha256_file, sign_file, verify_file, keygen,
)


KEYS_DIR = Path.home() / ".rsmm" / "keys"
REPOS_FILE = Path.home() / ".rsmm" / "repos.json"


def _load_repos() -> list[str]:
    if not REPOS_FILE.exists():
        return []
    try:
        return list(json.loads(REPOS_FILE.read_text(encoding="utf-8")).get("urls", []))
    except Exception:
        return []


def _save_repos(urls: list[str]) -> None:
    REPOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPOS_FILE.write_text(json.dumps({"urls": urls}, indent=2), encoding="utf-8")


def cmd_repo(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rsmm repo")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="show configured repo URLs")
    a = sub.add_parser("add")
    a.add_argument("url")
    r = sub.add_parser("remove")
    r.add_argument("url")
    v = sub.add_parser("validate")
    v.add_argument("path", type=Path,
        help="path to a local repo.json to validate")
    args = ap.parse_args(argv)

    if args.action == "list":
        for u in _load_repos():
            print(u)
        return 0
    if args.action == "add":
        urls = _load_repos()
        if args.url not in urls:
            urls.append(args.url)
            _save_repos(urls)
        print(f"added {args.url}")
        return 0
    if args.action == "remove":
        urls = [u for u in _load_repos() if u != args.url]
        _save_repos(urls)
        print(f"removed {args.url}")
        return 0
    if args.action == "validate":
        try:
            data = json.loads(args.path.read_text(encoding="utf-8"))
            idx = RepoIndex.load(data)
        except (RepoError, Exception) as e:
            print(f"invalid: {e}", file=sys.stderr)
            return 1
        print(f"ok: {idx.name} ({len(idx.mods)} mods)")
        return 0
    return 2


def cmd_sign(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rsmm sign")
    ap.add_argument("file", type=Path)
    ap.add_argument("--key", required=True,
                    help="key id under ~/.rsmm/keys/ (without .key suffix)")
    args = ap.parse_args(argv)
    pk = KEYS_DIR / f"{args.key}.key"
    if not pk.exists():
        print(f"key not found: {pk}", file=sys.stderr)
        return 1
    sig = sign_file(args.file, pk)
    sig_path = args.file.with_suffix(args.file.suffix + ".sig")
    sig_path.write_text(sig, encoding="utf-8")
    print(f"signed {args.file} -> {sig_path}")
    print(f"sha256 = {sha256_file(args.file)}")
    return 0


def cmd_verify(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rsmm verify")
    ap.add_argument("file", type=Path)
    ap.add_argument("--key", required=True,
                    help="key id under ~/.rsmm/keys/ (without .pub suffix)")
    ap.add_argument("--sig", type=Path, default=None,
                    help="signature file; defaults to <file>.sig")
    args = ap.parse_args(argv)
    pub = KEYS_DIR / f"{args.key}.pub"
    if not pub.exists():
        print(f"pubkey not found: {pub}", file=sys.stderr)
        return 1
    sig_path = args.sig or args.file.with_suffix(args.file.suffix + ".sig")
    if not sig_path.exists():
        print(f"sig file missing: {sig_path}", file=sys.stderr)
        return 1
    sig = sig_path.read_text(encoding="utf-8").strip()
    ok = verify_file(args.file, sig, pub)
    print("ok" if ok else "BAD SIGNATURE")
    return 0 if ok else 1


def cmd_keygen(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rsmm keygen")
    ap.add_argument("name", help="key id (file basename under ~/.rsmm/keys/)")
    args = ap.parse_args(argv)
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv, pub = keygen()
    priv_path = KEYS_DIR / f"{args.name}.key"
    pub_path = KEYS_DIR / f"{args.name}.pub"
    if priv_path.exists() or pub_path.exists():
        print(f"refusing to overwrite existing key files in {KEYS_DIR}",
              file=sys.stderr)
        return 1
    priv_path.write_text(priv, encoding="utf-8")
    pub_path.write_text(pub, encoding="utf-8")
    priv_path.chmod(0o600)
    print(f"wrote {priv_path} (mode 0600) and {pub_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Multiplex on argv[0] so the same module backs four `rsmm` subcommands
    # without duplicating the entry-points.
    argv = list(argv if argv is not None else sys.argv[1:])
    name = (argv[0:1] or ["repo"])[0]
    rest = argv[1:]
    if name == "repo":
        return cmd_repo(rest)
    if name == "sign":
        return cmd_sign(rest)
    if name == "verify":
        return cmd_verify(rest)
    if name == "keygen":
        return cmd_keygen(rest)
    print(f"unknown subcommand: {name}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
