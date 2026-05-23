# Spawning — runtime entity creation primitives

> Status: confirmed via live Ghidra MCP session against
> `Ravenswatch.exe`. Companion to
> [`MOD_HOOKS.md`](MOD_HOOKS.md) (level-load pipeline + library ABI)
> and [`HOOKPOINTS.md`](HOOKPOINTS.md) (feature → function map).

This page documents **how the engine actually creates one entity at a
position** so the SDK can drop the clone-and-patch-asset-only workflow
in favor of a real "spawn this thing here" call.

## TL;DR

The spawn primitive is a `vftable[3]` call on the scene context's
inline **`oCEntitySpawnerGo`** dispatcher. The signature is:

```c
oCEntity* Spawn(oCEntitySpawnerGo* this,
                void*              position_handle,   // from FUN_140678250
                oCEntitySpawnData* spawn_data);       // transform + flags blob
```

Both `SpawnAllObjects` (magical objects) and `SpawnAllMelodies` call
the **same** virtual through a dispatcher stored inline in the
relevant library/scene-context (object case at `+0x30`, melody case at
`+0x28`). The result is a freshly-constructed entity that can then be
walked via `FUN_1406ca380(entity, oCMetaClass*)` to attach the
type-specific definition pointer.

## The spawn dispatcher

### Function pointer used in the wild

Object loader (`FUN_140254280`, "InitialLoading - MagicalObject SpawnAllObjects"):

```c
(**(code **)(param_1[6]    + 0x18))(param_1 + 6,    uVar7, &spawn_data);
// param_1[6]    == *(qword*)(lib + 0x30)    // dispatcher vftable ptr
// param_1 + 6   == lib + 0x30                // dispatcher 'this'
```

Melody loader (`FUN_140255a90`, "InitialLoading - Melody SpawnAllMelodies"):

```c
(**(code **)(*(longlong *)(param_1 + 0x28) + 0x18))
   ((longlong *)(param_1 + 0x28), uVar7, &spawn_data);
```

In both cases the inline dispatcher is initialized by `FUN_1406e7210`
called near the start of the loader on `scene_context + 0x1a8` — the
scene context owns the dispatcher and the loaders simply bind it to
their library before iterating.

### Layout of the dispatcher object

| Offset | Field | Notes |
|---|---|---|
| `+0x00` | `void** vftable` | first qword; `[3]` (byte `+0x18`) is `Spawn` |
| `+0x190` | `oIEntityCpnt** components` | array head, walked by `FUN_1406ca380` |
| `+0x198` | `u32 component_count` | matching count for the head above |

The MetaClass class-name string is `"oCEntitySpawnerGo"` (string at
`0x140ee43f0`). Its sibling state class is `"oCEntitySpawnerGoState"`
(`0x140ee4598`).

## `oCEntitySpawnData` — transform + flags blob

Constructed inline by every caller before `Spawn`. Size 0x60 bytes
(matches the `oCEntitySpawner` `sizeof` from
[`MOD_HOOKS.md`](MOD_HOOKS.md#registry-key-is-32-bytes-not-4)).

| Offset | Field | Value written by loaders |
|---|---|---|
| `+0x00` | `vftable` | `oCEntitySpawnData::vftable` |
| `+0x08..+0x18` | pad / 0 | `0` |
| `+0x18` | `flags` (`u32`) | `_DAT_140fa4470` (default spawn flags) |
| `+0x1c..+0x28` | reserved | `_UNK_140fa4474`, `_UNK_140fa4478` |
| `+0x30..+0x38` | `scale_xy` (`f32 x2`) | `0x3f8000003f800000` = `(1.0f, 1.0f)` |
| `+0x38..+0x3c` | `scale_z` (`f32`) | `0x3f800000` = `1.0f` |
| `+0x40..+0x60` | unused / 0 | `0` |

Anything left zero means "use defaults" — the loaders don't override
position from inside the struct (position comes in via the second
argument, the position handle).

## Position handle — `FUN_140678250`

Signature:

```c
TransformNode* FUN_140678250(void* pool_root /* def + 0x18 or def + 0xb0 */);
```

This is a **pool allocator**: it pops a free `TransformNode` off the
intrusive linked list at `pool_root`, links it into the active list,
and returns the pointer that callers pass straight into `Spawn`.

* The pool root for magical-object spawns is `def + 0x18` (object
  case) or `def + 0xb0` (melody case) — the per-definition spawn
  anchor.
* The returned `TransformNode` holds a placeholder world transform
  (`-1` sentinel in slot `[3]`) that the spawned entity's components
  fill in during construction.

For a custom mod that wants to spawn at an arbitrary world position,
write the world transform into the returned node **before** calling
`Spawn`, or skip `FUN_140678250` entirely and synthesize a transform
node by hand (size + layout still TBD — `# TODO: confirm`).

## Generic by-name lookup — `FUN_140463210`

```c
void* FUN_140463210(void* table, const char** name_token);
//
//   table + 0x80   -> ptr to entry array
//   table + 0x88   -> entry count (u32)
//   entry + 0x50   -> char* name (cstr)
//   name_token[0]  -> char* search name
//   name_token[1]  -> u32 length / hash (only low 31 bits used)
```

Linear scan. Used inside the level-load orchestrator to resolve
`MENU_SPAWNER`, `BOOK_SPAWNER`, etc. by name; the returned entry's
`+0x160` field is the actual spawner instance whose `Spawn` you call.

## Find sub-component by type — `FUN_1406ca380`

```c
oIEntityCpnt* FUN_1406ca380(oCEntitySpawnerGo* go, oCMetaClass* meta);
//
//   walks go[+0x190..+0x198] (u32 count) array of oIEntityCpnt*
//   each entry's vftable[0] returns its meta; vftable[0x58] is
//   MetaClass::IsKindOf(meta).
//   returns first match, or NULL.
```

Called right after `Spawn` to fish out the typed component the loader
wants to wire the def pointer into. Generic — works for **any** kind.

## High-level recipe — spawn one entity from a def

```c
// 1) Resolve the def by name through the library's vftable[3]
//    (oIResourceManager::FindOrLoad — see MOD_HOOKS.md).
oCDtMagicalObject* def = lib_FindOrLoad(magical_obj_lib, "rwd_my_sword");

// 2) Init spawn_data + grab a position handle.
oCEntitySpawnData sd = {};
sd.vftable  = oCEntitySpawnData::vftable;
sd.flags    = _DAT_140fa4470;
sd.scale_x  = sd.scale_y = sd.scale_z = 1.0f;
TransformNode* pos = FUN_140678250(((char*)def) + 0xb0);

// 3) Call Spawn through the scene-context dispatcher
//    (lives inline at scene_ctx+0x1a8's "+0x30" field on the lib).
oCEntitySpawnerGo* go = lib_dispatcher(magical_obj_lib);
oCEntity*          ent = (*((Spawn_t**)go)[3])(go, pos, &sd);

// 4) Bind the def to the typed component on the spawned entity.
oIEntityCpnt* cpnt = FUN_1406ca380(ent, DAT_141447f48 /* obj meta */);
cpnt->m_def = def;
```

Repeat for any other kind by swapping the library, the meta-class
pointer, and the position-pool offset.

## Cross-references — known meta-class pointers

| Kind | MetaClass global | Used in |
|---|---|---|
| `oCDtEntityCpntMagicalObject` | `DAT_141447f48` | `FUN_140254280` (objects) |
| `MelodyDefinition` typed cpnt | `DAT_141448040` | `FUN_140255a90` (melodies) |
| `oIGameUiOwner` (UI spawners) | `DAT_141446f38` | `FUN_14025b9e0` (UI spawn loop) |
| `oCDtRewardDefinition` | `DAT_141447bd0` | reward selector resolve |
| `oCEntitySpawner` registry | `DAT_141446ed8` (UID `0x17bcd54b`, size `0x60`) | spawn primitive class |
| `oCSpawner` registry | `DAT_141447238` (UID `0xc3baa69`, size `0x58`) | base class |

## Named-event surface (alternative path)

The string `"Spawn"` at `0x140ef851c` is a **state name**, not an
event — it's pushed into a `hero.state` metric inside `FUN_140391400`
(state-machine logger). It is **not** a `oCGameNamedEvent` you can
fire to make something spawn.

The real named-event spawn surface is documented in
[`MOD_HOOKS.md` "The mod hook surface"](MOD_HOOKS.md#the-mod-hook-surface):

| Event | CRC global | What fires it |
|---|---|---|
| `"Generate rewards"` | `PTR_DAT_1412c0998` | `LevelGs_StateLoadingResource_Load` stage 10 |
| `"Generate enemy camps"` | `PTR_DAT_1412c09e0` | stage 12 |

Listening to these events lets a mod *react* during scene
construction and call the spawn primitive above without patching the
level-load orchestrator.

## What this unlocks for the SDK

Phases 1 & 2 (the existing `_pending_*` manifests):
* still required — the def has to *exist* in its library before
  anyone can spawn it.

Phase 3 (new, now feasible):
* **Runtime spawn API** — once the loader DLL stabilizes, expose
  `rsmm.spawn(def_path, x, y, z)` that resolves the def, allocates a
  `TransformNode`, fills it with the caller's world position, and
  invokes `Spawn` through the scene-context dispatcher.
* **Listener-based content** — a mod can subscribe to
  `"Generate rewards"` / `"Generate enemy camps"` via the
  named-event listener API (once that's mined, see
  [`MOD_HOOKS.md` "Still to be confirmed"](MOD_HOOKS.md#still-to-be-confirmed))
  and call `rsmm.spawn(...)` from the listener.

## Still to be confirmed

* `TransformNode` byte layout (size, field offsets for position/rotation/scale).
* `oCEntitySpawnData::vftable` actual address (anchor `0x140fa4470` is
  a *flags* word, not the vftable itself — the vftable address shows
  up in the disassembly literal, needs a Ghidra label).
* The dispatcher's per-library offset table (object lib uses `+0x30`,
  melody lib uses `+0x28`, enemy + reward libs unmined).
* `oCGameNamedEvent` listener registration API (open across
  [`MOD_HOOKS.md` "Still to be confirmed"](MOD_HOOKS.md#still-to-be-confirmed)
  and [`HOOKPOINTS.md` recommended first POC](HOOKPOINTS.md#recommended-first-poc-for-rsmmhook-validation-task-6)).
