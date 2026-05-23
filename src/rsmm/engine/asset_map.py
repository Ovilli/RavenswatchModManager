"""Cached loader for asset_map.json."""

from __future__ import annotations

import json
from functools import lru_cache

from .paths import ASSET_MAP_JSON


@lru_cache(maxsize=1)
def encoded_to_decoded() -> dict[str, str]:
    """encoded cooked path -> decoded human path. Cached."""
    return json.loads(ASSET_MAP_JSON.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def decoded_to_encoded() -> dict[str, str]:
    """Decoded path (forward-slash, posix-style) -> encoded cooked path
    (with backslashes, as stored in UsedRscList.ot).

    Warns if two different encoded paths decode to the same key — only the
    last one survives.
    """
    enc_dec = encoded_to_decoded()
    out: dict[str, str] = {}
    for enc, dec in enc_dec.items():
        key = dec.replace("\\", "/")
        if key in out:
            import logging
            logging.warning(
                f"duplicate decoded path {key!r} "
                f"(old={out[key]!r}, new={enc!r})"
            )
        out[key] = enc
    return out
