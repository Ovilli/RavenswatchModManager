"""Option providers for `multiselect` config fields.

A mod that wants the player to choose from a list the GAME defines — every
magical object, say — cannot spell those options out in its manifest: it does
not know them, they carry art, and they change when the game is patched. So the
schema names a provider and the CLI fills the options in.

The allowlist is the security boundary. A mod supplies a NAME, never a path, a
URL or a command. The desktop webview can spawn the CLI, so anything a mod could
inject here would be arbitrary code execution on the player's machine — the same
reason overlay shape is data and never markup.

An option is a flat record the client renders generically:

    {"id", "label", "group", "icon", "description"}

``icon`` is an inline ``data:image/png;base64,`` URL or empty. Never a path and
never a remote URL, so the client is never made to fetch on a mod's behalf.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)

__all__ = ["PROVIDERS", "provide", "ICON_PREFIX", "MAX_ICON_CHARS"]

ICON_PREFIX = "data:image/png;base64,"
#: A 64px PNG data URL runs ~6 KB. The cap is generous for one and small enough
#: that a provider cannot wedge the client with megabytes of base64.
MAX_ICON_CHARS = 64 * 1024
#: Providers may return large lists (the item catalog is 104), but not unbounded
#: ones — the whole set is rendered at once.
MAX_OPTIONS = 512


def _item_catalog() -> list[dict[str, Any]]:
    """Every magical object the install's catalog can offer.

    The catalog, not the shipped asset corpus: the corpus carries ~20 entities
    the game never offers (``*_Model`` templates, unreleased items), and an
    option nothing can act on is a trap. This is also exactly the set an item
    ban can remove, so the picker cannot show a choice that would not apply.
    """
    import base64

    from rsmm.cli import apply_mods as A
    from rsmm.engine import item_catalog

    game_dir = A.find_game_dir()
    if game_dir is None:
        return []
    out: list[dict[str, Any]] = []
    for it in item_catalog.catalog(game_dir)[:MAX_OPTIONS]:
        png = item_catalog.icon_png(game_dir, it)
        out.append({
            "id": it.id,
            "label": it.name or it.id,
            "group": it.rarity,
            "icon": (ICON_PREFIX + base64.b64encode(png).decode()) if png else "",
            "description": it.description or "",
        })
    return out


def _enemy_roster() -> list[dict[str, Any]]:
    """Every creature a camp selector can roll, grouped by the chapter it
    ships in.

    The spawnable set, not every enemy definition: bosses, summons and quest
    enemies are placed by the script owning their encounter, so casting one
    would emit a definition pointing at a prefab no chapter streams. Same rule
    the `enemy` kind enforces at emit — the picker must not offer a choice that
    would then be refused.

    Ids are prefab stems (`Standard_Reef_Crab`), which are unique across the
    50 and are one of the three spellings `rsmm.sdk.kinds.enemies` accepts, so
    a stored selection reads the same by hand or through the panel. No icons:
    enemy art lives in the entity's material chain rather than in a UI atlas
    the way an item's does.

    Read through `enemy_pools`, which answers from the uncooked mirror on an
    authoring checkout and from the game install's own cooked tree everywhere
    else — so the picker is populated on a plain install, which is the only
    machine that matters for a downloaded mod. Empty only when rsmm cannot
    find the game at all.
    """
    from rsmm.engine import enemy_pools as EP

    by_pool = EP.pool_of_entity()
    out: list[dict[str, Any]] = []
    for ent in EP.spawnable_entities()[:MAX_OPTIONS]:
        stem = ent.replace("/", "\\").split("\\")[-1].split(".", 1)[0]
        out.append({
            "id": stem,
            "label": stem.replace("_", " "),
            "group": (by_pool.get(ent.lower()) or "").replace("_", " "),
            "icon": "",
            "description": ent,
        })
    return out


#: name -> builder. The single source of truth for what a schema's `source` may
#: name; `rsmm.sdk.config` validates against these keys.
PROVIDERS: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "item-catalog": _item_catalog,
    "enemy-roster": _enemy_roster,
}


def _clean(opt: Any) -> dict[str, Any] | None:
    if not isinstance(opt, dict):
        return None
    oid = str(opt.get("id", "")).strip()
    if not oid:
        return None
    icon = opt.get("icon") or ""
    if (not isinstance(icon, str) or not icon.startswith(ICON_PREFIX)
            or len(icon) > MAX_ICON_CHARS):
        icon = ""
    return {
        "id": oid,
        "label": str(opt.get("label") or oid)[:120],
        "group": str(opt.get("group") or "")[:40],
        "icon": icon,
        "description": str(opt.get("description") or "")[:400],
    }


def provide(name: str) -> list[dict[str, Any]]:
    """Options for an allowlisted provider.

    Returns an empty list — never raises — when the provider is unknown or
    cannot read the game: a config panel that opens with no options is a far
    better failure than one that will not open at all.
    """
    build = PROVIDERS.get(name)
    if build is None:
        _log.warning("unknown config option provider %r", name)
        return []
    try:
        raw = build()
    except Exception as exc:                    # noqa: BLE001 - provider is data-driven
        _log.warning("config option provider %s failed: %s", name, exc)
        return []
    return [c for c in (_clean(o) for o in raw[:MAX_OPTIONS]) if c is not None]
