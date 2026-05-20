#!/usr/bin/env bash
# Install the mod manager into the Ravenswatch game directory.
# Renames the stock winhttp.dll to winhttp_real.dll (so our proxy can forward
# every export back to it), then drops our build in place. Copies asset_map.json
# and the mods/ directory next to the game executable.
set -euo pipefail

GAME_DIR="${1:-$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch}"
# Walk up from src/rsmm/cli/<this script> to the repo root.
REPO_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

if [[ ! -f "$GAME_DIR/Ravenswatch.exe" ]]; then
    echo "Ravenswatch.exe not found in: $GAME_DIR" >&2
    exit 1
fi

DLL="$REPO_DIR/dist/winhttp.dll"
if [[ ! -f "$DLL" ]]; then
    echo "Build first: loader/build.sh" >&2
    exit 1
fi

# Replace existing winhttp.dll if it's the BepInEx Doorstop (does NOT forward
# to a real winhttp). Also replace any winhttp_real.dll that turns out to be
# the same Doorstop renamed.
is_doorstop() { strings "$1" 2>/dev/null | grep -q "doorstop.dll"; }

if [[ -f "$GAME_DIR/winhttp.dll" ]] && is_doorstop "$GAME_DIR/winhttp.dll"; then
    echo "Removing BepInEx/Doorstop winhttp.dll"
    rm -f "$GAME_DIR/winhttp.dll"
fi
if [[ -f "$GAME_DIR/winhttp_real.dll" ]] && is_doorstop "$GAME_DIR/winhttp_real.dll"; then
    echo "Removing BepInEx/Doorstop winhttp_real.dll"
    rm -f "$GAME_DIR/winhttp_real.dll"
fi

# Source winhttp_real.dll from wine if missing. Try the Ravenswatch prefix
# first, then any Proton install.
if [[ ! -f "$GAME_DIR/winhttp_real.dll" ]]; then
    SRC=""
    for c in \
        "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/2071280/pfx/drive_c/windows/system32/winhttp.dll" \
        "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Proton Hotfix/files/lib/wine/x86_64-windows/winhttp.dll" \
        "$HOME/.steam/steam/steamapps/common/Proton - Experimental/files/lib/wine/x86_64-windows/winhttp.dll"; do
        if [[ -e "$c" ]]; then SRC="$c"; break; fi
    done
    if [[ -n "$SRC" ]]; then
        # cp -L resolves the symlink so we drop a real DLL, not a dead link.
        cp -L "$SRC" "$GAME_DIR/winhttp_real.dll"
        echo "Sourced winhttp_real.dll from: $SRC"
    else
        echo "ERROR: could not find a real winhttp.dll to use as winhttp_real.dll" >&2
        exit 1
    fi
fi

install -m 0644 "$DLL" "$GAME_DIR/winhttp.dll"
install -m 0644 "$REPO_DIR/data/asset_map.json" "$GAME_DIR/asset_map.json"

# Lua-side SDK: mods do `require "rsmm"` and get the documented R.* surface.
SDK_SRC="$REPO_DIR/src/loader/lua"
mkdir -p "$GAME_DIR/rsmm/lib"
if [[ -d "$SDK_SRC" ]]; then
    cp -a "$SDK_SRC/." "$GAME_DIR/rsmm/lib/"
elif [[ -f "$REPO_DIR/src/loader/lib/rsmm.lua" ]]; then
    install -m 0644 "$REPO_DIR/src/loader/lib/rsmm.lua" "$GAME_DIR/rsmm/lib/rsmm.lua"
fi

mkdir -p "$GAME_DIR/mods"
# Sync mod manifests + init.lua so the loader's scan_mods sees every
# repo-side mod AND can run each mod's Lua. Cooked-asset overrides go
# in via apply_mods.py separately.
for mod_dir in "$REPO_DIR"/mods/*/; do
    [[ -f "$mod_dir/manifest.toml" ]] || continue
    name=$(basename "$mod_dir")
    mkdir -p "$GAME_DIR/mods/$name"
    install -m 0644 "$mod_dir/manifest.toml" "$GAME_DIR/mods/$name/manifest.toml"
    [[ -f "$mod_dir/init.lua" ]] && install -m 0644 "$mod_dir/init.lua" "$GAME_DIR/mods/$name/init.lua"
done

# Disable BepInEx config so Doorstop (if any lingers) does nothing harmful.
if [[ -f "$GAME_DIR/doorstop_config.ini" ]]; then
    sed -i 's/^enabled\s*=.*/enabled = false/' "$GAME_DIR/doorstop_config.ini"
fi

echo "Installed mod manager into $GAME_DIR"
