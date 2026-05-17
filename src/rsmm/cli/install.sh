#!/usr/bin/env bash
# One-shot setup + apply. Rebuilds the asset map (if missing) then runs
# `rsmm apply` to install mods/ into the game install.
#
# To uninstall every active override:
#
#   rsmm restore --all
#
set -euo pipefail

# Walk up from src/rsmm/cli/<this script> to the repo root.
REPO_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

USED="${USEDRSCLIST:-$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Ravenswatch/DarkTalesResources/UsedRscList.ot}"
MAP="$REPO_DIR/data/asset_map.json"
if [[ ! -f "$MAP" || ( -f "$USED" && "$USED" -nt "$MAP" ) ]]; then
    echo "Building decoded asset map..."
    ( cd "$REPO_DIR" && python3 -m rsmm.engine.find_iyg )
fi

echo "Applying mods..."
"$REPO_DIR/rsmm" apply "$@"
