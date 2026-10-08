#!/usr/bin/env python3
"""
Build the rsmm CLI as the desktop app's sidecar, then prove the build works.

The desktop app runs this one frozen binary for everything, so it is the build
users actually get. This script is the ONLY definition of what goes into it:
`.github/workflows/release.yml` and the CI `sidecar` job both call it. There
used to be three hand-synced copies of the file list (this script, an inline
PyInstaller call in release.yml and a build-sidecar.sh that bundled no data at
all), and a file missing from the one that shipped only showed up as a crash
on a user's fresh install.

After building, the binary is checked twice:

* contents: every file of every BUNDLE entry is inside the binary's archive;
* runs: started from an empty directory with a throwaway home, game and mods
  folder, every routed subcommand starts, the read-only `json` calls the
  desktop makes return JSON, `doctor` finds the bundled asset map and
  `changelog` falls back to the bundled release notes.

Usage:
    python3 scripts/build-sidecar.py                   # build for this platform, then check it
    python3 scripts/build-sidecar.py --no-check        # build only
    python3 scripts/build-sidecar.py --check-only      # check the binary already built
    python3 scripts/build-sidecar.py --require-loader  # fail without dist/winhttp.dll (release)

RSMM targets Windows + Linux only (macOS support dropped). PyInstaller cannot
cross-compile, so the sidecar is always built for the platform it runs on.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"

TARGET_TRIPLES = {
    "linux": "x86_64-unknown-linux-gnu",
    "windows": "x86_64-pc-windows-msvc",
}

EXTENSIONS = {
    "linux": "",
    "windows": ".exe",
}

#: Everything the frozen CLI reads from the repo tree, as
#: (source relative to the repo, directory inside the bundle, required).
#: The frozen binary resolves REPO_ROOT to _MEIPASS, so each entry is
#: reachable at the same relative path it had in source; anything not listed
#: here is silently missing at runtime. A missing required entry fails the
#: build instead of shipping without it.
BUNDLE: list[tuple[str, str, bool]] = [
    ("pyproject.toml", ".", True),
    ("data/asset_map.json", "data", True),
    ("data/asset_map.csv", "data", True),
    ("data/loader_version.json", "data", True),
    # Offline fallback for `rsmm changelog` / the desktop "What's new" dialog
    # when the rolling channel is unreachable and nothing is cached yet.
    ("data/changelog.json", "data", True),
    ("src/rsmm/cli/install_loader.sh", "src/rsmm/cli", True),
    ("src/rsmm/cli/install_loader.ps1", "src/rsmm/cli", True),
    ("src/rsmm/cli/install_loader.bat", "src/rsmm/cli", True),
    # `rsmm editor`: its pages (.html + common.css/js) and three.js for the
    # map's 3D view. editor.app.asset_dir finds them here in a frozen build.
    ("src/rsmm/cli/editor/pages", "src/rsmm/cli/editor/pages", True),
    ("src/rsmm/cli/editor/static", "src/rsmm/cli/editor/static", True),
    ("src/loader/lua", "src/loader/lua", True),
    # The canonical SDK entrypoint (full rsmm.lua) + generated engine_gen.lua
    # live in lib/. install_loader.{sh,ps1} overwrite the stripped lua/ stub
    # with these; if lib/ isn't bundled the frozen install silently ships the
    # stub (no R.engine, broken R.kv).
    ("src/loader/lib", "src/loader/lib", True),
    # Game-derived and gitignored: release.yml fetches it from the rolling
    # pattern-db release first. Without it the loader falls back to rebased
    # stored VAs, and `rsmm update-data` fetches it on the user's machine.
    ("data/function_patterns.json", "data", False),
    ("data/function_patterns.meta.json", "data", False),
    ("data/schemas", "data/schemas", False),
    ("data/templates", "data/templates", False),
    # Required with --require-loader (the release builds it first).
    ("dist/winhttp.dll", "dist", False),
]

LOADER_DLL = "dist/winhttp.dll"

#: Read-only `rsmm json` calls the desktop app makes on its first screens.
#: Each must exit 0 and print JSON in a fresh install with no mods.
DESKTOP_JSON_CALLS = [
    ["json", "list"],
    ["json", "list-profiles"],
    ["json", "doctor"],
    ["json", "loader-flags", "get"],
    ["json", "loader-runs"],
    ["json", "loader-health"],
    ["json", "active-overrides"],
    ["json", "game-status"],
    ["json", "conflicts"],
    ["json", "overlays"],
]


def detect_platform() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    if system in ("windows", "msys", "cygwin"):
        return "windows"
    print(f"Unsupported platform: {system} (RSMM targets Windows + Linux only)")
    sys.exit(1)


def binary_path(target: str) -> Path:
    return OUT_DIR / f"rsmm-{TARGET_TRIPLES[target]}{EXTENSIONS[target]}"


def bundle_entries(require_loader: bool = False) -> tuple[list[tuple[Path, str]], list[str]]:
    """The (source, bundle dir) pairs present on disk, plus what is missing
    but required."""
    present: list[tuple[Path, str]] = []
    missing: list[str] = []
    for rel, dest, required in BUNDLE:
        src = REPO_ROOT / rel
        if src.exists():
            present.append((src, dest))
        elif required or (require_loader and rel == LOADER_DLL):
            missing.append(rel)
        else:
            print(f"  [skip] optional, not present: {rel}")
    return present, missing


def build_sidecar(target: str, require_loader: bool) -> Path:
    out = binary_path(target)
    print(f"Building sidecar for {target} ({TARGET_TRIPLES[target]})...")
    print(f"Output: {out}")

    present, missing = bundle_entries(require_loader)
    if missing:
        for rel in missing:
            print(f"ERROR: required bundle file missing: {rel}", file=sys.stderr)
        sys.exit(1)

    try:
        import PyInstaller
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # Subcommands are loaded dynamically via importlib (rsmm/cli/_dispatch.py)
    # and mod authors import the rsmm.sdk surface at runtime; PyInstaller's
    # static analysis sees neither, so walk each package and take every module.
    collect_args = [
        "--collect-submodules=rsmm.cli",
        "--collect-submodules=rsmm.engine",
        "--collect-submodules=rsmm.sdk",
    ]
    add_data_args: list[str] = []
    for src, dest in present:
        add_data_args += ["--add-data", f"{src}{os.pathsep}{dest}"]

    # Work and spec dirs stay inside the workspace: on Windows runners the
    # workspace is on D: and the system temp on C:, and PyInstaller's relpath
    # calls fail across drives.
    work = OUT_DIR / "build"
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--noconfirm",
            "--name", out.stem,
            "--distpath", str(OUT_DIR),
            "--specpath", str(OUT_DIR),
            "--workpath", str(work),
            "--paths", str(REPO_ROOT / "src"),
            *collect_args,
            *add_data_args,
            str(REPO_ROOT / "rsmm"),
        ],
        check=True, cwd=REPO_ROOT,
    )

    shutil.rmtree(work, ignore_errors=True)
    for spec in OUT_DIR.glob("*.spec"):
        spec.unlink()
    if not out.is_file():
        print(f"ERROR: PyInstaller did not produce {out}", file=sys.stderr)
        sys.exit(1)
    if EXTENSIONS[target] == "":
        out.chmod(out.stat().st_mode | 0o111)
    print(f"Done: {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")
    return out


# --- check: contents ---------------------------------------------------------

def check_contents(binary: Path, require_loader: bool) -> list[str]:
    """Every file of every BUNDLE entry present on disk is in the archive."""
    from PyInstaller.archive.readers import CArchiveReader

    bundled = {name.replace("\\", "/") for name in CArchiveReader(str(binary)).toc}
    present, missing = bundle_entries(require_loader)
    problems = [f"required bundle file missing from the source tree: {rel}" for rel in missing]
    expected = 0
    for src, dest in present:
        files = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file())
        for f in files:
            rel = f.name if src.is_file() else f.relative_to(src).as_posix()
            name = rel if dest == "." else f"{dest}/{rel}"
            expected += 1
            if name not in bundled:
                problems.append(f"not in the binary: {name}")
    print(f"  contents: {expected - len(problems)}/{expected} bundled files present")
    return problems


# --- check: runs -------------------------------------------------------------

def _isolated_env(tmp: Path) -> dict[str, str]:
    """A throwaway home, game install and mods folder.

    Every RSMM_* override is dropped: RSMM_REPO_ROOT in particular would point
    the binary at the source tree and hide a file missing from the bundle.
    """
    home = tmp / "home"
    game = tmp / "game"
    (game / "DarkTalesResources" / "_Cooking").mkdir(parents=True)
    (game / "Ravenswatch.exe").write_bytes(b"")
    (tmp / "mods").mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("RSMM_")}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        APPDATA=str(home / "AppData" / "Roaming"),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        RSMM_GAME_DIR=str(game),
        RSMM_MODS_DIR=str(tmp / "mods"),
        # Unreachable on purpose, so `changelog` must use the bundled copy.
        RSMM_CHANGELOG_BASE="https://127.0.0.1:9",
        NO_COLOR="1",
    )
    return env


def _routed_commands() -> list[str]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from rsmm.cli._dispatch import iter_commands

    return [name for name, _mod in iter_commands()]


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def check_runs(binary: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="rsmm-sidecar-check-") as t:
        tmp = Path(t)
        env = _isolated_env(tmp)
        # Run from an empty directory: a frozen rsmm also looks for data/ next
        # to the executable and in the cwd, and the repo root would mask a
        # file missing from the bundle.
        cwd = tmp / "cwd"
        cwd.mkdir()

        def run(argv: list[str]) -> tuple[list[str], subprocess.CompletedProcess]:
            proc = subprocess.run(
                [str(binary), *argv], cwd=cwd, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=180,
                stdin=subprocess.DEVNULL,
            )
            return argv, proc

        calls = [["--help"], ["doctor", "--json"], ["changelog", "--json", "-n", "1"],
                 *DESKTOP_JSON_CALLS,
                 *([cmd, "--help"] for cmd in _routed_commands())]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, calls))

    problems: list[str] = []
    for argv, proc in results:
        label = "rsmm " + " ".join(argv)
        out = proc.stdout + proc.stderr
        # A subcommand may refuse `--help` (exit 1/2); it must not crash.
        if "Traceback (most recent call last)" in out:
            problems.append(f"{label} crashed:\n{out.strip()[-2000:]}")
            continue
        if len(argv) == 2 and argv[1] == "--help":
            continue  # started without crashing; that is all asked of it
        if argv == ["--help"]:
            if proc.returncode != 0 or "json" not in proc.stdout:
                problems.append(f"{label}: exit {proc.returncode}, no command listing")
        elif argv[:2] == ["doctor", "--json"]:
            report = _json_or_none(proc.stdout)
            asset = [r for s in (report or {}).get("sections", [])
                     if s.get("section") == "asset map" for r in s.get("results", [])]
            if not asset or any(r.get("kind") != "OK" for r in asset):
                problems.append(f"{label}: the bundled asset map was not found\n"
                                f"{out.strip()[-2000:]}")
        elif argv[0] == "changelog":
            feed = _json_or_none(proc.stdout) or {}
            if feed.get("status") != "bundled" or not feed.get("entries"):
                status = feed.get("status")
                problems.append(f"{label}: no bundled release notes (status {status!r})")
        elif argv[0] == "json":
            if proc.returncode != 0 or _json_or_none(proc.stdout) is None:
                problems.append(f"{label}: exit {proc.returncode}, not JSON\n{out.strip()[-2000:]}")
    print(f"  runs: {len(results) - len(problems)}/{len(results)} commands passed")
    return problems


def check_sidecar(binary: Path, require_loader: bool) -> int:
    print(f"Checking {binary}...")
    if not binary.is_file():
        print(f"ERROR: no sidecar at {binary}", file=sys.stderr)
        return 1
    problems = check_contents(binary, require_loader) + check_runs(binary)
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s): this sidecar would break on a user's install.",
              file=sys.stderr)
        return 1
    print("Sidecar OK.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and check the rsmm CLI sidecar binary")
    parser.add_argument(
        "--target",
        choices=list(TARGET_TRIPLES.keys()),
        default=detect_platform(),
        help="Target platform; must be this one, PyInstaller cannot cross-compile",
    )
    parser.add_argument("--no-check", action="store_true", help="build without checking")
    parser.add_argument("--check-only", action="store_true",
                        help="check the binary already in the output dir without rebuilding")
    parser.add_argument("--require-loader", action="store_true",
                        help=f"fail if {LOADER_DLL} is missing or not bundled")
    args = parser.parse_args()

    if args.target != detect_platform():
        print(f"Cannot build the {args.target} sidecar on {detect_platform()}: PyInstaller "
              "cannot cross-compile. Run this on the target platform.", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    built = binary_path(args.target)
    if not args.check_only:
        built = build_sidecar(args.target, args.require_loader)
    if args.check_only or not args.no_check:
        sys.exit(check_sidecar(built, args.require_loader))
