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

# Source winhttp_real.dll from wine. Our proxy STATICALLY forwards every
# export to winhttp_real.<fn>, so the source MUST be a real-export PE. The
# prefix's drive_c/windows/system32/winhttp.dll is often a Wine *builtin
# stub* with ZERO PE exports — forwarding to it makes Wine fail to load our
# proxy (it silently falls back to the builtin winhttp, so the loader never
# runs and no mods/_log.txt is written). Prefer Proton's PE-format builtin
# under lib/wine/x86_64-windows, and VALIDATE that the chosen file actually
# exports WinHttpOpen before accepting it.
winhttp_exports_open() {
    # True if $1 is a real winhttp PE (not a 0-export Wine builtin stub).
    # objdump isn't reliably present / consistent across the CLI's subprocess
    # env, so use a portable byte heuristic: a real winhttp PE carries its ~45
    # "WinHttp*" export-name strings (hundreds of "WinHttp" byte hits); a stub
    # has effectively none. Require a healthy count.
    local f="$1" n
    [[ -f "$f" ]] || return 1
    n=$(grep -oa "WinHttp" "$f" 2>/dev/null | wc -l)
    [[ "$n" -ge 20 ]]
}

# Re-source if missing OR if the existing copy is a 0-export stub.
if [[ ! -f "$GAME_DIR/winhttp_real.dll" ]] || ! winhttp_exports_open "$GAME_DIR/winhttp_real.dll"; then
    SRC=""
    # Real PE builtins (lib/wine/x86_64-windows) first; prefix system32 last.
    candidates=()
    while IFS= read -r c; do candidates+=("$c"); done < <(
        ls -1 \
          "$HOME"/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d/*/files/lib/wine/x86_64-windows/winhttp.dll \
          "$HOME"/.local/share/Steam/compatibilitytools.d/*/files/lib/wine/x86_64-windows/winhttp.dll \
          "$HOME"/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Proton*/files/lib/wine/x86_64-windows/winhttp.dll \
          "$HOME"/.steam/steam/steamapps/common/Proton*/files/lib/wine/x86_64-windows/winhttp.dll \
          2>/dev/null
    )
    candidates+=("$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/2071280/pfx/drive_c/windows/system32/winhttp.dll")
    for c in "${candidates[@]}"; do
        if [[ -e "$c" ]] && winhttp_exports_open "$c"; then SRC="$c"; break; fi
    done
    if [[ -n "$SRC" ]]; then
        # cp -L resolves the symlink so we drop a real DLL, not a dead link.
        cp -L "$SRC" "$GAME_DIR/winhttp_real.dll"
        echo "Sourced winhttp_real.dll from: $SRC"
    else
        echo "ERROR: no real-export winhttp.dll found to use as winhttp_real.dll" >&2
        echo "       (every candidate was a stub; install a Proton with a PE winhttp)" >&2
        exit 1
    fi
fi

install -m 0644 "$DLL" "$GAME_DIR/winhttp.dll"
install -m 0644 "$REPO_DIR/data/asset_map.json" "$GAME_DIR/asset_map.json"
install -d "$GAME_DIR/rsmm/data"
install -m 0644 "$REPO_DIR/data/function_patterns.json" "$GAME_DIR/rsmm/data/function_patterns.json"
if [ -f "$REPO_DIR/data/function_patterns.meta.json" ]; then
    install -m 0644 "$REPO_DIR/data/function_patterns.meta.json" "$GAME_DIR/rsmm/data/function_patterns.meta.json"
fi

# Lua-side SDK: mods do `require "rsmm"` and get the documented R.* surface.
# The require entrypoint is src/loader/lib/rsmm.lua (the full SDK with
# R.item/R.on/R.kv/R.engine that matches the C++ bindings rsmm._internal.*).
# Copy the modular src/loader/lua/ tree first (rsmm/*.lua submodules that
# lib/rsmm.lua require-merges: health/config/i18n/api/schedule), then install
# the entrypoint + generated engine_gen.lua from lib/. Both src/loader/lua AND
# src/loader/lib are bundled into the frozen sidecar (scripts/build-sidecar.py);
# if lib/ is missing, R.engine/engine_gen and the full SDK won't ship.
SDK_SRC="$REPO_DIR/src/loader/lua"
mkdir -p "$GAME_DIR/rsmm/lib"
if [[ -d "$SDK_SRC" ]]; then
    cp -a "$SDK_SRC/." "$GAME_DIR/rsmm/lib/"
fi
if [[ -f "$REPO_DIR/src/loader/lib/rsmm.lua" ]]; then
    install -m 0644 "$REPO_DIR/src/loader/lib/rsmm.lua" "$GAME_DIR/rsmm/lib/rsmm.lua"
fi
# Generated engine-symbol table (R.engine.* resolves names via this).
if [[ -f "$REPO_DIR/src/loader/lib/engine_gen.lua" ]]; then
    install -m 0644 "$REPO_DIR/src/loader/lib/engine_gen.lua" "$GAME_DIR/rsmm/lib/engine_gen.lua"
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
    # Copy pointers.json for function-resolution hooks.
    [[ -f "$mod_dir/pointers.json" ]] && install -m 0644 "$mod_dir/pointers.json" "$GAME_DIR/mods/$name/pointers.json"
    # Copy user config so the loader's config_get bindings see it in-game.
    [[ -f "$mod_dir/config.toml" ]] && install -m 0644 "$mod_dir/config.toml" "$GAME_DIR/mods/$name/config.toml"
    # Copy asset overrides so the runtime IAT hook can find them.
    if [[ -d "$mod_dir/assets" ]]; then
        mkdir -p "$GAME_DIR/mods/$name/assets"
        cp -a "$mod_dir/assets/." "$GAME_DIR/mods/$name/assets/"
    fi
done

# Disable BepInEx config so Doorstop (if any lingers) does nothing harmful.
if [[ -f "$GAME_DIR/doorstop_config.ini" ]]; then
    sed -i 's/^enabled\s*=.*/enabled = false/' "$GAME_DIR/doorstop_config.ini"
fi

echo "Installed mod manager into $GAME_DIR"
