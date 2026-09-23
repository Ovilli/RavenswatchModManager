"""Magic item (MagicalObject) registry.

Reads every shipped `EntitySettings/Objects/Magical_Objects/<rarity>/<id>`
entity through `rsmm.engine.corpus` (the game install, or the mirror on an
authoring checkout), lists its embedded strings, and extracts the text-bank
keys (Name / Description / SuperEffect) and icon decoded path.

It used to read `*.gen.txt` dumps from the mirror instead. Those are only
written by a hand-run `scripts/decode_gen_sidecars.py`, so the registry was
empty on every machine — including developer checkouts whose mirror had been
re-extracted. `entity_strings.list_strings` on the cooked file yields the same
string sequence the dump did (checked over all 125 shipped items).

Each magic item ID is the filename stem (e.g. `Armor_Per_Object`).
The registry powers SDK and CLI surfaces that need to enumerate items
or validate item references.

It needs a readable game install (or the mirror); without one it is empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from rsmm.logging import get_logger

logger = get_logger(__name__)

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


_MAGIC_DIR = "EntitySettings/Objects/Magical_Objects/"
_ENTITY_SUFFIX = ".entity.ot.EntitySettingsResource.gen"


def _strings_in(txt: str) -> list[str]:
    out: list[str] = []
    for line in txt.splitlines():
        m = _STR_LINE.match(line)
        if m:
            out.append(m.group(1))
    return out


def _scan_one(item_id: str, rarity: str, gen_txt_path: Path) -> MagicItem:
    """Scan an `ot_decoder` text dump (`*.gen.txt`) of one item."""
    txt = gen_txt_path.read_text(encoding="utf-8", errors="replace")
    return _scan_strings(item_id, rarity, _strings_in(txt))


def _scan_strings(item_id: str, rarity: str, strs: list[str]) -> MagicItem:
    """Build the record from an item entity's embedded strings, in file order."""

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
    for item_id, rarity, strs in _sources():
        try:
            out[item_id] = _scan_strings(item_id, rarity, strs)
        except Exception as e:
            # Best-effort; a broken entity just gets skipped, but log so a
            # missing item in the registry is diagnosable.
            logger.debug("skipping unscannable magic item %s: %s", item_id, e)
    return out


def _sources():
    """Yield ``(item_id, rarity, strings)`` for every shipped magic item."""
    from . import corpus
    from . import entity_strings as ES

    for rel in corpus.rels(_MAGIC_DIR, _ENTITY_SUFFIX):
        rarity, _, leaf = rel[len(_MAGIC_DIR):].rpartition("/")
        if not rarity or "/" in rarity:
            continue
        raw = corpus.read(rel)
        if raw is None:
            continue
        try:
            strs = [s for _sec, _off, s in ES.list_strings(raw)]
        except ValueError as e:
            logger.debug("skipping unparseable magic item %s: %s", rel, e)
            continue
        yield leaf[: -len(_ENTITY_SUFFIX)], rarity, strs


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
        print("(no magic items found — is the game install readable? set RSMM_GAME_DIR)")
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
