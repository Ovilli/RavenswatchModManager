#!/usr/bin/env bash
# Build a single-file binary launcher with PyInstaller.
#
# Usage:
#   ./scripts/build_launcher.sh
#
# Outputs (depending on host platform):
#   dist/RavenswatchModManager           Linux / macOS
#   dist/RavenswatchModManager.exe       Windows (run from a Windows shell)
#
# Optional second step: wrap the Linux binary into an AppImage for
# point-and-click distribution. Requires `appimagetool` on $PATH.
#
#   APPIMAGE=1 ./scripts/build_launcher.sh
#
# The script installs PyInstaller into a local venv so it doesn't
# touch the user's global Python.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv-build"
if [[ ! -x "$VENV/bin/python3" && ! -x "$VENV/Scripts/python.exe" ]]; then
    echo "==> creating build venv at $VENV"
    python3 -m venv "$VENV"
fi

if [[ -x "$VENV/bin/python3" ]]; then
    PY="$VENV/bin/python3"
else
    PY="$VENV/Scripts/python.exe"
fi

echo "==> upgrading pip"
"$PY" -m pip install --upgrade pip >/dev/null

echo "==> installing pyinstaller"
"$PY" -m pip install --upgrade pyinstaller >/dev/null

# Optional runtime extras — the GUI works without them, but Pillow +
# texture2ddecoder unlock live game icons / logo inside the UI.
if [[ "${WITH_TEXTURES:-1}" == "1" ]]; then
    echo "==> installing optional decoders (Pillow + texture2ddecoder)"
    "$PY" -m pip install --upgrade Pillow texture2ddecoder >/dev/null || \
        echo "  (warn) decoder install failed — bundle will skip live icons"
fi

echo "==> cleaning previous build"
rm -rf "$ROOT/build" "$ROOT/dist/RavenswatchModManager" \
       "$ROOT/dist/RavenswatchModManager.exe"

echo "==> running pyinstaller"
"$PY" -m PyInstaller --clean -y rsmm.spec

# Locate the produced binary
BIN="$ROOT/dist/RavenswatchModManager"
[[ -x "$BIN" ]] || BIN="$ROOT/dist/RavenswatchModManager.exe"

if [[ ! -e "$BIN" ]]; then
    echo "!! pyinstaller produced no expected output under dist/"
    exit 1
fi

SIZE=$(du -h "$BIN" | cut -f1)
echo
echo "==> built $BIN ($SIZE)"
echo
echo "Smoke test (source-mode dispatch via the same code path):"
echo "    \"$BIN\" lint"
echo
echo "Open the GUI:"
echo "    \"$BIN\""
echo

# Optional AppImage packaging
if [[ "${APPIMAGE:-0}" == "1" ]]; then
    if ! command -v appimagetool >/dev/null; then
        echo "!! APPIMAGE=1 set but appimagetool not on PATH; skipping."
        exit 0
    fi
    APPDIR="$ROOT/build/RavenswatchModManager.AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin"
    cp "$BIN" "$APPDIR/usr/bin/RavenswatchModManager"
    cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/RavenswatchModManager" "$@"
EOF
    chmod +x "$APPDIR/AppRun"
    cat > "$APPDIR/RavenswatchModManager.desktop" <<'EOF'
[Desktop Entry]
Name=Ravenswatch Mod Manager
Exec=RavenswatchModManager
Icon=RavenswatchModManager
Type=Application
Categories=Game;Utility;
Terminal=false
EOF
    # tiny placeholder icon — replace with a real .png/.svg before
    # shipping to users.
    printf '\x89PNG\r\n\x1a\n' > "$APPDIR/RavenswatchModManager.png"
    OUT="$ROOT/dist/RavenswatchModManager.AppImage"
    ARCH=$(uname -m) appimagetool "$APPDIR" "$OUT" || {
        echo "!! appimagetool failed"; exit 1; }
    echo "==> built $OUT ($(du -h "$OUT" | cut -f1))"
fi
