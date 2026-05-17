"""Canonical paths for the repo + the live Ravenswatch install.

Everything else imports REPO_ROOT / ASSET_MAP_JSON from here. Never
hardcode paths in CLI subcommands or SDK modules.
"""

from __future__ import annotations
import os
import sys
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


COOKING_SUBDIR: str = "DarkTalesResources/_Cooking"


def _game_dir_candidates() -> list[Path]:
    """Per-platform Ravenswatch install candidates. Order = preference."""
    home = Path.home()
    cands: list[Path] = []
    if sys.platform == "win32":
        # Standard Steam library roots on every drive letter that exists.
        drives = []
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{d}:\\")
            if root.exists():
                drives.append(d)
        if not drives:
            drives = ["C", "D", "E"]
        for d in drives:
            cands += [
                Path(f"{d}:\\Program Files (x86)\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\Program Files\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\Steam\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\SteamLibrary\\steamapps\\common\\Ravenswatch"),
                Path(f"{d}:\\Games\\Steam\\steamapps\\common\\Ravenswatch"),
            ]
        # Honor LOCALAPPDATA / PROGRAMFILES env vars if set unusually.
        pf86 = os.environ.get("ProgramFiles(x86)")
        if pf86:
            cands.append(Path(pf86) / "Steam" / "steamapps" / "common" / "Ravenswatch")
        pf = os.environ.get("ProgramFiles")
        if pf:
            cands.append(Path(pf) / "Steam" / "steamapps" / "common" / "Ravenswatch")
    elif sys.platform == "darwin":
        cands += [
            home / "Library/Application Support/Steam/steamapps/common/Ravenswatch",
        ]
    else:  # linux + others
        cands += [
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
                   "/steamapps/common/Ravenswatch",
            home / ".steam/steam/steamapps/common/Ravenswatch",
            home / ".local/share/Steam/steamapps/common/Ravenswatch",
            Path("/mnt") / "Steam/steamapps/common/Ravenswatch",
        ]
    return cands


def _default_game_dir() -> Path:
    """First candidate whose `_Cooking` tree exists; otherwise the first
    candidate. So autodetect works on Windows/macOS/Linux without the
    user passing --game-dir."""
    cands = _game_dir_candidates()
    for c in cands:
        if (c / COOKING_SUBDIR).is_dir():
            return c
    return cands[0]


REPO_ROOT: Path     = _find_repo_root()
DATA_DIR: Path      = REPO_ROOT / "data"
MODS_DIR: Path      = REPO_ROOT / "mods"
DIST_DIR: Path      = REPO_ROOT / "dist"
ASSET_MAP_JSON: Path = DATA_DIR / "asset_map.json"
ASSET_MAP_CSV: Path  = DATA_DIR / "asset_map.csv"

DEFAULT_GAME_DIR: Path = _default_game_dir()
