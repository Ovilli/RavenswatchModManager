#!/usr/bin/env python3
"""
Build the rsmm CLI as a standalone executable for the current platform
using PyInstaller. The output binary is placed where Tauri's sidecar
resolver expects it.

Usage:
    python3 scripts/build-sidecar.py                  # auto-detect platform
    python3 scripts/build-sidecar.py --target linux
    python3 scripts/build-sidecar.py --target macos
    python3 scripts/build-sidecar.py --target windows
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"

TARGET_TRIPLES = {
    "linux": "x86_64-unknown-linux-gnu",
    "macos": "x86_64-apple-darwin",
    "macos-arm": "aarch64-apple-darwin",
    "windows": "x86_64-pc-windows-msvc",
}

EXTENSIONS = {
    "linux": "",
    "macos": "",
    "macos-arm": "",
    "windows": ".exe",
}


def detect_platform() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    elif system == "darwin":
        # Check if running on Apple Silicon
        if platform.machine() == "arm64":
            return "macos-arm"
        return "macos"
    elif system in ("windows", "msys", "cygwin"):
        return "windows"
    else:
        print(f"Unsupported platform: {system}")
        sys.exit(1)


def build_sidecar(target: str) -> None:
    triple = TARGET_TRIPLES[target]
    ext = EXTENSIONS[target]
    binary_name = f"rsmm-{triple}{ext}"
    binary_path = OUT_DIR / binary_name

    print(f"Building sidecar for {target} ({triple})...")
    print(f"Output: {binary_path}")

    # Ensure PyInstaller is installed
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        check=True, capture_output=True,
    )

    # Bundle runtime data needed by CLI commands in frozen mode.
    add_data_args = [
        "--add-data", f"{REPO_ROOT / 'pyproject.toml'}{os.pathsep}.",
        "--add-data", f"{REPO_ROOT / 'data' / 'asset_map.json'}{os.pathsep}data",
        "--add-data", f"{REPO_ROOT / 'data' / 'asset_map.csv'}{os.pathsep}data",
        "--add-data", f"{REPO_ROOT / 'data' / 'function_patterns.json'}{os.pathsep}data",
        "--add-data", f"{REPO_ROOT / 'data' / 'schemas'}{os.pathsep}data/schemas",
        "--add-data", f"{REPO_ROOT / 'data' / 'templates'}{os.pathsep}data/templates",
    ]

    # Build with PyInstaller
    # The entry point is rsmm.cli._dispatch:main
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name", "rsmm",
            "--distpath", str(OUT_DIR),
            "--specpath", str(OUT_DIR),
            "--workpath", str(OUT_DIR / "build"),
            *add_data_args,
            str(REPO_ROOT / "src" / "rsmm" / "__init__.py"),
        ],
        check=True, cwd=REPO_ROOT,
    )

    # PyInstaller produces OUT_DIR/rsmm[.exe]; rename to triple-suffixed name
    src = OUT_DIR / f"rsmm{ext}"
    if src.exists():
        if binary_path.exists():
            binary_path.unlink()
        shutil.move(str(src), str(binary_path))
        print(f"Moved: {src} -> {binary_path}")
    else:
        print(f"ERROR: PyInstaller did not produce {src}")
        sys.exit(1)

    # Clean up PyInstaller artifacts
    shutil.rmtree(OUT_DIR / "build", ignore_errors=True)
    for spec in OUT_DIR.glob("*.spec"):
        spec.unlink()

    # Make executable on Unix
    if ext == "":
        binary_path.chmod(binary_path.stat().st_mode | 0o111)

    size_mb = binary_path.stat().st_size / 1024 / 1024
    print(f"Done: {binary_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build rsmm CLI sidecar binary")
    parser.add_argument(
        "--target",
        choices=list(TARGET_TRIPLES.keys()),
        default=detect_platform(),
        help="Target platform (auto-detected by default)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build for all platforms (requires cross-compilation tools)",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.all:
        for t in TARGET_TRIPLES:
            print(f"\n{'='*60}")
            build_sidecar(t)
    else:
        build_sidecar(args.target)
