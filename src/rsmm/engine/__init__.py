"""Engine internals: cipher, decoder, asset map loader, repo paths.

Modder code should import from `rsmm.sdk` (when added) or call the
top-level `rsmm` CLI. This package is internal and stable only across
RE-version bumps.
"""

from .paths import (
    REPO_ROOT,
    DATA_DIR,
    MODS_DIR,
    DIST_DIR,
    ASSET_MAP_JSON,
    ASSET_MAP_CSV,
    DEFAULT_GAME_DIR,
    COOKING_SUBDIR,
)

__all__ = [
    "REPO_ROOT",
    "DATA_DIR",
    "MODS_DIR",
    "DIST_DIR",
    "ASSET_MAP_JSON",
    "ASSET_MAP_CSV",
    "DEFAULT_GAME_DIR",
    "COOKING_SUBDIR",
]
