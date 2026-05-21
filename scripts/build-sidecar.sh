#!/usr/bin/env bash
set -euo pipefail

# Build the Python CLI as a standalone binary (sidecar) for the current platform.
# Uses PyInstaller to produce a single executable that Tauri can bundle.
#
# Usage:
#   ./scripts/build-sidecar.sh              # detect current platform
#   ./scripts/build-sidecar.sh windows       # cross-compile for Windows
#   ./scripts/build-sidecar.sh linux
#   ./scripts/build-sidecar.sh macos
#
# Output: apps/desktop/src-tauri/binaries/rsmm-<target-triple>[.exe]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
OUT_DIR="$REPO_ROOT/apps/desktop/src-tauri/binaries"

PLATFORM="${1:-auto}"

if [ "$PLATFORM" = "auto" ]; then
  case "$(uname -s)" in
    Linux)   PLATFORM="linux" ;;
    Darwin)  PLATFORM="macos" ;;
    MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
    *) echo "Unknown platform: $(uname -s)"; exit 1 ;;
  esac
fi

case "$PLATFORM" in
  linux)
    TARGET="x86_64-unknown-linux-gnu"
    EXT=""
    ;;
  macos)
    TARGET="x86_64-apple-darwin"
    EXT=""
    ;;
  windows)
    TARGET="x86_64-pc-windows-msvc"
    EXT=".exe"
    ;;
  *)
    echo "Unknown target: $PLATFORM"
    echo "Usage: $0 {linux|macos|windows}"
    exit 1
    ;;
esac

echo "Building sidecar for $PLATFORM ($TARGET)..."

cd "$REPO_ROOT"

# Create a PyInstaller spec that bundles the rsmm CLI
cat > /tmp/rsmm-sidecar.spec << 'PYSPEC'
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['src/rsmm/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['rsmm.cli', 'rsmm.engine', 'toml', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='rsmm',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_trap=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
PYSPEC

# Install PyInstaller if needed
pip install pyinstaller 2>/dev/null

# Build
pyinstaller /tmp/rsmm-sidecar.spec --clean --distpath "$OUT_DIR"

# PyInstaller puts it in OUT_DIR/rsmm, we need it at OUT_DIR/rsmm-$TARGET$EXT
mkdir -p "$OUT_DIR"
mv "$OUT_DIR/rsmm/rsmm" "$OUT_DIR/rsmm-${TARGET}${EXT}" 2>/dev/null || \
mv "$OUT_DIR/rsmm/rsmm.exe" "$OUT_DIR/rsmm-${TARGET}${EXT}" 2>/dev/null || true

# Clean up PyInstaller artifacts
rm -rf "$OUT_DIR/rsmm" build/ /tmp/rsmm-sidecar.spec

echo "Done: $OUT_DIR/rsmm-${TARGET}${EXT}"
ls -lh "$OUT_DIR/rsmm-${TARGET}${EXT}"
