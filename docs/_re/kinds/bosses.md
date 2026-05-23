# Custom bosses — BossTimer controller, named-event triggers, reward hookup

> Status: Tier-1 RE notes for `src/rsmm/sdk/kinds/bosses.py`. Derived
> from live Ghidra MCP + headless decompilation under `docs/_re/out/`.
> Anything marked `# TODO: confirm` is provisional; everything else is
> read from the binary.

This page is the per-kind companion to
[`../MOD_HOOKS.md`](../MOD_HOOKS.md) "Enemies & bosses" / "level-load
pipeline" notes. It focuses on **one** content kind: a custom boss
encounter — a tagged enemy with a `oCDtBossTimerUiControllerEntityCpnt`
component, wired into the existing named-event spawn fabric, and
guaranteed to drop a `oCDtRewardDefinition`.

## TL;DR — bosses are tagged enemies with a controller component

Confirmed from the binary:

1. `oCDtBossTimerUiControllerEntityCpnt` (ctor `0x140368970`, dtor
   `0x140368ab0`, vftable @ `0x14147ff74`) is the runtime component
   that drives the boss-fight UI / HP bar. It is **not** in
   `class_registry.json` — it's a component, not a UID-keyed
   serializable record (same pattern as `oCDtEntityCpntMagicalObject`).
2. `oCDtBossTimerUiControllerEntityCpntSettings` (ctor `0x140368860`)
   is the *authored* settings container — that's what asset bytes
   describe. Its four embedded `oCEntityCpntPicker` slots
   (`+0x0f8, +0x138, +0x250, +0x310`) are the picker fields a level
   designer would fill in.
3. The encounter is gated by `oCGameNamedEvent`s named
   `BOSS_FIGHTING_START` / `BOSS_ACTIVATED` / `BOSS_FIGHTING_STOP` /
   `BOSS_DEFEATED`. Each string is CRC32-keyed at static-init into a
   `_DAT_*` slot; `FUN_14027fde0` is the master listener-binder that
   wires those keys to per-listener thunks (e.g. `LAB_1402c8680` is
   the `BOSS_FIGHTING_START` handler closure inside the active
   `MapSceneContext`).
4. Bosses are otherwise vanilla `oCDtEnemyDefinition` records
   (UID `0x176debb7`, size `0x350`, library `0x1414118c0`) — the
   "is a boss" property is a **bit set in the enemy's
   `oCCustomFlagList`**, not a separate class. Per MOD_HOOKS, flag
   bits are unnamed (`"Flag 0".."Flag 63"` are the only string labels
   in the binary at `0x140f4b568..`).

## The chain

```
oCDtEnemyDefinition                       data class (UID 0x176debb7)
    +-- oCCustomFlagList                  tag list — one bit = "is_boss" (# TODO: confirm exact bit index)
    |
    +-- oCDtBossTimerUiControllerEntityCpntSettings   per-encounter cfg
            +-- picker @ +0xf8   target enemy / arena anchor
            +-- picker @ +0x138  intro / cinematic ref
            +-- picker @ +0x250  music cue / FMOD event
            +-- picker @ +0x310  post-kill reward (oCDtRewardDefinition)
            |
            v (resolved at level-load via FUN_140368fc0)
        oCDtBossTimerUiControllerEntityCpnt   runtime component (UI + HP bar + timer)
            +-- oCEntitySpawner    embedded at +0x68 (param_1[0xd])
            +-- bool signals       at +0x18 (is_active) / +0x38 (ever_activated)

  External wiring (named events):
    BOSS_FIGHTING_START key  -> _DAT_1412c0430
    BOSS_ACTIVATED      key  -> _DAT_1412bfcb8
    BOSS_DEFEATED       key  -> (CRC of "BOSS_DEFEATED" @ 0x140ef1788)
    BOSS_FIGHTING_STOP  key  -> (CRC of "BOSS_FIGHTING_STOP" @ 0x140ef1798)
```

## Confirmed addresses

| Symbol | Address | Notes |
|---|---|---|
| `oCDtBossTimerUiControllerEntityCpnt::vftable` | `0x14147ff74` | DATA xref to ctor |
| `oCDtBossTimerUiControllerEntityCpnt` ctor | `0x140368970` | 304 B — installs vftable chain (`oIEntityCpnt → oCDtBossTimerUiControllerEntityCpnt`), wires two `EntityCpntValueSignal<bool>` at `[3]/[7]`, embeds an `oCEntitySpawner` at `[0xd]` |
| `oCDtBossTimerUiControllerEntityCpnt` dtor | `0x140368ab0` | refcount-releases two heap signals at `[0x1b]` and `[0x1d]` |
| `oCDtBossTimerUiControllerEntityCpntSettings` ctor | `0x140368860` | 229 B — installs settings vftable + 4 pickers at `[0x1f], [0x27], [0x4a], [0x62]` |
| `oCDtBossTimerUiControllerEntityCpntSettings::deserialize` | `0x140368e90` | tests presence of fields at `+0xf8`, `+0x138`, `+0x178`, `+0x250`, `+0x290`, `+0x310` |
| `oCDtBossTimerUiControllerEntityCpntSettings::resolve` | `0x140368fc0` | post-deserialize fix-up — chases picker resolution at `+0x118 / +0x158 / +0x1b0 / +0x2c8 / +0x330` |
| String `"BossTimer update"` | `0x140f08a88` | log-tag for the per-tick handler (DATA xrefs from `0x140368c8c`, `0x140368c93` — inside the runtime tick fn) |
| String `"Boss timer UI controller"` | `0x140f08a50` | display name (set by schema-declarer for the cpnt) |
| String `"oCDtBossTimerUiControllerEntityCpntSettings"` | `0x140f0a7b8` | RTTI class name |
| Named event `"BOSS_FIGHTING_START"` | `0x140ef1758` | CRC32-keyed by `FUN_14002ebd0`, stored at `_DAT_1412c0430` |
| Named event `"BOSS_FIGHTING_STOP"` | `0x140ef1798` | key in `_DAT_*` (sibling registrar at `0x14002ed70`) |
| Named event `"BOSS_ACTIVATED"` | `0x140ef1860` | CRC32-keyed by `FUN_14002f590`, stored at `_DAT_1412bfcb8` |
| Named event `"BOSS_DEFEATED"` | `0x140ef1788` | sibling CRC registrar at `0x14002ed70` |
| Metric tag string `"active_boss"` | `0x140ef27b8` | written by `FUN_1401f4f10` into telemetry on encounter end |
| Master listener-binder | `0x14027fde0` | wires `BOSS_FIGHTING_START`-key to `LAB_1402c8680` closure on the active `MapSceneContext` |

## `oCDtBossTimerUiControllerEntityCpnt` runtime layout

Derived from `FUN_140368970` (ctor) + `FUN_140368ab0` (dtor). Layout
mirrors `oCDtEntityCpntHeroSpawner` (same spawner-shaped pattern in
MOD_HOOKS).

| Offset | qword | Field |
|---|---|---|
| `+0x00` | `[0]` | `oCDtBossTimerUiControllerEntityCpnt::vftable` (`oIEntityCpnt` first, then specialized) |
| `+0x08..+0x10` | `[1..2]` | parent / scene-graph backrefs (`0` at ctor) |
| `+0x18` | `[3]` | `oe::EntityCpntValueSignal<bool>` — **is_active** (set when boss enters fight) |
| `+0x20..+0x30` | `[4..6]` | signal body (listener list head/tail) |
| `+0x38` | `[7]` | `oe::EntityCpntValueSignal<bool>` — **ever_activated** (first-encounter flag) |
| `+0x40..+0x50` | `[8..10]` | signal body |
| `+0x58` | `[0xb]` | reserved (`0`) |
| `+0x60` | `[0xc]+0` | reserved u32 |
| `+0x64` | `[0xc]+4` | low-nibble-masked status byte (`& 0xf0` cleared by ctor) |
| `+0x68` | `[0xd]` | embedded `oCEntitySpawner` — **the spawner that actually creates the boss entity** (per MOD_HOOKS "What 'spawn' actually means") |
| `+0x70..+0x88` | `[0xe..0x11]` | spawner body — `[0x11] = 0xffffffffffffffff` is the unresolved-prefab sentinel |
| `+0x90..+0xb8` | `[0x12..0x17]` | spawner state (parent entity backref, prefab cache) |
| `+0xc0..+0xe8` | `[0x18..0x1d]` | controller state — boss-fight HUD / HP bar context (`# TODO: confirm`) |
| `+0xd8` | `[0x1b]` | heap signal-listener pointer; released by dtor when non-null |
| `+0xe4` | `[0x1c]+4` | int — current phase (`# TODO: confirm`); zeroed before release in dtor |
| `+0xe8` | `[0x1d]` | heap signal-listener pointer; released by dtor when non-null |
| `+0xf4` | `[0x1e]+4` | int — phase count (`# TODO: confirm`); zeroed before release in dtor |
| `+0xf8..+0x120` | `[0x1f..0x24]` | tail / padding (`0` after ctor) |
| `+0x120` low byte | `[0x24]` | flags (`0`) |

> `# TODO: confirm` — labels for `[0x1c]+4`/`[0x1e]+4` as
> "phase index / phase count" are inferred from the dtor's
> matched pair of refcounted listeners (one signal per phase
> transition), not from a string in the binary.

## `oCDtBossTimerUiControllerEntityCpntSettings` layout

Derived from `FUN_140368860` (ctor) + `FUN_140368e90` (deserialize) +
`FUN_140368fc0` (resolve). The settings struct is the **authoring**
record — what an asset file describes. Each picker is an
`oCEntityCpntPicker` (the same primitive items uses for "pick one
named resource").

| Offset | qword | Field | Notes |
|---|---|---|---|
| `+0x00` | `[0]` | `oCDtBossTimerUiControllerEntityCpntSettings::vftable` | primary |
| `+0x08` | `[1]` | secondary vftable | multiple-inheritance ABI |
| `+0xf8` | `[0x1f]` | **picker 1** vftable (`oCEntityCpntPicker → oISerializable`) | "target entity" — anchor to attach the boss prefab to |
| `+0x100` | `[0x20]` | picker 1 name ptr | empty-string sentinel post-ctor |
| `+0x108` | `[0x21]` | picker 1 hash | `0x80000000` (unresolved) |
| `+0x118` | `[0x23]` | picker 1 resolved `oCMetaClass*` | fixed up by `FUN_140368fc0` |
| `+0x120..+0x138` | `[0x24..0x27]` | picker 1 tail (`0`) |
| `+0x138` | `[0x27]` | **picker 2** vftable | "intro cinematic" / "intro entity" (`# TODO: confirm`) |
| `+0x158` | `[0x2b]` | picker 2 resolved meta | |
| `+0x178` | `[0x2f]` | **scalar/array slot** (no picker vftable) | iterated by `FUN_140368e90` — likely an array of phase settings or per-phase HP cutoffs (`# TODO: confirm`) |
| `+0x1b0` | `[0x36]` | array-tail pointer | resolved to `+0x278` by `FUN_140368fc0` (i.e. `*(this + 0x1b0) + 0x98 → this + 0x278`) |
| `+0x250` | `[0x4a]` | **picker 3** vftable | "music cue" — likely `oCEntityCpntPicker` over the FMOD event library (`# TODO: confirm`) |
| `+0x278` | `[0x4f]` | array-tail (computed) | |
| `+0x290` | `[0x52]` | **scalar/array slot** | second iterated field — possibly the `oCCustomFlagList` of fight-tags (boss-room flags) |
| `+0x2c8` | `[0x59]` | picker target ptr | resolved-meta sentinel |
| `+0x310` | `[0x62]` | **picker 4** vftable | "reward" — references the guaranteed-drop `oCDtRewardDefinition` (`# TODO: confirm`) |
| `+0x330` | `[0x66]` | picker 4 resolved meta | |
| `+0x33c..` | tail | trailing pad (`0`) |

The deserialize path at `0x140368e90` calls
`(**param_2[0xa0])(param_2, this+offset, 0)` six times — one per
field at `+0xf8, +0x138, +0x178, +0x250, +0x290, +0x310`. The
sixth call (`+0x310`) is **gated** by a check against
`FUN_1404e46c0(param_2, _, 0x17e9a0ae)` returning non-zero, which is
the cooked-asset *version-tag* test; this means the reward picker
(`+0x310`) is a **newer schema addition** and may be absent on older
records. Mods MUST emit the version tag `0x17e9a0ae` for the reward
picker to deserialize.

## Spawn trigger — how the boss actually appears

There is **no direct factory call** in `LevelGs_StateLoadingResource_Load`
for bosses. Instead:

1. Stage 3 (`Enemies settings loading`, MOD_HOOKS) walks
   `oCTLibrary<oCDtEnemyDefinition>` and filters via
   `EnemyDefInternal::SearchFilter` + `oCCustomFlagFilter`. An enemy
   that survives the filter is added to the camp pool.
2. Stage 12 (`Generate enemy camps`) fires
   `oCGameNamedEvent` keyed by `PTR_DAT_1412c09e0` — that's where the
   camp-spawner components instantiate enemies. A boss enemy lands
   in the camp pool with the right tag, and the camp's
   `oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings`
   ("Enemy flaglist entity selector to spawn", string at
   `0x140f033c8`) picks it because its
   `oCCustomFlagList` matches.
3. When the player approaches the boss arena, the *attached*
   `oCDtBossTimerUiControllerEntityCpnt` (sitting on the same entity
   or on a sibling arena anchor) wakes — its `is_active` signal
   flips, the engine raises `BOSS_FIGHTING_START`
   (`_DAT_1412c0430`), and `FUN_14027fde0`'s closure
   `LAB_1402c8680` runs (it's an inline lambda capture of the
   `MapSceneContext`).
4. On death, the `BOSS_DEFEATED` event fires; the reward picker at
   `+0x310` is dispatched via the same
   `oCDtRewardEntitySelectorToSpawnEntityCpntSettings` chain
   documented in [`items.md`](items.md).

So **the "spawn the boss" hook is not a direct call** — it's the
combination of:

- a tagged `oCDtEnemyDefinition` clearing the stage-3 filter,
- a `oCDtBossTimerUiControllerEntityCpnt` component attached to that
  enemy (or its arena anchor) at level-load,
- existing camp / spawn machinery doing the actual entity creation
  during stage 12.

Modders therefore **do not** need to listen for or fire any new event
— if the enemy has the boss tag and the controller component, the
engine handles the rest.

## Reward integration

The fourth picker (`+0x310`) on the settings struct is the
**guaranteed reward** drop. Per the schema gate at `0x17e9a0ae` this
is a new-format field — older boss records may not have it, in which
case the reward is supplied by a separate
`oCDtRewardEntitySelectorToSpawnEntityCpntSettings` instance attached
to the same entity (older pre-version-tag path).

Both routes funnel through `InitAllRewards` (`FUN_1401e6030`, see
MOD_HOOKS "Reward / item drop pipeline") at stage-9
(`MapSceneContext OnLevelStart`). For mod purposes, the simpler
recipe is:

1. Create / clone an `oCDtRewardDefinition` (see
   [`items.md` insertion recipe](items.md#insertion-recipe)).
2. Set the boss settings' picker `+0x310` name slot to that reward's
   path.
3. Emit the version-tag header `0x17e9a0ae` so the picker
   deserializes.

## What "boss flag" means concretely

Per MOD_HOOKS "Generate enemy camps" + "stage 3 filter", the engine
walks every enemy in `oCTLibrary<oCDtEnemyDefinition>` and checks
each against `oCCustomFlagFilter`. The camp's selector
(`oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings`) carries
its own `oCCustomFlagList`. A boss is an enemy whose
`oCCustomFlagList` bitfield has the bit the boss-arena camp filter
demands.

The exact bit index isn't string-labelled in the binary (flags are
just "Flag 0".."Flag 63"). Practically:

- Pick a vanilla boss (e.g. `enemy_boss_giant`), read its asset's
  `oCCustomFlagList` bitfield → that's the boss bit.
- For a new boss, copy that bitfield onto your custom enemy.

`# TODO: confirm` — automate via a save-game / asset-dump diff at
SDK build time; cache the discovered bit in `data/schemas/boss_flag.json`.

## Insertion recipe (host-side mod, no TLS injection yet)

1. **Enemy definition** — clone a vanilla boss
   `oCDtEnemyDefinition`. Set:
   - resource path / name (slots `[0x40]/[0x48]` per `items.md`
     `oCDtRewardDefinition` layout — same `oCDtDefinition` ancestor),
   - HP / damage scalars,
   - `oCCustomFlagList` bits to **include the boss flag** the
     stage-3 camp filter looks for.
   - Insert via `oIResourceManager::FindOrLoad` slot 3 on
     `oCTLibrary<oCDtEnemyDefinition>` singleton `0x1414118c0`.
2. **BossTimer settings** — construct an
   `oCDtBossTimerUiControllerEntityCpntSettings` with:
   - picker `+0xf8` → arena anchor entity name,
   - picker `+0x138` → intro entity / cinematic,
   - picker `+0x250` → FMOD music cue,
   - picker `+0x310` → guaranteed reward definition,
   - version tag `0x17e9a0ae` written in the cooked stream so the
     reward picker deserializes.
3. **Component attach** — at level-load, a
   `oCDtBossTimerUiControllerEntityCpnt` must be attached to either
   the boss enemy itself or its arena anchor. The component reads
   its settings via the normal entity-component plumbing.
4. **Arena (map)** — the existing map's camp must include a
   spawn-tag that matches the new enemy's `oCCustomFlagList` (or
   route through a per-map `EnemyCampEntitySelectorToSpawn` patch).

## Insertion recipe — what the SDK builder emits

Until TLS injection lands and we can do step 1/3 at runtime, the
builder writes a **manifest** under
`<out>/_pending_bosses/<id>/` describing the four pieces above:

```
_pending_bosses/<id>/
  boss.json        # { name, hp, base, music_cue, intro_text, phases, ... }
  enemy.json       # cloned oCDtEnemyDefinition diff (HP, flags, name)
  bosstimer.json   # picker targets + scalar fields with their offsets
  reward.json      # oCDtRewardDefinition reference (id or clone diff)
  spawn.json       # arena (level id) + boss-flag bit + camp filter tag
```

The apply pipeline (next phase) translates these into either:
- cooked-asset writes the engine loads through
  `LoadUsedRscList_or_Archive`, *or*
- a runtime patch the loader DLL applies once stable.

Unknown fields fall back to **clone-from-base**: copy a vanilla
boss's bytes verbatim and patch only the offsets above. The
manifest carries a `synthesized: {offset: value}` map and a
`cloned_from: <base_id>` field so the apply layer can audit which
bytes are real schema vs which are inherited.

## See also

- [`../MOD_HOOKS.md`](../MOD_HOOKS.md) — `oCTLibrary` ABI, named-event
  level-load pipeline (stages 3/9/10/12), `EnemyDefInternal::SearchFilter`.
- [`items.md`](items.md) — the `oCDtRewardDefinition` insertion recipe
  the reward-drop step reuses.
- [`../GHIDRA_MCP.md`](../GHIDRA_MCP.md) — live RE harness.
- `docs/_re/out/class_registry.json` — confirms BossTimer is *not* a
  UID-keyed serializable type (component-only).
- `docs/_re/out/libraries.json` — `oCDtEnemyDefinition` library
  singleton at `0x1414118c0` (the boss enemy lands here).
