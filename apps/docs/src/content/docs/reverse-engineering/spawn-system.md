---
title: Spawn system
description: The spawner-component pipeline behind enemy/pet/prop creation, and the engine call R.spawn is built on.
---

:::note
Status 2026-09-13: **the instantiator is found** and `R.spawn` is built on it
(`src/loader/lua/rsmm/spawn.lua`); in-game proof is still owed. Every engine
spawner ends in
`EntityStore_CreateEntity(sceneSpawner, settings, &spawnData, nullptr)`: the
template is an `oCEntitySettings` (a resource's embedded one lives at `+0x98`),
whose own spawnable pool constructs the entity. The spawner is the
`oCEntitySpawner` at `+0xa0` of the scene's `oCEntitySceneContext`. The spawn
data holds position (`+0x10`), quaternion (`+0x1c`), scale (`+0x2c`) and parent
(`+0x38`). The full evidence table is in `docs/_re/kinds/spawn-system.md` and
on the `EntityStore_CreateEntity` symbol. The June notes below are kept as
history. Their conclusion, that the instantiator was statically unreachable,
turned out to be wrong.
:::

## Goal

A generic SDK `R.spawn(template, transform)` that instantiates any entity
(rat/pet/enemy/prop) at runtime. The loader already exposes typed FFI by symbol
(`_internal.resolve`/`call`), so the SDK side is light **once the spawn fn + ABI
is known** — the whole cost is the RE.

## Pipeline

Entities are **not** spawned by a global `spawn(template, pos)`. The path is a
generic spawner component that holds a candidate-template list and instantiates
on tick:

1. **Picker** — `Enemy_RuntimeSpawnPicker` (`FUN_140330db0`). Enumerates enemy
   defs from the class registry (`Registry_EnemyDefinition_desc` `0x141470208`),
   filters by tier/flags/tribe, weighted-random picks, then lazily resolves each
   picked def's entity ref via `ResourceRef_Resolve` (`FUN_140491690`) →
   resolved template ptr at `def+0x2b8`.
2. **Spawn-data entry** — an `oCEntitySettingsRootPtr` (0x30 bytes): alloc
   `FUN_140338fa0`, fill `FUN_1406e5ef0` (typed-ref setter — stores the resolved
   template at `entry+0x18`, refcounts it, registers on the template's
   resolve/unresolve notify lists). A live, refcounted, auto-invalidating handle.
3. **Spawner candidate vector** on the component — `spawnerCpnt+0x68` data,
   `+0x70` count, `+0x74` cap (stride 8). The picker push_backs here. The prepare
   step `FUN_140330c30` resizes two parallel arrays at `+0x80`/`+0xa0` and stores
   an RNG seed at `+0xb8`.
4. **Instantiation — NOT located.** A later component virtual consumes
   `+0x68`/`+0x80` and creates live entities at the spawner transform (a 0x40-byte
   4×4 f32 matrix, not bare xyz). This is the remaining RE target.

## Why the instantiator is unreachable

Three Ghidra-MCP passes plus two headless passes converged: the runtime
create-entity routine is **vtable-dispatched** on the runtime component class
(`oCEntityCpntEntitySpawner` / `oCSpawnerGoEntityCollector`), whose metaclass/
vtable registrations sit in code regions Ghidra left **undefined**. The seeds
that looked promising resolved to *Settings* class registrars (reflection
metadata only — no instantiation):

- `0x140228547` → registrar for `oIEntityCollectorSettings` (hash `0x12cccf23`).
- `0x1402fadb9` → registrar for `oIEntityCpntSettings` (hash `0xc608329`).

The `oCEntitySpawnerGo` cluster (`FUN_140745620` build / `FUN_140745200`
activate) is the **editor/preview gizmo layer** — it builds a preview sub-level,
never a gameplay entity. Surgical static RE is exhausted.

## Levers (cheapest first)

- **A. Hijack a live spawner.** Enemy camps already hold configured spawners with
  valid transform/faction/scene context. Append a resolved-template entry to an
  existing spawner's `+0x68` vector, then let its tick instantiate with correct
  context. (Caveat: appending to the *selector*'s `+0x68` and ticking it **frees**
  entries — the live spawner must be the instantiating component, not the selector.)
- **B. Call the instantiator directly.** Needs the create fn + its full context
  ABI RE'd first.
- **C. Cold-construct a spawner.** Most general, most work.

## Recommended next step — dynamic trace

Static RE can't pin the create fn. Detour the selector prepare virtual
`FUN_140330c30` (clean unique pattern, like `hook_skills.cpp`) to capture a live
`spawnerCpnt` + its owning entity at runtime, then trace the subsequent vtable
calls to the actual create call site with real pointers. Needs a loader build +
playtest.

:::tip[Shippable now for the Piper rat-spawn goal]
No spawn primitive needed — tune the vanilla Ghost-Horde talent's two values
(notes, rats) and apply. See [Pickable talents](/reverse-engineering/pickable-talents/).
:::

## Symbols

In `data/symbols.json`: `Enemy_RuntimeSpawnPicker` `FUN_140330db0`,
`Registry_EnemyDefinition_desc` `0x141470208`, the ResourceRef resolve path.
To add once located: the entity factory, `SpawnEntry_Alloc` `FUN_140338fa0`,
`SpawnEntry_SetTemplate` `FUN_1406e5ef0`, `oCEntitySpawner::vftable` `0x140f023f8`.
