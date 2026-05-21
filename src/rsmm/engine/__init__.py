"""Engine internals: cipher, decoder, asset map loader, repo paths.

Modder code should not import from this package directly. The supported
mod-authoring surface is the Lua SDK (`require "rsmm"` from init.lua);
this Python tree is host-only infrastructure used by the CLI to install
mods and ship the loader.
"""

from .paths import (
    ASSET_MAP_CSV,
    ASSET_MAP_JSON,
    COOKING_SUBDIR,
    DATA_DIR,
    DEFAULT_GAME_DIR,
    DIST_DIR,
    MODS_DIR,
    REPO_ROOT,
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
