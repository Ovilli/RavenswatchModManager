"""The magical objects a player can actually be offered, with their art.

Built to back an item PICKER: a ban is declared by internal id, and those ids
are not guessable from the game — ``Avoid_Death_Once_Per_Chapter`` is shown to
players as "Water of Life", and ``Armor_Per_Object`` as "Green Armor". Anyone
choosing what to ban needs the icon and the display name, not the id.

Everything is read from the INSTALL, never from ``data/uncooked``: the corpus
is a developer mirror, gitignored and absent on a user's machine, and it is a
superset of what the game actually offers (it carries ``*_Model`` templates and
unreleased items the catalog never lists). The authority for "can this be
offered" is the LiveOps versiondef magical-object vector, which is also exactly
what a ban edits — so the picker cannot list an item the ban cannot remove.

Icons are decoded with :mod:`rsmm.engine.icon_decode` and cached as PNG under
``<game>/rsmm/cache/items/``; decoding all of them costs a few seconds of pure
Python, which is fine once and not fine on every screen open.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

_log = logging.getLogger(__name__)

__all__ = ["ItemInfo", "catalog", "icon_png", "cache_dir", "ICON_MAX_EDGE"]

#: Longest edge of a cached icon. The shipped art is 192x192 (164x164 for the
#: power-ups) and a picker grid renders it far smaller, so carrying full-res
#: would roughly triple the payload the desktop loads for no visible gain.
ICON_MAX_EDGE: Final = 64

_BANK: Final = "Text/Magical_Objects~GAM.xls.LocalText.gen"
_NAME_LABEL: Final = "Name Value"
#: The game's own spelling. Do not "fix" it — it is matched against shipped bytes.
_DESC_LABEL: Final = "Descripton Format"


@dataclass(frozen=True)
class ItemInfo:
    id: str
    rarity: str
    name: str | None
    description: str | None
    icon: str | None

    def to_json(self) -> dict:
        return asdict(self)


def cache_dir(game_dir: Path) -> Path:
    return game_dir / "rsmm" / "cache" / "items"


def _cooked_path(game_dir: Path, asset_map: dict[str, str], decoded: str) -> Path | None:
    enc = asset_map.get(decoded)
    if not enc:
        return None
    from rsmm.cli.apply_mods import COOKING_REL
    p = game_dir / COOKING_REL / Path(*enc.split("\\"))
    return p if p.is_file() else None


def _text_values(game_dir: Path, asset_map: dict[str, str], lang: str = "EN") -> dict[str, str]:
    """``text key -> display string`` for the magical-object bank.

    The base ``.LocalText.gen`` holds the KEYS and the per-language sibling
    holds the VALUES at matching indices, so the two are zipped rather than
    parsed as pairs.
    """
    from rsmm.engine import text_patches as TP

    base = _cooked_path(game_dir, asset_map, _BANK)
    if base is None:
        return {}
    try:
        keys = TP.parse_text_file(base).entries
        sib = TP.lang_path_for(base, lang)
        if not sib.is_file():
            return {}
        vals = TP.parse_text_file(sib).entries
    except (OSError, ValueError) as e:
        _log.warning("item catalog: unreadable text bank: %s", e)
        return {}
    # strict=False: a language sibling shorter than the key list still yields
    # every key it does cover, which beats losing the whole bank.
    return dict(zip(keys, vals, strict=False))


def _key_after(lstrings: list[str], label: str) -> str | None:
    """The text key a ``<label> -> 'Text' -> <bank> -> <key>`` run points at.

    Item display names are NOT derivable from the id — several items reference
    another item's key outright (``Avoid_Death_Once_Per_Chapter`` resolves
    through ``Fully_Health_Day_Night_Name``) — so the key is read from the
    entity rather than composed.
    """
    for i, s in enumerate(lstrings):
        if s != label or i + 3 >= len(lstrings):
            continue
        if lstrings[i + 1] == "Text" and ".xls" in lstrings[i + 2]:
            return lstrings[i + 3]
    return None


def _plain(text: str | None) -> str | None:
    """Strip the game's inline display markup from a bank string.

    Shipped strings carry styling controls — ``#highlight@``, ``&value~`` — and
    ``{0}``-style placeholders the engine substitutes at runtime. The controls
    are dropped and the placeholders left in place: a picker tooltip reading
    "gain +{0}% Crit Chance" is honest about the number varying, whereas
    dropping the token would read as a missing word.
    """
    if not text:
        return None
    out = text.translate({ord(c): None for c in "#@&~"})
    return " ".join(out.split()) or None


def _entity_decoded(vector_path: str) -> str:
    """Versiondef reference form -> decoded cooked path of the entity."""
    rel = vector_path.replace("\\", "/")
    return f"EntitySettings/{rel}.EntitySettingsResource.gen"


def catalog(game_dir: Path | None = None, *, lang: str = "EN") -> list[ItemInfo]:
    """Every magical object the install's catalog lists, sorted by rarity+name.

    Empty when no install is reachable — callers render an empty picker rather
    than a picker full of items the game does not have.
    """
    from rsmm.cli import apply_mods as A
    from rsmm.engine import magic_item_cook as cook

    game_dir = game_dir or A.find_game_dir()
    if game_dir is None:
        return []
    gen = A._locate_cooked_by_leaf(game_dir, A.VERSIONDEF_GEN_LEAF)
    if gen is None:
        return []
    # The pristine backup when one exists: the live file may already carry a
    # ban, and a picker that hides what you banned cannot un-ban it.
    bak = gen.with_name(gen.name + A.BACKUP_SUFFIX)
    blob = (bak if bak.exists() else gen).read_bytes()
    loc = A._find_mo_vector(blob)
    if loc is None:
        return []
    co, _end, cnt = loc
    entries = A._mo_vector_entries(blob, co, cnt)

    asset_map = A.load_asset_map()
    text = _text_values(game_dir, asset_map, lang)

    out: list[ItemInfo] = []
    for _s, _e, ref in entries:
        item_id = A._mo_entry_stem(ref)
        parts = ref.replace("/", "\\").split("\\")
        rarity = parts[-2] if len(parts) >= 2 else "Unknown"
        p = _cooked_path(game_dir, asset_map, _entity_decoded(ref))
        name = desc = icon = None
        if p is not None:
            try:
                data = p.read_bytes()
                ls = [s for _o, s in cook.find_lstrings(data)]
                name = text.get(_key_after(ls, _NAME_LABEL) or "")
                desc = text.get(_key_after(ls, _DESC_LABEL) or "")
                icon = cook.find_icon(data)
            except (OSError, ValueError) as e:
                _log.debug("item catalog: %s unreadable: %s", item_id, e)
        out.append(ItemInfo(id=item_id, rarity=rarity, name=_plain(name),
                            description=_plain(desc), icon=icon))
    out.sort(key=lambda i: (i.rarity, (i.name or i.id).lower()))
    return out


def _icon_stem(icon: str | None) -> str | None:
    """``Objects\\UI_Object_GreenArmor.png`` -> ``UI_Object_GreenArmor``."""
    if not icon:
        return None
    leaf = icon.replace("/", "\\").rsplit("\\", 1)[-1]
    return leaf[:-4] if leaf.lower().endswith(".png") else leaf


def icon_png(game_dir: Path, item: ItemInfo, *, max_edge: int = ICON_MAX_EDGE) -> bytes | None:
    """Decoded PNG for one item's icon, memoised on disk. None if unavailable.

    A missing or undecodable icon is not an error: the picker shows a
    placeholder and the item stays selectable, because the icon is a convenience
    and the ban does not depend on it.
    """
    from rsmm.cli import apply_mods as A
    from rsmm.engine import icon_decode

    stem = _icon_stem(item.icon)
    if not stem:
        return None
    cache = cache_dir(game_dir) / f"{stem}@{max_edge}.png"
    try:
        if cache.is_file():
            return cache.read_bytes()
    except OSError:
        pass

    src = _cooked_path(game_dir, A.load_asset_map(),
                       f"Ui/Objects/{stem}.png.Texture.dxt")
    if src is None:
        return None
    try:
        png = icon_decode.texture_to_png(src.read_bytes(), max_edge=max_edge)
    except (OSError, ValueError, KeyError, IndexError) as e:
        _log.debug("item catalog: icon %s undecodable: %s", stem, e)
        return None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(png)
    except OSError:
        pass                                    # cache is an optimisation only
    return png


def to_json(game_dir: Path | None = None, *, icons: bool = False,
            lang: str = "EN") -> str:
    """The whole catalog as JSON, optionally with base64 PNG icons inlined."""
    import base64

    from rsmm.cli import apply_mods as A

    game_dir = game_dir or A.find_game_dir()
    items = catalog(game_dir, lang=lang)
    rows = []
    for it in items:
        row = it.to_json()
        if icons and game_dir is not None:
            png = icon_png(game_dir, it)
            row["icon_png"] = (
                "data:image/png;base64," + base64.b64encode(png).decode()
            ) if png else None
        rows.append(row)
    return json.dumps({"items": rows, "count": len(rows)}, indent=1)
