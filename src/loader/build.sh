#!/usr/bin/env bash
# Build the Windows mod-manager DLL from Linux via MinGW.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
build="$here/build"
# Walk up from src/loader/ to the repo root, then dist/.
dist="$(cd "$here/../.." && pwd)/dist"

[[ -f "$here/third_party/minhook/src/hook.c" ]] || "$here/fetch_deps.sh"

cmake -S "$here" -B "$build" \
    -DCMAKE_TOOLCHAIN_FILE="$here/cmake/toolchain-mingw.cmake" \
    -DCMAKE_BUILD_TYPE=Release

cmake --build "$build" -j"$(nproc)"

mkdir -p "$dist"
cp "$build/winhttp.dll" "$dist/winhttp.dll"
echo "Built: $dist/winhttp.dll"
