"""Enemy content builder.

Spawns custom non-boss enemies into vanilla camps by *cloning* a vanilla
``oCDtEnemyDefinition`` (UID ``0x176debb7``, library ``0x1414118c0``,
cooked ext ``*.enemydef.ot``) and re-emitting it under a new id. :func:`emit`
writes one cooked record directly into the mod's ``assets/`` tree at
``Definitions/Enemies/<id>.enemydef.ot.DtEnemyDefinition.gen``; the generic
``apply_mods.py`` new-asset path then registers it in ``UsedRscList.ot`` so
the engine loads it (mirrors the item pipeline — see
:mod:`rsmm.sdk.kinds.items`).

Spawn linkage is by data, not by roster patch. A camp's flag-list entity
selector (``oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings``) picks
enemies whose ``flags`` + ``tribe_ref`` match — so a clone that keeps the
base's flags + tribe is automatically considered wherever the base spawns.
Vanilla ``oCDtEnemyTribeDefinition`` records carry NO enemy roster (all ship
empty), so there is deliberately no tribe-def patch here — the older
``tribe_patch.json`` model was wrong. See ``docs/_re/kinds/enemies.md`` and
the ``enemy-spawn-model`` RE note.

Not yet patchable: HP / damage / on-screen name live on the visual
``oCEntitySettings`` referenced by ``entity_ref`` (``+0x298``), not on the
enemy def — a clone shares its base's stats and name until entity cloning
lands. The byte-level codec is :data:`rsmm.engine.cooked_schemas.definitions`
``oCDtEnemyDefinition`` (round-trips byte-stable).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ...engine import cooked
from ...engine.cooked_schemas import definitions as _defs
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Where the vanilla enemy definitions live in-repo (one cooked `.gen` per
#: enemy id). The clone source for a custom enemy.
_ENEMY_DIR = DATA_DIR / "uncooked" / "Definitions" / "Enemies"
_ENEMY_GEN_SUFFIX = ".enemydef.ot.DtEnemyDefinition.gen"
#: Decoded asset path (forward-slash) the apply pipeline registers in
#: UsedRscList. The stem is the enemy's library identity.
_ENEMY_ASSET_SUBDIR = "Definitions/Enemies"

# --------------------------------------------------------------------------- #
# Class registry constants — confirmed via FUN_140229990 and the live Ghidra
# session. Mirror the table in docs/_re/MOD_HOOKS.md.
# --------------------------------------------------------------------------- #

ENEMY_DEF_UID: Final[int] = 0x176DEBB7
ENEMY_DEF_SIZE: Final[int] = 0x350
ENEMY_DEF_LIBRARY: Final[int] = 0x1414118C0
ENEMY_DEF_RESOURCE_EXT: Final[str] = "*.enemydef.ot"

ENEMY_TRIBE_DEF_LIBRARY: Final[int] = 0x141411200
ENEMY_TRIBE_DEF_RESOURCE_EXT: Final[str] = "*.enemytribedef.ot"

ENEMY_CAMP_TIER_DEF_UID: Final[int] = 0x176E18F8
ENEMY_CAMP_TIER_DEF_SIZE: Final[int] = 0x2A0
ENEMY_CAMP_TIER_DEF_LIBRARY: Final[int] = 0x141411560

#: ctor `FUN_1401db800` writes this to every unresolved name slot. The
#: deserializer treats it as an empty-string sentinel. Re-exported from
#: :mod:`rsmm.sdk.kinds._common` for module-local readability.
EMPTY_STRING_SENTINEL: Final[int] = C.EMPTY_STRING_SENTINEL
UNRESOLVED_NAME_HASH: Final[int] = C.UNRESOLVED_NAME_HASH

#: Schema version of the JSON intermediate written by :func:`emit`. Bump
#: whenever any field below moves or its semantics change so the migrations
#: pipeline (`src/rsmm/sdk/migrations.py`) can rewrite older mods.
ENEMY_MANIFEST_SCHEMA_VERSION: Final[int] = 1


# --------------------------------------------------------------------------- #
# `oCDtEnemyDefinition` (size 0x350) field offsets. Confirmed against
# FUN_1401db800 (ctor), FUN_1401db9b0 (dtor), and FUN_14030b000 (Stage-3
# filter that reads several of these directly). See docs/_re/kinds/enemies.md
# for the full per-offset writeup.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EnemyDefOffsets:
    """Byte offsets into the `oCDtEnemyDefinition` instance."""

    vftable: int = 0x000
    # oCDtDefinition parent (display-name slot, used by oIResourceManager
    # for path-based lookup via library vftable slot 3).
    display_name_ptr: int = 0x270        # ptr<char[]> in parent's body
    flags_word: int = 0x284              # u16 = 0x0101
    # oCDtEnemyDefinition body.
    name_ptr: int = 0x288                # ptr<char[]> — definition id
    name_hash: int = 0x290               # u32, default 0x80000000
    entity_asset_ptr: int = 0x298        # ptr<char[]> — visual entity ref
    entity_asset_hash: int = 0x2A0       # u32, default 0x80000000
    excluded_byte: int = 0x2B0           # u8 — Stage-3 filter reads this
    # MaxOccurence vector (tier curve, head — see filter line 263).
    # NOTE: filter reads {data_ptr@+0x2b8, count@+0x2c0}; the ctor expresses
    # the same span as the oCCustomFlagList vftable@+0x2c0 — these aliases
    # overlap. See enemies.md "Notes" for the reconciliation.
    max_occurrence_ptr: int = 0x2B8
    max_occurrence_count: int = 0x2C0
    flag_list_data_ptr: int = 0x2C8      # oCCustomFlagList::data
    flag_list_count: int = 0x2D0         # oCCustomFlagList::count
    flag_list_capacity: int = 0x2D8      # oCCustomFlagList::capacity, init 1
    min_tier_float: int = 0x2DC          # f32, init 0.1f
    tier_range: int = 0x2E0              # u64 = {u32 min, u32 max}
    has_tribe_byte: int = 0x310          # u8 — gate for tribe ptr read
    tribe_ptr: int = 0x318               # oCDtEnemyTribeDefinition* (raw)
    default_weight: int = 0x320          # f32, init -1.0f
    tier_weight_table_a_ptr: int = 0x328   # {u32 tier, f32 weight}[]
    tier_weight_table_a_count: int = 0x330  # u32
    secondary_weight: int = 0x338        # f32, init -1.0f
    tier_weight_table_b_ptr: int = 0x340
    tier_weight_table_b_count: int = 0x348


ENEMY_DEF: Final = EnemyDefOffsets()


# --------------------------------------------------------------------------- #
# Public emit() — see docstring at top of file for the JSON layout.
# --------------------------------------------------------------------------- #

# Fields accepted on a ContentDef.fields dict.
_KNOWN_FIELDS = (
    "base", "name", "display_name", "tribe", "flags", "add_flags",
    "weight", "entity",
)


def _enemy_class() -> str:
    return "oCDtEnemyDefinition"


def _load_base_cooked(base_id: str) -> bytes | None:
    """Return the cooked bytes of a vanilla enemy def, or None if no such
    enemy ships under the in-repo enemy-definition tree."""
    p = _ENEMY_DIR / f"{base_id}{_ENEMY_GEN_SUFFIX}"
    return p.read_bytes() if p.is_file() else None


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a single custom enemy as a cooked ``oCDtEnemyDefinition``.

    Clone-and-patch: the cooked bytes of a vanilla ``base`` enemy are
    decoded, the spawn-relevant body fields are overridden, and the
    record is re-emitted under a NEW filename. The stem of that filename
    is the enemy's library identity; ``apply_mods.py`` registers it in
    ``UsedRscList`` so the engine loads it. Because the camp spawn
    selector picks enemies by ``flags`` + ``tribe`` (not by id — see
    docs/_re/kinds/enemies.md and the enemy-spawn-model note), a clone
    that keeps the base's flags + tribe is considered by every camp the
    base spawns in.

    Required fields:
        ``base``   id of a vanilla enemy to clone (e.g. ``Gnoll_Shielded``).

    Optional fields (each defaults to the base's value):
        ``tribe``  tribe name → repoints ``tribe_ref`` at
                   ``EnemyTribes\\<tribe>.enemytribedef.ot``.
        ``flags``  replace the ``oCCustomFlagList`` tag list outright.
        ``add_flags`` extend the base's tag list (ignored if ``flags`` set).
        ``weight`` spawn weight (float) the selector uses to bias picks.
        ``entity`` raw ``entity_ref`` path override (advanced; default
                   reuses the base's visual entity, so the clone looks
                   like its base). HP/damage/name live on that entity —
                   not yet patchable, so a clone shares the base's stats
                   and on-screen name until entity cloning lands.

    Returns ``[<out_dir>/Definitions/Enemies/<id>.enemydef.ot.DtEnemyDefinition.gen]``.
    """
    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise ContentError(
            f"enemy {defn.id}: needs a 'base' (vanilla enemy id) to clone, "
            f"e.g. base=\"Gnoll_Shielded\". See docs/_re/kinds/enemies.md."
        )
    try:
        C.validate_id("enemy", defn.id)
    except ValueError as e:
        raise ContentError(str(e)) from e

    base_cooked = _load_base_cooked(base)
    if base_cooked is None:
        raise SchemaNotMined(
            f"enemy {defn.id}: base {base!r} not found under "
            f"{_ENEMY_DIR} — pass a vanilla enemy id whose cooked def is "
            f"bundled (run `rsmm enemies` to list bases)."
        )

    spec = _defs._SPECS[_enemy_class()]
    try:
        cf = cooked.parse(base_cooked)
        body = spec.decode_body(cf.sections[-1].payload)
    except (ValueError, IndexError) as e:
        raise ContentError(
            f"enemy {defn.id}: failed to decode base {base!r}: {e}"
        ) from e

    # --- patch body ------------------------------------------------------- #
    tribe = defn.fields.get("tribe")
    if tribe is not None:
        if not isinstance(tribe, str) or not C.ID_PATTERN.match(tribe):
            raise ContentError(
                f"enemy {defn.id}: 'tribe' must match {C.ID_PATTERN.pattern}."
            )
        ns = body["tribe_ref"][0] or "Definitions"
        body["tribe_ref"] = [ns, f"EnemyTribes\\{tribe}.enemytribedef.ot"]
        body["base_flags"] = [1, 1]  # has-tribe gate on

    if defn.fields.get("flags") is not None:
        flags = list(defn.fields["flags"])
    else:
        flags = list(body.get("flags") or [])
        flags += list(defn.fields.get("add_flags") or [])
    if not all(isinstance(t, str) and C.ID_PATTERN.match(t) for t in flags):
        raise ContentError(
            f"enemy {defn.id}: every flag must match {C.ID_PATTERN.pattern} "
            f"(game-side tag strings are strict)."
        )
    # de-dupe preserving order
    body["flags"] = list(dict.fromkeys(flags))

    weight = defn.fields.get("weight")
    if weight is not None:
        body["spawn_weight"] = float(weight)

    entity = defn.fields.get("entity")
    if entity is not None:
        if not isinstance(entity, str):
            raise ContentError(f"enemy {defn.id}: 'entity' must be a string path.")
        ns = body["entity_ref"][0] or "EntitySettings"
        body["entity_ref"] = [ns, entity]

    # --- re-emit cooked record under the new id --------------------------- #
    cf.sections[-1] = cooked.Section(payload=spec.encode_body(body))
    new_cooked = cooked.emit(cf)

    decoded_rel = f"{_ENEMY_ASSET_SUBDIR}/{defn.id}{_ENEMY_GEN_SUFFIX}"
    dest = out_dir / Path(*decoded_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_cooked)
    _log.info(
        "enemy %s/%s: emitted cooked def (base=%s, tribe=%s, flags=%s, weight=%s)",
        mod_id, defn.id, base, body["tribe_ref"][1], body["flags"],
        body["spawn_weight"],
    )
    return [dest]
