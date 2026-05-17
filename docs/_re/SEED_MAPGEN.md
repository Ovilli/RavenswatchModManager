# Seed + map generation surface

Reverse-engineered from `Ravenswatch.exe` (build hashed under
`data/exe_catalog.json`). Confirmed via Ghidra xref scan of the seed
strings interned in the read-only data segment. Addresses are
link-time VAs; resolve at runtime via image-base relocation.

## Built-in "Forced seed" exists

The game ships a `oe::UIntGameOption` field literally named `"Forced
seed"`, registered by the global game-options constructor at:

| Item | Address |
|---|---|
| Constructor that wires the field | `0x1401c6d60` |
| String `"Forced seed"` (ro-data)  | `0x140eed8b8` |
| Field ID (u32) at the call site   | `0x1949b098`  |
| Vtable used for the field         | `oe::UIntGameOption::vftable` |
| Companion enable flag             | id `0x1949b099`, `oe::BoolGameOption` |
| Format string `"Forced seed : {}"` | `0x140ef4068` (log line) |

So a "forced seed" code path is already plumbed in the engine — a mod
doesn't have to *invent* a seed hook, only flip the option on and
write the value.

## How to set it (without hooks)

The game's option system reads its initial values from
`DarkTalesResources/ApplicationSettings.ot`, which is plain
oCTextSaver text and already accepted by the `_root/` override
mechanism (`docs/MODDING.md`).

1. Open `data/uncooked/_root/DarkTalesResources/ApplicationSettings.ot`.
2. Find the block with the `Forced seed` option declaration
   (`oCTString` keys are stored verbatim).
3. Set the companion bool (id `0x1949b099`) true and the u32 (id
   `0x1949b098`) to the seed you want.
4. Ship the modified `ApplicationSettings.ot` under
   `mods/<id>/_root/DarkTalesResources/ApplicationSettings.ot`.

Until the settings block is fully decoded, the safer path is the in-
process route below.

## How to set it (Lua / DLL loader)

The loader DLL (`dist/winhttp.dll`) hosts a Lua VM per mod. To set the
forced seed from Lua you need one new `rsmm.*` binding that wraps a
write to the global option table. Skeleton (C++ side, `src/loader/`):

```c
// Resolve the GameOption registry once at boot via pattern signature
// (don't bake the absolute VA — it shifts on every game patch).
auto registry = ResolveGameOptionRegistry();

// Set the u32 field by id.
registry.SetUInt(0x1949b098, mod_seed);
// Flip the enable flag.
registry.SetBool(0x1949b099, true);
```

Expose as `rsmm.set_forced_seed(seed)`. Modder writes:

```lua
rsmm.on_event("ready", function()
    rsmm.set_forced_seed(42)
end)
```

## Other seed-adjacent symbols

| Address | What |
|---|---|
| `0x140f59758` | Field name `"m_uRandomSeed"` (entity persistent data) |
| `0x14073df80` | Function that registers the `m_uRandomSeed` field, class id `0x1bdf6dd3` ("Entity Cpnt Selector Persistent Data") |
| `0x140eef7f0` | String `"Rose seed"` — second seed channel (per-run RNG?) |
| `0x140ef13a8` | String `"CLEAR_ROSE_SEED"` — game event name, fires 48 places |
| `0x140ef1a70` | Format string `"Seed : {}"` |
| `0x140c92ef4` | `_Random_device` (40 bytes) — std::random_device singleton |

Decompiled bodies for every xref of these targets live under
`docs/_re/out/xref_targets/`. Open the `*.c` next to the symbol name
to see how it's used.

## What's still unknown

- The actual map-generation algorithm and where it pulls the seed
  from (per chapter? per map slot?). Need to follow the use of
  `m_uRandomSeed` through `oCEntityCpntSelector*`.
- Whether `Forced seed` overrides every RNG stream or only the
  top-level run seed. `Rose seed` looks like a separate stream so
  there may be more.

Next: trace `oCEntitySettingsResource` for the seed-consuming entity
("Entity Cpnt Selector"). The class registration at `0x14073df80`
gives the body offset (0x48) for the field, which is what an in-place
binary patch on a saved level cooked file would target.
