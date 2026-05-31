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

## OPEN / UNVERIFIED (needs in-game Windows test)

Registering a roster slot is proven byte-for-byte here, but two things
are **not yet confirmed in-game**:

1. **Selectability per hero.** A hero shows a pack only when its `+0x78`
   matches the entry `+0x3c` key (and likely an ownership/entitlement
   gate keyed off the AC/AL ids). Whether a brand-new key surfaces in the
   grid for a chosen hero — vs being filtered out by category/ownership —
   is unverified.
2. **Asset resolution.** The AC/AL/base ids look like content/entitlement
   ids; the actual per-hero skin **model+material** is resolved elsewhere
   from `(hero, pack)`. A new slot likely needs matching cooked assets
   under whatever naming that resolver expects, which is the next RE step
   (find the `(hero,pack)->asset` lookup). Until then, the safe, shippable
   variant is to **reuse an existing slot's AC/AL id** and override the
   cooked asset behind it via the install-time replacement pipeline.
