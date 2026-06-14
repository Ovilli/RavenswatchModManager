# Entity values — the engine's generic keyed stat / modifier store

> Status: RE complete, 2026-06-14. Addresses verified live against the shipped
> Ravenswatch.exe via the Ghidra MCP bridge (image base 0x140000000). Read path
> fully mapped; no runtime code shipped yet.

## What it is

Beyond the few stats that have plain fixed offsets on the hero controller (HP at
+0x15c8 — see `heroes.md`), most dynamic per-entity values — combat modifiers,
"dream shards on damage", run meta, scaling coefficients — live in a generic
**keyed value store**. Each value is addressed by a 32-bit **CRC key** derived
from its name (same id space as the gameplay-bus event ids). This is the engine's
`oCEntityValue` system.

This is how the game keeps hundreds of tunable per-entity values without a field
per stat, and it is the read surface a mod would use to inspect any named value.

## Read path

```text
valueCtx = *(hero + 0x2f8)          # the entity's value context
store    = *(valueCtx + 0x4c8)      # the value map (0 => no values, empty default)
EntityValue_Lookup(store, &out, crcKey)   # out is a ~0x20-byte oCEntityValueUnion
```

`EntityValue_Get` (`FUN_1403c71e0`) is the wrapper that does the `+0x4c8` deref;
`EntityValue_Lookup` (`FUN_1407481d0`) is the core lookup.

`EntityValue_Lookup(store, out, key)`:

1. Linear scan of an **override array** — `store+0xc0`, count at `store+0xc8`,
   0x38-byte entries, key = int at entry+0x0. This holds values that have been
   modified at runtime.
2. Fallback **hash map** at `store+0x80` (Fibonacci hash, multiplier
   `0xde5fb9d2630458e9`) — the base/default values from the definition.
3. Miss => the union is initialised to value `0`.

## oCEntityValueUnion (~0x20 bytes)

vftable = `oCEntityValueUnion_vftable` @ `0x140f8fed8`
(base `oISerializable::vftable` @ `0x140efed08`).

```text
+0x00  vftable
+0x08  type tag        (4 = value stored inline at +0x10)
+0x10  value           (inline f32 when tag==4; otherwise (tag & ~1) is a
                        pointer to the value)
+0x18  u16 = 0x000a
+0x1a  byte = 0
```

Read pattern used by the engine itself (e.g. in `Entity_ModifyHealth`):

```c
EntityValue_Lookup(store, &out, key);
float* p = (float*)(out + 0x10);
if (*(uint64_t*)(out + 8) != 4) p = (float*)(*(uint64_t*)(out + 8) & ~1ull);
float value = *p;
// then destruct: FUN_14082ca50(&out)
```

## Keys

`crcKey` is the CRC id of the value name. Observed in the heal/damage handlers:
`0x173900d4`, `0x173900d6` (dream-shards-on-damage family), `0x188831a6`,
`0x188832a9`, `0x1887e5ac`, `0x1ab19456`. The CRC algorithm is the same one
behind the gameplay-bus event ids (`NamedEvent_Id_FromCrc` / `FUN_14051e0e0`) —
confirming it would let a mod compute a key from a plain name string instead of
hard-coding observed ids. **TODO: confirm the exact CRC matches event-id CRC.**

## Toward a mod-facing API (future work)

`R.entity.value(name)` (read-only) is buildable:

1. resolve `EntityValue_Lookup` / `EntityValue_Get` by pattern (already symbols),
2. compute `crcKey` from `name` (pending CRC confirmation; until then accept a
   numeric key),
3. allocate a zeroed ~0x20-byte scratch buffer for `out`, call the lookup,
4. read the value per the union layout above,
5. call the union destructor `FUN_14082ca50(&out)`.

All reads are safe; the only sharp edge is providing a correct `out` buffer and
destructing it. A **write** path (modifying a value) would go through the
override array and is a separate, riskier RE item — not yet mapped.
