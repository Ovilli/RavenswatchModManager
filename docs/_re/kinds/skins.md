# Custom skins — `oCAdditionalContent` SkinPack roster

> Status: Tier-1 RE backing `src/loader/src/hook_skins.cpp`. Derived from
> live Ghidra MCP + verification against the shipped `Ravenswatch.exe`
> (image base `0x140000000`; the anchor `mov [rcx+0x13C8], 9` occurs
> exactly once in `.text` at `0x1401dcaf4`, confirming the analyzed build
> == the installed build). Addresses are preferred-base VAs.

## TL;DR

The selectable skin roster is **not data-driven**. There is no per-hero
skin list and no per-hero skin count. Skins are **9 global "SkinPack"
slots** (`oCAdditionalContent` entries) shared by every hero; a hero
carries only a pack-id int (`+0x78`) that is matched against an entry's
`+0x3c` key. The roster is built once at startup with the count written
as the **immediate constant `9`** — so a 10th slot cannot be added by
shipping a cooked file. It requires a runtime detour, which the native
loader (`winhttp.dll` + MinHook) already makes possible.

See also the `skin-roster-hardcoded` memory and
[`heroes.md`](heroes.md) (same "no UID, built inline" shape).

## The roster builder — `FUN_1401dcae0(ctx)`

Runs once from `FUN_1401d16c0` (call site `0x1401d208e`, the global
game-systems bootstrap). It manages a fixed array on the manager ctx and
threads each entry into a global linked list:

```
ctx + 0x13c0   oCAdditionalContent* array  (malloc/realloc'd to 9*0xA0 = 0x5A0)
ctx + 0x13c8   count      <- *** immediate 9 *** (mov dword [rcx+0x13C8], 9)
ctx + 0x13cc   capacity   <- pinned to 9
```

Each entry is `0xA0` bytes. The loop (`i = 0..8`) fills:

| Off    | Type        | Source array (`.rdata`, stride) | Meaning                    |
|--------|-------------|---------------------------------|----------------------------|
| +0x00  | vtable      | `oCAdditionalContent::vftable`  | set by ctor (below)        |
| +0x08  | ptr         | list: next (old head)           | linked-list field          |
| +0x10  | ptr         | list: back-link slot            | written into prev head     |
| +0x18  | ptr         | `DAT_141436590` (manager)       | owner                      |
| +0x30  | u64         | `5`                             | type/state enum (ctor)     |
| +0x3c  | i32         | `DAT_140f07b80` (×4)            | **pack key** (hero+0x78 matches this) |
| +0x48  | i32         | `DAT_140f0d8a0` (×4)            | 1-based index (1..9)       |
| +0x50  | std::string | `0x140f08380` (×0x10)           | AC asset id `RW000PSAC000000N` |
| +0x60  | std::string | `0x140f06de0` (×0x10)           | AL asset id `RW000PSAL000000N` |
| +0x70  | std::string | `0x140f0e830` (×0x10)           | base id `9PM96K8TFJC4`-style   |
| +0x90  | std::string | `0x140f0d8e0` (×0x10)           | display name `"… SkinPack"`    |

Shipped names[0..8]: Fairytales / Ravens / Nightmares / Unleashed
SkinPack, Romeo & Juliet HeroPack, Romeo & Juliet SkinPack, Timeless
SkinPack, Merlin HeroPack, Mercenaries SkinPack.

### Per-entry construction (two helpers — reused by the detour)

- `FUN_140214bb0(base, count)` — placement ctor: sets vtable at +0x00
  (`oCAdditionalContent::vftable`), `+0x30 = 5`, zeroes the list fields,
  and initialises the four string members to the empty sentinel
  `{ ptr=&DAT_140ed5a10, lenflags=0x80000000 }`.
- `FUN_1405288b0(dst_slot, src_desc)` — string assign. `src_desc` is a
  16-byte `{ const char* ptr; u32 lenflags; u32 pad }`. High bit of
  `lenflags` (`0x80000000`) = **literal / non-owned**: the helper adopts
  the pointer verbatim (no copy), so the backing string must outlive the
  entry. Pass `lenflags = len` (no high bit) to force an owned heap copy.

### Global manager list — `DAT_141436590`

`MOV RAX, [rip]->0x141436590` (a **pointer load**: the global holds
`oIAdditionalContentManager*`). Consumers (skin-grid populate
`FUN_1401f0f10`; selection handlers `FUN_140382bf0`, `FUN_1403ed3e0`, …)
walk this list, **not** the fixed array — so a new node only needs to be
on the list, not in `ctx+0x13c0`.

```
mgr + 0x08   i32 node-count
mgr + 0x10   head
mgr + 0x18   tail
```

Insert sequence the builder uses (push-front — replicate exactly):

```c
e[0x18] = mgr;                              // owner
if (mgr[0x08] == 0) mgr[0x18] = e;          // empty -> tail = e
else                (*mgr[0x10])[0x10] = e; // old_head+0x10 = e
e[0x08] = mgr[0x10];                        // e->next = old head
mgr[0x08] += 1;
mgr[0x10] = e;                              // head = e
```

## Append strategy (implemented in `hook_skins.cpp`)

POST-detour `FUN_1401dcae0`. After the engine builds its 9 entries,
allocate **standalone `0xA0` nodes** (NOT in the fixed array — so the
engine's realloc/shrink on any re-run can't clobber them), construct each
with `FUN_140214bb0(e,1)`, set `+0x3c`/`+0x48`, assign the 4 strings with
`FUN_1405288b0` (literal bit + leaked C-strings), and push onto the
manager list with the sequence above. Guarded by `std::call_once`.

The three functions are pattern-resolved (`data/function_patterns.json`,
verified by `scripts/test_pattern_resolve.py`) and `fn_verify`'d before
call, so the hook degrades to a no-op on a future patch rather than
jumping into moved code. The only hard-coded absolute is
`DAT_141436590`, relocated by the live image base.

## Authoring (SDK)

```python
from rsmm import sdk
with sdk.Mod("crimson_skins", version="1.0.0", author="me", name="Crimson Skins") as m:
    m.skinpack("Crimson Pack", key=0x900001,
               ac_id="RW000PSAC000000A", al_id="RW000PSAL000000A", base_id="CUSTOM01")
    # stage the cooked per-skin assets the resolver expects (naming TBD):
    # m.asset("3D/Characters/Heroes/Aladdin/Textures/Crimson/M_AladdinCrimson.mat.ot", ...)
```

`Mod().skinpack(name, key, *, ac_id, al_id, base_id)` writes
`mods/<id>/skinpacks.json`. The loader (`install_skin_hooks`) aggregates
that across every **enabled** mod (plus an optional hand-authored
top-level `mods/skinpacks.json`); keys must be unique across all sources.

## The skin-grid filter — `FUN_1401f0f10` (why a new key is invisible)

The roster list is built; the *grid* is a separate, filtered copy. The
populate `FUN_1401f0f10(ctx, scene)` walks the manager list `DAT_141436590`
(head `+0x10`, next `+0x08`) and for each node calls the manager
**vtable[1]** filter:

```
RAX = [mgr];  iVar = (*(int(*)(void*,void*))[RAX+0x8])(mgr, node);
if (iVar == 3) <push node into ctx grid vector>   // 0x1401f1690: CMP EAX,0x3
```

Only nodes the filter scores `3` become buttons. The grid vector lives on
the screen ctx as a `{ptr; i32 count; u32 cap}` triple:

```
ctx + 0x2f8   ptr        ctx + 0x300   count        ctx + 0x304   cap
```

and grows through `FUN_140154c20(vec, <unused RDX>, u32 new_cap)` — the
**new capacity is the 3rd integer arg (R8)**; RDX is dead at the call sites
(`0x1401f16c8`). Layout the helper assumes: `{ptr@+0, count@+8, cap@+0xc}`.

So our appended node is on the roster list but the filter rejects a
brand-new key → no button. That is the user-visible "no new skin button".

## A1 — force-show (implemented, env-gated)

`hook_skins.cpp` now post-detours `FUN_1401f0f10` when
`RSMM_SKIN_FORCE_SHOW=1`: it calls the filter for each of our nodes (to
**log the verdict** for the A2 RE), then force-pushes every node into the
grid vector via the engine's own `grid_push`/grow sequence regardless of
the result. Both `FUN_1401f0f10` and `FUN_140154c20` are now in
`data/function_patterns.json` (added via `scripts/add_function_patterns.py`,
validated by `scripts/test_pattern_resolve.py`).

In-game (Windows): `src/loader/build.bat`, set `RSMM_SKIN_FORCE_SHOW=1`,
launch, open the skin grid — the extra button should appear; `./rsmm log`
prints `filter=<n>` per node. Capture those values for A2.

## A2 — the filter is identified (static RE, from `ExportVftables.java`)

The manager class hierarchy has three instantiable variants (the base
`oIAdditionalContentManager` is abstract). Their vtables were recovered
via `scripts/ghidra_scripts/ExportVftables.java` → `data/vftables.jsonl`:

```
oIAdditionalContentManager::vftable        @ 0x140f3e288   (base — slot[1] is stub)
oCNullAdditionalContentManager::vftable     @ 0x140f3e1e0   (null — slot[1] is also stub)
oCLocalAdditionalContentManager::vftable    @ 0x140f3e578   (local — slot[1] checks file existence)
oCSteamAdditionalContentManager::vftable    @ 0x140f8db00   (steam — slot[1] checks Steam ownership)
```

All four share a common "base dtor" (`FUN_1406472e0`) which nulls the global
`DAT_141436590`. Each ctor sets its own vtable pointer, then calls
`FUN_1406472e0` as the base initializer. The runtime instance stored at
`DAT_141436590` is whichever the game's init path constructs — most likely
`oCSteamAdditionalContentManager` for the Steam build, or
`oCLocalAdditionalContentManager` for a DRM-free/local build.

Vtable slot[1] (the grid-populate filter, called as
`(**(code**)(*mgr + 8))(mgr, node)` by `FUN_1401f0f10`):

| Class | Slot[1] address | Behavior |
|-------|----------------|----------|
| `oIAdditionalContentManager` | `0x1400c07a0` | `return 0;` — stub, always reject |
| `oCNullAdditionalContentManager` | `0x1400c07a0` | same stub (inherited) |
| `oCLocalAdditionalContentManager` | `FUN_140647440` | reads `char**` at `node+0x80`, calls `FUN_1405225f0(&path)` which prepends `\\?\` and calls `GetFileAttributesW` — if the file exists → return 3 |
| `oCSteamAdditionalContentManager` | `FUN_140a2c600` | reads `uint32` key at `node+0x3c`, calls `ISteamApps::BIsDLCEnabled` (vtable[0x38]) on the Steam context — if owned → return 3 |

**Local filter** (`FUN_140647440`):
```c
undefined8 FUN_140647440(undefined8 mgr, longlong node) {
    char** path_ptr = *(char***)(node + 0x80);
    if (**path_ptr != '\0') {
        if (FUN_1405225f0(path_ptr))  // file-existence check (GetFileAttributesW)
            return 3;
    }
    return 0;
}
```

**Steam filter** (`FUN_140a2c600`):
```c
undefined8 FUN_140a2c600(undefined8 mgr, longlong node) {
    uint key = *(uint*)(node + 0x3c);
    if (DAT_1412ce535 != 0) {  // Steam initialised
        void* steam_ctx = SteamInternal_ContextInit(&PTR_FUN_1412d22d0);
        if ((**(code**)(*(longlong*)*steam_ctx + 0x38))(steam_ctx, key))
            return 3;
    }
    return 0;
}
```

**A2 verdict**: A brand-new key fails both filters:
- The Steam filter rejects it because `ISteamApps::BIsDLCEnabled(new_key)` is false (Steam doesn't know the key).
- The local filter rejects it because `node+0x80` is NULL (zero-initialised by the entry ctor) — the null dereference would crash, but the Steam filter is active on the Steam build, so the local path is unused.

**Verified at runtime** (Linux, GE-Proton10-34, Steam build): the active filter
is `oCSteamAdditionalContentManager::vftable[1]` (`FUN_140a2c600`). Our custom
node (key `0xa00001`) logged `filter=0` — the Steam DLC check rejected it.
The force-show hook (`RSMM_SKIN_FORCE_SHOW=1`) pushes it into the grid anyway.

To retire force-show the Steam filter must be hooked: intercept
`FUN_140a2c600` (the actual vtable slot), check if the key matches one of
our packs, and return `3` for our keys while forwarding all others to the
original. The `node+0x80` path is irrelevant for the Steam build — the
local filter's file-existence path is never evaluated.

## A3 — asset naming is solved (from `data/asset_map.json`)

The `(hero,pack) -> model/material` *resolver* function is still un-decompiled,
but the **cooked-asset naming it expects is fully enumerable from the asset
map** (2280 hero-skin texture entries; decoded values). Per (hero, skin):

```
3D\Characters\Heroes\<Hero>\Textures\<Skin>\M_<Hero><Skin>.mat.ot.Material.gen
3D\Characters\Heroes\<Hero>\Textures\<Skin>\M_<Hero><Skin>Static.mat.ot.Material.gen
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_ALB.tga.Texture.dxt   (albedo)
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_EMI.tga.Texture.dxt   (emissive)
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_MRA.tga.Texture.dxt   (metal/rough/ao)
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_NRM.tga.Texture.nrm   (normal)
```

60 vanilla skin folders exist (Classic, Dark, Raven, Pirate, Dracula,
1001Nights, Nightmare, Royal, Lich, Djinn, …). Implication for authoring: a
custom skin ships a new `Textures/<Skin>/` set per hero under the above names,
cooked into the corresponding encoded paths. The remaining unknown is which
field on the roster entry (or hero pack-id) selects the `<Skin>` folder — that
is the resolver to decompile next, but assets can be staged against this naming
now and reused once A2 makes the slot selectable.

Safe variant until A2/resolver land: **reuse an existing slot's AC/AL id** and
override that slot's cooked asset, scoped to the slot's `Textures/<Skin>/` path
(NOT the hero's default-skin path) to avoid mutating the default skin.

### A3 verdict: no runtime resolver to hook

After exhaustive search across all 54,450 decompiled functions in
`data/decompiled.jsonl` and the Ghidra server's full `.text` section
(`0x140001000..0x140eb37ff`):

- **No function** constructs cooked asset path strings (`Characters`, `Textures`,
  `Material.gen`, `M_`, `T_`) from AC/AL/Base ID fragments at runtime.
- **No function** reads entry offsets `+0x50`/`+0x60`/`+0x70` and builds a path.
- The AC/AL IDs (`RW000PSAC0000001`-style) are referenced **only** in the
  roster builder (`FUN_1401dcae0` / `FUN_1401d98e0`).

**Why**: the engine uses a **cooked binary asset registry** — the same one that
produces `data/asset_map.json`. AC/AL/Base IDs are opaque keys into this
registry, which maps logical item IDs → pre-computed cooked paths at
load/init time, not at runtime via string concatenation. This is the same
pattern Unreal Engine uses with its `AssetRegistry`.

**Practical implication for RSMM**: hooking a "resolver" function is neither
possible nor necessary. The asset-registry entries are baked into the game's
`.pak` at cook time and cannot be injected by a DLL at runtime without
reimplementing the full engine asset system. The correct approach is the
one the Python CLI already uses: **on-disk file replacement** at the cooked
path, scoped to an existing slot's asset folder. Custom skins with unique
AC/AL IDs that need new `<Skin>` folders must wait for the asset-registry
format to be reverse-engineered (low priority — the reuse-vanilla-slot path
handles the immediate use case).
