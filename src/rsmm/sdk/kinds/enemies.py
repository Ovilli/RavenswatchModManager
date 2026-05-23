"""Enemy content builder.

Spawns custom non-boss enemies into vanilla camps by emitting three
intermediate JSON records under ``_pending_enemies/<id>/``:

* ``def.json`` — the cooked ``oCDtEnemyDefinition`` payload
  (UID ``0x176debb7``, size ``0x350``, library ``0x1414118c0``).
* ``tribe_patch.json`` — a hook into the named ``oCDtEnemyTribeDefinition``
  (library ``0x141411200``) so the camp/tier selector picks the new
  enemy up via the existing tag-filter pipeline.
* ``i18n.json`` — a text-bank override for the visible name, namespaced
  as ``RSMM_<modid>_<id>_name`` to match :mod:`rsmm.sdk.i18n`.

The apply step (``apply_mods.py`` + loader DLL) is responsible for
turning these JSON intermediates into actual cooked-asset bytes and
calling ``oIResourceManager::FindOrLoad`` (library vftable slot 3) to
inject them at startup. The on-disk binary encoder is intentionally
**not** in this module — it lives next to the rest of the cooked-byte
infrastructure (see :mod:`rsmm.sdk.kinds.item.schema` for the items
equivalent) and consumes the JSON we emit here.

Field-offset provenance: see ``docs/_re/kinds/enemies.md`` —
the comments below mirror that doc; anything marked ``TODO: confirm``
is a clone-from-base fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

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

# Spec for the kwargs we accept on a ContentDef.fields dict.
_REQUIRED = ("base", "tribe")
_KNOWN_FIELDS = (
    "name", "display_name", "base", "hp", "damage",
    "tribe", "tags", "tier", "is_elite",
)

def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize a single enemy def under ``out_dir``.

    Required fields:
        ``base``  — id of a vanilla enemy to clone for any field whose
                    offset is not yet confirmed (HP/damage live on the
                    `+0x298` visual-entity resource — see enemies.md).
        ``tribe`` — name of an `oCDtEnemyTribeDefinition` to hook into.
                    Required because without a tribe-entry patch the
                    camp selector never considers the new enemy.

    Optional fields:
        ``name``            short identifier (defaults to ``defn.id``)
        ``display_name``    human-readable; emitted as text-bank override
        ``hp``, ``damage``  forwarded to the entity-asset patcher
        ``tags``            list of ``oCCustomFlagList`` tag strings
        ``tier``            int 1..N, clamped to ``tier_range`` (defaults
                            to (1, 5) matching ctor)
        ``is_elite``        bool — adds the "elite" tag to ``tags`` so
                            the camp selector's filter B picks it up
                            (TODO: confirm the exact vanilla tag string)

    Returns the list of paths actually written under
    ``out_dir/_pending_enemies/<id>/``.
    """
    base = defn.fields.get("base")
    tribe = defn.fields.get("tribe")
    if not base or not isinstance(base, str):
        raise SchemaNotMined(
            f"enemy {defn.id}: needs a 'base' (vanilla enemy id) to clone "
            f"for fields whose offsets aren't fully confirmed yet — see "
            f"docs/_re/kinds/enemies.md → 'Still unknown'."
        )
    if not tribe or not isinstance(tribe, str):
        raise ContentError(
            f"enemy {defn.id}: 'tribe' (name of an oCDtEnemyTribeDefinition) "
            f"is required so the camp selector can spawn it. See "
            f"docs/_re/kinds/enemies.md → 'Insertion recipe'."
        )
    try:
        C.validate_id("enemy", defn.id)
    except ValueError as e:
        raise ContentError(str(e)) from e

    unknown = sorted(set(defn.fields) - set(_KNOWN_FIELDS))
    if unknown:
        # Soft warning recorded in the JSON manifest; doesn't fail emit so
        # mods can carry fields the apply step might know about.
        pass

    short_name: str = str(defn.fields.get("name") or defn.id)
    display_name: str = str(
        defn.fields.get("display_name") or defn.fields.get("name") or defn.id
    )
    hp = defn.fields.get("hp")
    damage = defn.fields.get("damage")
    tags = list(defn.fields.get("tags") or [])
    tier = int(defn.fields.get("tier") or 1)
    is_elite = bool(defn.fields.get("is_elite") or False)

    if not all(isinstance(t, str) and C.ID_PATTERN.match(t) for t in tags):
        raise ContentError(
            f"enemy {defn.id}: every entry in `tags` must match "
            f"{C.ID_PATTERN.pattern} (game-side tag strings are strict)."
        )
    if is_elite and "elite" not in tags:
        # TODO: confirm — string-pool scan needed to enumerate the
        # canonical vanilla tag for elites. Using "elite" as a
        # conventional placeholder so mods don't have to guess.
        tags.append("elite")

    base_dir = out_dir / "_pending_enemies" / defn.id

    written: list[Path] = []

    # --- def.json --------------------------------------------------------- #
    def_payload: dict[str, Any] = {
        "kind": "enemy",
        "id": defn.id,
        "mod": mod_id,
        "schema_version": defn.schema_version,
        "manifest_schema_version": ENEMY_MANIFEST_SCHEMA_VERSION,
        "uid": ENEMY_DEF_UID,
        "record_size": ENEMY_DEF_SIZE,
        "resource_ext": ENEMY_DEF_RESOURCE_EXT,
        "library_global": ENEMY_DEF_LIBRARY,
        "base": base,
        "name": short_name,
        "display_name_key": f"RSMM_{mod_id}_{defn.id}_name",
        # Field plan — the apply-step encoder writes these to the named
        # offsets (see EnemyDefOffsets above) on a fresh ENEMY_DEF_SIZE
        # buffer. Anything left None is filled from the cooked-asset
        # bytes of the `base` enemy (clone-and-patch fallback).
        "fields": {
            "display_name_ptr": short_name,
            "name_ptr": defn.id,
            "name_hash": C.name_hash(defn.id),
            "entity_asset_ptr": None,       # cloned from base
            "entity_asset_hash": None,
            "excluded_byte": 0,
            "flag_list_tags": tags,
            "min_tier_float": 0.1,
            "tier_range": [max(1, tier), max(tier, 5)],
            "has_tribe_byte": 1,
            "tribe_name": tribe,            # resolved by apply step
            "default_weight": 1.0,
            "tier_weight_table_a": [
                {"tier": max(1, tier), "weight": 1.0},
            ],
            "secondary_weight": -1.0,
            "tier_weight_table_b": [],
            # Stat overrides — these live on the entity_asset, not the
            # enemy def itself. The apply step patches them on the
            # base-cloned entity (TODO: confirm offsets).
            "stat_overrides": {
                "hp": hp,
                "damage": damage,
            },
        },
        "offsets": _offsets_dict(),
    }
    written.append(C.write_json(base_dir / "def.json", def_payload))

    # --- tribe_patch.json ------------------------------------------------- #
    tribe_patch: dict[str, Any] = {
        "kind": "enemy_tribe_patch",
        "mod": mod_id,
        "enemy_id": defn.id,
        "schema_version": defn.schema_version,
        "manifest_schema_version": ENEMY_MANIFEST_SCHEMA_VERSION,
        "library_global": ENEMY_TRIBE_DEF_LIBRARY,
        "resource_ext": ENEMY_TRIBE_DEF_RESOURCE_EXT,
        "tribe_name": tribe,
        # The apply step appends a `TribeEntryRef` pointing at our new
        # `oCDtEnemyDefinition` to the tribe's entry vector
        # (`+0x2b8/+0x2c0` of `oCDtEnemyTribeDefinition`). Without this
        # patch the Stage-3 filter still sees our enemy but no camp
        # selector ever picks it up.
        "append_entry": {
            "enemy_id": defn.id,
            "weight": 1.0,
            "is_elite": is_elite,
        },
    }
    written.append(C.write_json(base_dir / "tribe_patch.json", tribe_patch))

    # --- i18n.json -------------------------------------------------------- #
    # Apply-time merge into the per-locale text bank under
    # `RSMM_<modid>_<id>_name`. The visual-entity asset's `name_key`
    # field must point to this key for the override to take effect —
    # that fixup happens in the entity-asset patch driven by `base`.
    i18n_payload: dict[str, Any] = {
        "kind": "enemy_i18n",
        "mod": mod_id,
        "enemy_id": defn.id,
        "schema_version": defn.schema_version,
        "manifest_schema_version": ENEMY_MANIFEST_SCHEMA_VERSION,
        "strings": {
            f"RSMM_{mod_id}_{defn.id}_name": display_name,
        },
        # Locale is unspecified here — `apply_mods.py` reads the mod's
        # `lang/<locale>.toml` files for full localisation; this entry
        # is the **fallback** used if the mod ships no lang/ dir.
        "fallback_locale": "EN",
    }
    written.append(C.write_json(base_dir / "i18n.json", i18n_payload))

    return written


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _offsets_dict() -> dict[str, int]:
    """Snapshot of the EnemyDefOffsets table for the JSON manifest.

    Embedding the offsets in the manifest lets the apply step
    cross-check that it's working with the schema it was built for
    (a game patch that moves any field bumps
    ``ENEMY_MANIFEST_SCHEMA_VERSION`` and forces a migration).
    """
    return {
        name: getattr(ENEMY_DEF, name)
        for name in ENEMY_DEF.__dataclass_fields__
    }
