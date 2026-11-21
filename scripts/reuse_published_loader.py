#!/usr/bin/env python3
"""Put the PUBLISHED loader DLL in dist/ when it is the build this commit would make.

Why: every pipeline used to compile its own winhttp.dll — publish-loader.yml for
the loader channel, publish-cli.yml for the CLI channel, release.yml for the app
— and compiles are not byte-identical. So "loader v63" was three different files,
and the app's loader check (which trusts a DLL only when its hash matches the
planted manifest or the DLL the running CLI carries) called a perfectly good
plant "dev" whenever the DLL came from one pipeline and the CLI from another.
A player saw "dev · active" beside "Up to date" on 2026-11-21.

Reusing the channel's signed DLL makes one loader version one file. It is only
reused when it really is this commit's loader:

* the channel's `loader_version` equals this checkout's stamp
  (data/loader_version.json), and
* nothing the DLL is compiled from changed since the channel's `commit`:
  `src/loader/` minus the disk-loaded Lua SDK (`lib/`, `lua/`), which is not
  inside the DLL.

Anything else — channel behind or ahead, an unknown commit (shallow clone),
offline, a bad signature — prints why and reports `reused=false`, and the
workflow compiles as before. It never fails the job: compiling is always a
correct fallback, just one that brings back a second hash.

Writes `reused=true|false` to $GITHUB_OUTPUT when set.

Usage: python scripts/reuse_published_loader.py [--force]
  (meant for CI; --force replaces a local dist/winhttp.dll)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

#: What the DLL is built from, as git pathspecs (relative to the repo root).
DLL_INPUTS = [
    "src/loader",
    ":(exclude)src/loader/lib",
    ":(exclude)src/loader/lua",
]


def _output(reused: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"reused={'true' if reused else 'false'}\n")


def _dll_sources_unchanged(commit: str) -> tuple[bool, str]:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)

    if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        return False, f"commit {commit} is not in this clone (fetch-depth: 0 needed)"
    diff = git("diff", "--name-only", commit, "HEAD", "--", *DLL_INPUTS)
    if diff.returncode != 0:
        return False, f"git diff failed: {diff.stderr.strip()}"
    changed = [line for line in diff.stdout.splitlines() if line]
    if changed:
        shown = ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")
        return False, f"{len(changed)} DLL source file(s) changed since {commit}: {shown}"
    return True, ""


def main() -> int:
    from rsmm.engine import loader_update as lu

    # Outside CI a dist/winhttp.dll is usually the developer's own build.
    dll = lu.bundled_loader_dll()
    if dll.exists() and not os.environ.get("GITHUB_ACTIONS") and "--force" not in sys.argv:
        print(f"reuse-loader: {dll} exists and this is not CI - leaving it "
              f"(pass --force to replace it)")
        _output(False)
        return 0
    stamp = lu.bundled_version()
    try:
        manifest = lu.fetch_manifest()          # signature-verified
    except (lu.LoaderUpdateError, OSError) as e:
        print(f"reuse-loader: channel unavailable ({e}) - compiling")
        _output(False)
        return 0
    remote = int(manifest["loader_version"])
    commit = str(manifest.get("commit") or "")
    if remote != stamp:
        print(f"reuse-loader: channel is v{remote}, this checkout is v{stamp} - compiling")
        _output(False)
        return 0
    if not commit:
        print("reuse-loader: channel manifest names no commit - compiling")
        _output(False)
        return 0
    ok, why = _dll_sources_unchanged(commit)
    if not ok:
        print(f"reuse-loader: {why} - compiling")
        _output(False)
        return 0
    try:
        got = lu.fetch_prebuilt_dll()           # bundle hash + member hash checked
    except (lu.LoaderUpdateError, OSError) as e:
        print(f"reuse-loader: download failed ({e}) - compiling")
        _output(False)
        return 0
    print(f"reuse-loader: dist/winhttp.dll = published loader v{got['loader_version']} "
          f"(built from {commit}); skipping the compile")
    _output(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
