"""Magic item (MagicalObject) registry.

Scans `data/uncooked/EntitySettings/Objects/Magical_Objects/<rarity>/`
for `*.entity.ot.EntitySettingsResource.gen.txt` files produced by
`ot_decoder`, extracts the text-bank keys (Name / Description /
SuperEffect) and icon decoded path for each item.

Each magic item ID is the filename stem (e.g. `Armor_Per_Object`).
The registry powers SDK and CLI surfaces that need to enumerate items
or validate item references.

This is a static, data-driven registry — it does not need the game to
be installed. It only reads the repo's `data/uncooked/` mirror.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

MAGIC_RARITIES = ("Common", "Rare", "Epic", "Legendary", "Cursed", "Powerups")

# Pattern matches lines like:  @00bb  str(len=21)  "Armor_Per_Object_Name"
_STR_LINE = re.compile(r'^\s*@[0-9a-fA-F]+\s+str\(len=\d+\)\s+"(.*)"\s*$')


@dataclass
class MagicItem:
    """One magic-item entity discovered in data/uncooked."""
    id: str                              # filename stem, e.g. "Armor_Per_Object"
    rarity: str                          # "Common" | "Rare" | ...
    entity_decoded_path: str             # decoded cooked path
    name_key: str | None = None          # text-bank key for the name
    desc_key: str | None = None          # text-bank key for description
    super_keys: list[str] = field(default_factory=list)  # super-effect text keys
    icon_decoded_path: str | None = None # decoded path of the .png.Texture.dxt
    debug_name: str | None = None        # human label (e.g. "Green_Armor")


_UNCOOKED = DATA_DIR / "uncooked"
_MAGIC_DIR = _UNCOOKED / "EntitySettings" / "Objects" / "Magical_Objects"


def _strings_in(txt: str) -> list[str]:
    out: list[str] = []
    for line in txt.splitlines():
        m = _STR_LINE.match(line)
        if m:
            out.append(m.group(1))
    return out


def _scan_one(item_id: str, rarity: str, gen_txt_path: Path) -> MagicItem:
    txt = gen_txt_path.read_text(encoding="utf-8", errors="replace")
    strs = _strings_in(txt)

    # Walk pairs: a "Text" + "Magical_Objects~GAM.xls" pair is followed
    # by the key string. The decoded dump emits Text bank refs as
    # adjacent str lines.
    keys: list[str] = []
    for i, s in enumerate(strs):
        if s == "Magical_Objects~GAM.xls" and i + 1 < len(strs):
            keys.append(strs[i + 1])

    name_key = next((k for k in keys if k.endswith("_Name")), None)
    desc_key = next((k for k in keys if k.endswith("_Description")), None)
    super_keys = [k for k in keys if "SuperEffect" in k]

    # Icon: any "Objects\<prefix>_Object_*.png" entry. Prefix varies
    # (`UI_Object_`, `Icon_Object_`, ...) so match by suffix instead.
    icon = None
    for s in strs:
        norm = s.replace("\\", "/")
        if norm.startswith("Objects/") and norm.endswith(".png"):
            icon = "Ui/" + norm + ".Texture.dxt"
            break

    # Debug name: a [Value] Magical_Objects_Model\Debug Name section
    # has the debug string as the *value*. Lookup pattern: find
    # "Debug Name" then the next str is the debug name.
    debug_name = None
    for i, s in enumerate(strs):
        if s == "Debug Name" and i + 1 < len(strs):
            debug_name = strs[i + 1]
            break

    decoded = (
        f"EntitySettings/Objects/Magical_Objects/{rarity}/"
        f"{item_id}.entity.ot.EntitySettingsResource.gen"
    )
    return MagicItem(
        id=item_id, rarity=rarity, entity_decoded_path=decoded,
        name_key=name_key, desc_key=desc_key, super_keys=super_keys,
        icon_decoded_path=icon, debug_name=debug_name,
    )


@lru_cache(maxsize=1)
def registry() -> dict[str, MagicItem]:
    """item_id -> MagicItem. Empty if data/uncooked/ is missing."""
    out: dict[str, MagicItem] = {}
    if not _MAGIC_DIR.is_dir():
        return out
    for rarity_dir in _MAGIC_DIR.iterdir():
        if not rarity_dir.is_dir():
            continue
        rarity = rarity_dir.name
        for f in rarity_dir.glob("*.entity.ot.EntitySettingsResource.gen.txt"):
            item_id = f.name.split(".entity.ot.", 1)[0]
            try:
                out[item_id] = _scan_one(item_id, rarity, f)
            except Exception:
                # Best-effort; broken/partial dumps just get skipped.
                continue
    return out


def get(item_id: str) -> MagicItem | None:
    """Lookup by ID. Case-sensitive (matches decoded filenames)."""
    reg = registry()
    if item_id in reg:
        return reg[item_id]
    # case-insensitive fallback
    low = item_id.lower()
    for k, v in reg.items():
        if k.lower() == low:
            return v
    return None


def list_ids(rarity: str | None = None, grep: str | None = None) -> list[str]:
    needle = grep.lower() if grep else None
    out: list[str] = []
    for k, v in registry().items():
        if rarity and v.rarity.lower() != rarity.lower():
            continue
        if needle and needle not in k.lower():
            continue
        out.append(k)
    return sorted(out)


def to_json() -> str:
    """Snapshot for tests / CLI introspection."""
    return json.dumps(
        {k: asdict(v) for k, v in sorted(registry().items())},
        indent=2,
    )


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Magic-item registry inspector")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--grep", default=None)
    ap.add_argument("--rarity", default=None,
                    help="filter by rarity: " + ", ".join(MAGIC_RARITIES))
    ap.add_argument("--show", metavar="ID", help="dump one item")
    ap.add_argument("--json", action="store_true",
                    help="dump full registry as JSON")
    a = ap.parse_args()
    if a.json:
        print(to_json())
        return 0
    if a.show:
        item = get(a.show)
        if not item:
            print(f"unknown magic item: {a.show}")
            return 1
        for k, v in asdict(item).items():
            print(f"  {k:>22s}: {v}")
        return 0
    ids = list_ids(rarity=a.rarity, grep=a.grep)
    if not ids:
        print("(no magic items found — does data/uncooked/ exist?)")
        return 1
    reg = registry()
    for k in ids:
        v = reg[k]
        print(f"  [{v.rarity:>10s}]  {k}"
              f"  (name={v.name_key!r}, icon={v.icon_decoded_path!r})")
    print(f"\n{len(ids)} item(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
