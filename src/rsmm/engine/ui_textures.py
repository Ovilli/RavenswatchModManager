"""Game UI textures as PNG data URLs, for config editors that theme themselves.

An `item-grid` config field may name game textures to dress its editor in
(:mod:`rsmm.sdk.config_grid`). Those are decoded here, from the player's own
install, when the editor opens — so a mod themes itself with the game's art
without shipping a byte of it.

The path rule is the security boundary: only a ``Ui/…png`` path that the game's
own asset map resolves is ever read. A schema cannot name an arbitrary file.
"""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

_log = logging.getLogger(__name__)

PNG_PREFIX = "data:image/png;base64,"
_PATH = re.compile(r"^Ui/[A-Za-z0-9_ .\-/]+\.png$")
#: A decoded texture over this many base64 characters is dropped, not sent.
MAX_CHARS = 1024 * 1024


def cache_dir(game_dir: Path) -> Path:
    return game_dir / "rsmm" / "cache" / "ui"


def png(game_dir: Path, decoded: str, max_edge: int) -> bytes | None:
    """Decoded PNG for one UI texture (``Ui/…/X.png``), memoised on disk."""
    if not _PATH.match(decoded) or ".." in decoded:
        return None
    from rsmm.cli import apply_mods as A

    from . import icon_decode
    from .item_catalog import _cooked_path

    safe = decoded.replace("/", "__")
    cache = cache_dir(game_dir) / f"{safe}@{max_edge}.png"
    try:
        if cache.is_file():
            return cache.read_bytes()
    except OSError:
        pass
    src = _cooked_path(game_dir, A.load_asset_map(), decoded + ".Texture.dxt")
    if src is None:
        return None
    try:
        out = icon_decode.texture_to_png(src.read_bytes(), max_edge=max_edge)
    except (OSError, ValueError, KeyError, IndexError) as e:
        _log.debug("ui texture %s undecodable: %s", decoded, e)
        return None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(out)
    except OSError:
        pass                                    # the cache is an optimisation only
    return out


def data_url(game_dir: Path, decoded: str, max_edge: int) -> str:
    """``png`` as an inline data URL, or ``""`` when unavailable or too large."""
    blob = png(game_dir, decoded, max_edge)
    if not blob:
        return ""
    url = PNG_PREFIX + base64.b64encode(blob).decode()
    return url if len(url) <= MAX_CHARS else ""
