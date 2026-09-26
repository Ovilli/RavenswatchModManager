"""How several mods' edits to ONE game file are combined at apply time.

Most assets are last-writer-wins, but some files are shared state that every
mod appends to: text banks, the hero-alias table in ApplicationSettings.ot, a
map's tile pool and resource caches. Those are merged here (unions, never a
winner), and a map's tile pool is checked against its preload cache.
Moved out of ``cli/apply_mods.py`` (2026-09-26); ``apply_mods`` re-exports
every name.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Collection
from pathlib import Path

from . import rsc_cache

_TEXT_BANK_RE = re.compile(r"\.LocalText\.gen(\.Lang.+)?$")


def is_text_bank(decoded: str) -> bool:
    """True for a `~GAM.xls.LocalText.gen` base or a `.Lang<XX>` sibling — the
    index-aligned key/value text files that multiple item mods append to."""
    return bool(_TEXT_BANK_RE.search(decoded))


# Staging dir for merged text banks (one writer per apply; src must outlive the
# plan→copy step). Lives under the mods dir so it's cleaned by `restore --all`.
_TEXT_MERGE_DIR_NAME = ".rsmm_text_merge"


def _text_merge_dir() -> Path:
    """Where merged text banks are staged, resolved at CALL time.

    ⚠ NOT `MODS_DIR / _TEXT_MERGE_DIR_NAME`. `MODS_DIR` is a PEP 562 lazy attr
    bound when this module is IMPORTED, so a later `RSMM_MODS_DIR` override
    never reaches it — and the three merge sites that used it wrote into the
    developer's (and CI's) REAL `mods/` directory no matter what a test set.
    That surfaced as `.rsmm_text_merge` appearing in the repo and the
    `_guard_real_mods_dir` conftest guard failing four unrelated tests at
    teardown, in whichever worker happened to be running when it appeared.
    `paths.mods_dir()` reads the override every time, which is the whole reason
    it exists.
    """
    from rsmm.engine import paths as _paths
    return _paths.mods_dir() / _TEXT_MERGE_DIR_NAME


def _merge_text_bank(enc: str, srcs: list[Path],
                     vanilla: Path | None) -> Path | None:
    """Merge several mods' versions of ONE text-bank file into vanilla + the
    union of each mod's appended tail, preserving index alignment.

    Each mod's file is vanilla + that mod's appended entries (``append_bank_keys``
    appends the same count to the base keys file and every language sibling), so
    concatenating each mod's tail — in a fixed mod order applied identically to
    the base and every sibling — keeps keys and values aligned. Returns the path
    to the written merged file, or ``None`` if it can't be parsed as a bank.
    """
    from rsmm.engine import text_patches as TP
    if vanilla is None:
        return None                     # a text bank is always a shipped file
    try:
        van = TP.parse_text_file(vanilla)
    except Exception:  # noqa: BLE001 — not a parseable bank; skip merge
        return None
    n = len(van.entries)
    merged = list(van.entries)
    for src in srcs:
        try:
            tf = TP.parse_text_file(src)
        except Exception:  # noqa: BLE001 — not a parseable bank; skip merge
            return None
        if len(tf.entries) >= n:
            merged.extend(tf.entries[n:])
    out_tf = TP.TextFile(path=vanilla, header=van.header, entries=merged,
                         footer=van.footer)
    out_dir = _text_merge_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Encode the enc path into a flat, unique filename.
    flat = enc.replace("\\", "__").replace("/", "__")
    out_path = out_dir / flat
    out_path.write_bytes(TP.write_text_file(out_tf))
    return out_path


def is_app_settings(decoded: str) -> bool:
    """True for `_root/DarkTalesResources/ApplicationSettings.ot`, which every
    custom-hero mod extends with an alias (and `ot` patches edit)."""
    return decoded == "_root/DarkTalesResources/ApplicationSettings.ot"


def _merge_app_settings(enc: str, srcs: list[Path],
                        vanilla: Path | None) -> Path | None:
    """Every mod's hero aliases in one ApplicationSettings.ot.

    Each custom hero emits the game's file plus its own `AliasDesc`, and the
    `ot` patch merge emits the game's file plus field edits. Last-writer-wins
    would drop every hero but one, and a hero whose alias is missing has skins
    that bind to nothing. `merge_app_settings` keeps the copy with the fewest
    aliases (the one carrying non-alias edits) and adds everyone's aliases.
    """
    from rsmm.engine import hero_cook
    try:
        texts = [src.read_text(encoding="utf-8", errors="surrogateescape")
                 for src in srcs]
        merged = hero_cook.merge_app_settings(texts)
    except (OSError, hero_cook.HeroCookError):
        return None
    out_dir = _text_merge_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / enc.replace("\\", "__").replace("/", "__")
    out_path.write_text(merged, encoding="utf-8", errors="surrogateescape")
    return out_path


#: Cooked suffix of a chapter's map definition (see `rsmm.engine.map_pool`).
_MAPDEF_GEN_SUFFIX = ".mapdef.ot.DtMapDefinition.gen"


def is_map_def(decoded: str) -> bool:
    """True for a `*.mapdef.ot.DtMapDefinition.gen` — the per-chapter def whose
    trailing tile pool several `poi` mods may each want to extend."""
    return decoded.endswith(_MAPDEF_GEN_SUFFIX)


def is_rsc_cache(decoded: str) -> bool:
    """True for a `*.UsedRscCache.ot` — a definition's preload manifest, which
    several mods editing the same definition may each want to extend."""
    return decoded.endswith(rsc_cache.CACHE_SUFFIX)


def _merge_rsc_cache(enc: str, srcs: list[Path],
                     vanilla: Path | None) -> Path | None:
    """Union several mods' additions to ONE resource cache.

    Exactly the same problem as the tile pool, on the file that decides whether
    a pooled tile is ever loaded: two `poi` mods targeting one chapter each emit
    vanilla-plus-their-own-lines, so last-writer-wins would drop the other mod's
    resources and its POI would be pooled but unloadable — invisible short of a
    full playthrough. The union is de-duplicated and re-sorted: the engine
    looks a resource up in this file rather than scanning it, so a line out of
    ascending order is a line that is never found (see
    :func:`rsmm.engine.rsc_cache.extend`).
    """
    # `vanilla is None` = a cache this mod introduced, so there is no shipped
    # baseline and the union IS the file.
    try:
        base = rsc_cache.parse(vanilla.read_bytes()) if vanilla else []
    except (OSError, UnicodeDecodeError):
        return None
    merged, have = list(base), set(base)
    for src in srcs:
        try:
            lines = rsc_cache.parse(src.read_bytes())
        except (OSError, UnicodeDecodeError) as e:
            # Skip the unreadable source, keep everyone else's lines. Failing
            # the whole merge drops the union back to last-writer-wins, which
            # silently deletes the OTHER mods' preloads — and a missing cache
            # line is a tile that is registered and never placed, or a null the
            # teardown loop destroys unchecked. One broken file must not cost
            # the rest their content.
            print(f"  [warn] resource cache '{enc}': skipping unreadable "
                  f"source {src}: {e}", file=sys.stderr)
            continue
        for ln in lines:
            if ln not in have:
                merged.append(ln)
                have.add(ln)
    out_dir = _text_merge_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / enc.replace("\\", "__").replace("/", "__")
    out_path.write_bytes(rsc_cache.render(sorted(merged)))
    return out_path


def _merge_map_pool(enc: str, srcs: list[Path],
                    vanilla: Path | None) -> Path | None:
    """Union several mods' tile-pool additions to ONE mapdef.

    Each `poi` mod emits vanilla-plus-its-own-tiles, so without this the last
    writer wins and every other mod's POI is registered as an asset but never
    pooled — it loads and is never placed, which is invisible until someone
    plays a full run looking for it. Merging takes the vanilla pool and appends
    whatever each mod added, in a fixed mod order, de-duplicated.

    Returns the merged file's path, or ``None`` when any input isn't a parseable
    mapdef (caller then falls back to the last-writer-wins warning).
    """
    from rsmm.engine import map_pool as MP
    if vanilla is None:
        return None                     # a mapdef is always a shipped file
    try:
        base = MP.read_pool(vanilla.read_bytes())
    except Exception:  # noqa: BLE001 — not a parseable mapdef; skip merge
        return None
    if base is None:
        return None
    merged = list(base)
    have = set(base)
    for src in srcs:
        try:
            pool = MP.read_pool(src.read_bytes())
        except Exception:  # noqa: BLE001
            return None
        if pool is None:
            return None
        for p in pool:
            if p not in have:
                merged.append(p)
                have.add(p)
    try:
        out_bytes = MP.set_pool(vanilla.read_bytes(), merged)
    except Exception:  # noqa: BLE001
        return None
    out_dir = _text_merge_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    flat = enc.replace("\\", "__").replace("/", "__")
    out_path = out_dir / flat
    out_path.write_bytes(out_bytes)
    return out_path


_TILEDEF_CACHE_CLASS = "oCDtTileDefinition"


def check_tile_cache_gates(mapdef_decoded: str,
                           read: Callable[[str], bytes | None],
                           vanilla_pool: Collection[str] = ()) -> list[str]:
    """Problems with the two cache gates of one tile-generated map.

    A pooled tile is only ever placed when BOTH hold, and each fails silently
    in game (registered, never placed, nothing logged):

    1. the mapdef's own cache lists every pooled tiledef, one for one;
    2. every pooled tiledef has a sibling ``.tiledef.UsedRscCache.ot``.

    Both caches must also be in ascending order: the engine looks lines up
    rather than scanning, so an out-of-order line is never found (and in a
    tile cache that is a null the level teardown destroys unchecked).

    ``read(decoded)`` returns the bytes the game will see at that decoded path
    after this apply, or ``None`` when nothing will be there. Tiles in
    ``vanilla_pool`` skip the per-tile checks: the shipped Avalon pool names
    two tiledefs the game does not ship at all, and it runs fine.
    """
    from rsmm.engine import map_pool as MP
    raw = read(mapdef_decoded)
    if raw is None:
        return []
    try:
        pool = MP.read_pool(raw)
    except Exception:  # noqa: BLE001 — unparseable mapdef is reported elsewhere
        return []
    if not pool:
        return []
    problems: list[str] = []
    map_cache = rsc_cache.cache_path_for(mapdef_decoded)
    cache_raw = read(map_cache)
    if cache_raw is None:
        return [f"map cache '{map_cache}' is missing, so none of its "
                f"{len(pool)} pooled tiles is preloaded"]
    lines = rsc_cache.parse(cache_raw)
    if lines != sorted(lines):
        problems.append(f"map cache '{map_cache}' is not sorted")
    listed = {ln.split("|")[1] for ln in lines
              if ln.endswith("|" + _TILEDEF_CACHE_CLASS) and ln.count("|") == 2}
    for tile in pool:
        if tile not in listed:
            problems.append(f"pooled tile '{tile}' has no line in map cache "
                            f"'{map_cache}' (never preloaded, never placed)")
        if tile in vanilla_pool:
            continue
        tile_cache = "Definitions/" + tile.replace("\\", "/")
        tile_cache = tile_cache[: -len(".ot")] + rsc_cache.CACHE_SUFFIX
        tile_raw = read(tile_cache)
        if tile_raw is None:
            problems.append(f"pooled tile '{tile}' has no resource cache "
                            f"'{tile_cache}' (nothing preloaded, never placed)")
            continue
        tl = rsc_cache.parse(tile_raw)
        if tl != sorted(tl):
            problems.append(f"tile cache '{tile_cache}' is not sorted")
    if len(listed) != len(set(pool)):
        problems.append(f"map cache '{map_cache}' lists {len(listed)} tiledefs "
                        f"but the pool has {len(set(pool))}")
    return problems
