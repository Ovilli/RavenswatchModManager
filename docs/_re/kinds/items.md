# Custom items — magical objects, rewards, drop chain

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/items/** (`apps/docs/src/content/docs/reverse-engineering/items.md`).
> This file stays as the raw RE field notes.


> Status: Tier-1 RE notes for `src/rsmm/sdk/kinds/items.py`. Derived from
> live Ghidra MCP + headless decompilation under `docs/_re/out/`. Verify
> any field marked `# TODO: confirm` before relying on it for byte
> emission; everything else is read from the binary.

This page is the per-kind companion to
[`../MOD_HOOKS.md`](../MOD_HOOKS.md). It focuses on **one** content
kind: an in-run magical object (item) that can drop, be picked up, and
trigger a `oCDtRewardDefinition`-shaped reward.

## The chain

```
oCDtRewardDefinition                  data class
    |  referenced-by
    v
oCDtRewardEntitySelectorToSpawnEntityCpntSettings   per-drop selector
    |  owns
    v
oCCustomFlagList                      filter tags
    |
    v
oCDtEntityCpntMagicalObject           runtime component (pickup entity)
    |
    v
oCDtEntityCpntMagicalObjectsDropSettings   drop-table config (0xa50 bytes)
```

The "settings" type (`UID 0x168afca6`, size `0xa50`, schema-declarer
`FUN_1402d2290`, ctor `FUN_1402d2310`) is the *authored* container that
references each magical object's prefab. The runtime component
(`oCDtEntityCpntMagicalObject`, ctor `FUN_1401e0e10`, size `0x2b0`) is
the instance the engine spawns for one pickup.

## Class registry sources (so the schema is real)

The four addresses listed in the task brief are **schema-declarer
callbacks**, *not* deserialization factories — per
[`MOD_HOOKS.md#schema-declarer-pattern-confirmed`](../MOD_HOOKS.md#schema-declarer-pattern-confirmed),
each one calls `MetaClass::SetDisplayName(name)`, writes flags into
`meta->declarer_state[0]`, then registers the field groups. The
*constructor* / *destructor* / size info lives in a separate registrar
that walks `oCMetaClass_FindByKey` then `oCMetaClass_Alloc`.

Confirmed addresses:

| Class | UID | Size | Registrar | Schema callback | ctor | dtor | ctor thunk |
|---|---|---|---|---|---|---|---|
| `oCDtRewardDefinition` | `0x176f164e` | `0x298` | `FUN_140237f40` | `FUN_14031a040` | `FUN_1401e3ca0` | `FUN_1401e3d50` | `LAB_140246670` |
| `oCDtEntityCpntMagicalObjectsDropSettings` | `0x168afca6` | `0xa50` | `Register_oCDtEntityCpntMagicalObjectsDropSettings` (`0x140277790`) | `FUN_1402d2290` | `FUN_1402d2310` | `FUN_1402d0cc0` | `LAB_14027d6d0` |
| `oCDtEntityCpntMagicalObject` (runtime) | — | `≥ 0x2b0` | — (component, not registry-keyed) | — | `FUN_1401e0e10` | `FUN_1401e10f0` | — |
| `oCDtRewardEntitySelectorToSpawnEntityCpntSettings` | — | — | — | — | `FUN_1401e3e90` | — | — |
| `oCDtEntityCpntMagicalObjectSettings` (authoring) | — | `≥ 0xc00` | — | — | `FUN_1402ce2b0` | — | — |

The "Reward type item" string at `0x140f02bf0` is bound to
`FUN_140319a20`, a sibling schema callback wired to a different
MetaClass slot — likely the variant enum-tag for `RewardDefInternal`.

## `oCDtRewardDefinition` layout (size `0x298`)

Derived from `FUN_1401e3ca0` (ctor) and `FUN_1401e3d50` (dtor).

| Offset | qword | Field | Notes |
|---|---|---|---|
| `+0x00` | `[0x00]` | `vftable` | `oCDtRewardDefinition::vftable` |
| `+0x08..+0x20` | `[1..4]` | `oISerializable` slots | zeroed by ctor |
| `+0x28` | `[5]` | `oIResource::serial_id`? | `0` after ctor |
| `+0x30` | `[6]` low byte | `oIResource flags` | `& 0xe0`'d at ctor — high 3 bits preserved by caller |
| `+0x34` | `[6]+4` | refcount? | set to `1` by ctor |
| `+0x3c` | `[7]` | resource state | `0` |
| `+0x40` | `[8]` | `oCResourcePath::name` | string ptr — `0` post-ctor; this is where the id-name lives once loaded |
| `+0x48` | `[9]` | `oCResourcePath::hash` | u32, `0` post-ctor |
| `+0x50` | `[10]` | resource-list prev | freed by `FUN_140503ed0` in dtor |
| `+0x58` | `[11]` | resource-list next | zeroed alongside `+0x5c` count |
| `+0x5c` | `[0xb]+4` | resource-list count | `0` post-ctor |
| `+0x60..+0x260` | `[12..0x4c]` | `oCDtDefinition` body | sub-records; deferred to schema mining |
| `+0x268` | `[0x4d]` | `oCDtDefinition` u32 | `0` (likely "is-loaded" flag) |
| `+0x270` | `[0x4e]` | `oCDtDefinition` ptr | released by `FUN_1401334e0` in dtor — likely the display-name / description string |
| `+0x278` | `[0x4f]` | `oCDtDefinition` ptr | `0` |
| `+0x280` | `[0x50]` | `oCDtDefinition` u32 | `0` |
| `+0x284` | `[0x50]+4` | `oCDtDefinition` flags | `0x0101` (set by ctor) |
| `+0x288` | `[0x51]` | `oCDtRewardDefinition::entries` | ptr to qword array; freed slot-by-slot via `FUN_1401256a0` in dtor |
| `+0x290` | `[0x52]` low u32 | `entries.length` | dtor loops `0..length` |
| `+0x294` | `[0x52]+4` | `entries.capacity` | dtor releases the buffer when non-zero |

> `# TODO: confirm` — the named slot at `+0x40/+0x48` is what
> `oIResourceManager::FindOrLoad` keys on (see `MOD_HOOKS.md`
> "Slot 3 = the by-name lookup"). The asset's logical id (e.g.
> `"rwd_my_sword"`) belongs there.

## `oCDtEntityCpntMagicalObject` layout (size `≥ 0x2b0`)

Derived from `FUN_1401e0e10` (ctor) + `FUN_1401e10f0` (dtor).

| Offset | qword | Field |
|---|---|---|
| `+0x00` | `[0]` | `oCDtEntityCpntMagicalObject::vftable` |
| `+0x18` | `[3]` | `oe::EntityCpntValueSignal<bool>` — "is_active" |
| `+0x38` | `[7]` | `oe::EntityCpntValueSignal<bool>` — "ever_spawned" |
| `+0x58..+0x68` | `[0xb..0xd]` | small int / flag block (low nibble of `+0x64` masked) |
| `+0x68` | `[0xd]+0` | `int 4` (initial count?) |
| `+0x90..+0x98` | `[0x12..0x13]` | first closure slot (signal binder header) |
| `+0x98..+0xa8` | `[0x13..0x15]` | first closure body (ctx + del) |
| `+0xc0..+0xd0` | `[0x18..0x1a]` | second closure |
| `+0xe0..+0xf8` | `[0x1c..0x1f]` | third closure (5 slots) |
| `+0x1f8` | `[0x3f]` | `oe::EntityCpntValueSignal<int>` — **rarity** (`# TODO: confirm`) |
| `+0x218` | `[0x43]` | `oe::EntityCpntValueSignal<int>` — **count** (`# TODO: confirm`) |
| `+0x238` | `[0x47]` | `oe::EntityCpntValueSignal<int>` — **level** (`# TODO: confirm`) |
| `+0x290` | `[0x52]` | `oCCustomFlagList::vftable` — tag list |
| `+0x298..+0x2a8` | `[0x53..0x55]` | `oCCustomFlagList` body |
| `+0x2ac` | `[0x55]+4` | `0xffffffff` sentinel |

The "rarity / count / level" labels are *educated guesses* from the
ordering inside `oCDtEntityCpntMagicalObject` — there is no schema
string in the binary that proves the mapping. **Mark them as
provisional until a save-game diff confirms which signal carries which
int.** No SDK code writes them: the item kind clones a shipped item's
cooked bytes and patches only labelled values (see below), so they are
open RE only.

## `oCDtEntityCpntMagicalObjectsDropSettings` layout (size `0xa50`)

Derived from `FUN_1402d2310` (ctor) + `FUN_1402d0cc0` (dtor). High
level only — the body is a 0x80-byte stride array (`+0x1f0..+0x7f0`,
constructed by `_eh_vector_constructor_iterator_`).

| Offset | qword | Field |
|---|---|---|
| `+0x00` | `[0]` | `oCDtEntityCpntMagicalObjectsDropSettings::vftable` |
| `+0x1f8` (`+0x1f * 8`) | `[0x1f..0x7e]` | array of 12 × 0x80-byte entries (drop-table rows) |
| `+0x3f8` | `[0x7f]` | extra row 0 (header for picker-1) |
| `+0x478` | `[0x8f]` | row 1 |
| ... | ... | (pattern repeats up to `param_1[0x17f]`) |
| `+0x9d0` | `[0x13a]` | `oCEntityCpntPicker` 1 (`vftable@oISerializable`) |
| `+0xa10` | `[0x142]` | `oCEntityCpntPicker` 2 |
| `+0xa48` | `[0x149]` | tail / `0` |

The drop-table rows themselves are the per-entry slot; we don't
synthesize new drop-table rows yet, we only thread the new reward
through an existing one (clone-and-patch model).

## `oCDtRewardEntitySelectorToSpawnEntityCpntSettings` layout

Derived from `FUN_1401e3e90`.

| Offset | qword | Field |
|---|---|---|
| `+0x00` | `[0]` | vftable (`oIEntitySelectorToSpawnEntityCpntSettings` first, then specialized) |
| `+0x08` | `[1]` | secondary vftable (multiple-inheritance ABI) |
| `+0xf8` | `[0x1f]` | target name ptr → `DAT_140eb46d0` (empty-string sentinel) |
| `+0x100` | `[0x20]` | target name hash → `0x80000000` |
| `+0x104` | `[0x20]+4` | resolved? flag |
| `+0x108` | `[0x21]` | parent path name ptr → `DAT_140eb46d0` |
| `+0x110` | `[0x22]` | parent hash → `0x80000000` |
| `+0x114` | `[0x22]+4` | resolved? flag |
| `+0x118` | `[0x23]` | resolved `oCMetaClass*` = `DAT_141447bd0` (`oCDtRewardDefinition` meta) |
| `+0x120` | `[0x24]` low byte | enable flag (`1`) |
| `+0x128` | `[0x25]` | reserved (`0`) |
| `+0x130` | `[0x26]` | `oCCustomFlagList::vftable` |
| `+0x138..+0x148` | `[0x27..0x29]` | flag-list body |

So a selector pins to:
1. one named reward definition (slots `[0x1f]/[0x20]`),
2. its parent resource group (slots `[0x21]/[0x22]`), and
3. a tag filter (slots `[0x26..0x29]`).

## Insertion recipe

Following the
[`oIResourceManager` slot-3 lookup](../MOD_HOOKS.md#slot-3--the-by-name-lookup-findname)
ABI:

1. **Register UID** — the `oCMetaClass` for `oCDtRewardDefinition` is
   `DAT_141447bd0`. If our DLL ships after the registrar at
   `FUN_140237f40` has already run (it static-inits before
   `main()`), no work is needed. If we ship a *new* UID for a custom
   reward class, we must call the same `oCMetaClass_FindByKey →
   oCMetaClass_Alloc → set sizeof+align → SetDisplayName →
   FUN_1404f3c70(meta, factory)` sequence ourselves at boot.
2. **Construct** an `oCDtRewardDefinition` (or clone bytes of a vanilla
   reward def) and fill `+0x40 = "rwd_<mod>_<id>"`,
   `+0x48 = name_hash`, the `oCDtDefinition` fields at `+0x270`, etc.
3. **Insert** into `oCTLibrary<oCDtRewardDefinition>` (singleton
   `0x141412e00`) by calling the vftable's slot 3 (`+0x18`,
   `oIResourceManager::FindOrLoad`) with our `oCResourcePath`. The
   library allocates an entry, links it into the `+0x150` head /
   `+0x148` tail list under the `+0x118` critsec, and returns a
   ref-counted pointer.
4. **Selector** — for every drop site (boss kill, chest, etc.),
   `oCDtRewardEntitySelectorToSpawnEntityCpntSettings::target_name`
   (`+0xf8/+0x100`) must match the new reward's name. The tag list
   at `+0x130..+0x148` must contain at least one tag that matches the
   dropper's `oCCustomFlagFilter`.
5. **Magical object** — for the *visible* pickup entity, the
   per-instance `oCDtEntityCpntMagicalObject` at offset `+0x290` owns
   the `oCCustomFlagList` whose tags must overlap the
   `oCDtEntityCpntMagicalObjectsDropSettings` row's filter.

## What this means for the v3 SDK builder

None of the offsets above are emitted. The item kind
(`src/rsmm/sdk/kinds/items.py`) clones a shipped item's cooked entity
through `engine/magic_item_cook.py`, applies only label-resolved
`value_patches`, and registers it via the versiondef MO vector +
`UsedRscCache` (verified in game). A `base` that names no shipped item
is an emit error.

The earlier plan — a `_pending_items/<id>.json` manifest carrying these
offsets for a later apply step — was never consumed by anything and was
removed on 2026-10-10, along with `kinds/item/builder.py` and
`kinds/item/schema.py`. Its only effect had been to hide a mistyped
`base`: the mod applied cleanly and the item never existed.

## Item data, its countdown, and how value links bind (RE 2026-10-20)

Static RE on build `b9c3642884a8` (corpus `docs/_re/out_new`), done after
three playtests of the `effect` builder went wrong on guesses. Facts first,
then what is still open.

**`oCDtEntityCpntMagicalObjectDataSettings`** (the "Dt Magical Object Data"
part every item carries; vftable `0x140f22f18`, serializer `FUN_1402cf8a0`,
version key `0x1892b5f4`). Versioned fields, in our field names:

| ours | settings offset | read as |
|---|---|---|
| `bytes_3` | `+0x100` 16-byte GUID, `+0x110`, `+0x114` | id + two small ints. Unique per item (114/114), found in no other file (12024 scanned). Registered at init into global `DAT_1414369e8` via `+0xf8` when `+0x33` is set, next to the `oIGameProfileDataOwner` base: most likely the item's profile/compendium key. |
| `value_4` | `+0x138` value picker | the countdown's FULL time |
| `value_5` | `+0x1b8` value picker | the countdown's CURRENT progress |
| `bytes_6` | `+0x238` (v5+) | — |

**Runtime `oCDtEntityCpntMagicalObjectData`** (vftable `0x140f0fed0`).
Init (`FUN_1402cfcc0`) binds `value_4` → `+0x70/+0x78` and `value_5` →
`+0x80/+0x88` with the generic picker binder `FUN_14026f520`, and looks up
the item's runtime object into `+0x68`. Slot 28 subscribes `FUN_1402cff70`
to both: when the item's state (`+0x68`→`+0x68`) is 2 and `value_4 > 0`, it
sets the "in cooldown" bool `+0x98` = `value_5 / value_4 < 1.0`
(`FUN_1402cc640` is that ratio) and notifies `+0xb0`. Outputs by key (slot
11): `0x1d294a5d` → `+0x90` (in-cooldown, unique to this class; no cooked
data reads it), plus the generic `0x0fd2832a`/`0x0fd2833c`. **It only reads
`value_4`/`value_5`; it never writes a timer and applies no cooldown
reduction.**

**The icon countdown** is `MagicalObjectUiViewerEntityCpnt`
(`FUN_140446200` bind, `FUN_1404472a0` refresh): it reaches the data part
through the item runtime object `+0x280`, subscribes to its `+0xb0`, and
copies `value_4` → `+0x4b0`, `value_5` → `+0x4d0`, ratio → `+0x490`.

**How a value picker binds** (`FUN_14026f520` → `FUN_140273bb0`): the
picker's accessor key sits at picker `+0x58` (`-1` = plain number), the
target is resolved by GUID inside the entity (`FUN_140712090` → SwissTable
`FUN_1406dabe0`). The binder asks the target `vt[13](key)` (float outputs),
then `vt[10](key)`. A Value part answers `vt[10]` for `0x0fd2c964 + its
type byte`. A **Timer** answers `vt[13]` for `0x0fd2825a` (+0xa0),
`0x0fd28264` (+0xc0), `0x1683197e` (+0x100), `0x16831980` (+0x120),
`0x1896c3bb` (+0x140) and `vt[12]` for `0x0fd28263`; its `vt[10]` is the
`return 0` default. The binding starts from the picker's INLINE number and
is only updated by the target's change callbacks (registration
`FUN_14027c420` copies nothing).

**Timer update** (`FUN_140729550`, registered by `FUN_1407281f0` as
"oCEntityCpntTimer - Update"): remaining `+0x90 -= dt`, elapsed
`+0x98 += dt`; at `remaining <= 0` it adds the duration (+ random bias,
`FUN_140729c90`), counts a tick, and stops at the count limit. Plain frame
time: no cooldown reduction.

**Which timer key means what** (every cooked picker that reads a Timer,
4769 entities): `0x16831980` = time LEFT ("Transformed Time Left Value",
"Deathdoor Timer Label"); `0x1683197e` = cooldown progress (9 hero
SkillControllers, Increase_Shield's "Cooldown Value Selector", and the one
working item countdown, `Curse_Lose_Life_Gain_Damage`: `value_4` → its
period Value with `0x0fd2c964`, `value_5` → its timer with `0x1683197e`).
**Increase_Shield, Gain_Regeneration_On_Low_Life and Defense_Heal link
`value_5` to a timer with `0x0fd2c964`, a key no Timer answers: their
countdown link never binds.** Copying that link is why the `effect`
builder's countdown never showed.

**`CHARACTER_HAS_BEEN_HIT` reaches no one.** Its only sender is
`Character_Common`'s "CHARACTER_HAS_BEEN_HIT Event Sender": world flag off,
an empty `targets` collector, and `mode` 0 where every other part has 1. The
named-event sender (`FUN_140780390`) sends to its resolved targets unless the
world flag is set, so with none the event goes nowhere; `Passive_Heal`'s
on-hit listener is dead in the shipped game. A named listener
(`FUN_140781170`) subscribes on its own entity's dispatcher (`+0x4d8`) and the
world's (`+0x30`→`+0x1a8`→`+0x340`). The `effect` builder dropped its `hit`
trigger for this (it never fired in 18 hits); `damage_taken` covers it.

**Open (needs a live probe, not more static reading):**
- Why links from copied parts to COPIED Value parts read the picker's
  inline number in game (effect test: every bonus was the donor's 0.05),
  while Pebbles' copied modifier linked to the item's OWN Shield Value did
  read 0.3. The binder starts at the inline number and waits for a change
  callback, so init order or the GUID map (`FUN_1406dabe0` over a table at
  `+0x148/+0x160`) are the candidates; `R.debug.dump` on a live item would
  settle it.
- The "abilities faster" report from the 2026-10-20 effect test: key
  `0x1894f1a2` is the engine's own "Life on hit" (registry `FUN_1401d0030`,
  read on hit by `FUN_1403cd950`), so the test stat is not it; and the
  countdown link does not touch timers. Unexplained.
- The ~3 s durations in that test were a decoding artefact (one ON and one
  OFF in the same poll decode as unrelated triggers), not shortened timers.

## See also

- [`../MOD_HOOKS.md`](../MOD_HOOKS.md) for the registry / library
  vftable ABI shared by every kind.
- [`../GHIDRA_MCP.md`](../GHIDRA_MCP.md) for the live RE harness.
- `docs/_re/out/class_registry.json` — table of every registered class.
- `docs/_re/out/libraries.json` — table of every library singleton.
