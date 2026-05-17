# Calling game functions from a mod

Goal: any reverse-engineered function in `Ravenswatch.exe` is callable
from a mod's `init.lua` by name, without rebuilding the loader and
without baking absolute addresses that break on every game patch.

This document is the user-facing API + the design that backs it.

## Pipeline

```
Ravenswatch.exe                                      data/
  │                                                    │
  │   Ghidra headless analyze                          │
  │   docs/_re/scripts/dump_symbols_strings.py         │
  ▼                                                    │
docs/_re/out/symbols.json (54k function VAs + names)   │
  │                                                    │
  │   scripts/gen_function_patterns.py                 │
  │   (disassembles each prologue, masks               │
  │    relocation-sensitive bytes, extends             │
  │    until pattern is unique-or-indexed)             │
  ▼                                                    │
data/function_patterns.json (53k entries)──────────────┘
  │
  │   shipped alongside winhttp.dll
  ▼
loader DLL → fn_resolver scans .text at runtime
           → fn_call_raw invokes via Win x64 ABI
           → exposed to Lua as rsmm.resolve / rsmm.call
```

## Lua API

```lua
-- 1. Resolve a function by symbolic name (defaults to the FUN_xxx
--    symbol Ghidra assigned, unless a label has been pinned).
local seed_register = rsmm.resolve("FUN_14073df80")
if not seed_register then error("not found — game patched?") end

-- 2. Call it. Signature is "<ret><args>" using single-char type codes:
--    i u l f d p s v   (int32, uint32, int64/ptr, float, double,
--                       void*, c-string, void)
rsmm.call(seed_register, "v l", entity_persistent_data_ptr)

-- 3. Or call by name in one shot:
rsmm.call("FUN_1401c6d60", "v l", game_options_struct)

-- 4. Raw memory access for game globals:
local module = rsmm.module_base()              -- runtime image base
local seed_va = module + 0xf59758              -- m_uRandomSeed string
rsmm.write_u32(seed_va, 42)                    -- override
print(rsmm.read_u32(seed_va))

-- 5. Read a c-string:
local s = rsmm.read_cstr(module + 0xeed8b8)    -- "Forced seed"
```

### Custom-seed example (speedrun use case)

```lua
-- mods/SeedPinner/init.lua
rsmm.on_event("ready", function()
    local SEED = 12345
    -- Game has a built-in "Forced seed" oe::UIntGameOption (id 0x1949b098).
    -- Easiest: find the global option registry and set the u32 field.
    local set_uint = rsmm.resolve("oe_GameOptions_set_uint")  -- alias TBD
    if not set_uint then
        rsmm.log("[SeedPinner] set_uint missing — game version drift")
        return
    end
    local enable = rsmm.resolve("oe_GameOptions_set_bool")
    rsmm.call(set_uint, "v u u", 0x1949b098, SEED)
    rsmm.call(enable,   "v u u", 0x1949b099, 1)       -- flip the enable bool
    rsmm.log(("[SeedPinner] seed forced to %d"):format(SEED))
end)
```

## Type codes

| Code | C type        | Reg slot (x64)            |
|------|---------------|---------------------------|
| `i`  | int32_t       | rcx/rdx/r8/r9 (or stack)  |
| `u`  | uint32_t      | rcx/rdx/r8/r9             |
| `l`  | int64_t       | rcx/rdx/r8/r9             |
| `p`  | void*         | rcx/rdx/r8/r9             |
| `f`  | float         | xmm0..xmm3                |
| `d`  | double        | xmm0..xmm3                |
| `s`  | const char*   | rcx/rdx/r8/r9 (pointer)   |
| `v`  | void          | return-type only          |

Max 8 args. Beyond that you need either a wrapper function recorded as
its own pattern, or libffi which we haven't pulled in.

## How resolution survives game patches

Every entry in `data/function_patterns.json` carries:

```json
{
  "name": "FUN_14073df80",
  "addr": "0x14073df80",          // link-time VA when captured
  "size": 832,
  "pattern": "48 89 5c 24 ?? ...", // first ≥12, up to 128 bytes
  "used_bytes": 64,
  "match_index": 3                 // Nth match in .text scan
}
```

`pattern` is the instruction prologue with relocation-sensitive bytes
(CALL/JMP rel32, RIP-relative leas, MOV mem disp32) replaced by `??`.
What stays in `pattern` is opcodes + register encoding + small
immediates — the *shape* of the instruction stream.

After a game patch:
1. Compiler emits the same source as a similar instruction sequence.
2. Addresses shift; opcode bytes stay.
3. `fn_resolver` scans `.text`, finds the same pattern at a new VA.
4. `match_index` disambiguates when multiple functions share a
   prologue (templated dtors, vtable thunks, tiny wrappers).

Validated on the current build: **>99% of patterns resolve to the
exact recorded VA** under the same exe. Cross-build drift is empirically
~90% — short patterns survive; functions that the optimizer reshuffled
need a regenerated entry. The pipeline is one command:

```sh
./rsmm rebuild-asset-map           # re-runs the Ghidra dumps
python3 scripts/gen_function_patterns.py
```

## Anti-tamper caveat

`rsmm.call` invokes game functions via a normal indirect call. The
anti-tamper layer in this title is sensitive to *hooks* (CreateFileW,
present-time Vulkan), not to direct calls — so calling is safe.

`rsmm.hook(...)` is **deliberately not exposed**. The MinHook engine
in `src/loader/` is wired for it, but every hookpoint we've tried so
far (CreateFileW, IDXGISwapChain::Present analogues) crashes the
process at startup. Until we have an injection mechanism that survives
the anti-tamper integrity check, mods can read + call but not
intercept.

## Memory access discipline

`rsmm.write_*` writes process memory directly. There is **no guard**
against writing into:

- `.text`  — would crash or be reverted by AT;
- vtables — corrupts dispatch;
- save data — corrupts player progress.

Treat writes as a sharp tool. Pattern-resolve the field's owner first
(`rsmm.resolve` returns the function that registers it), inspect the
decompile output, then poke. The
`docs/_re/out/decompiled_all/<bucket>/<name>__<addr>.c` files are the
authoritative reference for what each address means.

## Where to look

| Want to know… | Read |
|---|---|
| every function's prototype | `docs/_re/out/symbols.json` |
| what a function does | `docs/_re/out/decompiled_all/.../<name>.c` |
| every string the game uses | `docs/_re/out/strings.json` |
| what calls a given address | `docs/_re/out/xrefs.json` |
| how seed plumbing works | `docs/_re/SEED_MAPGEN.md` |

## Status

- **`rsmm.resolve` / `rsmm.call`** — designed and wired into
  `src/loader/src/script_lua.cpp`. Build the loader (`src/loader/build.sh`)
  and `./rsmm install-loader` to deploy.
- **Pattern database** — 53,427 entries, regen'd from current exe.
- **Aliases** (friendly names instead of `FUN_xxx`) — not yet shipped.
  Today modders look up symbols via grep on `symbols.json` and the
  decompiled C; aliases land when we hand-RE more subsystems.
- **Hook API** — blocked on anti-tamper; not on the surface.
