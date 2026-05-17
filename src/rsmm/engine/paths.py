"""Canonical paths for the repo + the live Ravenswatch install.

Everything else imports REPO_ROOT / ASSET_MAP_JSON from here. Never
hardcode paths in CLI subcommands or SDK modules.
"""

from __future__ import annotations
from pathlib import Path


def _find_repo_root() -> Path:
    """Walk up from this file until we hit the directory that contains
    `data/asset_map.json`. Robust against the source tree being moved
    around inside `src/`.
    """
    here = Path(__file__).resolve()
    for cand in [here.parent, *here.parents]:
        if (cand / "data" / "asset_map.json").exists():
            return cand
    # Fall back to four-levels-up (`src/rsmm/engine/paths.py` -> repo root)
    return here.parents[3]


REPO_ROOT: Path     = _find_repo_root()
DATA_DIR: Path      = REPO_ROOT / "data"
MODS_DIR: Path      = REPO_ROOT / "mods"
DIST_DIR: Path      = REPO_ROOT / "dist"
ASSET_MAP_JSON: Path = DATA_DIR / "asset_map.json"
ASSET_MAP_CSV: Path  = DATA_DIR / "asset_map.csv"

DEFAULT_GAME_DIR: Path = Path.home() / (
    ".var/app/com.valvesoftware.Steam/.local/share/Steam/"
    "steamapps/common/Ravenswatch"
)
COOKING_SUBDIR: str = "DarkTalesResources/_Cooking"
