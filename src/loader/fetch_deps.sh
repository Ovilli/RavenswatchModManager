#!/usr/bin/env bash
# Fetch third-party dependencies for the Ravenswatch Mod Manager loader.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
tp="$here/third_party"
mkdir -p "$tp"

clone() {
    local repo="$1" dest="$2" rev="${3:-}"
    if [[ ! -d "$dest/.git" ]]; then
        git clone --depth 1 "$repo" "$dest"
    fi
    if [[ -n "$rev" ]]; then
        git -C "$dest" fetch --depth 1 origin "$rev"
        git -C "$dest" checkout "$rev"
    fi
}

clone https://github.com/TsudaKageyu/minhook                "$tp/minhook"
# Pinned: master changes the ImFontLoader callback types (ImWchar -> int
# codepoint, 2026-10) and overlay_menu.cpp implements them.
clone https://github.com/ocornut/imgui                      "$tp/imgui" b2546a5c93090c70610046fe547b946ee3d8d986
clone https://github.com/KhronosGroup/Vulkan-Headers        "$tp/Vulkan-Headers"
clone https://github.com/lua/lua                            "$tp/lua"

mkdir -p "$tp/nlohmann" "$tp/tomlplusplus"
curl -fsSL https://github.com/nlohmann/json/releases/latest/download/json.hpp \
    -o "$tp/nlohmann/json.hpp"
curl -fsSL https://raw.githubusercontent.com/marzer/tomlplusplus/master/toml.hpp \
    -o "$tp/tomlplusplus/toml.hpp"

echo "deps OK in $tp"
