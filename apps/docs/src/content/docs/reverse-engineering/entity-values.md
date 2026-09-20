---
title: Entity values
description: The engine's generic CRC-keyed per-entity value store — where most dynamic stats and modifiers live.
---

:::note
Status: read path fully mapped 2026-06-14 and shipping since; the write path was
mapped later and is **not** what this page originally assumed — see
[The mod-facing API](#the-mod-facing-api). Addresses verified live against the
shipped `Ravenswatch.exe` (image base `0x140000000`).
:::

## What it is

A few quantities sit at plain fixed offsets: health on the HitPoint component,
dream shards at `heroController+0x15c8`. See
[Anatomy of an entity](/reverse-engineering/entity-anatomy/) for which is which.

Everything else dynamic and per-entity — combat modifiers, "dream shards on
damage", run meta, scaling coefficients — lives in a generic **keyed value
store**, and there are hundreds of them. Each value is addressed
by a 32-bit key (same id space as gameplay-bus event ids). This is the engine's
`oCEntityValue` system, and it is the read surface a mod uses to inspect any
named value.

## Read path

```text
valueCtx = *(hero + 0x2f8)          # the entity's value context
store    = *(valueCtx + 0x4c8)      # the value map (0 => no values)
EntityValue_Lookup(store, &out, crcKey)   # out is a ~0x20-byte union
```

`EntityValue_Get` (`FUN_1403c7fa0`) wraps the `+0x4c8` deref;
`EntityValue_Lookup` (`FUN_140749260`) is the core lookup:

1. Linear scan of an **override array** — `store+0xc0`, count at `store+0xc8`,
   0x38-byte entries, key = int at `entry+0x0`. Holds runtime-modified values.
2. Fallback **hash map** at `store+0x80` (Fibonacci hash, multiplier
   `0xde5fb9d2630458e9`) — the base/default values from the definition.
3. Miss → the union is initialised to value `0`.

## oCEntityValueUnion (~0x20 bytes)

vftable `0x140f8fed8` (base `oISerializable::vftable` `0x140efed08`).

```text
+0x00  vftable
+0x08  type tag   (4 = value stored inline at +0x10)
+0x10  value      (inline f32 when tag==4; else (tag & ~1) is a pointer to it)
+0x18  u16 = 0x000a
```

Engine read pattern (e.g. in `Hero_ModifyDreamShards`):

```c
EntityValue_Lookup(store, &out, key);
float* p = (float*)(out + 0x10);
if (*(uint64_t*)(out + 8) != 4) p = (float*)(*(uint64_t*)(out + 8) & ~1ull);
float value = *p;
FUN_14082ca50(&out);   // destruct the union
```

## Keys are sequential ids, NOT name hashes

`crcKey` is a 32-bit value id. Observed: `0x173900d4`, `0x173900d6`,
`0x188831a6`, `0x12e831f3`/`0x12e831f4`, `0x171c27b5`. Two proofs they are
**structured ids, not hashes of the value name**:

1. **Adjacency** — `0x12e831f3`/`0x12e831f4` differ by 1; `0x173900d4`/`0x173900d6`
   by 2. Independent CRC32 hashes could never land on consecutive integers.
2. **Computed base+index** (decisive) — `Hero_GrantMagicalObject` reads
   `EntityValue_Lookup(store, &out, rarityIdx + 0x1a19e789)` where `rarityIdx` is
   0..5. The key is literally a base id plus an index.

So a mod **cannot** compute a value key by hashing a name — the key must come
from the value's definition (a GUID/id) or be discovered empirically (observe the
immediate the engine routine uses).

For contrast, the engine's string→id hash *does* exist and **is** plain CRC32 —
`Id_HashString` (`FUN_14033f7a0`) = `crc32_pair(0, crc32(name))`, poly
`0x04C11DB7`. But that scheme is for **named events / interned name ids**, not
these value keys.

## The mod-facing API

Both halves ship now. `R.entity.value(name)` and `R.stat.get` take the read path
above: resolve `EntityValue_Lookup` by pattern, take a **numeric** key, allocate
a zeroed ~0x20-byte scratch for `out`, call the lookup, read per the union
layout, then destruct.

The **write** path turned out not to be the override array. Poking a value into
`store+0xc0` works only until the next `EntityValueStore_Recompute`, which
rebuilds every entry from the definition's base value plus the registered
modifiers and discards the poke. A durable write therefore has to *be* a
modifier, and the reliable way to register one is the game's own: `R.stat.modify`
dispatches an `ADD_MODIFIER` named event on the hero's bus, which applies once,
refreshes the display cache and survives a chapter change. See
[Stats & XP](/reverse-engineering/stats/#making-a-write-durable) for the routes and
their trade-offs, and for the mined catalog of 221 keys.

## See also

- [Anatomy of an entity](/reverse-engineering/entity-anatomy/) — how this store relates to components and plain fields.
- [Stats & XP](/reverse-engineering/stats/) — the key catalog and the write routes.
- [Combat & damage](/reverse-engineering/combat-damage/) — `Hero_ModifyDreamShards` reads this store.
