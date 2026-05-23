#!/usr/bin/env python3
"""Bump the desktop release version across every file that has to agree.

Four files hold the user-facing release version and must move in lockstep
on every release (the updater feed in `apps/desktop/UPDATER.md` and CI's
release.yml both rely on `tauri.conf.json` matching the git tag, while
the Cargo build refuses to start if Cargo.lock disagrees with Cargo.toml):

    apps/desktop/src-tauri/tauri.conf.json   ("version": "X.Y.Z")
    apps/desktop/src-tauri/Cargo.toml        (version = "X.Y.Z")
    apps/desktop/src-tauri/Cargo.lock        ([[package]] name = "rsmm-desktop")
    apps/desktop/package.json                ("version": "X.Y.Z")

Usage:
    python scripts/bump-version.py patch          # 0.1.10 -> 0.1.11
    python scripts/bump-version.py minor          # 0.1.10 -> 0.2.0
    python scripts/bump-version.py major          # 0.1.10 -> 1.0.0
    python scripts/bump-version.py 0.1.15         # explicit version
    python scripts/bump-version.py patch --tag    # also create & push the v* git tag
    python scripts/bump-version.py patch --dry-run

The script is idempotent (re-running with the same target version is a
no-op) and refuses to write if it can't find the expected line in any of
the four files — better to fail loudly than ship a half-bumped release.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class Target:
    """One file + the exact line pattern we replace inside it.

    `pattern` must match exactly one line that contains the current
    version. `template` produces the replacement using the new version.
    """
    path: Path
    pattern: re.Pattern[str]
    template: str  # use {v} placeholder
    label: str


def targets() -> list[Target]:
    return [
        Target(
            path=REPO_ROOT / "apps/desktop/src-tauri/tauri.conf.json",
            pattern=re.compile(r'^(\s*"version"\s*:\s*)"[^"]+"(,?\s*)$', re.MULTILINE),
            template=r'\g<1>"{v}"\g<2>',
            label="tauri.conf.json",
        ),
        Target(
            path=REPO_ROOT / "apps/desktop/src-tauri/Cargo.toml",
            # First `version = "..."` after the [package] header.
            pattern=re.compile(
                r'(\[package\][\s\S]*?\nversion\s*=\s*)"[^"]+"',
            ),
            template=r'\g<1>"{v}"',
            label="Cargo.toml",
        ),
        Target(
            path=REPO_ROOT / "apps/desktop/src-tauri/Cargo.lock",
            # The rsmm-desktop crate's [[package]] entry.
            pattern=re.compile(
                r'(name\s*=\s*"rsmm-desktop"\s*\nversion\s*=\s*)"[^"]+"',
            ),
            template=r'\g<1>"{v}"',
            label="Cargo.lock",
        ),
        Target(
            path=REPO_ROOT / "apps/desktop/package.json",
            pattern=re.compile(r'^(\s*"version"\s*:\s*)"[^"]+"(,?\s*)$', re.MULTILINE),
            template=r'\g<1>"{v}"\g<2>',
            label="apps/desktop/package.json",
        ),
    ]


def current_version() -> str:
    """Read the canonical version from tauri.conf.json — every other file
    must agree, and the release workflow keys off this file."""
    path = REPO_ROOT / "apps/desktop/src-tauri/tauri.conf.json"
    text = path.read_text(encoding="utf-8")
    m = re.search(r'"version"\s*:\s*"([^"]+)"', text)
    if not m:
        sys.exit(f"could not find version in {path}")
    return m.group(1)


def bump_semver(current: str, kind: str) -> str:
    # `patch` / `minor` / `major` always re-base on a clean MAJOR.MINOR.PATCH,
    # which means any pre-release suffix (e.g. `0.1.11-alpha.1`) is dropped
    # rather than incremented. If you want to roll a pre-release, pass an
    # explicit version string instead of a bump kind.
    base = current.split("-", 1)[0]
    parts = base.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        sys.exit(f"current version {current!r} is not a clean MAJOR.MINOR.PATCH")
    major, minor, patch = (int(p) for p in parts)
    if kind == "patch":
        patch += 1
    elif kind == "minor":
        minor += 1
        patch = 0
    elif kind == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        sys.exit(f"unknown bump kind: {kind}")
    return f"{major}.{minor}.{patch}"


def resolve_new_version(arg: str, current: str) -> str:
    if arg in {"patch", "minor", "major"}:
        return bump_semver(current, arg)
    if SEMVER_RE.match(arg):
        return arg
    sys.exit(
        f"invalid version arg {arg!r}: expected 'patch', 'minor', 'major', "
        f"or an explicit semver like '0.1.15'"
    )


def apply(target: Target, new_version: str, dry_run: bool) -> bool:
    text = target.path.read_text(encoding="utf-8")
    replacement = target.template.format(v=new_version)
    new_text, n = target.pattern.subn(replacement, text, count=1)
    if n != 1:
        sys.exit(
            f"refusing to bump: expected exactly one match in {target.label}, "
            f"found {n}. The file may have been restructured — update "
            f"scripts/bump-version.py and rerun."
        )
    if new_text == text:
        return False
    if not dry_run:
        target.path.write_text(new_text, encoding="utf-8")
    return True


def git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=check, text=True, capture_output=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bump the desktop release version across every file in lockstep.",
    )
    ap.add_argument(
        "version",
        help="'patch' | 'minor' | 'major' | explicit semver (e.g. '0.1.15')",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="show what would change, don't write",
    )
    ap.add_argument(
        "--tag", action="store_true",
        help="after bumping, create commit + tag v<NEW> and push both",
    )
    ap.add_argument(
        "--no-commit", action="store_true",
        help="write the files and stop. Forbids --tag (you can't tag without "
             "a commit).",
    )
    args = ap.parse_args()

    # Reject the contradictory combination up front. Without this the script
    # falls past both early-return guards below and silently commits + tags
    # despite `--no-commit`, which is the opposite of what the flag promises.
    if args.no_commit and args.tag:
        sys.exit("--no-commit and --tag are mutually exclusive: a tag needs a commit")

    current = current_version()
    new = resolve_new_version(args.version, current)

    if new == current:
        print(f"already at {current} — nothing to do")
        return 0

    print(f"bumping {current} -> {new}")
    changed_any = False
    for t in targets():
        if not t.path.exists():
            sys.exit(f"missing file: {t.path}")
        changed = apply(t, new, args.dry_run)
        marker = "would update" if args.dry_run else ("updated" if changed else "unchanged")
        print(f"  [{marker}] {t.label}")
        changed_any |= changed

    if args.dry_run:
        print("(dry run — no files written)")
        return 0

    if not changed_any:
        # Shouldn't happen given the current != new check above, but the
        # belt-and-braces defense costs nothing.
        print("no files changed")
        return 0

    if args.no_commit:
        print("done. files written; commit + tag yourself when ready.")
        return 0

    # Commit only the four files we touched — don't sweep in unrelated
    # working-tree changes.
    paths = [str(t.path.relative_to(REPO_ROOT)) for t in targets()]
    git(["add", *paths])
    msg = f"chore(release): bump to {new}"
    git(["commit", "-m", msg])
    print(f"committed: {msg}")

    if args.tag:
        tag = f"v{new}"
        git(["tag", tag])
        # Push the current branch + the new tag. Atomic refuses if either
        # ref is behind, so we don't accidentally overwrite a remote tag.
        branch = git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        git(["push", "--atomic", "origin", branch, tag])
        print(f"pushed {branch} + {tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
