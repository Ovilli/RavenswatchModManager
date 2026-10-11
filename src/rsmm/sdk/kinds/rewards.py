"""**Reward placement** editor — ban/tune what spawns at reward points (SDK entry).

Unlike the clone-under-a-new-id kinds, a ``reward`` def is an **override of a
retail** ``*.rewarddef.ot`` — the emitted asset lands at the vanilla decoded
path and ``rsmm apply`` backs up + replaces the original (the plain override
path, same as textures). The seeded level-load roll
(``Reward_GenerateAndDistribute``) then never sees the banned entities, which
keeps multiplayer deterministic — every peer loads the same data.

This bans reward *objects* (chests / astrolabs / dream crystals at spawn
points). It does NOT ban talent/item *cards* — that lever is the LiveOps
versiondef MO vector (see docs/_re/kinds/rewards.md).

Fields:
    ``base`` (str, required)   retail rewarddef stem to override, e.g.
                               ``Camp_Rewards_Avalon_Update5``. The plain
                               ``Camp_Rewards_<Biome>`` defs are dead (nothing
                               references them) and are refused.
    ``ban`` (list[str], opt.)  entity-path substrings, case-insensitive. A match
                               on an item's ``entity`` drops it from all reward
                               categories; a match on its locked-variant ref
                               (``_ref_b``, e.g. ``ban=["Chest_Locked"]``) clears
                               that ref so the chest only spawns unlocked. Each
                               entry must match something (typo guard).
    ``counts`` (dict, opt.)    per-category spawn-count override,
                               ``{category_index: [min, max]}`` (a category =
                               one ``reward_types`` row of the decoded def;
                               ``[0, 0]`` bans the whole category).

PROVEN IN GAME 2026-09-19 on Camp_Rewards_Dark_Hills_Update5: forcing the
astrolab type to [3, 3] placed exactly 3 (vanilla 0..1), and banning
DreamCrystal placed 0 (vanilla 1..3). Rewards built into a tile itself (a chest
standing in a camp tile) are part of that tile, not of this roll.

See ``docs/_re/kinds/rewards.md`` for the decoded layout and the roll gate.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ...engine import corpus
from ...engine.cooked_schemas.definitions import RewardDefinitionHandler
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Decoded directory of the retail reward defs (read through `engine.corpus`).
_REWARD_DIR = "Definitions/Rewards"
_ASSET_SUBDIR = "Definitions/Rewards"
GEN_SUFFIX = ".rewarddef.ot.DtRewardDefinition.gen"


def _basename(entity_path: str) -> str:
    return entity_path.replace("\\", "/").rsplit("/", 1)[-1]


def _apply_ban(doc: dict, patterns: list[str], defn_id: str) -> list[int]:
    """Ban reward entities matching any pattern. A pattern matching an item's
    ``entity`` drops that item from every reward_types row (the row itself
    stays — unreferenced sub-objects are inert — so indices remain stable).
    A pattern matching only the ``_ref_b`` locked-variant path clears that
    ref instead (empty ref is a valid retail state), so the item keeps
    spawning but never as its locked variant. Returns the dropped indices."""
    banned: set[int] = set()
    for pat in patterns:
        pat_lc = pat.lower()
        hit = False
        for i, item in enumerate(doc["reward_items"]):
            if pat_lc in item["entity"].lower():
                banned.add(i)
                hit = True
            elif item["_ref_b"][1] and pat_lc in item["_ref_b"][1].lower():
                item["_ref_b"] = ["", ""]
                hit = True
        if not hit:
            known = sorted(
                {_basename(i["entity"]) for i in doc["reward_items"]}
                | {_basename(i["_ref_b"][1]) for i in doc["reward_items"] if i["_ref_b"][1]}
            )
            raise ContentError(
                f"reward {defn_id}: ban pattern {pat!r} matches no reward item. "
                f"Entities in this def: {', '.join(known)}."
            )
    for t in doc["reward_types"]:
        t["items"] = [i for i in t["items"] if i not in banned]
        if not t["items"]:
            # A category with no candidates left must not be rolled at all.
            t["min_count"] = 0
            t["max_count"] = 0
    return sorted(banned)


def _apply_counts(doc: dict, counts: dict, defn_id: str) -> None:
    n_types = len(doc["reward_types"])
    for key, val in counts.items():
        try:
            idx = int(key)
        except (TypeError, ValueError):
            raise ContentError(
                f"reward {defn_id}: counts key {key!r} must be a category index "
                f"(0..{n_types - 1})."
            ) from None
        if not 0 <= idx < n_types:
            raise ContentError(
                f"reward {defn_id}: counts index {idx} out of range "
                f"(def has {n_types} categories)."
            )
        if (not isinstance(val, (list, tuple)) or len(val) != 2
                or not all(isinstance(v, int) and v >= 0 for v in val)
                or val[0] > val[1]):
            raise ContentError(
                f"reward {defn_id}: counts[{idx}] must be [min, max] with "
                f"0 <= min <= max, got {val!r}."
            )
        doc["reward_types"][idx]["min_count"] = val[0]
        doc["reward_types"][idx]["max_count"] = val[1]


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize an edited retail rewarddef as an override asset."""
    C.validate_id("reward", defn.id)

    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise ContentError(
            f"reward {defn.id}: needs a 'base' (retail rewarddef stem) to edit, "
            f'e.g. base="Camp_Rewards_Avalon". See docs/_re/kinds/rewards.md.'
        )

    base_bytes = corpus.read(f"{_REWARD_DIR}/{base}{GEN_SUFFIX}")
    if base_bytes is None:
        raise SchemaNotMined(
            f"reward {defn.id}: base {base!r} is not a shipped rewarddef — pass a "
            f"retail rewarddef stem (the game install, or data/uncooked, must be "
            f"readable)."
        )

    # A base with an `_Update5` sibling is DEAD: only the LiveOps5 versiondef
    # references reward defs, and it names the Update5 ones (checked over the
    # shipped corpus 2026-09-19 — Camp_Rewards_<Biome> is referenced by
    # nothing). Editing the dead one installs cleanly and changes nothing,
    # which is how an earlier ban read as "unreliable".
    if corpus.exists(f"{_REWARD_DIR}/{base}_Update5{GEN_SUFFIX}"):
        raise ContentError(
            f"reward {defn.id}: {base!r} is superseded and never loaded — the game "
            f"rolls from {base}_Update5. Use base = \"{base}_Update5\".")

    ban = defn.fields.get("ban")
    counts = defn.fields.get("counts")
    if ban is None and counts is None:
        raise ContentError(
            f"reward {defn.id}: no edits — give 'ban' (entity substrings) "
            f"and/or 'counts' ({{category: [min, max]}})."
        )
    if ban is not None and (not isinstance(ban, (list, tuple))
                            or not all(isinstance(p, str) and p for p in ban)):
        raise ContentError(
            f"reward {defn.id}: 'ban' must be a list of non-empty entity-path "
            f"substrings, got {ban!r}."
        )
    if counts is not None and not isinstance(counts, dict):
        raise ContentError(
            f"reward {defn.id}: 'counts' must be a mapping "
            f"{{category_index: [min, max]}}, got {counts!r}."
        )

    h = RewardDefinitionHandler()
    doc = json.loads(h.decode_cooked(base_bytes))
    banned: list[int] = []
    if ban:
        banned = _apply_ban(doc, list(ban), defn.id)
    if counts:
        _apply_counts(doc, counts, defn.id)
    new_cooked = h.encode_container(json.dumps(doc).encode("utf-8"))

    # Override the RETAIL path — apply backs up + replaces the original.
    decoded_rel = f"{_ASSET_SUBDIR}/{base}{GEN_SUFFIX}"
    dest = out_dir / Path(*decoded_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_cooked)
    _log.info("reward %s/%s: override %s (banned items=%s, counts=%s)",
              mod_id, defn.id, base, banned, counts)
    return [dest]
