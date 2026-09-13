"""The magical objects the Sandman's offer generators can sell, read from the install.

Data only: this module knows which items are shop-eligible and what they cost,
not how anything is displayed. It backs the ``shop-items`` config option
provider (:mod:`rsmm.sdk.config_choices`) and the ``shop`` content kind.

Which items qualify is decided by the engine rules traced in
:mod:`rsmm.engine.sandman_shop`:

* the item must be in the LiveOps catalog, or it is never in the pool the
  generators search;
* it must carry a flag node of its own, because slot membership is written by
  appending a pool tag to that node (an item that inherits its flags has no
  node to edit, and adding one is a component insertion this does not attempt);
* its quality must resolve to ``powerup``, because every Sandman slot's weights
  sit on that quality alone.

Name, description, icon, quality and price are resolved through the item's
parent chain (``Power_Up_Grimoire_Armor_High`` -> ``..._Armor_Model`` ->
``Magical_Objects_Model``), since most of them live on a template rather than on
the item. Only an item with its OWN ``Powerup Price`` node has an editable price.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import sandman_shop as S

_log = logging.getLogger(__name__)

POWERUP_QUALITY: Final = 5
#: Generators whose item list can be edited, in the shop's own order.
EDITABLE: Final = ("minor", "medium", "medium_duplicate", "medium_object",
                   "major", "major_duplicate", "major_object")
#: Generators that ship rolling a random magical object by rarity rather than
#: from a flag pool (their pool is empty). They hold no item list until one is
#: chosen, and choosing one replaces the random object with those items.
OBJECT_SLOTS: Final = ("medium_object", "major_object")

#: Longest edge of an item icon in the option list.
ICON_EDGE: Final = 96

_PARENT_RE = re.compile(r"^Objects\\Magical_Objects[\\_].*\.entity\.ot$")
_TIER_FLAGS: Final = ("Low", "Medium", "High")


@dataclass
class ShopItem:
    id: str
    label: str
    description: str
    icon: str
    group: str
    #: "duplicate" for the powerups that copy an object, else "offer".
    role: str
    flags: list[str]
    price: int
    price_editable: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "description": self.description,
            "icon": self.icon, "group": self.group, "role": self.role,
            "price": self.price, "priceEditable": self.price_editable,
        }


@dataclass
class ShopData:
    items: dict[str, ShopItem] = field(default_factory=dict)
    gens: dict[str, S.OfferGen] = field(default_factory=dict)

    def vanilla_members(self, key: str) -> list[str]:
        # An object slot's empty pool matches every flag list, but it only ever
        # offers magical objects by rarity — none of these powerups.
        if key in OBJECT_SLOTS:
            return []
        pool = self.gens[key].pool
        return sorted(i.id for i in self.items.values() if S.pool_matches(pool, i.flags))


# --- reading vanilla bytes ---------------------------------------------------

def vanilla_bytes(decoded: str, game_dir: Path | None) -> bytes | None:
    """The unmodded bytes of one cooked asset, or None when unreachable.

    The in-repo mirror first (a developer checkout), then the install's
    ``.rsmm.bak`` — ``apply`` backs a file up before overriding it, so the live
    file may already be this very mod's output — and only then the live file.
    """
    from .paths import DATA_DIR

    mirror = DATA_DIR / "uncooked" / Path(*decoded.split("/"))
    if mirror.is_file():
        return mirror.read_bytes()
    if game_dir is None:
        return None
    from rsmm.cli import apply_mods as A

    from .item_catalog import _cooked_path

    live = _cooked_path(game_dir, A.load_asset_map(), decoded)
    if live is None:
        return None
    bak = live.with_name(live.name + A.BACKUP_SUFFIX)
    return (bak if bak.is_file() else live).read_bytes()


def _entity_decoded(ref: str) -> str:
    """``Objects\\...\\X.entity.ot`` -> the decoded path of its cooked file."""
    return "EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen"


def _chain(first: bytes, game_dir: Path | None, own_ref: str) -> list[bytes]:
    """The item followed by its parents, nearest first (at most five deep)."""
    from .magic_item_cook import find_lstrings

    out, seen, cur = [first], {own_ref}, first
    for _ in range(5):
        parent = next((s for _o, s in find_lstrings(cur)
                       if _PARENT_RE.match(s) and s not in seen), None)
        if parent is None:
            break
        seen.add(parent)
        data = vanilla_bytes(_entity_decoded(parent), game_dir)
        if data is None:
            break
        out.append(data)
        cur = data
    return out


def _first_int(chain: list[bytes], label: str) -> tuple[int | None, bool]:
    """``(value, found_on_the_item_itself)`` for an int value node."""
    from .talent_values import list_union_values

    for depth, data in enumerate(chain):
        if label.encode() not in data:
            continue
        try:
            unions = list_union_values(data, label, limit=1)
        except ValueError:
            continue
        if unions:
            return int(unions[0][1]), depth == 0
    return None, False


# --- the item set ------------------------------------------------------------

def load(game_dir: Path | None, *, icons: bool = True, lang: str = "EN") -> ShopData:
    """Shop-eligible items plus the seven generators, from the install."""
    from rsmm.cli import apply_mods as A

    from . import item_catalog as IC
    from .magic_item_cook import find_icon, find_lstrings

    data = ShopData()
    npc = vanilla_bytes(S.NPC_ASSET, game_dir)
    if npc is None:
        return data
    data.gens = S.read_offer_gens(npc)

    if game_dir is not None:
        text = IC._text_values(game_dir, A.load_asset_map(), lang)
        ids = [i.id for i in IC.catalog(game_dir, lang=lang) if i.rarity == "Powerups"]
    else:
        # No install: an authoring checkout's mirror stands in for the catalog
        # (minus the `_Model` templates it lists and the catalog never offers),
        # with no text bank and no art. Enough to validate and emit a shop.
        from .paths import DATA_DIR

        text, icons = {}, False
        mirror = DATA_DIR / "uncooked" / Path(*S.ITEM_DIR_ASSET.split("/"))
        ids = sorted(p.name.removesuffix(S.ITEM_SUFFIX)
                     for p in mirror.glob(f"*{S.ITEM_SUFFIX}")
                     if not p.name.removesuffix(S.ITEM_SUFFIX).endswith("_Model"))
    for item_id in ids:
        ref = f"Objects\\Magical_Objects\\Powerups\\{item_id}.entity.ot"
        own = vanilla_bytes(_entity_decoded(ref), game_dir)
        if own is None or not S.has_own_flags(own):
            continue
        chain = _chain(own, game_dir, ref)
        quality, _ = _first_int(chain, "Quality Value")
        if quality != POWERUP_QUALITY:
            continue
        price, own_price = _first_int(chain, "Powerup Price")
        flags = S.read_flags(own)

        name = desc = icon_ref = None
        for d in chain:
            ls = [s for _o, s in find_lstrings(d)]
            name = name or text.get(IC._key_after(ls, IC._NAME_LABEL) or "")
            desc = desc or text.get(IC._key_after(ls, IC._DESC_LABEL) or "")
            icon_ref = icon_ref or find_icon(d)
        label = IC._plain(name) or item_id.removeprefix("Power_Up_").replace("_", " ")
        tier = next((t for t in _TIER_FLAGS if t in flags), None)
        if tier and "Sandman" not in flags and not label.endswith(tier):
            label = f"{label} ({tier})"
        group = next((g for g in ("Sandman", "Grimoire", "Astral") if g in flags),
                     "Wishing Well" if "WishingWell" in flags else "Other")

        icon = ""
        if icons and game_dir is not None and icon_ref:
            from . import ui_textures

            stem = icon_ref.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".png")
            icon = ui_textures.data_url(game_dir, f"Ui/Objects/{stem}.png", ICON_EDGE)
        data.items[item_id] = ShopItem(
            id=item_id, label=label, description=IC._plain(desc) or "", icon=icon,
            group=group, role="duplicate" if "_Duplicate_" in item_id else "offer",
            flags=flags, price=price if price is not None else 0,
            price_editable=own_price,
        )
    return data


def options(game_dir: Path | None) -> list[dict[str, Any]]:
    """Shop-eligible items as config options, with the attributes a grid can
    filter and edit on: ``role``, ``price``, ``priceEditable`` and ``defaultIn``
    (the generators that offer the item in the unmodded game)."""
    if game_dir is None:
        return []
    data = load(game_dir)
    out = []
    for item in sorted(data.items.values(), key=lambda i: (i.group, i.label)):
        out.append({
            "id": item.id, "label": item.label, "group": item.group,
            "icon": item.icon, "description": item.description,
            "attrs": {
                "role": item.role, "price": item.price,
                "priceEditable": item.price_editable,
                "defaultIn": [k for k in EDITABLE if item.id in data.vanilla_members(k)],
            },
        })
    return out
