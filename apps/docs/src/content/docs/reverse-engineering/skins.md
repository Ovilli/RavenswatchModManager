---
title: Skins
description: The nine hardcoded SkinPack slots, the Steam-ownership grid filter that hides a tenth, and why the cooked asset registry means there is no resolver to hook.
---

:::note
Status: Tier-1 RE backing `src/loader/src/hook_skins.cpp`. The custom slot ships
(count detour + grid-filter detour). New `Skin` folders remain blocked on the
asset registry. Addresses are preferred-base VAs (image base `0x140000000`).
:::

## Summary

The selectable skin roster is **not data-driven**. There is no per-hero skin list
and no per-hero skin count. Skins are **9 global "SkinPack" slots**
(`oCAdditionalContent` entries) shared by every hero; a hero carries only a
pack-id int at `+0x78`, matched against an entry's `+0x3c` key. The roster is built
once at startup with the count written as the **immediate constant `9`** — so a
10th slot cannot be added by shipping a cooked file. It needs a runtime detour,
which the native loader already makes possible.

Same "no UID, built inline" shape as heroes — see
[Heroes](/reverse-engineering/heroes/).

## The roster builder

`FUN_1401dcae0(ctx)` runs once from the global game-systems bootstrap. It manages
a fixed array on the manager ctx and threads each entry into a global linked list:

```
ctx + 0x13c0   oCAdditionalContent* array  (malloc/realloc'd to 9*0xA0 = 0x5A0)
ctx + 0x13c8   count      <- *** immediate 9 *** (mov dword [rcx+0x13C8], 9)
ctx + 0x13cc   capacity   <- pinned to 9
```

Each entry is `0xA0` bytes. The loop (`i = 0..8`) fills:

| Off | Type | Source array (`.rdata`, stride) | Meaning |
|--------|-------------|---------------------------------|----------------------------|
| +0x00  | vtable      | `oCAdditionalContent::vftable`  | set by ctor |
| +0x08  | ptr         | list: next (old head)           | linked-list field |
| +0x10  | ptr         | list: back-link slot            | written into prev head |
| +0x18  | ptr         | `DAT_141436590` (manager)       | owner |
| +0x30  | u64         | `5`                             | type/state enum (ctor) |
| +0x3c  | i32         | `DAT_140f07b80` (×4)            | **pack key** (`hero+0x78` matches this) |
| +0x48  | i32         | `DAT_140f0d8a0` (×4)            | 1-based index (1..9) |
| +0x50  | std::string | `0x140f08380` (×0x10)           | AC asset id `RW000PSAC000000N` |
| +0x60  | std::string | `0x140f06de0` (×0x10)           | AL asset id `RW000PSAL000000N` |
| +0x70  | std::string | `0x140f0e830` (×0x10)           | base id, `9PM96K8TFJC4`-style |
| +0x90  | std::string | `0x140f0d8e0` (×0x10)           | display name, `"… SkinPack"` |

Shipped names[0..8]: Fairytales / Ravens / Nightmares / Unleashed SkinPack,
Romeo & Juliet HeroPack, Romeo & Juliet SkinPack, Timeless SkinPack, Merlin
HeroPack, Mercenaries SkinPack.

### Per-entry construction (two helpers, reused by the detour)

- `FUN_140214bb0(base, count)` — placement ctor: sets the vtable at `+0x00`,
  `+0x30 = 5`, zeroes the list fields, and initialises the four string members to
  the empty sentinel `{ ptr=&DAT_140ed5a10, lenflags=0x80000000 }`.
- `FUN_1405288b0(dst_slot, src_desc)` — string assign. `src_desc` is a 16-byte
  `{ const char* ptr; u32 lenflags; u32 pad }`. The high bit of `lenflags`
  (`0x80000000`) means **literal / non-owned**: the helper adopts the pointer
  verbatim, so the backing string must outlive the entry. Pass `lenflags = len`
  (no high bit) to force an owned heap copy.

### Global manager list

`DAT_141436590` is a **pointer load** — the global holds
`oIAdditionalContentManager*`. Consumers (skin-grid populate, selection handlers)
walk this list, **not** the fixed array, so a new node only needs to be on the
list.

```
mgr + 0x08   i32 node-count
mgr + 0x10   head
mgr + 0x18   tail
```

Push-front sequence the builder uses — replicate exactly:

```c
e[0x18] = mgr;                              // owner
if (mgr[0x08] == 0) mgr[0x18] = e;          // empty -> tail = e
else                (*mgr[0x10])[0x10] = e; // old_head+0x10 = e
e[0x08] = mgr[0x10];                        // e->next = old head
mgr[0x08] += 1;
mgr[0x10] = e;                              // head = e
```

## Append strategy

POST-detour the roster builder. After the engine builds its 9 entries, allocate
**standalone `0xA0` nodes** — not in the fixed array, so the engine's
realloc/shrink on a re-run can't clobber them — construct each with the placement
ctor, set `+0x3c`/`+0x48`, assign the 4 strings, and push onto the manager list.
Guarded by `std::call_once`. The helpers are pattern-resolved and verified before
call, so the hook degrades to a no-op on a future patch instead of jumping into
moved code. The only hardcoded absolute is `DAT_141436590`, relocated by the live
image base.

## Authoring

```python
from rsmm import sdk
with sdk.Mod("crimson_skins", version="1.0.0", author="me", name="Crimson Skins") as m:
    m.skinpack("Crimson Pack", key=0x900001,
               ac_id="RW000PSAC000000A", al_id="RW000PSAL000000A", base_id="CUSTOM01")
```

`Mod().skinpack(name, key, *, ac_id, al_id, base_id)` writes
`mods/<id>/skinpacks.json`. The loader aggregates that across every **enabled**
mod (plus an optional hand-authored top-level `mods/skinpacks.json`); keys must be
unique across all sources.

## The grid filter — why a new key was invisible

The roster list is built; the *grid* is a separate, filtered copy. The populate
`FUN_1401f0f10(ctx, scene)` walks the manager list and for each node calls the
manager's **vtable[1]** filter:

```
RAX = [mgr];  iVar = (*(int(*)(void*,void*))[RAX+0x8])(mgr, node);
if (iVar == 3) <push node into ctx grid vector>
```

Only nodes scoring `3` become buttons. The grid vector lives on the screen ctx as
a `{ptr; i32 count; u32 cap}` triple at `ctx+0x2f8` / `+0x300` / `+0x304`, grown
through `FUN_140154c20(vec, <unused RDX>, u32 new_cap)` — **the new capacity is
the 3rd integer arg (R8)**; RDX is dead at the call sites.

### Which filter is live

Three instantiable manager variants exist (the base is abstract), vtables
recovered via `ExportVftables.java` → `data/vftables.jsonl`:

| Class | Slot[1] | Behavior |
|-------|---------|----------|
| `oIAdditionalContentManager` `0x140f3e288` | `0x1400c07a0` | `return 0;` — stub, always reject |
| `oCNullAdditionalContentManager` `0x140f3e1e0` | `0x1400c07a0` | same stub (inherited) |
| `oCLocalAdditionalContentManager` `0x140f3e578` | `FUN_140647440` | reads `char**` at `node+0x80`, prepends `\\?\`, `GetFileAttributesW` — file exists → 3 |
| `oCSteamAdditionalContentManager` `0x140f8db00` | `FUN_140a2c600` | reads the u32 key at `node+0x3c`, `ISteamApps::BIsDLCEnabled` — owned → 3 |

A brand-new key fails both: Steam doesn't know the key, and `node+0x80` is NULL on
the local path. **Verified at runtime** (Linux, GE-Proton10-34, Steam build): the
active filter is the Steam one, and a custom node logged `filter=0`.

### The filter detour (default-on)

`hook_skins.cpp` MinHook-detours the grid filter so custom packs pass the gate as
proper buttons. `hook_filter(mgr, node)` returns `3` when the node's key matches a
registered pack and forwards every other node to the original, so vanilla DLC and
skin slots keep their real ownership / file-existence checks.
`RSMM_SKIN_FORCE_SHOW` is retained only as a fallback diagnostic.

**The filter address is read from the live vtable, not pattern-resolved.**
`install_filter_hook(mgr)` reads `*(*(void**)mgr + 8)` — the actual slot the engine
calls — and hooks that. Correct for whichever manager class the build constructs,
and it needs no per-function signature.

:::caution
The `function_patterns.json` entries for `FUN_140a2c600` and `FUN_140647440` are
**stale** — each resolves to a single *wrong* address and the recorded VA isn't
among the matches. Do not `fn_resolve` these two until the patterns are
regenerated; the vtable read sidesteps them entirely.
:::

## Asset naming

The `(hero, pack) → model/material` resolver is un-decompiled, but the cooked-asset
naming it expects is fully enumerable from `data/asset_map.json` (2280 hero-skin
texture entries). Per (hero, skin):

```
3D\Characters\Heroes\<Hero>\Textures\<Skin>\M_<Hero><Skin>.mat.ot.Material.gen
3D\Characters\Heroes\<Hero>\Textures\<Skin>\M_<Hero><Skin>Static.mat.ot.Material.gen
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_ALB.tga.Texture.dxt   (albedo)
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_EMI.tga.Texture.dxt   (emissive)
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_MRA.tga.Texture.dxt   (metal/rough/ao)
3D\Characters\Heroes\<Hero>\Textures\<Skin>\T_<Hero><Skin>_NRM.tga.Texture.nrm   (normal)
```

60 vanilla skin folders exist (Classic, Dark, Raven, Pirate, Dracula, 1001Nights,
Nightmare, Royal, Lich, Djinn, …).

### There is no runtime resolver to hook

After an exhaustive search across all 54,450 decompiled functions and the full
`.text` section:

- **No function** builds cooked asset path strings from AC/AL/Base ID fragments at
  runtime.
- **No function** reads entry offsets `+0x50`/`+0x60`/`+0x70` and builds a path.
- The AC/AL IDs are referenced **only** in the roster builder.

The engine uses a **cooked binary asset registry** — the same one that produces
`data/asset_map.json`. AC/AL/Base IDs are opaque keys into it, resolved at cook
time, not by runtime string concatenation.

So hooking a resolver is neither possible nor necessary. The correct approach is
the one the CLI already uses: on-disk file replacement at the cooked path, scoped
to an existing slot's `Textures/<Skin>/` folder (**not** the hero's default-skin
path, or you mutate the default skin). Custom skins needing brand-new `<Skin>`
folders wait on the asset-registry format being reverse-engineered.
