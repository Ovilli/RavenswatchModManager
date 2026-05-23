"""Magical-object / reward schema constants.

All offsets are bytes from the start of the class instance. Source for
each one is recorded inline; cross-reference
`docs/_re/kinds/items.md` and `docs/_re/MOD_HOOKS.md` for full
provenance. Anything marked ``TODO_CONFIRM`` is an educated guess that
the emit layer **must** stamp into the manifest's ``synthesized`` map
so the apply pipeline can later audit it.

The numbers in here are read by:

* :mod:`rsmm.sdk.kinds.items` (emit pipeline)
* the apply-step encoder that turns a ``_pending_items/<id>.json``
  manifest into cooked bytes once it lands.

We intentionally keep the values in pure Python (no native build) so
the apply layer stays portable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ----------------------------------------------------------------------------
# Class registry — see docs/_re/MOD_HOOKS.md "The two systems you need".
# ----------------------------------------------------------------------------

# `oCDtRewardDefinition`. Registrar: FUN_140237f40. Schema callback:
# FUN_14031a040 ("Reward definition"). Resource extension: "*.rewarddef.ot".
REWARD_DEF_UID: Final = 0x176F164E
REWARD_DEF_SIZE: Final = 0x298
REWARD_DEF_META_GLOBAL: Final = 0x141447BD0  # oCMetaClass*
REWARD_DEF_LIBRARY_GLOBAL: Final = 0x141412E00  # oCTLibrary<...>
REWARD_DEF_RESOURCE_EXT: Final = "*.rewarddef.ot"

# `oCDtEntityCpntMagicalObjectsDropSettings`. Registrar: FUN_140277790.
# Schema callback: FUN_1402d2290 ("Magical Object Drops"). Ctor: FUN_1402d2310.
MAGICAL_OBJECTS_DROP_SETTINGS_UID: Final = 0x168AFCA6
MAGICAL_OBJECTS_DROP_SETTINGS_SIZE: Final = 0xA50
MAGICAL_OBJECTS_DROP_SETTINGS_META_GLOBAL: Final = 0x141447F98

# `oCDtEntityCpntMagicalObject` (runtime component, NOT registry-keyed).
# Ctor: FUN_1401e0e10. Size derived by walking the ctor body (last write
# is `param_1[0x55]+4 = 0xffffffff` → offset 0x2ac → next aligned size = 0x2b0).
MAGICAL_OBJECT_RUNTIME_SIZE: Final = 0x2B0

# `oCDtRewardEntitySelectorToSpawnEntityCpntSettings`. Ctor: FUN_1401e3e90.
# Body extends through `[0x28]` so size >= 0x148.
REWARD_SELECTOR_MIN_SIZE: Final = 0x148

# ----------------------------------------------------------------------------
# Field offsets — `oCDtRewardDefinition` (size 0x298).
# Source: FUN_1401e3ca0 (ctor) + FUN_1401e3d50 (dtor). See items.md.
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class RewardDefOffsets:
    vftable: int = 0x00
    # oCResourcePath shape (used by oIResourceManager slot 3).
    name_ptr: int = 0x40              # ptr<char[]>
    name_hash: int = 0x48             # u32
    # oCDtDefinition body (parent class).
    display_name_ptr: int = 0x270     # ptr — released by FUN_1401334e0 in dtor
    flags_word: int = 0x284           # u16 = 0x0101 by default
    # oCDtRewardDefinition body.
    entries_ptr: int = 0x288          # ptr to qword[] of reward entries
    entries_length: int = 0x290       # u32
    entries_capacity: int = 0x294     # u32


REWARD_DEF: Final = RewardDefOffsets()


# ----------------------------------------------------------------------------
# Field offsets — `oCDtEntityCpntMagicalObject` (size 0x2b0).
# Source: FUN_1401e0e10 (ctor) + FUN_1401e10f0 (dtor).
# The three int signals are at +0x1f8/+0x218/+0x238 — labels are
# TODO_CONFIRM (educated guess from declaration order).
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class MagicalObjectOffsets:
    vftable: int = 0x00
    # bool signals.
    signal_is_active: int = 0x18      # EntityCpntValueSignal<bool>
    signal_ever_spawned: int = 0x38   # EntityCpntValueSignal<bool>
    # int signals — labels are speculative (TODO_CONFIRM).
    signal_rarity: int = 0x1F8        # EntityCpntValueSignal<int>
    signal_count: int = 0x218         # EntityCpntValueSignal<int>
    signal_level: int = 0x238         # EntityCpntValueSignal<int>
    # tag list at tail.
    flag_list_vftable: int = 0x290
    flag_list_sentinel: int = 0x2AC   # 0xffffffff


MAGICAL_OBJECT: Final = MagicalObjectOffsets()


# ----------------------------------------------------------------------------
# Field offsets — `oCDtRewardEntitySelectorToSpawnEntityCpntSettings`.
# Source: FUN_1401e3e90.
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class RewardSelectorOffsets:
    vftable_primary: int = 0x00
    vftable_secondary: int = 0x08
    target_name_ptr: int = 0xF8       # ptr<char[]> — name of referenced reward
    target_name_hash: int = 0x100     # u32, default 0x80000000 (unresolved)
    target_resolved_flag: int = 0x104
    parent_name_ptr: int = 0x108
    parent_name_hash: int = 0x110     # u32, default 0x80000000
    parent_resolved_flag: int = 0x114
    target_meta_ptr: int = 0x118      # oCMetaClass* (REWARD_DEF_META_GLOBAL)
    enabled_byte: int = 0x120
    flag_list_vftable: int = 0x130
    flag_list_body_end: int = 0x148


REWARD_SELECTOR: Final = RewardSelectorOffsets()


# ----------------------------------------------------------------------------
# Sentinels (referenced by ctors that emit unresolved-name slots).
# ----------------------------------------------------------------------------

#: Address of the global empty-string sentinel — every "named slot" in a
#: just-constructed `oCDtRewardEntitySelectorToSpawnEntityCpntSettings`
#: points here until the asset loader resolves the names.
EMPTY_STRING_SENTINEL: Final = 0x140EB46D0

#: u32 sentinel hash meaning "name not yet resolved".
UNRESOLVED_NAME_HASH: Final = 0x80000000

#: Default `oCDtDefinition` flags word (set in `FUN_1401e3ca0`).
REWARD_DEF_DEFAULT_FLAGS: Final = 0x0101


# ----------------------------------------------------------------------------
# Schema-version table — bump per kind whenever the offsets above change.
# Consumed by `rsmm.sdk.kinds.item.migrations`.
# ----------------------------------------------------------------------------

#: Current schema version for the `item` kind manifest.
ITEM_MANIFEST_SCHEMA_VERSION: Final = 2
