# Mod hookpoints — how the game creates / spawns / loads things

> Status: **draft, derived from headless RE artifacts** under
> `docs/_re/out/`. Use [GHIDRA_MCP.md](GHIDRA_MCP.md) to verify and
> deepen anything below interactively.

This document explains *why* asset edits weren't taking effect: the
game does not read loose definition files — it reads UID-keyed binary
records into singleton libraries at startup, and every "create item",
"spawn enemy", "instantiate boss" call goes through that registry.

## The two systems you need

### 1. The **class registry** (UID → factory)

Every serializable type registers itself on startup with a 32-bit UID,
a class-name string, a struct size, an alignment, a ctor thunk, and a
deserialization factory. The pattern (from
`FUN_140277790` registering `oCDtEntityCpntMagicalObjectsDropSettings`):

```c
local_38 = 0x168afca6;                           // class UID
lVar1   = FUN_1404f3bb0(0, &local_38);            // existing? lookup
plVar2  = FUN_1401a6c20();                        // allocate registry slot
(**(code **)(*plVar2 + 0xd8))(plVar2, 0xa50, 8);  // sizeof = 0xa50, align = 8
local_48 = "oCDtEntityCpntMagicalObjectsDropSettings";
(**(code **)(*plVar2 + 0x10))(plVar2, &local_48); // store name
*(undefined4 *)(plVar2 + 5) = 0x168afca6;         // store UID
FUN_1404f3c70(uVar4, plVar2, FUN_1402d2290);      // register factory
plVar2[0x10] = (longlong)&LAB_1401b6e70;          // ctor thunk
```

| Symbol | Meaning |
|---|---|
| `FUN_1404f3bb0(0, &uid)` | registry lookup — returns slot or 0 |
| `FUN_1401a6c20()` | allocate new registry slot |
| `FUN_1404f3c70(_, slot, factory)` | insert factory into hash table |
| `slot[5]` | UID (4 bytes) |
| `slot+0xd8 thunk` | set sizeof+align |
| `slot[0x10]` | ctor thunk pointer |
| `slot+0x10 thunk` | set class-name string |

**Where this matters for mods:** when the engine deserializes a cooked
record it reads the leading UID, looks the slot up, allocates
`sizeof` bytes, invokes the ctor thunk, then calls the factory to
populate fields from the byte stream. Without a registered UID the
record is silently skipped. Custom classes therefore need a
registrar call before any asset that mentions their UID is loaded.

The full table (706 classes, 337 with factories, 646 with sizes) is
saved as [out/class_registry.json](out/class_registry.json). The
short list below is the mod-relevant subset.

### 2. The **`oCTLibrary<T>` singletons** (runtime collections)

After a class is registered, the *instances* live in a per-type
template library. Each library is a singleton at a fixed global
address, has its own critical section, and exposes lookup + iteration
through its vftable. The library vftable is installed at static-init
(example for rewards, `FUN_14004adc0`):

```c
FUN_14048b230(&DAT_141412e00);
_DAT_141412e00 = oCTLibrary<class_oCDtRewardDefinition>::vftable;
_DAT_141412f70 = 1;
InitializeCriticalSectionAndSpinCount(&DAT_141412f80, 4000);
atexit(&LAB_140e73cd0);          // dtor on shutdown
```

Library singleton addresses are saved in
[out/libraries.json](out/libraries.json). The mod-relevant ones:

| Type | Singleton | Type UID | Record size |
|---|---|---|---|
| `oCDtRewardDefinition` | `0x141412e00` | `0x176f164e` | `0x298` |
| `oCDtEnemyDefinition` | `0x1414118c0` | `0x176debb7` | `0x350` |
| `oCDtEnemyTribeDefinition` | `0x141411200` | — | — |
| `oCDtEnemyCampTierDefinition` | `0x141411560` | `0x176e18f8` | `0x2a0` |
| `oCDtEnemyCampDifficultyDefinition` | `0x141411710` | — | — |
| `oCDtHeroDefinition` | *(via FUN_14032deb0 dtor)* | — | ≥ `0x2c4` |
| `oCDtMapDefinition` | `0x141412520` | — | — |
| `oCDtTileDefinition` | `0x141412080` | `0x1781ca4d` | `0x358` |
| `oCDtDreamShardDefinition` | `0x141411050` | — | — |
| `oCDtIngredientDefinition` | `0x141412c50` | — | — |
| `MelodyDefinition` | `0x1414129c0` | — | — |
| `oCEntitySettingsResource` | `0x141441b60` | — | — |
| `oCGlobalEntityValueSettings` | `0x141441980` | — | — |

`oCDtHeroDefinition`, `oCDtMapDefinition`, etc. with no UID column are
**not standalone records** — they live as nested definitions inside a
larger container, so they don't register their own UID.

## What "spawn" actually means

`oCEntitySpawner` (UID `0x17bcd54b`, size `0x60`) is the root spawn
primitive. Specialized spawners are *component-shaped* — they own an
`oCEntitySpawner` instance as an inner field. Confirmed for
`oCDtEntityCpntHeroSpawner` (`FUN_1402cce30`):

```c
*param_1     = oIEntityCpnt::vftable;
param_1[3]   = oe::EntityCpntValueSignal<bool>::vftable;
param_1[7]   = oe::EntityCpntValueSignal<bool>::vftable;
*param_1     = oCDtEntityCpntHeroSpawner::vftable;
param_1[0xd] = oCSpawner::vftable;        // → upgrades to oCEntitySpawner below
param_1[0xd] = oCEntitySpawner::vftable;
```

Layout per spawner-shaped component:

| Offset | Purpose |
|---|---|
| `+0x00` | derived `oIEntityCpnt` vftable |
| `+0x18` (param_1[3]) | "is active" bool signal |
| `+0x38` (param_1[7]) | "spawned at least once" bool signal |
| `+0x68` (param_1[0xd]) | embedded `oCEntitySpawner` instance |

So "spawning" is **not** `new Boss()` — it's:

1. Lookup target type in its library (`oCTLibrary<X>::Find(name)` —
   indirect via vftable slot).
2. Allocate an entity (size from registry slot).
3. Call ctor thunk → fills vftable chain.
4. Run deserialization factory against the library's stored byte
   record → populates fields.
5. Attach the resulting component to a parent entity in the scene
   graph.
6. Fire the `EntityCpntValueSignal<bool>` signals to wake listeners.

## Reward / item drop pipeline

`oCDtRewardDefinition` (`0x176f164e`, size `0x298`, factory
`FUN_14031a040`, library `0x141412e00`) is the data class for every
droppable reward type. The runtime walker is
`_InitAllRewards` = `FUN_1401e6030` (7351 bytes) — string
`"_InitAllRewards"` is stored at `0x140ef1a30` and used as a log tag.
Key strings it formats:

```
"Seed : {}"
"{} ({} reward spawners)"
"Reward type {}"
"Reward definition"
"Reward type item"
```

The function iterates over a list at `param_1 + 0x1d8`, pulls each
reward entry, queries its embedded spawner via a vftable dispatch
`(**(*plVar25 + 0x38))(plVar25, &local_288)`, and ends up building a
per-reward spawner table. The reward-selector component itself is
`oCDtRewardEntitySelectorToSpawnEntityCpntSettings` (factory
`FUN_1401e3e90`) — a thin wrapper around
`oIEntitySelectorToSpawnEntityCpntSettings` plus an
`oCCustomFlagList` for tags.

So "add a new item that can drop" requires:

1. A new `oCDtRewardDefinition` instance in
   `oCTLibrary<oCDtRewardDefinition>` (singleton `0x141412e00`).
2. A `oCDtRewardEntitySelectorToSpawnEntityCpntSettings` referencing
   it on whichever entity should drop it (boss kill, chest, etc.).
3. The selector's `oCCustomFlagList` tags must match the
   loot-table filter the dropper queries.

## Magical objects (in-run items)

Distinct from rewards — these are the *visible* magical pickup
entities. The component chain:

| Class | UID | Factory | Notes |
|---|---|---|---|
| `oCDtEntityCpntMagicalObject` | — | — | runtime entity component (ctor `FUN_1401e0e10`, 721 B) |
| `oCDtEntityCpntMagicalObjectsDropSettings` | `0x168afca6` | `FUN_1402d2290` | drop-table config, size `0xa50` |
| `oCDtEntityCpntMagicalObjectsDrop` | — | — | drop runtime — ctor at `FUN_140253e40` etc. |

The runtime component declares three `EntityCpntValueSignal<int>` at
offsets `+0x1f8`, `+0x218`, `+0x238` (param_1[0x3f/0x43/0x47]) —
likely rarity / count / level. The settings struct's `0xa50` size
suggests a sizeable drop table (dozens of weighted entries).

## Heroes

`oCDtHeroDefinition` has no registered UID — it is contained in a
parent record, and only its library singleton is observable. The
ctor `FUN_1403143b0` (1339 B) builds the inheritance chain:

```
oISerializable  →  oIResource  →  oCDtDefinition  →  oCDtHeroDefinition
```

It also writes two copies of `&DAT_140eb46d0` (a global empty-string
sentinel) at multiple member offsets — these are the named slots
(power IDs, talent IDs, melody IDs, animation IDs) waiting to be
populated by the asset loader. Each named slot is shaped:

```
ptr<char[]> name = &DAT_140eb46d0   // empty-string default
u32 hash = 0x80000000               // sentinel "unresolved"
u32 _pad = 0
```

The dtor `FUN_140314930` (1020 B) clears parallel pointer arrays at
`+0x114`, `+0x116`, `+0x118` (lengths at `+0x115`, `+0x117`, `+0x119`)
— these are the variable-length collections that get populated from
the asset bytes (likely lists of attached entities / powers /
talents).

To add a hero you either:

- Construct a new `oCDtHeroDefinition` post-ctor and inject into
  `oCTLibrary<oCDtHeroDefinition>` (host-side, before any code path
  iterates the library); or
- Subclass and register your own UID, then ship the asset record so
  the loader pulls it in via the normal path.

## Enemies & bosses

`oCDtEnemyDefinition` is fully registered: UID `0x176debb7`, size
`0x350`, factory `FUN_14030a190`, library `0x1414118c0`. Camp
machinery:

| Class | UID | Library | Purpose |
|---|---|---|---|
| `oCDtEnemyDefinition` | `0x176debb7` | `0x1414118c0` | one enemy stat block |
| `oCDtEnemyTribeDefinition` | — | `0x141411200` | tribe = group/faction |
| `oCDtEnemyCampTierDefinition` | `0x176e18f8` | `0x141411560` | difficulty tier of one camp |
| `oCDtEnemyCampDifficultyDefinition` | — | `0x141411710` | global difficulty curve |
| `oCDtEnemyCampEntitySelectorToSpawnEntityCpntSettings` | `0x16b7d175` | — | per-camp spawn selector |
| `oCDtEnemyCampEntitySelectorToSpawnTribeEntrySettings` | `0x16b81d80` | — | one tribe entry inside a camp |
| `oCDtEnemyFlagListEntitySelectorToSpawnEntityCpntSettings` | `0x17019bf9` | — | tag-filtered enemy selector |

Bosses are not a separate class — they are enemies tagged via the
flag-list selector, gated by `oCDtBossTimerUiControllerEntityCpnt`
(string `"BossTimer update"` at `0x140f08a88`, ctor at `FUN_140368970`).

## Reproduction recipe

To regenerate or update the tables above after a game patch:

```bash
cd docs/_re/out
python3 - <<'PY'
import os, re, subprocess, json
r = subprocess.run(['grep','-rl','--include=*.c','-F','FUN_1404f3bb0','decompiled_all/'],
                   capture_output=True, text=True, timeout=120)
files = r.stdout.strip().splitlines()
recs = []
for f in files:
    body = open(f, errors='ignore').read()
    names = re.findall(r'"((?:oC|oS|oI|oe)[A-Z][A-Za-z0-9_<>:]+)"', body)
    uids  = re.findall(r'local_\w+\s*=\s*(0x[0-9a-f]{6,8})\b', body)
    fact  = re.search(r'FUN_1404f3c70\s*\([^,]+,[^,]+,(FUN_[0-9a-f]+)\s*\)', body)
    size  = re.search(r'\*plVar2\s*\+\s*0xd8\)\)\(plVar2,(0x[0-9a-f]+),', body)
    if names:
        recs.append({'fn': os.path.basename(f).split('__')[0],
                     'class': names[0],
                     'uid': uids[0] if uids else None,
                     'size': size.group(1) if size else None,
                     'factory': fact.group(1) if fact else None})
recs.sort(key=lambda r: r['class'])
json.dump(recs, open('class_registry.json','w'), indent=1)
print(len(recs), '→ class_registry.json')
PY
```

Library singletons can be re-extracted with:

```bash
grep -rh --include='*.c' -oE '_?DAT_[0-9a-f]+ = oCTLibrary<[^>]+>::vftable' decompiled_all/ \
  | sort -u
```

## MCP-confirmed engine internals (live RE)

The headless data above has been refined against a live Ghidra MCP
session against the same binary. Renamed functions in the Ghidra DB:

| Address | Renamed | Role |
|---|---|---|
| `0x1404f3bb0` | `oCMetaClass_FindByKey` | scan registry list for matching 32-byte key |
| `0x1401a6c20` | `oCMetaClass_Alloc` | malloc 0x90-byte oCMetaClass instance, install vftable |
| `0x140277790` | `Register_oCDtEntityCpntMagicalObjectsDropSettings` | sample registrar (kept as anchor) |
| `0x1404a3ad0` | `Register_oIBinarySerializationAccess` | binary deserializer interface registrar |
| `0x140488f50` | `LoadUsedRscList_or_Archive` | parses `UsedRscList.ot` manifest + Archive.ini |
| `0x140289b30` | `LevelGs_StateLoadingResource_Load` | master level-load orchestrator (14 stages) |
| `0x1401e6030` | `InitAllRewards` | builds per-reward spawner table from `MapSceneContext + 0x1d8` |

### Registry key is 32 bytes, not 4

The "UID" you see in registrars (e.g. `0x168afca6`) is the **first
4 bytes of a 32-byte key**. `oCMetaClass_FindByKey` compares all 32
bytes against an `oCMetaClass` vftable callout (`(**(*plVar2 + 0x20))`)
that emits the key on demand. The trailing bytes are zeros for nearly
every class today, but assume the full 32-byte slot when injecting.

### Three parallel registry arrays at `0x14140ded0..ee0`

| Global | Contents |
|---|---|
| `DAT_14140ded0` | `oCMetaClass*` list (one per registered type) |
| `DAT_14140ded8` | matching dtor/destroy thunks |
| `DAT_14140dee0` | matching schema-declarer callbacks (the third arg to `FUN_1404f3c70`) |

Each array stores `{ptr=elems, count, _, capacity}`. The schema
callback (e.g. `FUN_1402d2290` for `MagicalObjectsDropSettings`) is
**not** a deserializer — it sets the human-readable name + declares
the field schema. Actual binary deserialization happens through
`oIBinarySerializationAccess`-derived classes; the field schema is
consulted at read time.

### Schema-declarer pattern (confirmed)

```c
// FUN_1402d2290 — body of MagicalObjectsDropSettings schema callback
local_18 = "Magical Object Drops";          // user-facing display name
(**(*param_1 + 0x18))(param_1, &local_18);  // MetaClass::SetDisplayName
*(uint *)param_1[0x11] = 0xc0001;           // flags
FUN_1401c8b40();                            // register field group 1
FUN_1404f5700();                            // register field group 2
FUN_140215b10(param_1 + 6, ...);            // append to child list
```

### Level-load pipeline (`LevelGs_StateLoadingResource_Load`)

Confirmed stage table at `*(LevelCtx + 0x2b0)`:

| Stage | Label | Notes |
| --- | --- | --- |
| 0 | `LoadAndGetRandomHeroEntity` / `LoadAndGetPlayedHeroEntity` | loops `Map+0x720..0x728` random heroes + `Map+0x738..0x748` played heroes |
| 1 | `DayNightCycle InitCycle` | |
| 2 | `Barks manager loading` | |
| **3** | **`Enemies settings loading`** | walks `oCDtEnemyDefinition` list at `LevelCtx+0x198`, filters by tier (`uStack_5ac`), seed (`fStack_5a8`), and tag list (`oCCustomFlagFilter`, `EnemyDefInternal::SearchFilter`) |
| 4 | `MapDefinition loading` | |
| 5 | `TileDefinition loading` | iterates `Map+0x3c8..0x3d0` tile defs |
| 6 | `AddMasterLevel` | |
| 7 | `Update partitioning boundings` | |
| 8 | `Rebuild terrain` | |
| **9** | **`MapSceneContext OnLevelStart`** | calls `InitAllRewards(SceneContext)` and `FUN_1401e7e20(SceneContext)` |
| **10** | **`Generate rewards`** | fires `oCGameNamedEvent` keyed by `PTR_DAT_1412c0998` |
| 11 | `Rebuild navmesh` | |
| **12** | **`Generate enemy camps`** | fires `oCGameNamedEvent` keyed by `PTR_DAT_1412c09e0` |
| 13 | `Register game objects to sectorization` | |

### **The mod hook surface**

Stages 10 and 12 are **`oCGameNamedEvent` dispatches**, not direct
factory calls. That is the practical injection point:

- An entity listening for the "Generate rewards" event can spawn
  *additional* `oCDtRewardDefinition`-based entities into the level
  without patching `LevelGs_StateLoadingResource_Load`.
- Same for "Generate enemy camps" → custom camp spawns.
- For stage 3 (Enemies settings loading), the filter consults
  `EnemyDefInternal::SearchFilter` and `oCCustomFlagFilter`. Adding
  tags to a custom `oCDtEnemyDefinition` (UID `0x176debb7`,
  size `0x350`, library `0x1414118c0`) is sufficient to include it.

This finally explains why prior asset edits failed in isolation: the
*record* needs to exist in `oCTLibrary<oCDtEnemyDefinition>` AND the
camp's `EnemyCampEntitySelector` filter has to match its tags. Editing
one without the other no-ops silently.

### Hero library — still partially unknown

`oCTLibrary<oCDtHeroDefinition>` is referenced only by its dtor
(`FUN_14032deb0`). The init must happen via a runtime service
locator rather than a static global. `oCDtHeroDefinition` itself
**has no registered UID** — confirmed: its name string at
`0x140eddd78` only appears inside `Register_SkillProfileDataSettings`
(`FUN_140192330`, UID `0x186adbdf`) as a referenced field type. So
heroes are not standalone serializable records; they live as
typed-field children of larger settings classes.

## `oCTLibrary<T>` vftable ABI (= `oIResourceManager`)

Resolved against `oCTLibrary<oCDtRewardDefinition>` vftable @ `0x140f028b8`
and cross-checked against `oCTLibrary<oCDtEnemyDefinition>` vftable @
`0x140f022d0`. The library is a templated `oIResourceManager`: base
implements two shared slots, per-class slots override type info and
free-list pooling.

| Slot | Offset | Kind | Reward impl | Enemy impl | Renamed to |
|---|---|---|---|---|---|
| 0 | `+0x00` | per-class | `0x14032e120` | `0x14030c350` | `oCTLibrary_<T>__scalar_dtor` |
| 1 | `+0x08` | **base shared** | `0x14048baf0` | `0x14048baf0` | `oIResourceManager__detach_entry` |
| 2 | `+0x10` | per-class | `0x1401e3c80` | `0x1401db7e0` | `oCTLibrary_<T>__get_class_meta` |
| 3 | `+0x18` | **base shared** | `0x14048be40` | `0x14048be40` | `oIResourceManager__find_or_load_by_path` |
| 4 | `+0x20` | per-class | `0x14030be90` | — | `oCTLibrary_<T>__get_class_name_ref` |
| 5 | `+0x28` | per-class | `0x14032eb10` | — | `oCTLibrary_<T>__acquire_entry` |
| 6 | `+0x30` | per-class | `0x14030c770` | — | `oCTLibrary_<T>__release_entry` |
| 7 | `+0x38` | RTTI | — | — | end of primary vftable |

Base init / cleanup: `FUN_14048b230` / `FUN_14048b4a0` — renamed
`oIResourceManager__base_init` / `__base_cleanup`. Per-class
static-init thunks renamed: reward `0x14004adc0`
(`oCTLibrary_RewardDefinition__static_init`), enemy `0x140048e10`
(`oCTLibrary_EnemyDefinition__static_init`).

### Slot 3 = the by-name lookup (`Find(name)`)

`oIResourceManager::FindOrLoad(this, oCResourcePath*, flags, out_ref, extra)`
takes a path shaped `{ char* name, u32 hash, char* parent }`:

- If the path matches a 4-byte token at `DAT_140f1dab4` (likely an
  extension magic — TPI / TPDL), allocates a fresh entry via slot 5
  (`acquire_entry`), links it into the active list at `+0x140/+0x148`
  under the `+0x118` critical section, then ref-counts it into
  `*out_ref`.
- Otherwise calls `FUN_14048b600` (sibling lookup by parent path) and
  falls through to `FUN_14048d780` to materialize the resource.

Adding a `oCDtRewardDefinition` named `rwd_custom_sword` therefore
reduces to: construct an `oCResourcePath` with `name =
"rwd_custom_sword"` and the right parent, invoke
`(*reward_lib->vftable[3])(reward_lib, &path, flags, &out_ref, ...)`
— the base implementation allocates, links, and hands back a
ref-counted pointer.

### Library object layout (offsets used by base slots)

| Offset | Field |
|---|---|
| `+0x118` | active-list critical section |
| `+0x140` | active count |
| `+0x148` | active list tail |
| `+0x150` | active list head |
| `+0x158` | recent count |
| `+0x160` | recent list head |
| `+0x168` | recent list tail |
| `+0x170` | free-list head (slots 5/6) |
| `+0x180` | free-list critical section |

## Spawn primitive (confirmed)

See [`SPAWNING.md`](SPAWNING.md) — `Spawn(this, position, &oCEntitySpawnData)`
is `vftable[3]` (byte `+0x18`) on the scene context's inline
`oCEntitySpawnerGo` dispatcher. Used by `SpawnAllObjects`
(`FUN_140254280`) and `SpawnAllMelodies` (`FUN_140255a90`); generic
across kinds. Sub-component lookup post-spawn is `FUN_1406ca380(go, meta)`.

## Still to be confirmed

- `oCGameNamedEvent` listener API — once we know how to register a
  listener, the "Generate rewards" / "Generate enemy camps" injection
  pattern is fully unlocked.
- `oIBinarySerializationAccess` runtime read path — UID
  `0x1c5258`, size 8, MetaClass singleton `DAT_1414494f0`. The path
  from raw cooked bytes to per-field reads via the schema declared in
  the schema callback is still uncharted.
- Hero library singleton address (see above).
- Reward weighting inside the 7 KB `InitAllRewards` body — header is
  understood (per-reward spawner table iteration), the inner
  weighting model is not.
