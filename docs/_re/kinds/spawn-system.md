# Spawn system — RE toward a generic `R.spawn` SDK primitive

> 📖 Prose version on the docs site: **https://docs.rsmm.me/reverse-engineering/spawn-system/** (`apps/docs/src/content/docs/reverse-engineering/spawn-system.md`).
> This file stays as the raw RE field notes.


> Goal: an SDK `R.spawn(template, pos, opts)` that instantiates an arbitrary
> entity (rat/pet/enemy/prop) at runtime. Driver: Piper Ghost Horde needs a
> standalone rat-spawn (the gameplay-event log has NO global spawn-rat event;
> rats only spawn via the hero's data spawner when the trait is equipped).
> RE date 2026-06-17, image base 0x140000000, via Ghidra MCP.

## Verdict so far: tractable but multi-step; instantiator not yet located

The loader already exposes typed FFI by symbol (`_internal.resolve`/`call`), so
the SDK side is light **once the spawn fn + ABI is known**: add a symbol with a
`cabi`, add an `R.spawn` Lua wrapper (main-thread-guarded per
[[loader-thread-model]]). The whole cost is the RE.

## Spawn pipeline (mapped)

Entities are NOT spawned by a global `spawn(template,pos)`. The path is a
generic **spawner component** that holds a candidate-template list and
instantiates on tick:

1. **Picker** — `Enemy_RuntimeSpawnPicker` = `FUN_140330db0(spawnerCpnt)`.
   - Enumerates ALL enemy defs from the class registry (`Registry_EnemyDefinition_desc`
     `0x141470208`, fallback all-instances `DAT_141439de0/+8`), filters by
     tier/flags/allowed-tribe, weighted-random picks (per-thread RNG via TLS+0xff3c).
   - Lazily resolves each picked def's entity ref:
     `FUN_140491690(def+0x288, srcList, def+0x2b8, owner)` = ResourceRef_Resolve →
     **resolved entity template ptr at `def+0x2b8`** (def+0x288 = the unresolved
     `oCEntitySettingsRootPtr` block).
   - Builds a spawn-data entry and appends it to the spawner's candidate vector.

2. **Spawn-data entry** = an **`oCEntitySettingsRootPtr`** (0x30 bytes):
   - alloc: `FUN_140338fa0()` → mallocs 0x30, sets `vftable=oCEntitySettingsRootPtr::vftable`,
     zeroes +0x08..+0x28.
   - fill: `FUN_1406e5ef0(entry, &resolvedRef)` = the typed-ref SETTER. Stores the
     resolved template at **entry+0x18**, bumps its refcount, and registers the
     entry on the template's two resolve/unresolve notify lists
     (callbacks `LAB_1406fdfc0` / `LAB_1406fdfe0`, lists at template+0x68 / +0x80).
     So the entry is a live, refcounted, auto-invalidating handle to a template.

3. **Spawner candidate vector** on the component:
   - `spawnerCpnt+0x68` = data ptr, `+0x70` = count, `+0x74` = cap (grow via
     `FUN_140154c20`, stride 8 = array of entry ptrs). The picker push_backs here.

   - The picker is a **virtual** (in vtable, data ref `1414a53f4`), wrapped by the
     spawner **prepare** step `FUN_140330c30`: runs the picker, then resizes two
     parallel arrays `spawnerCpnt+0x80` and `+0xa0` to the candidate count
     (`FUN_1402739e0` = resize), and stores an RNG value at `+0xb8`. So the
     component layout = `+0x68` candidate templates / `+0x70` count / `+0x80`
     parallel array (likely transforms) / `+0xa0` parallel array (likely spawned
     instance slots) / `+0xb8` seed.

4. **Instantiation (NOT YET LOCATED)** — a *later* component virtual consumes
   `+0x68`(+`+0x80`) and creates live entities at the spawner's transform (with
   faction/owner/AI). PRECISE NEXT HOP: `FUN_140330c30` (prepare) is a virtual on
   the **`oCDtEnemyFlagListEntitySelectorToSpawnEntityCpnt`** component (vtable near
   `140f25ae0`; RTTI string `oCDtEnemyFlagListEntitySelectorToSpawnEntityCpnt`
   `140f25360`). The instantiator is an ADJACENT slot in that vtable — dump the
   vtable methods, find the one reading `+0x68`/`+0x80`, decompile for the
   instantiate ABI. This is the actual factory and the remaining RE target.

## SHIPPED 2026-06-18 — dynamic-trace loader hook (`hook_spawn.cpp`)

The static RE is bottomed out, so the recommended dynamic trace is now built.
`src/loader/src/hook_spawn.cpp` (`install_spawn_hooks`, wired in `dllmain.cpp`,
default OFF) detours the selector **prepare** virtual `FUN_140330c30` via a clean
unique pattern (added to `data/function_patterns.json`, 44 used bytes,
`53 48 83 ec 20 48 8b d9 e8 ?? .. 48 8b 43 10 80 b8 08 01 00 00 01 ..`). After the
original runs (picker has rebuilt the candidate list) it logs, per spawner tick
(capped 32 calls):

- `cpnt` + its **vtable VA** (the key datum — subtract the live module base for
  the static RVA, then map the adjacent vtable slots to find the instantiator),
- owner sub-object `[+0x10]` + its vtable,
- candidate vector `+0x68` {data/count/cap} and parallel arrays `+0x80`/`+0xa0`,
- (gated `RSMM_SPAWN_TRACE_VERBOSE`) each candidate entry + resolved template
  `entry+0x18` + template vtable.

READ-ONLY by design: there is **no** mutating lever — appending to the
*selector*'s `+0x68` and ticking it FREES entries (it is not the instantiating
component). Arm with `RSMM_ENABLE_SPAWN_HOOK=1`. NEXT (user playtest): capture
the `vt=` line in a camp, rebase to the static module, dump that vtable's slots
in Ghidra → identify the create-and-register method = the `R.spawn` factory.

## Realistic levers (cheapest first)

- **A. Hijack a live spawner (near-term).** Enemy camps already hold configured
  spawner components with valid transform/faction/scene context. Append a
  resolved-template entry (steps 2–3 above) to an existing spawner's `+0x68`
  vector pointing at ANY def, then let/force its tick → it instantiates our
  entity with correct context, no cold construction. Find a live spawner instance
  and the tick trigger.
- **B. Call the instantiator directly (mid-term).** Locate the spawner tick =
  the fn that reads `+0x68` and instantiates; if its ABI is `(spawnerCpnt, entry)`
  or `(scene, template, transform, owner)`, expose it as a symbol+cabi and build
  the transform/owner from the hero. Generic but needs the factory's full context
  args RE'd.
- **C. Cold-construct a spawner (large).** Build an `oCEntitySpawner` +
  game-object, configure template/faction, register with the scene. Most general,
  most work.

## Symbols touched / to add

Existing (in `data/symbols.json`): `Enemy_RuntimeSpawnPicker` `FUN_140330db0`,
`Registry_EnemyDefinition_desc` `0x141470208`, ResourceRef resolve path.
To add once located: `EntitySpawner_Tick`/`Entity_InstantiateFromTemplate`
(the factory), `SpawnEntry_Alloc` `FUN_140338fa0`, `SpawnEntry_SetTemplate`
`FUN_1406e5ef0`, `oCEntitySpawner::vftable` `0x140f023f8`, `oCSpawner::vftable`
`0x140ed2870`, `oCEntitySettingsRootPtr::vftable` (entry type).

## 3 RE passes done (2026-06-17) — instantiator is in UNDEFINED regions

Three Ghidra-MCP passes (incl. 2 subagents) converged:

- The selector component (oCDtEnemyFlagListEntitySelectorToSpawnEntityCpnt) ONLY
  builds/tears-down the `+0x68` candidate list. Appending to `+0x68` + ticking the
  selector **frees** entries, does NOT spawn. Selector vtable slots: prepare
  `FUN_140330c30` (@140f25ae0), getter `FUN_140330cf0` (returns `*(entry+0x18)+0x98`
  = `template+0x98` spawn payload), pop-one `FUN_140330d20`, teardown `FUN_140331720`.
- `template+0x98` = spawn-payload field handed to instantiation; `FUN_1406e0130(
  template+0x98, world=*(scene+0x30))` is a FILTER predicate, NOT create.
- The `oCEntitySpawnerGo` subsystem (`FUN_140745620` build / `FUN_1407457f0` +
  `FUN_140745c50` transforms / `FUN_140745200` activate / `FUN_1407453f0` teardown;
  metaclass global `DAT_141470400` hash `0x17a169a9`) is the **EDITOR/PREVIEW gizmo
  layer** — builds a preview sub-level (`oCGameLevel` malloc 0x1c8 via
  `FUN_140483e60`→`FUN_14047a3a0`), never mallocs a gameplay entity. NOT the creator.
- **Spawn transform = a 0x40-byte 4x4 f32 matrix** (quat→matrix), stride 0x40, NOT
  bare xyz. The create routine takes a matrix transform.

THE WALL: the runtime instantiator is a vtable-dispatched method on
`oCEntityCpntEntitySpawner` (RTTI 140f20cf0) / `oCSpawnerGoEntityCollector`
(140f06ad8), whose metaclass/vtable registrations are in code regions Ghidra left
UNDEFINED — `get_function_by_address` = "No function found":

- `0x1402fadb9` — oCEntityCpntEntitySpawner metaclass/vtable region (PRIMARY target).
- `0x140228547` — oCSpawnerGoEntityCollector region (likely the create-and-register
  loop owner).
- `0x1402263d4` — oCEntitySpawnerGoState region.

### Headless pass 1 (2026-06-17) — seeds were Settings registrars, not the create

Ran `analyzeHeadless` over `0x1402fadb9`/`0x140228547`/`0x1402263d4`. They resolved to
**metaclass registrars for the *Settings* classes** (reflection descriptor setup),
NOT the runtime spawn method:

- `0x140228547` → `FUN_140226c00` = registrar for **`oIEntityCollectorSettings`**
  (type hash `0x12cccf23`, field-setup callback `FUN_1406f2960`, deser thunk
  `LAB_1401b9240`).
- `0x1402fadb9` → `FUN_140190010` = registrar for **`oIEntityCpntSettings`**
  (hash `0xc608329`, field-cb `FUN_140710270`).

These only register descriptors. The instantiator is a vtable method on the
**runtime** component class (oCEntityCpntEntitySpawner / oCSpawnerGoEntityCollector),
distinct from its *Settings*. NEXT headless seed = the runtime component ctor/vtable
(find via the descriptor's ctor field, or decompile the field-cbs `FUN_1406f2960`/
`FUN_140710270` to map the collector data layout + locate the create-and-register
loop). Project copy lives at /tmp/rsmm_hl (full 724M); scripts at
/tmp/rsmm_ghidra_scripts. NOTE: MCP (live project) does NOT see headless edits — the
copy is separate; re-decompile via headless or in the GUI.

### Headless pass 2 (2026-06-17) — Settings carry NO create; STATIC BOTTOM reached

Seeded `0x1406f2960` / `0x140710270` (the Settings field-callbacks). Both are pure
reflection metadata — set display name (`"Entity Collector Settings"` /
`"Entity component settings"`) + a category flag, nothing else. The *Settings*
classes hold no instantiation.

**DEFINITIVE: the runtime create-entity routine is vtable-dispatched and statically
unreachable** from every entry point tried (selector methods, Settings registrars +
field-cbs, every defined consumer of the candidate template `FUN_140340140`/
`FUN_1406e0130` = filter/commit not create, the SpawnerGo editor-preview cluster).
Surgical static RE is exhausted. Remaining options for the generic primitive:

- **DYNAMIC TRACE (recommended).** Detour the selector prepare virtual
  `FUN_140330c30` (clean unique pattern, like hook_skills) to capture a live
  `spawnerCpnt` + its owning entity at runtime; log the subsequent vtable calls /
  set a one-shot breakpoint-style trampoline to observe the actual create call site
  with real pointers. Needs loader build + playtest (user env). This is the only
  tractable way to pin the create fn.
- **Broad re-analysis (expensive, low-yield).** Full auto-analysis of the undefined
  `0x140228xxx`/`0x1402fadxx` blocks, then identify the create among thousands of
  newly-defined fns — not surgical, may not converge.

SHIPPABLE-NOW alternative for the Piper goal (no spawn primitive needed):
**path A** = tune vanilla Horde talent's 2 values (notes->10, rats->4), declare +
enable + apply. See talents-pick.md / talent-value-editing.

## Next (resumable) — needs the headless-define bypass

1. Run `analyzeHeadless` + `DefineAndDecompile.java` ([[ghidra-headless-bypass]],
   `/tmp/rsmm_ghidra_scripts/`) on a project COPY over seeds `0x1402fadb9`,
   `0x140228547`, `0x1402263d4` (the live MCP project is locked).
2. In the collector, find: malloc-entity + register into scene
   (`*(entity+0x30)`) entity list + 0x40-matrix transform write = the
   `R.spawn(template, transform)` create routine. Decompile for its ABI.
3. Decide GO/NO-GO on exposing it as symbol+cabi vs the runtime-hook path:
   detour the selector prepare virtual `FUN_140330c30` (clean unique pattern, like
   hook_skills) to capture a live `spawnerCpnt`, then trace its caller (the tick) to
   the create call dynamically.
4. Decide lever A (hijack live camp spawner) vs B (direct call) for the first
   shippable `R.spawn`. Rats = pet entities spawned the same way → covers Piper.
