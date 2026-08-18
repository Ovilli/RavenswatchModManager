-- Unit tests for the loader SDK (src/loader/lib/rsmm.lua) under a mocked
-- native layer. Run with plain lua 5.4:  lua tests/lua/rsmm_spec.lua
--
-- rsmm.lua expects a global `rsmm` table (the native bindings the loader
-- injects) plus `rsmm._internal` with the memory / call / resolve primitives.
-- We stand up a byte-addressed fake memory and a tiny engine-call emulator so
-- the pointer-poking stat/durability code runs end-to-end with NO game — the
-- code most likely to crash a user's machine, previously untested.
--
-- Exits nonzero on the first failed assertion (pytest wrapper checks the code).

local LIB = (arg and arg[1]) or "src/loader/lib"
-- Both trees are merged into <game>/rsmm/lib at install time (install_loader
-- copies src/loader/lua/. then overwrites with lib/rsmm.lua), so the spec has
-- to put them BOTH on the path or every `require "rsmm.<submodule>"` misses
-- and R.health / R.config / R.i18n / R.api / R.schedule silently come back nil.
package.path = LIB .. "/?.lua;" .. LIB .. "/../lua/?.lua;" .. package.path

-- ---------------------------------------------------------------------------
-- byte-addressed little-endian fake memory
-- ---------------------------------------------------------------------------
local mem = {}                    -- addr(int) -> byte(0..255)

local function wbytes(addr, s)
    for i = 1, #s do mem[addr + i - 1] = s:byte(i) end
end
local function rbytes(addr, n)
    local t = {}
    for i = 0, n - 1 do t[i + 1] = string.char(mem[addr + i] or 0) end
    return table.concat(t)
end
local function wint(addr, val, n) wbytes(addr, string.pack("<I" .. n, val & (n == 8 and -1 or ((1 << (8 * n)) - 1)))) end
local function rint(addr, n)       return (string.unpack("<I" .. n, rbytes(addr, n))) end

-- ---------------------------------------------------------------------------
-- engine-call emulator: models just enough of the entity value store
-- ---------------------------------------------------------------------------
local HERO   = 0x10000000          -- fake hero character pointer
local STORE  = 0x20000000          -- fake value store
local MIRROR = 0x30000000          -- HUD HP mirror
local VALCTX_OFF, STORE_OFF = 0x2f8, 0x4c8
local OVR_DATA_OFF, OVR_COUNT_OFF, OVR_STRIDE = 0xc0, 0xc8, 0x38
local HP_OFF, MAXHP_OFF, HUDMIRROR_OFF, HASHMAP_OFF = 0x15c8, 0x15cc, 0x1d80, 0x80

-- XP component wiring (matches rsmm.lua constants)
local ENTITY   = 0x11000000        -- fake entity (hero+0x2f8 dereferences here)
local XPCOMP   = 0x12000000        -- fake XpComponent
local XPPROG   = 0x13000000        -- {level u32@0, xp u32@4}
local XPMAX    = 0x13f00000        -- max-level object (comp+0x70 -> [+8] = max)
-- Must track rsmm.lua's XP_VFTABLE_VA (corrected 2026-07-18: the old
-- 0x140f23200 was mid-vtable, not a vtable start).
local XP_VFTABLE_VA = 0x140f231b0
local XP_TESTER_VA  = 0x141476e00  -- XpComponent_TypeTester data global
local XP_SUBCLASS_VFT = 0x140f99990 -- a subclass vftable the exact scan can't match
local XP_ARR_OFF, XP_ARR_COUNT_OFF, XP_OWNER_OFF, XP_PROGRESS_OFF = 0x190, 0x198, 0x08, 0x108
local XP_GAIN_AMOUNT_OFF = 0x50

-- give pool wiring
local POOL_PTR_VA = 0x14143cc18    -- *(this) = pool vector
local POOL_VEC = 0x21000000        -- 8-aligned, ptr-plausible

-- Locate the override entry for `key` in the store's override vector, or nil.
local function ovr_entry(key)
    local data  = rint(STORE + OVR_DATA_OFF, 8)
    local count = rint(STORE + OVR_COUNT_OFF, 4)
    if data == 0 then return nil end
    for i = 0, count - 1 do
        local e = data + i * OVR_STRIDE
        if rint(e, 4) == key then return e end
    end
    return nil
end

-- Named engine functions rsmm.lua's R.stat path calls (dispatched by name).
local engine = {}
local heap = 0x50000000
local function scratch(sz)
    local a = heap; heap = heap + sz + 16
    for i = 0, sz - 1 do mem[a + i] = 0 end
    return a
end

engine["EntityValue_Get"] = function(valctx, out, key)
    -- Engine semantics (FUN_1403c7fa0): store = *(valctx+0x4c8). The caller
    -- must pass the LOADED context pointer *(hero+0x2f8) — passing the field
    -- address hero+0x2f8 instead reads a garbage store and faults in the real
    -- engine (the 2026-07-15 in-run crash). Model that hard requirement: any
    -- valctx whose store slot doesn't hold the seeded store raises, which the
    -- SDK's pcall turns into a nil read — so a wrong-arg regression makes the
    -- round-trip tests fail loudly instead of silently passing.
    local store = rint(valctx + STORE_OFF, 8)
    if store ~= STORE then
        error(string.format("EntityValue_Get: bad value-context 0x%x (store slot 0x%x)",
                            valctx, store))
    end
    -- override entry wins over base; report inline union at out+0x08/+0x10/+0x18
    local e = ovr_entry(key)
    if e then
        local u = e + 0x08
        wint(out + 0x08, rint(u + 0x08, 4), 4)  -- inline sentinel
        wbytes(out + 0x10, rbytes(u + 0x10, 4)) -- value bytes
        wint(out + 0x18, 0, 1)
    else
        wint(out + 0x08, 0, 4)                  -- no value: non-inline
    end
    return out
end

engine["EntityValueOverride_Alloc"] = function(vecPtr, count, n)
    local data = rint(vecPtr, 8)
    if data == 0 then
        data = scratch(OVR_STRIDE * 64)
        wint(vecPtr, data, 8)
    end
    wint(vecPtr + 8, count + n, 4)              -- store count is vec+8 (= STORE+0xc8)
    return data + count * OVR_STRIDE
end

engine["EntityValueUnion_DefaultCtor"] = function(u)
    -- Real ctor: vftable + inline sentinel 4 + default tag 10 (0x0a).
    wint(u + 0x08, 4, 8)
    wint(u + 0x18, 10, 2)
    return u
end
engine["EntityValueUnion_Destruct"] = function(u) return u end
engine["EntityValueUnion_InitAsType"] = function(u, t)
    -- Re-init as numeric: keep inline sentinel, tag byte = type (0 = number).
    wint(u + 0x08, 4, 8)
    wint(u + 0x18, t & 0xff, 1)
    return u
end

-- Models EntityValueStore_ApplyModifierEvent (FUN_14074b2f0): validates the
-- forged oCGameEventNetworkModifier the SDK builds, then folds the amount
-- additively into the key's override entry (a stand-in for the modifier
-- registry + recompute — enough to prove the event reaches the engine intact).
local MODEV_VFT = 0x140f322d0
engine["EntityValueStore_ApplyModifierEvent"] = function(store, ev)
    if store ~= STORE then
        error(string.format("ApplyModifierEvent: bad store 0x%x", store))
    end
    -- The engine dereferences the event's vtable and union unguarded — hold
    -- the SDK to the exact layout.
    local vft = rint(ev + 0x00, 8)
    if vft ~= MODEV_VFT then
        error(string.format("ApplyModifierEvent: bad vftable 0x%x", vft))
    end
    assert(rint(ev + 0x08, 4) == 0, "event state must be 0 (ready)")
    assert(rint(ev + 0x38, 8) == 0xffffffffffffffff, "fresh modifier id must be -1")
    assert(rint(ev + 0x68, 8) == 4, "union must be inline (sentinel 4)")
    assert(rint(ev + 0x78, 1) == 0, "union tag must be numeric (0)")
    local key = rint(ev + 0x54, 4)
    local amount = (string.unpack("<f", rbytes(ev + 0x70, 4)))
    local e = ovr_entry(key)
    if not e then
        local data = rint(STORE + OVR_DATA_OFF, 8)
        local count = rint(STORE + OVR_COUNT_OFF, 4)
        if data == 0 then
            data = scratch(OVR_STRIDE * 64)
            wint(STORE + OVR_DATA_OFF, data, 8)
        end
        e = data + count * OVR_STRIDE
        wint(STORE + OVR_COUNT_OFF, count + 1, 4)
        wint(e, key, 4)
        wint(e + 0x08 + 0x08, 4, 8)                 -- inline union
        wbytes(e + 0x08 + 0x10, string.pack("<f", 0.0))
    end
    local cur = (string.unpack("<f", rbytes(e + 0x08 + 0x10, 4)))
    wbytes(e + 0x08 + 0x10, string.pack("<f", cur + amount))
    return nil
end

-- Apply a raw HP delta to the hero character (models Entity_ModifyHealth).
engine["Entity_ModifyHealth"] = function(e, delta, _ctx)
    local hp = (string.unpack("<f", rbytes(e + HP_OFF, 4))) + delta
    wbytes(e + HP_OFF, string.pack("<f", hp))
    return 0
end

-- Models Entity_GetComponentByTester (FUN_1406e3210): walks the entity
-- component array (entity+0x190, count +0x198) and returns the first
-- component whose class IsKindOf the tester's type. IsKindOf resolves
-- inheritance, so unlike rsmm.lua's exact-vftable scan it also matches a
-- SUBCLASS vftable — model that with a two-vftable accept set. Raises on a
-- wrong tester so a bad rebase fails the test loudly.
engine["Entity_GetComponentByTester"] = function(entity, tester)
    if tester ~= XP_TESTER_VA then
        error(string.format("GetComponentByTester: bad tester 0x%x", tester))
    end
    local arr   = rint(entity + XP_ARR_OFF, 8)
    local count = rint(entity + XP_ARR_COUNT_OFF, 4)
    if arr == 0 then return 0 end
    for i = 0, count - 1 do
        local comp = rint(arr + i * 8, 8)
        local vft  = comp ~= 0 and rint(comp, 8) or 0
        if vft == XP_VFTABLE_VA or vft == XP_SUBCLASS_VFT then return comp end
    end
    return 0
end

-- The three XP-curve routines all operate on the LAST node of the component's
-- +0x110 next-link chain (disasm-verified 2026-07-19).
local function xp_chain_last(comp)
    local nxt = rint(comp + 0x110, 8)
    while nxt ~= 0 do comp = nxt; nxt = rint(comp + 0x110, 8) end
    return comp
end

-- Models FUN_1402e2d30: max level from the +0x70 object ([+8]), clamped >= 1.
-- The +0x68 inline-data fallback is not modeled — an unconfigured component
-- reads 0 and clamps to 1, which is exactly the retail no-op trap.
engine["XpComponent_GetMaxLevel"] = function(comp)
    comp = xp_chain_last(comp)
    local obj = rint(comp + 0x70, 8)
    local m = obj ~= 0 and rint(obj + 8, 4) or 0
    return m < 1 and 1 or m
end

-- Models FUN_1402e2d90 (the Hero_GainExperience gate): chain-last level >=
-- max level. The engine returns via `setae al`, leaving whatever was in the
-- upper bytes of eax — model that garbage so a caller that forgets to mask
-- the low byte fails the spec.
engine["XpComponent_IsMaxLevel"] = function(comp)
    comp = xp_chain_last(comp)
    local prog = rint(comp + XP_PROGRESS_OFF, 8)
    local at_max = rint(prog, 4) >= engine["XpComponent_GetMaxLevel"](comp) and 1 or 0
    return 0xa5a5a500 | at_max
end

-- Models FUN_1402e2c30: threshold table at *(node+0x10)+0x1d8 (enable flag
-- +0x1d0, count +0x1e0); level <= count -> table[level-1], else the last
-- entry, else 0xffffffff.
engine["XpComponent_XpForLevel"] = function(comp, level)
    local cfg = rint(xp_chain_last(comp) + 0x10, 8)
    if cfg == 0 then return 0xffffffff end
    local count = rint(cfg + 0x1e0, 4)
    local arr = rint(cfg + 0x1d8, 8)
    if rint(cfg + 0x1d0, 1) ~= 0 and level >= 1 and level <= count then
        return rint(arr + (level - 1) * 4, 4)
    end
    if count > 0 then return rint(arr + (count - 1) * 4, 4) end
    return 0xffffffff
end

-- Add XP to the component's progress block (models Hero_GainExperience: it reads
-- only *(int*)(gain+0x50); our emulator credits xp so the call path is
-- exercised end-to-end). Faithful to the retail gate: at max level the grant
-- is dropped without a trace — the exact silent no-op grant() must pre-flight.
engine["Hero_GainExperience"] = function(comp, gain)
    if (engine["XpComponent_IsMaxLevel"](comp) & 0xff) ~= 0 then return 0 end
    local amount = rint(gain + XP_GAIN_AMOUNT_OFF, 4)
    local prog = rint(comp + XP_PROGRESS_OFF, 8)
    wint(prog + 4, rint(prog + 4, 4) + amount, 4)
    return 0
end

-- ---------------------------------------------------------------------------
-- mock native bindings (the `rsmm` global rsmm.lua reads at load)
-- ---------------------------------------------------------------------------
local shared  = {}
local events  = {}                 -- event name -> { cb, ... }
local hooks = {}                   -- va -> {sig, cb} installed via rsmm.hook
local resolved = {}                -- pattern -> fake va ; and reverse (va -> pattern)
local resolve_n = 0                -- monotonic counter for unique fake VAs

local I = {}
function I.read_u8(a)  return rint(a, 1) end
function I.read_u16(a) return rint(a, 2) end
function I.read_u32(a) return rint(a, 4) end
function I.read_u64(a) return rint(a, 8) end
function I.read_f32(a) return (string.unpack("<f", rbytes(a, 4))) end
-- Faithful to mem_read_cstr: stops at the NUL, and at `max`. Unmapped fake
-- memory reads as 0, so a pointer into nothing yields "" rather than garbage —
-- the same "miss, not a fault" the page-guarded native read gives.
function I.read_cstr(a, max)
    local out = {}
    for i = 0, (max or 256) - 1 do
        local b = mem[a + i]
        if b == nil or b == 0 then break end
        out[#out + 1] = string.char(b)
    end
    return table.concat(out)
end
function I.write_u8(a, v)  wint(a, v & 0xff, 1) end
function I.write_u16(a, v) wint(a, v & 0xffff, 2) end
function I.write_u32(a, v) wint(a, v & 0xffffffff, 4) end
function I.write_u64(a, v) wbytes(a, string.pack("<I8", v)) end
function I.write_f32(a, v) wbytes(a, string.pack("<f", v)) end
function I.poke(a, v, n) wbytes(a, string.pack("<I" .. (n or 8), v)) end
function I.scratch(sz) return scratch(sz) end
function I.module_base() return 0x140000000 end
local va_trusted_val = true
function I.va_trusted() return va_trusted_val end
function I.is_grant_target() return true end
local steam_persona = "Ovilli"
function I.steam_name(id)
    if id then return nil end          -- Steam rarely knows a remote account
    return steam_persona
end
function I.shared_get(slot) return shared[slot] end
-- Faithful to lua_shared_set: slots 8..15 are the native hero-candidate ring
-- and REFUSE a Lua write. The mock accepted them, so a probe latch that took
-- slot 9 passed 628 assertions here and then silently evicted hero spawn
-- candidates in-game — `hero CAPTURED` simply stopped happening, with nothing
-- in the log tying it to the probe.
function I.shared_set(slot, v)
    assert(slot < 8, ("rsmm.shared_set: slot %d is the native hero ring (8..15) "
        .. "and is read-only from Lua"):format(slot))
    shared[slot] = v
end
function I.list_mods() return {} end
local hook_report_rows = {
    { tag = "hero-capture", what = "give handler", va = 0x140abc000, fires = 12 },
    { tag = "spawn-trace",  what = "selector prepare", va = 0x140def000, fires = 0 },
}
function I.hook_report() return hook_report_rows end
local in_main_menu = false
function I.is_in_main_menu() return in_main_menu end
function I.resolve(pat)
    local va = resolved[pat]
    if not va then
        resolve_n = resolve_n + 1
        va = 0x140000000 + resolve_n * 0x100
        resolved[pat] = va; resolved[va] = pat
    end
    return va
end
function I.call(va, _sig, ...)
    local name = resolved[va]
    local fn = name and engine[name]
    if fn then return fn(...) end
    return nil
end

-- Bindings the modular submodules (rsmm/*.lua) depend on. Before these
-- existed natively, R.api namespaced every mod as "?", R.schedule fell back to
-- one-second os.time() resolution, and R.health / R.i18n were pure no-ops.
function I.self_id() return "spec_mod" end

local fake_clock = 1000.0
function I.now() return fake_clock end

local i18n_strings = { greet = "Hello {name}", plain = "no vars" }
function I.i18n_table() return i18n_strings end
function I.i18n_locale() return "EN" end

local health_state = { crashes = { badmod = 2 }, errors = { badmod = "boom" },
                       disabled = {}, checkpoints = {} }
function I.health_count(id) return health_state.crashes[id] or 0 end
function I.health_last_error(id) return health_state.errors[id] end
function I.health_disable(id, reason) health_state.disabled[id] = reason or "" end
function I.health_checkpoint(step) table.insert(health_state.checkpoints, step) end

-- Cross-state API bridge. The real one marshals JSON between lua_States; here
-- one process-wide registry stands in, which is enough to pin the CONTRACT:
-- data-only arguments, provider errors surfacing as (false, msg).
local api_reg = {}   -- name -> { mod_id, version, table }
function I.api_expose(name, version, tbl)
    local prev = api_reg[name]
    if prev and prev.mod_id ~= I.self_id() then
        error("rsmm.api: '" .. name .. "' is already exposed by mod '" .. prev.mod_id .. "'")
    end
    api_reg[name] = { mod_id = I.self_id(), version = version, table = tbl }
    return true
end
function I.api_info(name)
    local e = api_reg[name]
    if not e then return nil end
    return e.mod_id, e.version
end
function I.api_list()
    local out = {}
    for n, e in pairs(api_reg) do out[n] = { mod_id = e.mod_id, version = e.version } end
    return out
end
function I.api_call(name, key, ...)
    local e = api_reg[name]
    if not e then return false, "rsmm.api: '" .. name .. "' is not exposed" end
    local v = e.table[key]
    if type(v) ~= "function" then return v ~= nil, v end
    local ok, res = pcall(v, ...)
    return ok, res
end

rsmm = {
    _internal = I,
    log = function() end,
    on_event = function(ev, cb) events[ev] = events[ev] or {}; table.insert(events[ev], cb) end,
    mod_dir = function() return "." end,
    -- Record installed hooks so a spec can simulate the hooked function
    -- firing. Returning a slot id keeps the existing arm paths happy.
    hook = function(va, sig, cb)
        hooks[va] = { sig = sig, cb = cb }
        return 1
    end,
    unhook = function() end,
    -- Mirrors the native emit: reserved names refused, provenance stamped by
    -- the loader (never by the caller), then dispatched to every subscriber.
    emit = function(name, payload)
        for _, p in ipairs({ "gameplay:", "ui:", "rsmm:" }) do
            if name:sub(1, #p) == p then error("rsmm.emit: '" .. name .. "' is reserved") end
        end
        for _, e in ipairs({ "setup", "ready", "tick", "exit", "*" }) do
            if name == e then error("rsmm.emit: '" .. name .. "' is a lifecycle event") end
        end
        local ev = {}
        for k, v in pairs(payload or {}) do ev[k] = v end
        ev.event, ev.source, ev.from = name, "mod", "spec_mod"
        _G.__spec_fire(name, ev)
        return true
    end,
}

-- Fire an event to every matching subscriber (exact name + "*" wildcard).
local function fire(name, payload)
    payload = payload or {}
    for _, cb in ipairs(events[name] or {}) do cb(payload, name) end
    for _, cb in ipairs(events["*"] or {}) do cb(payload, name) end
end
-- The mocked native emit dispatches through the same path.
_G.__spec_fire = fire

-- Make R.entity.hero() succeed: publish a plausible hero + wire the store.
-- Pointer chain matches the engine (FUN_140399d00): ctx = *(hero+0x2f8) is a
-- LOADED pointer (ENTITY doubles as the value context), store = *(ctx+0x4c8).
local function seed_hero()
    shared[0] = HERO                              -- native capture slot
    shared[2] = 1                                 -- native capture active
    I.write_f32(HERO + MAXHP_OFF, 100.0)
    I.write_f32(HERO + HP_OFF, 80.0)
    I.write_u64(HERO + HUDMIRROR_OFF, MIRROR)
    I.write_f32(MIRROR, 80.0)
    I.write_u64(HERO + VALCTX_OFF, ENTITY)              -- *(hero+0x2f8) = ctx
    I.write_u64(ENTITY + STORE_OFF, STORE)              -- *(ctx+0x4c8)  = store
    I.write_u32(STORE + OVR_COUNT_OFF, 0)
    I.write_u64(STORE + HASHMAP_OFF, 0x40000000)        -- non-null base map
    I.write_u64(STORE + OVR_DATA_OFF, 0)
end

-- Wire the hero's XP component: entity[0x190] -> [comp], comp identified by its
-- vftable + owner back-ptr, progress block at comp+0x108.
local function seed_xp(level, xp)
    I.write_u64(HERO + VALCTX_OFF, ENTITY)              -- *(hero+0x2f8) = entity
    I.write_u64(ENTITY + XP_ARR_OFF, 0x14000000)        -- component ptr array
    I.write_u32(ENTITY + XP_ARR_COUNT_OFF, 1)
    I.write_u64(0x14000000, XPCOMP)                     -- arr[0] = comp
    I.write_u64(XPCOMP, XP_VFTABLE_VA)                  -- *(comp) == vftable
    I.write_u64(XPCOMP + XP_OWNER_OFF, ENTITY)          -- owner back-ptr
    I.write_u64(XPCOMP + XP_PROGRESS_OFF, XPPROG)
    I.write_u32(XPPROG + 0, level)
    I.write_u32(XPPROG + 4, xp)
    I.write_u64(XPCOMP + 0x70, XPMAX)                   -- max-level object
    I.write_u32(XPMAX + 8, 10)                          -- retail curve: max > level
end

-- Wire a magical-object pool of `n` defs; def i has GUID (0xA000+i, 0xB000+i).
local function seed_pool(n)
    I.write_u64(POOL_PTR_VA, POOL_VEC)                  -- *(pool va) = vec
    local data = 0x22000000
    I.write_u64(POOL_VEC + 0, data)
    I.write_u32(POOL_VEC + 8, n)
    for i = 0, n - 1 do
        local def = 0x23000000 + i * 0x100
        I.write_u64(data + i * 8, def)
        I.write_u64(def + 0x88, 0xA000 + i)
        I.write_u64(def + 0x90, 0xB000 + i)
    end
end

-- ---------------------------------------------------------------------------
-- load the SDK under test
-- ---------------------------------------------------------------------------
local chunk = assert(loadfile(LIB .. "/rsmm.lua"))

-- Load it under the REAL sandbox. script_lua.cpp::apply_sandbox() strips these
-- globals from every mod state, and plain `lua rsmm_spec.lua` has all of them,
-- so the spec used to be strictly more permissive than the game. On 2026-08-16
-- a build stamp using `debug.getinfo` + `io.open` passed 628 assertions here
-- and then raised at load in-game, taking damage-meter (and every other mod)
-- with it. Nil them for the duration of the load so that gap cannot reopen.
local SANDBOXED = { "debug", "io", "load", "loadfile", "dofile", "collectgarbage" }
local _saved = {}
for _, g in ipairs(SANDBOXED) do _saved[g] = _G[g]; _G[g] = nil end
local ok_load, R = pcall(chunk)
for _, g in ipairs(SANDBOXED) do _G[g] = _saved[g] end
assert(ok_load, "rsmm.lua raised under the loader sandbox: " .. tostring(R))
assert(type(R) == "table", "rsmm.lua did not return the R table")

-- ---------------------------------------------------------------------------
-- tiny test runner
-- ---------------------------------------------------------------------------
local passed, failed = 0, 0
local function check(cond, msg)
    if cond then passed = passed + 1
    else failed = failed + 1; io.write("  FAIL: " .. tostring(msg) .. "\n") end
end
local function about(a, b) return math.abs(a - b) < 1e-3 end

-- 1. stat catalog integrity ------------------------------------------------
do
    -- Two per-slot families share their base key with the hero-wide stat: the
    -- registry's crit / cooldown families START at the hero-wide key, so
    -- `<stat>_primary` is genuinely the same id. attack_power does NOT alias.
    local allowed_alias = {
        crit_chance_primary        = "crit_chance",
        cooldown_reduction_primary = "cooldown_reduction",
    }
    local seen = {}
    for name, spec in pairs(R.stat.keys) do
        check(type(spec.key) == "number", "key not number: " .. name)
        check(spec.kind == "f32" or spec.kind == "int", "bad kind: " .. name)
        local prev = seen[spec.key]
        local ok = prev == nil or allowed_alias[name] == prev or allowed_alias[prev] == name
        check(ok, "duplicate key 0x" .. string.format("%x", spec.key)
            .. " (" .. name .. " vs " .. tostring(prev) .. ")")
        seen[spec.key] = prev or name
    end
    check(R.stat.keys.attack_power.key ~= R.stat.keys.attack_power_primary.key,
          "attack_power must NOT alias its per-slot family base")
    local names = R.stat.names()
    check(#names >= 10, "catalog suspiciously small")
    for i = 2, #names do check(names[i - 1] <= names[i], "names() not sorted") end
end

-- 1b. per-slot + status keys -----------------------------------------------
do
    local fam = { attack_power = 0x15a5cf40, crit_chance = 0x15c7d482,
                  cooldown_reduction = 0x15b45d80 }
    local order = { "primary", "secondary", "defensive", "trait", "ultimate" }
    for family, base in pairs(fam) do
        for i, slot in ipairs(order) do
            local spec = R.stat.keys[family .. "_" .. slot]
            check(spec ~= nil, "missing " .. family .. "_" .. slot)
            check(spec and spec.key == base + 2 * (i - 1),
                  family .. "_" .. slot .. " wrong key")
            check(spec and spec.kind == "f32", family .. "_" .. slot .. " should be f32")
        end
    end
    check(R.stat.keys.attack_power_basic.key == 0x15a5cf51, "attack_power_basic key")
    check(R.stat.keys.attack_power_dash.key == 0x183a609a, "attack_power_dash key")
    check(R.stat.keys.crit_chance_dash.key == 0x183a60b6, "crit_chance_dash key")
    check(R.stat.keys.cooldown_reduction_dash.key == 0x183a5fc9, "cooldown_reduction_dash key")
    check((R.stat.keys.attack_power_basic.key - 0x15a5cf40) % 2 == 1,
          "basic is off-parity, so it cannot be a 2*slot member")

    local st = { "strength", "regen", "haste", "concealed", "resistant",
                 "rooted", "vulnerable", "ignite", "chilled", "poison" }
    for i, n in ipairs(st) do
        local spec = R.stat.keys["status_" .. n]
        check(spec ~= nil, "missing status_" .. n)
        check(spec and spec.key == 0x16ede056 + 2 * (i - 1), "status_" .. n .. " wrong key")
        check(spec and spec.kind == "int", "status_" .. n .. " should be int")
    end
    for _, n in ipairs({ "shield", "bleed", "cursed", "marked" }) do
        check(R.stat.keys["status_" .. n] ~= nil, "missing status_" .. n)
    end

    check(R.stat.key("attack_power", "trait").key == 0x15a5cf46, "key() by slot name")
    check(R.stat.key("attack_power", 3).key == 0x15a5cf46, "key() by slot index")
    check(R.stat.key("attack_power") == R.stat.keys.attack_power, "key() with no slot")
    check(R.stat.key("attack_power", "nope") == nil, "key() unknown slot name -> nil")
    check(R.stat.key("attack_power", 99) == nil, "key() unknown slot index -> nil")
    check(R.stat.key("no_such_stat", "trait") == nil, "key() unknown stat -> nil")

    local names, found = R.stat.names(), {}
    for _, n in ipairs(names) do found[n] = true end
    check(found.attack_power_ultimate, "names() lists per-slot entries")
    check(found.status_poison, "names() lists status entries")
end

-- 2. writes are gated off by default ---------------------------------------
do
    seed_hero()
    check(R.stat.set("attack_power", 42) == false, "set must fail before enable_writes()")
end

-- 3. set / get round-trip through the override cache -----------------------
do
    R.stat.enable_writes()
    check(R.stat.set("attack_power", 500) == true, "set should succeed once enabled")
    check(about(R.stat.get("attack_power"), 500), "get should read back the set value")
end

-- 4. unknown stat names are rejected ---------------------------------------
do
    check(R.stat.set("not_a_stat", 1) == false, "unknown set must fail")
    check(R.stat.stick("not_a_stat", 1) == false, "unknown stick must fail")
end

-- 4b. native modifier: R.stat.modify builds a valid engine event ------------
do
    -- Seed the modifier-event vftable: slot 0 must point into the module
    -- (R.stat.modify probes it before forging the event).
    I.write_u64(MODEV_VFT, 0x140001000)

    check(R.stat.modify("attack_power", 25) == true, "modify should apply")
    check(about(R.stat.get("attack_power"), 525), "modifier folds additively (+25)")
    check(R.stat.modify("attack_power", -100) == true, "negative modify should apply")
    check(about(R.stat.get("attack_power"), 425), "modifier folds additively (-100)")
    check(R.stat.modify("not_a_stat", 1) == false, "unknown modify must fail")
    check(R.stat.modify("attack_power", "x") == false, "non-number amount must fail")

    -- int-kind stat rides the same union inline slot.
    check(R.stat.modify("dream_shards", 100) == true, "int-kind modify should apply")

    -- A garbage vftable slot (wrong build) must refuse before touching engine.
    I.write_u64(MODEV_VFT, 0)
    check(R.stat.modify("attack_power", 1) == false, "implausible vftable must refuse")
    I.write_u64(MODEV_VFT, 0x140001000)

    -- Restore the value later sections assert on.
    R.stat.set("attack_power", 500)
end

-- 5. durable stick: survives a recompute clobber ---------------------------
do
    check(R.stat.stick("move_speed", 2.5) == true, "stick should apply immediately")
    check(about(R.stat.get("move_speed"), 2.5), "stick value should be live")

    -- Simulate the engine recompute overwriting the override entry with base.
    local e = ovr_entry(0x044dadde)              -- move_speed key
    assert(e, "expected an override entry for move_speed")
    I.write_f32(e + 0x08 + 0x10, 1.0)            -- clobber union value -> base
    check(about(R.stat.get("move_speed"), 1.0), "clobber should be visible pre-reassert")

    -- A gameplay-bus event must re-assert the pinned value (drift-gated).
    fire("*", { source = "gameplay" })
    check(about(R.stat.get("move_speed"), 2.5), "stick must re-assert after clobber")

    -- A NON-gameplay (background) event must NOT trigger engine-mutating writes.
    I.write_f32(e + 0x08 + 0x10, 1.0)            -- clobber again
    fire("tick", { source = "loader" })
    check(about(R.stat.get("move_speed"), 1.0), "reassert must not run off the main thread")
end

-- 6. sticky() snapshot + unstick -------------------------------------------
do
    local snap = R.stat.sticky()
    check(snap.move_speed ~= nil, "sticky() should list pinned stats")
    snap.move_speed = 999                        -- mutate the copy
    check(R.stat.sticky().move_speed ~= 999, "sticky() must return an independent copy")
    check(R.stat.unstick("move_speed") == true, "unstick should report it was pinned")
    check(R.stat.unstick("move_speed") == false, "double unstick should report false")

    -- After unstick, a clobber is no longer re-asserted.
    local e = ovr_entry(0x044dadde)
    I.write_f32(e + 0x08 + 0x10, 1.0)
    fire("*", { source = "gameplay" })
    check(about(R.stat.get("move_speed"), 1.0), "unpinned stat must not be re-asserted")
end

-- 7. R.entity / R.combat: HP read + modify ---------------------------------
do
    check(about(R.entity.hp(), 80), "entity.hp reads the HP field")
    check(about(R.entity.max_hp(), 100), "entity.max_hp reads max")
    check(about(R.entity.hp_frac(), 0.8), "hp_frac = hp/max")
    check(R.combat.heal(15) == true, "heal should dispatch")
    check(about(R.entity.hp(), 95), "heal applies +15")
    check(R.combat.damage(35) == true, "damage should dispatch")
    check(about(R.entity.hp(), 60), "damage applies -35")
    check(R.combat.set_hp(50) == true, "set_hp should dispatch")
    check(about(R.entity.hp(), 50), "set_hp pins absolute HP")
end

-- 7b. the ctor hook must be armed at `setup`, not on first read -------------
-- Regression guard for session 974f: the level component is constructed once
-- at run start, so a hook installed lazily (on the first R.xp read, ~61s in)
-- is not merely late — it is guaranteed to miss. Asserted here, before any
-- section has called R.xp, so a lazy arm cannot make it pass by accident.
do
    local ctor_va = I.resolve("GroupLevelComponent_Ctor")
    check(hooks[ctor_va] == nil, "nothing has armed the ctor hook yet")
    fire("setup", {})
    check(hooks[ctor_va] ~= nil,
          "setup arms the ctor hook without anything having read xp")
    check(hooks[ctor_va].sig == "pp", "armed with the void*(void*) signature")
end

-- 8. R.xp: level / xp read + grant -----------------------------------------
do
    seed_xp(3, 120)
    check(R.xp.level() == 3, "xp.level reads the progress block")
    check(R.xp.xp() == 120, "xp.xp reads xp-within-level")
    check(R.xp.grant(0) == false, "grant of 0 is a no-op")
    check(R.xp.grant(50) == true, "grant should fire Hero_GainExperience")
    check(R.xp.xp() == 170, "grant credits xp through the engine call")
end

-- 8b. R.xp: engine-tester fallback when the component is a subclass ---------
-- The 2026-07-16 playtest kept reporting "XP component not found": the live
-- component's vftable isn't XpComponent's own, so the exact-vftable scan
-- misses. grant() (main thread) falls back to the engine's
-- Entity_GetComponentByTester, whose IsKindOf resolves subclasses, and caches
-- the hit so the tick-thread readers work afterwards without engine calls.
do
    local HERO2, ENTITY2 = 0x10800000, 0x11800000
    local XPCOMP2, XPPROG2, ARR2, MIRROR2 = 0x12800000, 0x13800000, 0x14800000, 0x30800000
    -- plausible hero + value wiring (reuse the seeded STORE)
    shared[0] = HERO2; shared[2] = 1
    I.write_f32(HERO2 + MAXHP_OFF, 100.0)
    I.write_f32(HERO2 + HP_OFF, 80.0)
    I.write_u64(HERO2 + HUDMIRROR_OFF, MIRROR2)
    I.write_f32(MIRROR2, 80.0)
    I.write_u64(HERO2 + VALCTX_OFF, ENTITY2)
    I.write_u64(ENTITY2 + STORE_OFF, STORE)
    -- XP component with a SUBCLASS vftable — invisible to the exact scan
    I.write_u64(ENTITY2 + XP_ARR_OFF, ARR2)
    I.write_u32(ENTITY2 + XP_ARR_COUNT_OFF, 1)
    I.write_u64(ARR2, XPCOMP2)
    I.write_u64(XPCOMP2, XP_SUBCLASS_VFT)
    I.write_u64(XPCOMP2 + XP_OWNER_OFF, ENTITY2)
    I.write_u64(XPCOMP2 + XP_PROGRESS_OFF, XPPROG2)
    I.write_u32(XPPROG2 + 0, 5)
    I.write_u32(XPPROG2 + 4, 200)
    I.write_u64(XPCOMP2 + 0x70, XPMAX)                  -- max level 10 > level 5
    -- the tester data global must hold a plausible vftable pointer
    I.write_u64(XP_TESTER_VA, 0x140f10000)

    check(R.xp.xp() == nil, "scan-only read path can't see a subclass component (by design)")
    check(R.xp.grant(25) == true, "grant finds the subclass via Entity_GetComponentByTester")
    check(R.xp.xp() == 225, "engine hit is cached — tick-thread reads now work")
    check(R.xp.level() == 5, "level reads through the cached component")

    shared[0] = HERO                                    -- restore for later sections
end

-- 8c. R.xp: constructor capture — the component is NOT on the hero ---------
-- Five playtests scanned the hero's component array; the 2026-07-19 run
-- settled it (absent from all 227 components of all 3 probed owners). Exactly
-- one oCDtEntityCpntGroupLevel is authored in the whole corpus, on
-- Group_Scaling.entity.ot, so no hero walk can ever reach it. R.xp therefore
-- detours the component's CONSTRUCTOR and keeps `this`.
do
    local BARE_HERO = 0x18800000               -- a hero with no XP component
    local GLCOMP, GLPROG, MIRROR3 = 0x19800000, 0x1a800000, 0x31800000
    shared[0] = BARE_HERO; shared[2] = 1
    I.write_f32(BARE_HERO + MAXHP_OFF, 100.0)
    I.write_f32(BARE_HERO + HP_OFF, 90.0)
    I.write_u64(BARE_HERO + HUDMIRROR_OFF, MIRROR3)
    I.write_f32(MIRROR3, 90.0)
    I.write_u64(BARE_HERO + VALCTX_OFF, 0)     -- no value ctx => no component array

    check(R.xp.level() == nil, "no component reachable from the hero (the real situation)")

    -- TIMING IS THE WHOLE BUG. Session 974f resolved and installed this hook
    -- correctly but lazily, on the first R.xp read — 61s after the run had
    -- already built the component, so the ctor could never fire again. The
    -- hook must therefore be armed by `setup`, BEFORE anything reads xp.
    local ctor_va = I.resolve("GroupLevelComponent_Ctor")
    check(hooks[ctor_va] ~= nil, "ctor hook is installed")
    check(hooks[ctor_va].sig == "pp", "signature is void*(void*) — one ptr arg, no floats")

    -- The engine constructs the component. The callback runs BEFORE the
    -- original, so at this instant the object is raw memory.
    check(hooks[ctor_va].cb(GLCOMP) == nil, "callback returns nil so the ctor runs exactly once")
    check(R.xp.level() == nil, "an unconstructed object is NOT promoted")

    -- Now the original ctor body runs: vftable at +0, progress block at +0x108.
    I.write_u64(GLCOMP, XP_VFTABLE_VA)
    I.write_u64(GLCOMP + XP_PROGRESS_OFF, GLPROG)
    I.write_u32(GLPROG + 0, 7)
    I.write_u32(GLPROG + 4, 340)

    check(R.xp.level() == 7, "captured component is promoted on the next read")
    check(R.xp.xp() == 340, "xp reads through the captured component")

    -- The retail trap (2026-07-19 playtest): the captured component had no
    -- max-level config, so GetMaxLevel clamps to 1, the gate says "at max"
    -- for a level-7 party, and Hero_GainExperience dropped the 200-xp grant
    -- without a trace while grant() logged success. grant() must pre-flight
    -- the gate and refuse loudly instead.
    check(R.xp.grant(100) == false, "grant refuses when the engine gate would drop it")
    check(R.xp.xp() == 340, "refused grant leaves xp untouched")

    -- With a real max level configured the same grant lands.
    local GLMAX = 0x1b800000
    I.write_u64(GLCOMP + 0x70, GLMAX)
    I.write_u32(GLMAX + 8, 20)
    check(R.xp.grant(100) == true, "grant lands once a level curve exists")
    check(R.xp.xp() == 440, "granted xp is credited through the engine call")

    -- A torn-down entity must not keep serving stale numbers.
    I.write_u64(GLCOMP, 0)
    check(R.xp.level() == nil, "capture is dropped once the object stops validating")

    -- 8d. Multiple constructions: session 5f36 proved the ctor can produce a
    -- TEMPLATE instance with no curve config whose level/xp never move. When
    -- several instances were constructed, the one with a usable curve must
    -- win even if a curve-less one was constructed more recently.
    local GL_LIVE, GL_LIVE_PROG, GL_LIVE_CFG = 0x1c800000, 0x1d800000, 0x1e800000
    local GL_TMPL, GL_TMPL_PROG = 0x1f800000, 0x20800000
    local ctor_cb = hooks[ctor_va].cb
    ctor_cb(GL_LIVE)
    ctor_cb(GL_TMPL)                                   -- template is NEWER
    for _, pair in ipairs({{GL_LIVE, GL_LIVE_PROG}, {GL_TMPL, GL_TMPL_PROG}}) do
        I.write_u64(pair[1], XP_VFTABLE_VA)
        I.write_u64(pair[1] + XP_PROGRESS_OFF, pair[2])
    end
    I.write_u32(GL_LIVE_PROG + 0, 4)
    I.write_u32(GL_LIVE_PROG + 4, 250)
    I.write_u32(GL_TMPL_PROG + 0, 1)
    I.write_u32(GL_TMPL_PROG + 4, 0)
    -- live instance gets a real curve: cfg flag +0x1d0, count +0x1e0
    I.write_u64(GL_LIVE + 0x10, GL_LIVE_CFG)
    I.write_u8(GL_LIVE_CFG + 0x1d0, 1)
    I.write_u32(GL_LIVE_CFG + 0x1e0, 20)
    check(R.xp.level() == 4, "instance WITH a curve beats a newer curve-less one")
    check(R.xp.xp() == 250, "xp reads through the curve-bearing instance")

    shared[0] = HERO                                    -- restore for later sections
end

-- 9. R.give: pool enumeration math -----------------------------------------
do
    seed_pool(3)
    check(R.give.count() == 3, "give.count reads pool source count")
    local lo, hi = R.give.guid_at(1)
    check(lo == 0xA001 and hi == 0xB001, "guid_at returns the def GUID")
    check(R.give.guid_at(-1) == nil, "guid_at rejects negative index")
    check(R.give.guid_at(3) == nil, "guid_at rejects out-of-range index")
    local seen = 0
    for i, glo, ghi in R.give.each() do
        check(glo == 0xA000 + i and ghi == 0xB000 + i, "each() yields matching GUIDs")
        seen = seen + 1
    end
    check(seen == 3, "each() iterates every loaded item exactly once")
end

-- 9b. R.give validates the dispatcher AT THE CALL ---------------------------
--
-- `_give_hero` is a raw engine pointer captured from an earlier event. A run
-- ending or a character switch frees the hero, and the capture only refreshes
-- when an anchor event happens to fire — so the pointer can be stale by the
-- time a grant is attempted. Native reads are page-guarded, but a pointer
-- handed to an engine call as an ARGUMENT is dereferenced by the engine, which
-- is the loader's #1 crash class.
do
    seed_pool(1)
    -- This block deliberately invalidates the hero capture, which later blocks
    -- rely on. Snapshot the cross-state slots and put them back at the end.
    local saved_shared = {}
    for k, v in pairs(shared) do saved_shared[k] = v end

    -- Capture a dispatcher the normal way: an anchor event with a live object.
    local DISP = scratch(0x40)
    I.write_u64(DISP, 0x140f00000)          -- a vtable inside the image
    fire("gameplay:ABILITY_EXIT", { source = "gameplay",
                                    dispatcher = string.format("0x%x", DISP) })
    check(R.give.ready(), "spec fixture: a live dispatcher is captured")

    -- The grant path builds an event object first; give it one so the test
    -- exercises the dispatcher guard rather than bailing before it.
    engine["NamedEvent_GiveMagicalObject_Ctor"] = function(buf) return buf end

    -- Sanity: with a LIVE dispatcher the grant goes through. Without this the
    -- refusal below could pass for the wrong reason.
    local dispatched = false
    engine["NamedEvent_Dispatch"] = function() dispatched = true end
    check(R.give.by_guid(0xA001, 0xB001) == true, "a live dispatcher grants")
    check(dispatched, "and the engine call is made")

    -- Now make it look dead, the way a freed hero does, and grant again.
    I.write_u64(DISP, 0)                    -- vtable slot no longer an object
    dispatched = false
    local ok = R.give.by_guid(0xA001, 0xB001)

    check(ok == false, "a grant on a dead dispatcher is refused, not attempted")
    check(not dispatched, "and the engine call is never made")
    check(not R.give.ready(), "the stale capture is dropped so it can re-arm")

    -- Re-arm for the blocks that follow: restore the slots and hand the bus a
    -- live dispatcher again.
    for k in pairs(shared) do shared[k] = nil end
    for k, v in pairs(saved_shared) do shared[k] = v end
    I.write_u64(DISP, 0x140f00000)
    fire("gameplay:ABILITY_EXIT", { source = "gameplay",
                                    dispatcher = string.format("0x%x", DISP) })
end

-- 10. fail-closed guards: the safety net that makes engine writes acceptable --
do
    -- (a) symbol-map/build mismatch (va_trusted == false) disables every
    -- va-gated, engine-mutating feature — no stray writes on a wrong build.
    va_trusted_val = false
    check(R.stat.set("attack_power", 1) == false, "stat.set must fail when va untrusted")
    check(R.stat.modify("attack_power", 1) == false, "stat.modify must fail when va untrusted")
    check(R.combat.heal(1) == false, "combat.heal must fail when va untrusted")
    check(R.xp.grant(1) == false, "xp.grant must fail when va untrusted")
    va_trusted_val = true

    -- (b) an implausible hero (garbage max-HP) is rejected: hero() goes nil, so
    -- reads return nil and mutators refuse rather than deref a bad pointer.
    local saved = I.read_f32(HERO + MAXHP_OFF)
    I.write_f32(HERO + MAXHP_OFF, 0.0)                 -- max HP 0 => implausible
    check(R.entity.hero() == nil, "implausible hero must not be captured")
    check(R.entity.hp() == nil, "hp() nil when no valid hero")
    check(R.combat.heal(1) == false, "combat refuses without a plausible hero")
    check(R.stat.set("attack_power", 1) == false, "stat.set refuses without a hero")
    I.write_f32(HERO + MAXHP_OFF, saved)              -- restore
    check(R.entity.hero() ~= nil, "hero recaptured after restore")

    -- (b2) the 2026-07-19 misfire shapes: a DENORMAL max-HP (1.6e-43, u32
    -- bits ~114 — passes a bare `> 0`) and a garbage current HP (7.6e+28)
    -- with max sane. Both must reject.
    I.write_u32(HERO + MAXHP_OFF, 114)                -- denormal float bits
    check(R.entity.hero() == nil, "denormal max-HP must not pass the gate")
    I.write_f32(HERO + MAXHP_OFF, saved)
    local savedhp = I.read_f32(HERO + HP_OFF)
    I.write_f32(HERO + HP_OFF, 7.6e28)
    check(R.entity.hero() == nil, "absurd current HP must not pass the gate")
    I.write_f32(HERO + HP_OFF, savedhp)
    -- (b3) a readable-but-garbage mirror value: bound, not just readability.
    local savedmv = I.read_f32(MIRROR)
    I.write_f32(MIRROR, -1.0)
    check(R.entity.hero() == nil, "negative HUD-mirror HP must not pass the gate")
    I.write_f32(MIRROR, savedmv)
    check(R.entity.hero() ~= nil, "hero recaptured after impostor-shape checks")

    -- (c) no value store => stat reads degrade to nil, writes refuse.
    local savedstore = I.read_u64(ENTITY + STORE_OFF)
    I.write_u64(ENTITY + STORE_OFF, 0)                -- *(ctx+0x4c8) = 0
    check(R.stat.get("attack_power") == nil, "stat.get nil with no store")
    check(R.stat.set("attack_power", 1) == false, "stat.set refuses with no store")
    I.write_u64(ENTITY + STORE_OFF, savedstore)

    -- (d) a dead value-context pointer (*(hero+0x2f8) = 0) => same fail-closed
    -- behavior; the engine is never called with an unvalidated context. This is
    -- the 2026-07-15 crash shape: an implausible ctx/store chain must never
    -- reach EntityValue_Get (whose mock raises on a bad context).
    local savedctx = I.read_u64(HERO + VALCTX_OFF)
    I.write_u64(HERO + VALCTX_OFF, 0)
    check(R.stat.get("attack_power") == nil, "stat.get nil with no value ctx")
    check(R.stat.set("attack_power", 1) == false, "stat.set refuses with no value ctx")
    I.write_u64(HERO + VALCTX_OFF, savedctx)
    check(about(R.stat.get("attack_power"), 500), "stat path healthy again after restore")
end

-- 11. pointer-safety library -----------------------------------------------
-- The guardrail that turns the crash-by-bad-pointer class (2026-07-15 ctx
-- deref, 2026-07-17 probe->engine walk) into fail-closed no-ops.
do
    local BASE = I.module_base()               -- 0x140000000 in the mock

    -- in_image: pointer inside the loaded game module span, else false.
    check(R.ptr.in_image(BASE + 0x1000) == true, "in_image accepts an image pointer")
    check(R.ptr.in_image(BASE + 0x2000000) == false, "in_image rejects past the image span")
    check(R.ptr.in_image(0x50000000) == false, "in_image rejects a heap pointer")
    check(R.ptr.in_image(0) == false, "in_image rejects null")

    -- has_vtable: object whose *(obj) points into the image.
    local OBJ = 0x60000000
    I.write_u64(OBJ, BASE + 0x1230)            -- vtable in image
    check(R.ptr.has_vtable(OBJ) == true, "has_vtable accepts obj with image vtable")
    I.write_u64(OBJ, 0x50000000)               -- vtable in heap = not a live object
    check(R.ptr.has_vtable(OBJ) == false, "has_vtable rejects obj with heap vtable")

    -- vector_valid: {data, count} array with per-entry validation.
    local HOLDER, ARR = 0x61000000, 0x62000000
    I.write_u64(HOLDER + 0x190, ARR)
    I.write_u32(HOLDER + 0x198, 2)
    for i = 0, 1 do
        local e = 0x63000000 + i * 0x1000
        I.write_u64(ARR + i * 8, e)
        I.write_u64(e, BASE + 0x100)           -- entry vtable in image
        I.write_u64(e + 8, HOLDER)             -- owner back-ptr
    end
    local function entry_ok(elem, owner)
        return R.ptr.has_vtable(elem) and I.read_u64(elem + 8) == owner
    end
    check(R.ptr.vector_valid(HOLDER, 0x190, 0x198, { min = 1, check_entry = entry_ok }) == true,
          "vector_valid accepts a fully-consistent array")
    -- corrupt entry 1's vtable -> whole vector rejected (fail closed).
    I.write_u64(0x63001000, 0x50000000)
    check(R.ptr.vector_valid(HOLDER, 0x190, 0x198, { min = 1, check_entry = entry_ok }) == false,
          "vector_valid rejects when any entry fails validation")
    I.write_u64(0x63001000, BASE + 0x100)      -- restore
    -- an insane count is rejected before any entry read (no spin / no fault).
    I.write_u32(HOLDER + 0x198, 0x99999)
    check(R.ptr.vector_valid(HOLDER, 0x190, 0x198, { min = 1 }) == false,
          "vector_valid rejects an out-of-bound count")
    I.write_u32(HOLDER + 0x198, 2)

    -- call_safe: on a bad pointer arg it must REFUSE before reaching the
    -- engine (returns nil, makes no call). A tripwire engine fn records if it
    -- was ever entered — it must stay false through every refusal.
    local called = false
    engine["Entity_GetComponentByTester"] = function() called = true; return 0 end
    -- Bad arg 1 (null) -> refused.
    check(R.engine.call_safe("Entity_GetComponentByTester", { 1 }, 0, BASE + 0x10) == nil,
          "call_safe refuses a null pointer arg")
    -- Bad arg 2 under a custom validator (must be in image) -> refused.
    check(R.engine.call_safe("Entity_GetComponentByTester", { { 2, R.ptr.in_image } },
          OBJ, 0x50000000) == nil, "call_safe refuses when a validator fails")
    check(called == false, "call_safe never entered the engine on a refusal")
end

-- 12. R.debug.find_arrays: the generalized struct-hunt aid -------------------
do
    local BASE = I.module_base()
    -- Build a holder whose field +0x38 points at an object carrying a valid
    -- 3-entry component array at +0x190/+0x198 (every entry an image-vtable'd
    -- object). find_arrays must locate exactly that field.
    local ROOT, SUB, ARR = 0x70000000, 0x71000000, 0x72000000
    I.write_u64(ROOT + 0x38, SUB)
    I.write_u64(SUB + 0x190, ARR)
    I.write_u32(SUB + 0x198, 3)
    for i = 0, 2 do
        local e = 0x73000000 + i * 0x1000
        I.write_u64(ARR + i * 8, e)
        I.write_u64(e, BASE + 0x200)           -- entry vtable in image
    end
    local hits = R.debug.find_arrays(ROOT, { max_off = 0x100,
        check_entry = function(elem) return R.ptr.has_vtable(elem) end })
    check(#hits == 1, "find_arrays locates exactly one array-holding field")
    check(hits[1] and hits[1].off == 0x38, "find_arrays reports the right field offset")
    check(hits[1] and hits[1].count == 3, "find_arrays reports the entry count")
    check(hits[1] and hits[1].holder == SUB, "find_arrays reports the holder pointer")
    -- an object with no valid sub-vector yields nothing (fail-quiet).
    check(#R.debug.find_arrays(0x74000000, { max_off = 0x40 }) == 0,
          "find_arrays returns empty when nothing matches")
end

-- 13. submodules actually load ---------------------------------------------
do
    for _, name in ipairs({ "health", "config", "i18n", "api", "schedule" }) do
        check(type(R[name]) == "table", "R." .. name .. " submodule failed to load")
    end
end

-- 14. R.schedule uses the monotonic clock ----------------------------------
do
    local fired = {}
    R.schedule.after(0.25, function() fired[#fired + 1] = "quarter" end)
    R.schedule.after(2.0,  function() fired[#fired + 1] = "two" end)
    R.schedule._tick()
    check(#fired == 0, "no timer fires before its deadline")
    fake_clock = fake_clock + 0.5          -- sub-second: only reachable via now()
    R.schedule._tick()
    check(#fired == 1 and fired[1] == "quarter",
          "sub-second timer fires once the monotonic clock passes it")
    fake_clock = fake_clock + 2.0
    R.schedule._tick()
    check(#fired == 2 and fired[2] == "two", "later timer fires in order")
    R.schedule._tick()
    check(#fired == 2, "a fired timer does not repeat")

    -- A callback that schedules more work must not be run again in the SAME
    -- drain. `_add` appends to the very table being walked, so an unbounded
    -- `ipairs` used to march straight into the new entries: with a zero delay,
    -- `R.schedule.after(0, poll)` from inside `poll` — the obvious way to
    -- write "poll as fast as possible" — spun forever inside one tick and hung
    -- the loader's pump thread, taking every mod's timers, the hero capture
    -- and the health canary with it.
    local hot, hot_handle = 0, nil
    local function spin()
        hot = hot + 1
        hot_handle = R.schedule.after(0, spin)
    end
    hot_handle = R.schedule.after(0, spin)
    R.schedule._tick()
    check(hot == 1, "a zero-delay self-reschedule fires ONCE per tick, not forever")
    R.schedule._tick()
    check(hot == 2, "and the work it queued runs on the NEXT tick")
    R.schedule.cancel(hot_handle)

    -- The carry-over must not drop it either: a self-rescheduling poll with a
    -- real delay keeps going.
    local polls = 0
    local function poll()
        polls = polls + 1
        if polls < 3 then R.schedule.after(1, poll) end
    end
    R.schedule.after(1, poll)
    for _ = 1, 4 do
        fake_clock = fake_clock + 1.5
        R.schedule._tick()
    end
    check(polls == 3, "a delayed self-rescheduling poll survives the drain")

    -- A repeater must be able to stop ITSELF — "repeat until done" is the
    -- whole reason `every` returns a handle. Cancel used to only remove the
    -- entry from the list, which a drain already in progress cannot observe:
    -- it held the same entry and wrote it straight back, so the timer polled
    -- for the rest of the session.
    local beats, handle = 0, nil
    handle = R.schedule.every(1, function()
        beats = beats + 1
        R.schedule.cancel(handle)
    end)
    for _ = 1, 3 do
        fake_clock = fake_clock + 1.5
        R.schedule._tick()
    end
    check(beats == 1, "a repeater that cancels itself fires exactly once")
    check(R.schedule.pending().timers == 0, "and leaves nothing pending")

    -- Cancelling from OUTSIDE a drain still works, and is idempotent.
    local never = R.schedule.every(1, function() check(false, "cancelled timer ran") end)
    check(R.schedule.cancel(never), "cancel reports it stopped a live timer")
    check(not R.schedule.cancel(never), "cancelling twice reports false")
    fake_clock = fake_clock + 5
    R.schedule._tick()

    -- next_main must NOT drain on the background tick pump.
    local main_ran = false
    R.schedule.next_main(function() main_ran = true end)
    R.schedule._tick()
    check(not main_ran, "next_main does not run on the background tick")
    R.schedule._main_tick()
    check(main_ran, "next_main runs on the main-thread pump")

    check(R.schedule.pending().timers == 0, "pending() reports a drained timer list")
    local ok = pcall(R.schedule.after, 1.0, "not a function")
    check(not ok, "after() rejects a non-function")
end

-- 15. R.i18n lookup + interpolation ----------------------------------------
do
    check(R.i18n.locale() == "EN", "locale comes from the native binding")
    check(R.i18n.t("greet", { name = "Piper" }) == "Hello Piper",
          "t() interpolates {vars}")
    check(R.i18n.t("plain") == "no vars", "t() returns a var-free string as-is")
    check(R.i18n.t("missing") == "missing", "t() falls back to the key")
    check(R.i18n.has("greet") and not R.i18n.has("missing"), "has() reports presence")
end

-- 16. R.health reads the crash history -------------------------------------
do
    check(R.health.crash_count("badmod") == 2, "crash_count reads native history")
    check(R.health.crash_count("cleanmod") == 0, "unknown mod has no crashes")
    check(R.health.last_error("badmod") == "boom", "last_error reads native history")
    R.health.checkpoint("phase1")
    check(health_state.checkpoints[#health_state.checkpoints] == "phase1",
          "checkpoint reaches the native canary")
    R.health.disable("badmod", "keeps crashing")
    check(health_state.disabled.badmod == "keeps crashing", "disable records a reason")
end

-- 17. R.api crosses the (mocked) state boundary -----------------------------
do
    R.api.expose{ api_name = "loot", version = "1.2.0",
                  roll = function(tier) return { id = "orb", tier = tier } end,
                  boom = function() error("provider exploded") end }
    check(R.api.has("loot"), "has() sees an exposed api")
    check(R.api.version("loot") == "1.2.0", "version() reports the exposed version")
    check(R.api.list().loot ~= nil, "list() includes the exposed api")

    local loot = R.api.require("loot", ">= 1.0")
    local item = loot.roll(3)
    check(type(item) == "table" and item.id == "orb" and item.tier == 3,
          "a call reaches the provider and returns its data")

    -- Version constraints are enforced.
    check(not pcall(R.api.require, "loot", ">= 2.0"), "require rejects an unmet spec")
    check(not pcall(R.api.require, "nope"), "require rejects an unknown api")

    -- A provider error surfaces as a consumer-side error, not a crash.
    check(not pcall(function() return loot.boom() end),
          "a raising provider becomes an error in the consumer")

    -- Callbacks cannot cross a state boundary: reject loudly rather than
    -- silently passing nil.
    check(not pcall(function() return loot.roll(function() end) end),
          "a function argument is refused")

    -- The proxy is read-only.
    check(not pcall(function() loot.roll = 1 end), "proxy rejects assignment")
end

-- 18. R.options.set type checking ------------------------------------------
do
    local OPT_OBJ = 0x60000000
    I.write_u64(0x140000000 + (0x14143cb58 - 0x140000000), OPT_OBJ)
    I.write_u8(OPT_OBJ + 0x0030 + 0x28, 1)     -- "Dev"  reads as a real bool
    I.write_u8(OPT_OBJ + 0x0060 + 0x28, 0)     -- "Test" reads as a real bool
    check(R.options.get("Dev") == true, "bool option round-trips")
    check(R.options.set("Forced seed", 12345), "numeric option accepts a number")
    check(R.options.get("Forced seed") == 12345, "numeric option round-trips")
    -- A non-number for a numeric option used to raise out of the setter
    -- (`value + 0.0`), aborting the calling mod instead of refusing.
    local ok, refused = pcall(R.options.set, "Forced seed", "oops")
    check(ok and refused == false, "non-number for a numeric option is refused, not raised")
    local ok2, refused2 = pcall(R.options.set, "Forced seed", nil)
    check(ok2 and refused2 == false, "nil for a numeric option is refused, not raised")
    check(R.options.get("Forced seed") == 12345, "a refused write leaves the value alone")
end

-- 19. R.emit: cross-mod signalling -----------------------------------------
do
    local got
    R.on("spec:thing", function(ev) got = ev end)
    check(R.emit("spec:thing", { n = 7 }) == true, "emit returns true")
    check(got ~= nil and got.n == 7, "subscriber receives the payload")
    check(got and got.event == "spec:thing", "loader stamps the event name")
    check(got and got.source == "mod", "loader stamps source=mod")
    check(got and got.from == "spec_mod", "loader stamps the emitting mod id")

    -- Provenance is NOT forgeable: a mod claiming source="gameplay" would be
    -- claiming "I am on the game's main thread", which is what R.schedule's
    -- main pump and R.stat's re-assert gate on.
    got = nil
    R.emit("spec:thing", { source = "gameplay", from = "someone_else" })
    check(got and got.source == "mod" and got.from == "spec_mod",
          "a caller cannot forge source/from")

    -- Reserved namespaces are refused.
    for _, name in ipairs({ "gameplay:FAKE", "ui:press", "rsmm:x",
                            "ready", "tick", "exit", "setup", "*" }) do
        check(not pcall(R.emit, name, {}), "emit refuses reserved name " .. name)
    end

    -- Argument validation.
    check(not pcall(R.emit, 42, {}), "emit rejects a non-string name")
    check(not pcall(R.emit, "spec:thing", "nope"), "emit rejects a non-table payload")
    check(pcall(R.emit, "spec:thing"), "emit accepts a nil payload")

    -- Emitting from inside a handler re-enters; must not blow up or lose the
    -- outer dispatch (the native side is a recursive mutex + snapshot).
    local depth, seen = 0, 0
    R.on("spec:nested", function()
        seen = seen + 1
        if depth < 2 then depth = depth + 1; R.emit("spec:nested", {}) end
    end)
    R.emit("spec:nested", {})
    check(seen == 3, "re-entrant emit dispatches each level exactly once")
end

-- 20. subscription lifecycle: off / once / patterns -------------------------
do
    local hits = 0
    local h = R.on("spec:sub", function() hits = hits + 1 end)
    fire("spec:sub"); check(hits == 1, "R.on fires")
    check(R.off(h) == true, "R.off reports it cancelled a live subscription")
    fire("spec:sub"); check(hits == 1, "a cancelled subscription stops firing")
    check(R.off(h) == false, "R.off is idempotent")

    local once = 0
    R.once("spec:once", function() once = once + 1 end)
    fire("spec:once"); fire("spec:once"); fire("spec:once")
    check(once == 1, "R.once fires exactly once")

    local matched = {}
    local m = R.on_match("^gameplay:ABILITY_", function(_, name)
        matched[#matched + 1] = name
    end)
    fire("gameplay:ABILITY_EXIT")
    fire("gameplay:ABILITY_MAX")
    fire("gameplay:COMBO_LINK")            -- must not match
    check(#matched == 2, "pattern subscription takes the whole family")
    check(matched[1] == "gameplay:ABILITY_EXIT", "pattern handler gets the event name")
    R.off(m)

    -- The callback gets (payload, name) for exact subscriptions too.
    local got_name
    local h2 = R.on("spec:named", function(_, name) got_name = name end)
    fire("spec:named")
    check(got_name == "spec:named", "exact handler receives the event name")
    R.off(h2)

    -- One handler raising must not stop the others on the same event.
    local after = false
    local hb = R.on("spec:boom", function() error("kaboom") end)
    local ha = R.on("spec:boom", function() after = true end)
    fire("spec:boom")
    check(after, "a raising handler does not break the rest of the chain")
    R.off(hb); R.off(ha)

    -- Subscribing from inside a dispatch must not fire for THIS event.
    local late = 0
    local hs = R.on("spec:reentrant", function()
        R.on("spec:reentrant", function() late = late + 1 end)
    end)
    fire("spec:reentrant")
    check(late == 0, "a handler added mid-dispatch does not fire for that event")
    fire("spec:reentrant")
    check(late >= 1, "the handler added mid-dispatch fires next time")
    R.off(hs)
end

-- 21. event catalog ---------------------------------------------------------
do
    fire("spec:cat", { alpha = 1, beta = "x" })
    fire("spec:cat", { alpha = 2 })
    local seen = R.events.seen()
    check(seen["spec:cat"] ~= nil, "catalog records an event it saw")
    check(seen["spec:cat"].count >= 2, "catalog counts fires")
    check(table.concat(seen["spec:cat"].keys, ","):find("alpha"),
          "catalog records payload keys")
    check(R.events.count("spec:cat") >= 2, "count() agrees with the catalog")
    check(R.events.count("spec:never") == 0, "unseen event counts zero")
    local list = R.events.list("^spec:")
    check(#list > 0, "list() filters by pattern")
    for i = 2, #list do check(list[i - 1] <= list[i], "list() is sorted") end

    -- The STATIC catalog: names available before anything has fired.
    local bus = R.events.known("gameplay")
    check(#bus > 100, "known('gameplay') carries the mined bus catalog")
    local by_name = {}
    for _, n in ipairs(bus) do by_name[n] = true end
    for _, n in ipairs({ "GIVE_MAGICAL_OBJECT", "BOSS_DEFEATED", "OPEN_CHEST",
                         "HERO_REVIVE", "NETWORK_DAMAGE" }) do
        check(by_name[n], "catalog contains " .. n)
    end
    check(R.events.category("BOSS_DEFEATED") == "boss", "category() maps a bus name")
    check(R.events.category("gameplay:BOSS_DEFEATED") == "boss",
          "category() accepts the qualified form")
    check(R.events.category("nope") == nil, "category() is nil for an unknown name")
    local all = R.events.known()
    local qualified = false
    for _, n in ipairs(all) do
        if n == "gameplay:GIVE_MAGICAL_OBJECT" then qualified = true end
    end
    check(qualified, "known() qualifies bus names with the gameplay: prefix")
    check(#R.events.known("lifecycle") == 4, "lifecycle group is listed")
    check(#R.events.known("derived") == 7, "loader-derived group is listed")
    check(#R.events.known("nosuchgroup") == 0, "unknown group yields an empty list")
end

-- 22. repeating + cancellable timers ---------------------------------------
do
    local n = 0
    local id = R.schedule.every(1.0, function() n = n + 1 end)
    R.schedule._tick(); check(n == 0, "every() does not fire before its interval")
    fake_clock = fake_clock + 1.0; R.schedule._tick()
    check(n == 1, "every() fires at the interval")
    fake_clock = fake_clock + 1.0; R.schedule._tick()
    check(n == 2, "every() re-arms itself")
    check(R.schedule.cancel(id) == true, "cancel() reports it removed the timer")
    fake_clock = fake_clock + 5.0; R.schedule._tick()
    check(n == 2, "a cancelled repeater stops")
    check(R.schedule.cancel(id) == false, "cancel() is idempotent")

    -- A raising repeater survives: a transient failure must not kill the timer.
    local tries = 0
    local bad = R.schedule.every(1.0, function() tries = tries + 1; error("nope") end)
    fake_clock = fake_clock + 1.0; R.schedule._tick()
    fake_clock = fake_clock + 1.0; R.schedule._tick()
    check(tries == 2, "a repeater whose callback raises still re-arms")
    R.schedule.cancel(bad)

    -- after() is still one-shot and cancellable.
    local once = 0
    local oid = R.schedule.after(1.0, function() once = once + 1 end)
    fake_clock = fake_clock + 1.0; R.schedule._tick()
    check(once == 1, "after() fires")
    fake_clock = fake_clock + 5.0; R.schedule._tick()
    check(once == 1, "after() does not repeat")
    check(R.schedule.cancel(oid) == false, "a fired one-shot is already gone")
end

-- 23. loader-derived events -------------------------------------------------
do
    -- Reach a known baseline BEFORE subscribing: an earlier test already
    -- drove a tick, so the poller has seen the hero once.
    shared[0] = 0
    fire("tick")                    -- drops the capture, unobserved

    local log = {}
    local subs = {}
    for _, name in ipairs({ "hero:captured", "hero:changed", "hero:lost",
                            "menu:enter", "menu:leave", "run:start", "run:end" }) do
        subs[#subs + 1] = R.on(name, function(ev) log[#log + 1] = { name, ev } end)
    end

    shared[0] = HERO
    fire("tick")
    check(#log == 1 and log[1][1] == "hero:captured", "hero:captured on first sight")
    check(log[1][2].hero == HERO, "hero:captured carries the hero pointer")
    check(log[1][2].source == "loader", "derived events are tagged source=loader")

    fire("tick")
    check(#log == 1, "no event while the hero is unchanged")

    -- Switch character: a different plausible hero pointer.
    local HERO2 = 0x10500000
    I.write_f32(HERO2 + MAXHP_OFF, 90.0)
    I.write_f32(HERO2 + HP_OFF, 90.0)
    I.write_u64(HERO2 + HUDMIRROR_OFF, MIRROR)
    shared[0] = HERO2
    fire("tick")
    check(#log == 2 and log[2][1] == "hero:changed", "hero:changed on a switch")
    check(log[2][2].previous == HERO and log[2][2].hero == HERO2,
          "hero:changed carries both pointers")

    shared[0] = 0
    fire("tick")
    check(#log == 3 and log[3][1] == "hero:lost", "hero:lost when capture drops")
    check(log[3][2].previous == HERO2, "hero:lost names the pointer it dropped")

    -- Menu transitions are edge-triggered (hero stays absent, so nothing else
    -- can add to the log here).
    local before = #log
    in_main_menu = true;  fire("tick")
    in_main_menu = true;  fire("tick")      -- no repeat on the same state
    in_main_menu = false; fire("tick")
    check(#log == before + 2, "menu fires once per edge, not per poll")
    check(log[before + 1][1] == "menu:enter", "menu:enter on the rising edge")
    check(log[#log][1] == "menu:leave", "menu:leave on the falling edge")

    -- Run boundaries normalise the analytics names and are idempotent.
    before = #log
    fire("run_start"); fire("run_start")
    check(#log == before + 1 and log[#log][1] == "run:start",
          "run:start fires once per run")
    check(R.run.active() == true, "R.run.active() true inside a run")
    fire("run_end"); fire("run_end")
    check(#log == before + 2 and log[#log][1] == "run:end",
          "run:end fires once per run")
    check(R.run.active() == false, "R.run.active() false after the run")

    for _, id in ipairs(subs) do R.off(id) end
end


-- ---------------------------------------------------------------------------
-- 24. spawn-init capture: instant, with no combat prerequisite
--
-- Without this source the Lua fallback only learns the hero from the heal or
-- item-grant handlers, i.e. from a hero ACTION. A playtest measured 73 seconds
-- before anything was captured, and the result was only [tentative] because it
-- came from the heal path. The hero's own post-load init runs once at spawn,
-- before it acts — but its fields are not live yet at that moment, so the
-- identity has to be stashed and promoted when it becomes readable.
-- ---------------------------------------------------------------------------
do
    -- Native capture OFF, so the Lua fallback path is the one under test.
    shared[0], shared[2], shared[3] = 0, 0, 0
    local SPAWN = 0x11000000
    I.write_f32(SPAWN + MAXHP_OFF, 0.0)          -- fields NOT live yet
    I.write_f32(SPAWN + HP_OFF, 0.0)
    I.write_u64(SPAWN + HUDMIRROR_OFF, 0)

    check(R.entity.hero() == nil, "no hero before the spawn-init hook fires")
    local sub_va = I.resolve("NamedEvent_HeroSubscribeAll")
    check(hooks[sub_va] ~= nil, "spawn-init hook armed on NamedEvent_HeroSubscribeAll")
    check(hooks[sub_va].sig == "vp", "armed with the void(hero) signature")

    hooks[sub_va].cb(SPAWN)
    check(R.entity.hero() == nil,
          "identity stashed, NOT captured while its fields are still zero")

    -- The init routine is what populates these; simulate it completing.
    I.write_f32(SPAWN + MAXHP_OFF, 120.0)
    I.write_f32(SPAWN + HP_OFF, 120.0)
    I.write_u64(SPAWN + HUDMIRROR_OFF, MIRROR)
    I.write_f32(MIRROR, 120.0)

    check(R.entity.hero() == SPAWN,
          "promoted on the first read after the fields go live")
    check(shared[0] == SPAWN, "published to the shared slot for other mod states")
end

-- ---------------------------------------------------------------------------
-- 24b. The candidate ring belongs to ONE chapter, and to ONE player
--
-- Two failures from the 2026-08-18 four-player session, both in this loop:
--
-- 1. The spawn-init hook that feeds the ring fires once per HERO, not once per
--    machine (three stashes inside 5 ms, four more at the next chapter). The
--    loop adopted the first plausible entry, i.e. whichever hero the allocator
--    put in the lower ring slot — so R.combat/R.stat/R.xp could have been
--    pointed at an ALLY's character. The engine's +0x1d88 byte decides it.
--
-- 2. Nothing retired a chapter's candidates. The engine rebuilds every hero
--    controller at a chapter load, freed memory keeps reading plausible, and
--    the native stash DEDUPES (so a retired pointer is never overwritten) —
--    the published hero stayed on the torn-down chapter's object for the rest
--    of the run. Retirement is by FINGERPRINT, not by address, so the next
--    chapter reusing the address is still adopted.
-- ---------------------------------------------------------------------------
do
    shared[0], shared[2], shared[3] = 0, 0, 0
    for i = 8, 15 do shared[i] = nil end
    package.loaded["rsmm"] = nil
    local Rr = require "rsmm"

    local ALLY, MINE = 0x11400000, 0x11500000
    for _, p in ipairs({ ALLY, MINE }) do
        I.write_f32(p + MAXHP_OFF, 100.0)
        I.write_f32(p + HP_OFF, 100.0)
        I.write_u64(p + HUDMIRROR_OFF, MIRROR)
    end
    I.write_f32(MIRROR, 100.0)
    I.write_u8(ALLY + 0x1d88, 0)          -- a remote ally
    I.write_u8(MINE + 0x1d88, 1)          -- this machine's player
    shared[8] = ALLY                      -- the LOWER slot, which used to win
    shared[9] = MINE

    check(Rr.entity.hero() == MINE,
          "the ring prefers the candidate the engine flags as local, not the "
          .. "one in the lowest slot")

    -- Chapter teardown: everything in the ring belongs to the old chapter.
    check(Rr.entity.invalidate_capture("spec") == true, "invalidate_capture runs")
    check(shared[0] == 0, "the published hero is dropped, not left dangling")
    check(Rr.entity.hero() == nil,
          "and no retired ring candidate is re-adopted, however plausible it "
          .. "still reads")

    -- Address reuse: the next chapter's hero lands on a retired address. The
    -- fingerprint moved, so it is a different object and must be adopted.
    I.write_f32(MINE + MAXHP_OFF, 250.0)
    check(Rr.entity.hero() == MINE,
          "a NEW object at a retired address is captured again")

    -- An ally-only ring still captures: the byte is a PREFERENCE, because a
    -- hero mid-load reads 0 there and refusing would mean never capturing.
    Rr.entity.invalidate_capture("spec")
    for i = 8, 15 do shared[i] = nil end
    shared[8] = ALLY
    I.write_f32(ALLY + MAXHP_OFF, 101.0)      -- not the retired fingerprint
    check(Rr.entity.hero() == ALLY,
          "with nothing claiming to be local, the old behaviour stands")

    Rr.entity.invalidate_capture("spec")
    for i = 8, 15 do shared[i] = nil end
    shared[0], shared[2], shared[3] = 0, 0, 0
    package.loaded["rsmm"] = nil
    R = require "rsmm"
    shared[0] = HERO                       -- restore for later sections
end

-- ---------------------------------------------------------------------------
-- 25. RSMM_ENABLE_HERO_CAPTURE off must mean off EVERYWHERE
--
-- The flag stopped the native hooks and nothing else: this Lua fallback then
-- installed detours on the same handlers the first time a mod touched
-- R.entity. A playtest log showed two `[hook] slot N installed` lines directly
-- under "[hero-capture] disabled", while the loader claimed R.combat/R.entity/
-- R.stat/R.xp were unavailable. The flag exists because these detours have
-- correlated with load-time crashes, so a refusal has to be honoured here too.
-- ---------------------------------------------------------------------------
do
    -- The capture handlers, by the names the fallback resolves them under.
    local capture_vas = {
        I.resolve("Entity_GainHealthHandler"),
        I.resolve("Entity_GiveHandler"),
        I.resolve("NamedEvent_HeroSubscribeAll"),
    }
    local function armed_count()
        local n = 0
        for _, va in ipairs(capture_vas) do if hooks[va] then n = n + 1 end end
        return n
    end
    local function fresh()
        for _, va in ipairs(capture_vas) do hooks[va] = nil end
        shared[0], shared[2], shared[3] = 0, 0, 0   -- nothing captured, native off
        package.loaded["rsmm"] = nil
        return require "rsmm"
    end

    shared[4] = 2                                   -- explicitly DENIED
    local Rd = fresh()
    check(Rd.entity.hero() == nil, "denied: no hero")
    check(armed_count() == 0,
          "denied: installed NO capture hooks (got " .. armed_count() .. ")")

    -- Unknown (an older loader that never writes the slot) keeps working, so a
    -- newer rsmm.lua on an older DLL does not silently lose capture.
    shared[4] = 0
    local Ru = fresh()
    Ru.entity.hero()
    check(armed_count() > 0,
          "loader too old to answer still arms capture (back-compat)")

    -- Permitted behaves like unknown.
    shared[4] = 1
    local Rp = fresh()
    Rp.entity.hero()
    check(armed_count() > 0, "permitted: capture hooks armed")

    shared[4] = 0
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- ---------------------------------------------------------------------------
-- R.projectile.scale_width — line-attack hit volume
-- ---------------------------------------------------------------------------
do
    local CPNT       = 0x30000000
    local WIDTH_OFF  = 0xe8
    local va         = I.resolve("ProjectileAttack_BeginAttack")
    hooks[va] = nil
    package.loaded["rsmm"] = nil
    local Rp = require "rsmm"

    check(Rp.projectile ~= nil, "R.projectile namespace exists")
    check(Rp.projectile.width_scale() == 1.0, "unscaled by default")

    check(Rp.projectile.scale_width(2.0) == true, "scale_width arms the hook")
    check(hooks[va] ~= nil, "hook installed on ProjectileAttack_BeginAttack")
    check(hooks[va].sig == "vp", "signature is void(void*) — one ptr arg, no floats")
    check(Rp.projectile.width_scale() == 2.0, "multiplier recorded")

    -- Simulate the engine: the ORIGINAL writes the width, so the mock
    -- trampoline is what seeds +0xe8. This is the ordering the hook depends
    -- on — scaling before the original runs would be overwritten.
    local orig_calls = 0
    local function next_stub(this)
        orig_calls = orig_calls + 1
        I.write_f32(this + WIDTH_OFF, 4.0)      -- vanilla width
    end

    local ret = hooks[va].cb(CPNT, next_stub)
    check(orig_calls == 1, "the original ran exactly once")
    check(about(I.read_f32(CPNT + WIDTH_OFF), 8.0), "width doubled (4.0 -> 8.0)")

    -- THE footgun this guards. hook_lua's dispatch replays the trampoline
    -- whenever the callback returns nil, and it does NOT track that next()
    -- already ran (hook_lua.cpp, the lua_isnoneornil branch). A callback that
    -- calls next() and then returns nil begins the attack TWICE.
    check(ret ~= nil,
          "callback returns non-nil after calling next(), so dispatch does "
          .. "not replay the trampoline a second time")

    -- Idempotent: retuning must not stack detours.
    local first_cb = hooks[va].cb
    check(Rp.projectile.scale_width(3.0) == true, "second call still reports live")
    check(hooks[va].cb == first_cb, "hook not reinstalled — same callback object")
    check(Rp.projectile.width_scale() == 3.0, "multiplier retuned in place")

    I.write_f32(CPNT + WIDTH_OFF, 0)
    hooks[va].cb(CPNT, next_stub)
    check(about(I.read_f32(CPNT + WIDTH_OFF), 12.0), "new multiplier applies (4.0 -> 12.0)")

    -- Clamps. A non-positive width collapses the volume so nothing can ever be
    -- hit; both ends degrade rather than erroring.
    Rp.projectile.scale_width(0)
    check(Rp.projectile.width_scale() == 0.01, "non-positive multiplier clamped up")
    Rp.projectile.scale_width(1e9)
    check(Rp.projectile.width_scale() == 100, "absurd multiplier clamped down")
    Rp.projectile.scale_width("nonsense")
    check(Rp.projectile.width_scale() == 1.0, "non-numeric falls back to 1.0")

    -- At 1.0 the hook stays installed but must not touch the field.
    I.write_f32(CPNT + WIDTH_OFF, 0)
    hooks[va].cb(CPNT, next_stub)
    check(about(I.read_f32(CPNT + WIDTH_OFF), 4.0), "x1.0 leaves the width alone")

    -- Implausible widths are left alone: a zero/negative/absurd read means
    -- this is not the object we think it is.
    Rp.projectile.scale_width(2.0)
    I.write_f32(CPNT + WIDTH_OFF, 0)
    hooks[va].cb(CPNT, function() end)          -- original writes nothing
    check(about(I.read_f32(CPNT + WIDTH_OFF), 0.0), "zero width not scaled")

    hooks[va] = nil
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.hooks: installed is not the same as fired -----------------------------
--
-- resolve + fn_verify + .pdata + MH_EnableHook all pass for a routine that has
-- moved to a DIFFERENT caller: it installs cleanly and never runs. That reads
-- as "the feature is broken" with nothing in the log to say why, and answering
-- it used to mean correlating loader timestamps against the game's own log.
do
    local all = R.hooks.status()
    check(#all == 2, "status() reports every armed hook")
    check(all[1].tag == "hero-capture", "and carries the subsystem tag")

    local silent = R.hooks.silent()
    check(#silent == 1, "silent() isolates the hooks that never fired")
    check(silent[1].what == "selector prepare",
          "which is the one whose target is not on a live path")

    -- Degrades on an older loader with no binding, rather than erroring.
    local real = I.hook_report
    I.hook_report = nil
    check(#R.hooks.status() == 0, "no native binding -> empty, not an error")
    I.hook_report = real
end

-- N. hero capture: a later spawn-init must not discard earlier candidates ---
--
-- Spawn-init fires several times per boot and the native side used ONE pending
-- slot, so each call overwrote the last. Measured 2026-08-14: five stashes
-- collapsed to a single candidate whose HP fields never went live, the pending
-- path was dead for the whole run, and capture instead waited ~94s for a
-- gain-health fire. The candidates are all hero-identity — they just go live
-- at different times — so all of them are kept and the first to validate wins.
do
    package.loaded["rsmm"] = nil
    local Rh = require "rsmm"
    local saved = {}
    for k, v in pairs(shared) do saved[k] = v end
    for k in pairs(shared) do shared[k] = nil end

    local DEAD, LIVE = 0x21000000, 0x22000000
    -- DEAD never populates: HP fields stay zero, exactly like the candidate
    -- that blocked the real run.
    I.write_f32(DEAD + 0x15c8, 0.0)
    I.write_f32(DEAD + 0x15cc, 0.0)
    I.write_u64(DEAD + 0x1d80, 0)
    -- LIVE is a fully populated hero.
    I.write_f32(LIVE + 0x15c8, 42.0)
    I.write_f32(LIVE + 0x15cc, 100.0)
    I.write_u64(LIVE + 0x1d80, 0x23000000)
    I.write_f32(0x23000000, 42.0)

    -- The dead one arrives LAST, which under the old single-slot design is
    -- what made it win and shadow everything before it.
    shared[8] = LIVE
    shared[9] = DEAD
    shared[3] = DEAD

    check(Rh.entity.hero() == LIVE,
          "a live ring candidate is promoted even when a dead one arrived later")
    check(shared[0] == LIVE, "and it is published to the shared hero slot")

    for k in pairs(shared) do shared[k] = nil end
    for k, v in pairs(saved) do shared[k] = v end
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. a bad pattern from one mod must not break the bus for everyone --------
--
-- `R.on_match` patterns are applied with `string.find`, which RAISES on a
-- malformed pattern. That call lives in the shared router, outside the
-- per-callback pcall, so one mod passing "%" used to unwind the whole dispatch
-- loop: every other mod's handlers stopped running, for every event, and the
-- error surfaced nowhere near the mod that caused it. The router now pcalls
-- the match too; this pins the half a spec can observe — the refusal at
-- subscribe time, where the offending mod is still on the stack.
do
    package.loaded["rsmm"] = nil
    local Rp = require "rsmm"

    check(not pcall(Rp.on_match, "%", function() end),
          "a malformed pattern is refused by on_match")
    check(not pcall(Rp.on_match, "[", function() end),
          "an unfinished character class is refused too")
    check(pcall(Rp.on_match, "^gameplay:", function() end),
          "a valid pattern is still accepted")

    -- A live pattern subscription must not disturb ordinary handlers.
    local plain, matched = false, 0
    Rp.on("gameplay:PING", function() plain = true end)
    Rp.on_match("^gameplay:PI", function() matched = matched + 1 end)
    fire("gameplay:PING", { source = "gameplay" })
    check(plain, "a plain handler still fires alongside a pattern subscription")
    check(matched == 1, "the pattern subscription fired exactly once")

    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. dispatcher offset is learned, and needs real corroboration ------------
--
-- The literal 0x4d8 was correct until the 2026-07-09 patch moved the
-- dispatcher sub-object, after which `disp - 0x4d8` landed on nothing and the
-- discriminator rejected the only real hero in the session ("give only works
-- on Aladdin"). It is derived at runtime now — but a single sighting is not
-- evidence: `disp - off` IS the hero by construction, so asking the engine to
-- vouch for it re-confirms the hero we already trusted and says nothing about
-- the dispatcher. A summon's dispatcher also fires anchor events, and latching
-- its delta would be permanent. Two DIFFERENT hero pointers agreeing on one
-- offset is what separates a layout constant from a heap coincidence.
do
    package.loaded["rsmm"] = nil
    local Rd = require "rsmm"
    local saved_shared = {}
    for k, v in pairs(shared) do saved_shared[k] = v end

    local OFF = 0x520                       -- deliberately NOT the old 0x4d8
    local function hero_at(addr)
        I.write_f32(addr + 0x15c8, 50.0)    -- hp
        I.write_f32(addr + 0x15cc, 100.0)   -- max hp
        I.write_u64(addr + 0x1d80, 0x12340000)
        I.write_u64(addr + 8, 0x13000000)   -- component store
        I.write_u64(0x13000000, 0x13000100)
        return addr
    end
    local function dispatcher_for(hero)
        local d = hero + OFF
        I.write_u64(d, 0x140f00000)         -- vtable inside the image
        return d
    end

    local asked = {}
    I.is_grant_target = function(e) asked[#asked + 1] = e; return true end

    -- Hero #1: one sighting must NOT be enough to latch an offset.
    local h1 = hero_at(0x11000000)
    shared[0] = h1
    check(Rd.entity.hero() == h1, "spec fixture: first hero is capturable")
    fire("gameplay:ABILITY_EXIT", { source = "gameplay",
        dispatcher = string.format("0x%x", dispatcher_for(h1)) })
    check(#asked == 0,
          "one sighting must not latch an offset (a summon could produce it)")

    -- Hero #2, a different pointer, same delta: now it is a layout offset.
    local h2 = hero_at(0x11800000)
    shared[0] = h2
    check(Rd.entity.hero() == h2, "spec fixture: second hero is capturable")
    fire("gameplay:COMBO_LINK", { source = "gameplay",
        dispatcher = string.format("0x%x", dispatcher_for(h2)) })
    check(#asked > 0, "a second, independent hero corroborates the offset")
    check(asked[#asked] == h2,
          "the derived entity is disp-off, i.e. the hero — not hero+0x4d8")

    for k in pairs(shared) do shared[k] = nil end
    for k, v in pairs(saved_shared) do shared[k] = v end
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. interaction bus + string harvest --------------------------------------
--
-- The payload words arrive as hex STRINGS (a Lua number is a double and would
-- lose the low bits of a 64-bit handle), which is the part most likely to be
-- mis-consumed by a mod, so it is pinned here rather than discovered live.
do
    local OBJ = scratch(0x100)
    local STR = scratch(0x40)
    wbytes(STR, "DarkHills\\SceneryObjects_DarkHills\\Carpet_4x4.entity.ot\0")
    wint(OBJ + 0x18, STR, 8)             -- a path pointer hanging off the object
    wint(OBJ + 0x20, 0x41, 8)            -- an int field: must not read as a string

    local seen = {}
    R.interact.on("success", function(ev) seen[#seen + 1] = ev end)
    local all = 0
    R.interact.on("*", function() all = all + 1 end)

    fire("gameplay:INTERACTION_SUCCESS", {
        source = "gameplay", seq = 7, class = "oCDtNamedEventInteraction",
        dispatcher = string.format("0x%x", OBJ),
        u38 = "0x0", u50 = string.format("0x%x", OBJ),
    })

    check(#seen == 1, "success handler fired once")
    check(seen[1] and seen[1].phase == "success", "phase normalised to 'success'")
    check(seen[1] and seen[1].dispatcher == OBJ, "hex-string dispatcher decoded to a number")
    check(seen[1] and seen[1].b == OBJ, "payload word +0x50 decoded to a number")
    check(seen[1] and seen[1].a == 0, "payload word +0x38 decoded (zero stays zero)")
    check(R.interact.last() == seen[1], "last() returns the same table the callback got")
    check(all == 1, "the wildcard phase subscriber also fired")

    -- A non-interaction event must not reach the module at all.
    fire("gameplay:OPEN_CHEST", { source = "gameplay", seq = 8 })
    check(all == 1, "an unrelated gameplay event does not enter the interaction bus")
    check(R.interact.last().seq == 7, "last() unchanged by an unrelated event")

    -- Identification: the resource path is found through the pointer field,
    -- and the integer field does not masquerade as a string.
    local path, paths = R.interact.identify(string.format("0x%x", OBJ), { log = false })
    check(path == "DarkHills\\SceneryObjects_DarkHills\\Carpet_4x4.entity.ot",
          "identify finds the resource path hanging off the object")
    check(#paths == 1, "exactly one path found, the int field is not one")

    -- Untyped build: no u38/u50, only the RSMM_EVENT_PROBE window. `a`/`b`
    -- must read the same either way, or a mod works on one build and silently
    -- sees nil on the next.
    fire("gameplay:INTERACTION_REQUEST", {
        source = "gameplay", seq = 9,
        dispatcher = string.format("0x%x", OBJ),
        w38 = "0x11", w50 = string.format("0x%x", OBJ),
    })
    check(R.interact.last().a == 0x11, "probe-window w38 fills in for u38")
    check(R.interact.last().b == OBJ, "probe-window w50 fills in for u50")

    -- A pointer to nothing is a miss, not an error.
    check(R.interact.identify(0) == nil, "identify(0) is nil")
    check(select(1, R.interact.identify(0x999)) == nil, "implausible pointer yields nil")

    local hits = R.debug.strings(OBJ, { log = false })
    check(#hits == 1 and hits[1].off == 0x18, "strings reports the offset it found the path at")
end

-- N. R.damage: per-player damage attribution -------------------------------
--
-- The meter has to be right about four things that are easy to get wrong and
-- invisible in-game: it must not change the damage the engine deals, it must
-- board ALLIES and not enemies, it must not count one hit twice when two
-- sources see it, and the ranking must follow the numbers. The hooks are
-- exercised through their recorded callbacks, so the ABI contracts (replay,
-- return the original's value, all five resolver arguments) are pinned here
-- rather than discovered in a playtest.
do
    package.loaded["rsmm"] = nil
    local Rd = require "rsmm"

    -- Two hero CONTROLLERS: ours (is-local byte set) and an ally's.
    local ME, ALLY = 0x50000000, 0x50100000
    local ME_ENT, ALLY_ENT = 0x41000000, 0x41100000
    -- Attack-resolver fixtures.
    local CTX, ENEMY_A, ENEMY_B = 0x40000000, 0x43000000, 0x43100000
    local FOE_CTX, FOE = 0x40100000, 0x44000000
    local TARGETS, TDATA = 0x42000000, 0x42001000
    -- oCDtProcessedDamage: +0x10 -> value object, +0xa0 -> source info.
    local PD, PDVAL, PDSRC = 0x46000000, 0x46100000, 0x46200000

    for _, e in ipairs({ ME_ENT, ALLY_ENT, ENEMY_A, ENEMY_B, FOE }) do
        I.write_u64(e + 8, 0x13000000)          -- plausible component store
    end
    I.write_u64(ME + 0x08, ME_ENT)
    I.write_u64(ALLY + 0x08, ALLY_ENT)
    I.write_u8(ME + 0x1d88, 1)                  -- the engine's is-local flag
    I.write_u8(ALLY + 0x1d88, 0)
    -- Local/remote is the engine's is-local byte at +0x1d88 (see the co-op
    -- section for why it is neither the net component nor the HUD mirror).
    I.write_u8(ME_ENT + 0x1d88, 1)
    I.write_u8(ALLY_ENT + 0x1d88, 0)
    I.write_u64(CTX + 8, ME_ENT)
    I.write_u64(FOE_CTX + 8, FOE)
    I.write_u64(PD + 0x10, PDVAL)
    I.write_u64(PD + 0xa0, PDSRC)

    local heroes = { [ME_ENT] = true, [ALLY_ENT] = true }
    I.is_grant_target = function(e) return heroes[e] == true end

    local function set_targets(list)
        I.write_u32(TARGETS, #list)
        I.write_u64(TARGETS + 8, TDATA)
        for i, e in ipairs(list) do I.write_u64(TDATA + (i - 1) * 8, e) end
    end

    -- The name probe arms from enable(). Mocking mem_find is what makes it get
    -- as far as claiming its shared slot — without this the probe declines
    -- early and the slot choice is never exercised, which is exactly how it
    -- shipped sitting on the native hero ring.
    I.mem_find = function() return {} end

    Rd.damage.enable{ window = 10 }
    check(I.shared_get(7) == 1,
          "the name probe latches shared slot 7 — slots 8..15 are the native "
          .. "hero candidate ring and a write there evicts a spawn candidate")
    local stats_hook = hooks[I.resolve("HeroStats_OnDamageDealt")]
    local atk_hook   = hooks[I.resolve("Entity_ResolveAttackHits")]
    check(stats_hook ~= nil and stats_hook.sig == "vpppi",
          "enable() hooks the engine's per-hero damage bookkeeping")
    check(atk_hook ~= nil and atk_hook.sig == "fpupff",
          "the resolver hook carries all five arguments — a short signature "
          .. "would replay the original with a garbage stack-passed base damage")
    check(Rd.damage.tracks_allies(), "ally tracking reports as available")

    -- Source 1: the bookkeeping hook. `next` is never called by an observer,
    -- so the loader replays the original itself; the callback returns nil.
    local function deal(hero, amount, atk_type)
        I.write_f32(PDVAL + 8, amount)
        I.write_u16(PDSRC + 0xc8, atk_type or 0)
        return stats_hook.cb(hero, ENEMY_A, PD, 0, function() error("observer must not replay") end)
    end

    check(deal(ME, 40.0, 5) == nil, "the bookkeeping hook returns nothing (void)")
    deal(ALLY, 25.0, 0)
    deal(ALLY, 25.0, 0)

    local board = Rd.damage.board()
    check(#board == 2, "an ally is boarded from the engine's own hook")
    check(board[1].label == "Ally" or board[1].dealt == 50.0,
          "the board is ranked by damage, ally first at 50 vs 40")
    check(board[1].rank == 1 and board[2].rank == 2, "rows carry their rank")
    local me, ally
    for _, row in ipairs(board) do
        if row.is_local then me = row else ally = row end
    end
    check(me and me.label == "Ovilli",
          "the local row uses the real Steam name, not a placeholder")
    check(me and me.dealt == 40.0, "our damage is credited once")
    check(me and me.by_type.ultimate == 40.0, "damage is split by ability type")
    check(ally and ally.dealt == 50.0 and ally.hits == 2, "ally damage accumulates")
    check(ally and ally.label == "Player 2", "the ally gets a join-order label")

    -- The lobby roster names that ally, but ONLY off the background tick: the
    -- scan costs seconds and the label path runs inside a damage detour.
    -- Publish a lobby block for that ally and let the resolver run.
    local LB = 0x1f000000
    local function putb(va, s)
        for k = 1, #s do I.write_u8(va + k - 1, s:byte(k)) end
        I.write_u8(va + #s, 0)
    end
    putb(LB - 0x60, "RequestedHero")
    putb(LB - 0x50, "Scarlet")
    putb(LB, "PlayerName")
    putb(LB + 0x10, "Juice")
    I.mem_find = function(needle)
        if needle == "PlayerName\0" then return { LB } end
        return {}
    end
    Rd.lobby.refresh(true)
    Rd.damage.relabel()
    local named
    for _, row in ipairs(Rd.damage.board()) do
        if not row.is_local then named = row end
    end
    check(named and named.label == "Juice",
          "the ally row is renamed from the lobby roster once it resolves")
    -- Relabelling is idempotent: a second pass must not shuffle names.
    Rd.damage.relabel()
    local again
    for _, row in ipairs(Rd.damage.board()) do
        if not row.is_local then again = row end
    end
    check(again and again.label == "Juice", "relabelling twice is stable")
    check(math.abs(me.share - 40 / 90) < 1e-6, "share is the fraction of team damage")

    -- Source 3 must not double-count a hit this machine already applied.
    -- There is no net id to match players on (asking the engine for one
    -- crashed the game — dump a97c76fe), so the test is amount+time across
    -- EVERY row: if we just applied a hit that size, the event is that hit
    -- coming back from another peer.
    fire("gameplay:NETWORK_DAMAGE", { source = "gameplay", value = 25.0,
                                      source_id = "0x99" })
    check(Rd.damage.total() == 90.0, "a replicated echo of a counted hit is dropped")
    check(#Rd.damage.board() == 2, "and it invents no phantom player")

    -- Damage this machine did NOT apply is somebody else's work, and it gets
    -- its own row: a replicated event is the only thing we know about it.
    fire("gameplay:NETWORK_DAMAGE", { source = "gameplay", value = 7.0,
                                      source_id = "0x99" })
    check(Rd.damage.total() == 97.0, "unseen replicated damage is credited")
    check(#Rd.damage.board() == 3, "as a row of its own, keyed by the payload net id")

    -- A second event from that same peer joins the row it already made.
    fire("gameplay:NETWORK_DAMAGE", { source = "gameplay", value = 11.0,
                                      source_id = "0x99" })
    check(#Rd.damage.board() == 3, "the same net id lands on the same row")
    check(Rd.damage.total() == 108.0, "and adds to it")

    -- A different peer is a different row.
    fire("gameplay:NETWORK_DAMAGE", { source = "gameplay", value = 12.0,
                                      source_id = "0x123" })
    check(#Rd.damage.board() == 4, "another net id is another player")

    -- The echo filter is global, not per row: a hit we applied for the local
    -- player must not be credited again just because it arrives under an id
    -- we have never seen.
    deal(ME, 500.0, 0)
    local before_echo = Rd.damage.total()
    fire("gameplay:NETWORK_DAMAGE", { source = "gameplay", value = 500.0,
                                      source_id = "0xabc" })
    check(Rd.damage.total() == before_echo,
          "a replicated echo of a locally-applied hit is dropped")
    check(#Rd.damage.board() == 4, "and it invents no phantom player either")

    -- Source 2: the resolver. With the bookkeeping hook armed it must NOT add
    -- dealt damage (that would double every hit), but it is still the only
    -- source of damage TAKEN.
    local replayed
    local function swing(ctx, targets, dmg)
        return atk_hook.cb(ctx, 0, targets, 1.5, 0.0, function(a, b, c, d, e)
            replayed = { a, b, c, d, e }
            return dmg
        end)
    end
    local before_swing = Rd.damage.total()
    set_targets({ ENEMY_A, ENEMY_B })
    check(swing(CTX, TARGETS, 40.0) == 40.0, "the resolver hook returns the engine's damage")
    check(replayed[1] == CTX and replayed[3] == TARGETS and replayed[4] == 1.5,
          "the original is replayed with the arguments it was given")
    check(Rd.damage.total() == before_swing,
          "the resolver does not re-count damage the bookkeeping hook owns")

    -- Damage TAKEN comes from the engine's own per-hero received-damage hook,
    -- not from the resolver: on the shipped build the resolver's victim cannot
    -- be identified as a hero at all (is_grant_target says false for both the
    -- controller and controller+0x8), which left the column empty for a whole
    -- co-op run. The hook hands over the same hero object the dealt side does,
    -- so the two merge with no translation.
    local taken_hook = hooks[I.resolve("HeroStats_OnDamageTaken")]
    check(taken_hook ~= nil and taken_hook.sig == "vpp",
          "enable() hooks the engine's damage-received bookkeeping")

    local taken_seen = 0
    Rd.damage.on(function(hit) if hit.kind == "taken" then taken_seen = taken_seen + 1 end end)
    local rows_before = #Rd.damage.board()
    local dealt_before
    for _, row in ipairs(Rd.damage.board()) do
        if row.is_local then dealt_before = row.dealt end
    end

    I.write_f32(PDVAL + 8, 12.0)
    check(taken_hook.cb(ME, PD, function() error("observer must not replay") end) == nil,
          "the damage-taken hook returns nothing (void)")
    check(taken_seen == 1, "a hit on a hero publishes a 'taken' hit")
    local hurt
    for _, row in ipairs(Rd.damage.board()) do
        if row.taken > 0 then hurt = row end
    end
    check(hurt and hurt.taken == 12.0, "damage taken lands on the victim's row")
    check(hurt and hurt.is_local and hurt.dealt == dealt_before,
          "and on the SAME row as that player's damage dealt")
    check(#Rd.damage.board() == rows_before, "taking a hit boards nobody new")

    -- An ally taking damage is boarded as that ally, not as us.
    I.write_f32(PDVAL + 8, 5.0)
    taken_hook.cb(ALLY, PD, function() end)
    local ally_row
    for _, row in ipairs(Rd.damage.board()) do
        if not row.is_local and row.taken == 5.0 then ally_row = row end
    end
    check(ally_row ~= nil, "an ally's damage taken lands on the ally's row")

    Rd.damage.name(2, "Ada")
    for _, row in ipairs(Rd.damage.board()) do
        if row.slot == 2 then check(row.label == "Ada", "name() relabels a slot") end
    end
    local top = Rd.damage.board()[1]
    check(Rd.damage.leader().dealt == top.dealt and Rd.damage.leader().rank == 1,
          "leader() is the top of the ranking")

    Rd.damage.reset()
    check(#Rd.damage.board() == 0 and Rd.damage.total() == 0,
          "reset clears the board for the next run")

    -- Metering off means both callbacks still behave exactly as if the mod had
    -- never hooked: the game must not be able to tell.
    Rd.damage.disable()
    deal(ME, 9.0, 0)
    set_targets({ ENEMY_A })
    check(swing(CTX, TARGETS, 9.0) == 9.0, "damage is untouched while disabled")
    check(#Rd.damage.board() == 0, "nothing is recorded while disabled")

    I.is_grant_target = function() return true end
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.damage: enemies vs scenery -----------------------------------------
--
-- Damage dealt to fences, jars and dream-shard nodes reaches the bookkeeping
-- hook exactly like damage dealt to a boss, and the engine's own end-screen
-- total counts it — so the meter counted it too, and a player who cleared a
-- room of furniture out-ranked one who fought.
--
-- The victim is classified by its COMPONENT MAP: an oCEntity keeps components
-- in an F14 table (slots @entity+0x5f0, stride 0x10 = {u32 class id, cpnt*},
-- mask @+0x600) keyed by the engine's 32-bit CLASS ID, and a gameplay enemy
-- carries oCDtEntityCpntEnemyController = 0x1561073c
-- (tools/mine_class_ids.py). ⚠ The FIRST attempt read the pointer array at
-- entity+0x190 instead — that array belongs to an oCEntitySpawnerGo, not to an
-- oCEntity, so every enemy in the 2026-08-17 playtest classified as "unknown"
-- and the filter was inert. A class id also survives a game patch, which a
-- vftable VA does not.
--
-- Reads only, and an unreadable victim is UNKNOWN, which counts: a failed read
-- must never delete a real player's damage.
do
    package.loaded["rsmm"] = nil
    local Rs = require "rsmm"
    local logged = {}
    local saved_log = rsmm.log
    rsmm.log = function(...) logged[#logged + 1] = table.concat({ ... }, " ") end

    local ENEMY_ID, HERO_ID, OTHER_ID = 0x1561073c, 0x155aac59, 0x11110000
    local ENEMY_VFT = I.module_base() + (0x140f30b78 - 0x140000000)
    local OTHER_VFT = I.module_base() + 0x1000

    local HERO, HERO_ENT = 0x60000000, 0x61000000
    I.write_u64(HERO + 0x08, HERO_ENT)
    I.write_u8(HERO + 0x1d88, 1)
    I.write_u8(HERO_ENT + 0x1d88, 1)
    I.write_u64(HERO_ENT + 8, 0x13000000)

    -- Build a victim: `ids` is the class id in each map slot. The map is
    -- power-of-two sized, so the fixture pads to the next power of two and
    -- leaves the spare slots empty — exactly what a real table looks like.
    local next_addr = 0x62000000
    local function victim(ids, opts)
        opts = opts or {}
        local ent = next_addr; next_addr = next_addr + 0x100000
        local slots = next_addr; next_addr = next_addr + 0x100000
        local cap = 1
        while cap < #ids do cap = cap * 2 end
        I.write_u64(ent, OTHER_VFT)                    -- the entity's own vftable
        I.write_u64(ent + 0x5f0, slots)
        I.write_u64(ent + 0x600, cap - 1)              -- bucket mask
        for i = 1, cap do
            local slot = slots + (i - 1) * 0x10
            local id = ids[i]
            if id then
                local comp = next_addr; next_addr = next_addr + 0x1000
                I.write_u32(slot, id)
                I.write_u64(slot + 8, comp)
                I.write_u64(comp, id == ENEMY_ID and ENEMY_VFT or OTHER_VFT)
                I.write_u64(comp + 8, opts.orphan and 0 or ent)   -- owner back-ptr
            else
                I.write_u32(slot, 0)
                I.write_u64(slot + 8, 0)
            end
        end
        return ent
    end

    local GNOLL = victim({ OTHER_ID, ENEMY_ID, OTHER_ID })
    local FENCE = victim({ OTHER_ID, OTHER_ID })
    -- A NULL map: slots and mask both zero. Two of twelve victims in session
    -- ec1d looked like this, all of them 1.0-damage props.
    local BLANK = 0x63000000
    -- A BROKEN map: a non-null pointer that is not readable. This is the only
    -- shape that may answer "unknown".
    local TORN = 0x63100000
    I.write_u64(TORN + 0x5f0, 0x5)
    I.write_u64(TORN + 0x600, 3)

    check(Rs.damage.is_enemy(GNOLL) == true,
          "an entity carrying the EnemyController component is an enemy")
    check(Rs.damage.is_enemy(FENCE) == false,
          "a destructible prop carries no controller and is scenery")
    check(Rs.damage.is_enemy(BLANK) == false,
          "an entity with NO component map owns no controller either — a null "
          .. "map is an answer, not a failed read")
    check(Rs.damage.is_enemy(TORN) == nil,
          "a component map we cannot read is UNKNOWN, never asserted scenery")
    check(Rs.damage.is_enemy(0x1) == nil,
          "an implausible pointer is refused before any read")

    -- The match must not depend on the component's owner back-pointer, nor on
    -- its vftable: both are probe DIAGNOSTICS, not requirements. The class id
    -- is the test, because it is the only one of the three that survives a
    -- game patch.
    check(Rs.damage.is_enemy(victim({ ENEMY_ID }, { orphan = true })) == true,
          "the enemy test matches on the class id, not on the back-pointer")
    local ODD = victim({ ENEMY_ID })
    I.write_u64(I.read_u64(I.read_u64(ODD + 0x5f0) + 8), OTHER_VFT)
    check(Rs.damage.is_enemy(ODD) == true,
          "nor on the component's vftable — a subclass would carry its own")

    -- An empty slot must not be mistaken for a component: id 0 with a null
    -- pointer is what most of a real table holds.
    check(Rs.damage.is_enemy(victim({ nil, nil, nil, nil })) == false,
          "empty map slots classify as scenery, not as an unreadable entity")

    I.mem_find = function() return {} end
    Rs.damage.enable{ window = 10, probe = true }
    local stats = hooks[I.resolve("HeroStats_OnDamageDealt")]
    local PD2, PDVAL2, PDSRC2 = 0x64000000, 0x64100000, 0x64200000
    I.write_u64(PD2 + 0x10, PDVAL2)
    I.write_u64(PD2 + 0xa0, PDSRC2)
    local function hit(target, amount)
        I.write_f32(PDVAL2 + 8, amount)
        I.write_u16(PDSRC2 + 0xc8, 0)
        stats.cb(HERO, target, PD2, 0, function() end)
    end

    -- Default is OFF: the meter agrees with the game, whose own end-screen
    -- total counts prop damage.
    check(Rs.damage.ignore_scenery() == false,
          "scenery filtering is opt-in — the default matches the game's total")
    hit(GNOLL, 10.0); hit(FENCE, 90.0)
    check(Rs.damage.total() == 100.0, "with the filter off, prop damage counts")

    Rs.damage.reset()
    check(Rs.damage.ignore_scenery(true) == true, "the filter can be toggled at runtime")
    hit(GNOLL, 10.0); hit(FENCE, 90.0); hit(FENCE, 5.0)
    check(Rs.damage.total() == 10.0,
          "with the filter on, only damage dealt to enemies is ranked")
    local row = Rs.damage.board()[1]
    check(row.scenery == 95.0 and row.scenery_hits == 2,
          "the dropped damage is still totalled per row, never silently lost")
    check(Rs.damage.scenery_total() == 95.0, "and session-wide")
    check(row.hits == 1, "a filtered hit does not inflate the hit count")

    hit(TORN, 7.0)
    check(Rs.damage.total() == 17.0,
          "an UNREADABLE victim is still counted — a failed read must never "
          .. "delete a player's damage")

    Rs.damage.reset()
    check(Rs.damage.scenery_total() == 0, "reset clears the scenery total too")

    -- The probe is a diagnostic, and it runs on the MAIN THREAD inside the
    -- damage detour: it must report each victim once and then stop for good.
    local probes = 0
    for _, line in ipairs(logged) do
        if line:find("victim probe #", 1, true) and not line:find("components:", 1, true) then
            probes = probes + 1
        end
    end
    check(probes == 3, "the probe reports each distinct victim exactly once")
    hit(GNOLL, 1.0)
    local probes2 = 0
    for _, line in ipairs(logged) do
        if line:find("victim probe #", 1, true) and not line:find("components:", 1, true) then
            probes2 = probes2 + 1
        end
    end
    check(probes2 == probes, "and never reports the same victim twice")

    local enemy_line
    for _, line in ipairs(logged) do
        if line:find("victim probe", 1, true) and line:find("enemy=true", 1, true) then
            enemy_line = line
        end
    end
    check(enemy_line and enemy_line:find("slot=1", 1, true),
          "the probe reports which component slot matched")
    check(enemy_line and enemy_line:find("owner_ok=true", 1, true),
          "and whether the matched component's back-pointer agrees")

    Rs.damage.ignore_scenery(false)
    Rs.damage.disable()
    rsmm.log = saved_log
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.damage: an unreadable victim is classified by its TYPE ---------------
--
-- `unknown` is FAIL-OPEN — the damage is counted, because a bad read must never
-- delete a real player's damage. That makes an unreadable victim FAMILY
-- expensive: the 2026-08-18 co-op log put one player at 11,612 hits for 613k
-- damage (59 per hit, against 353 for the top row), with long runs of exactly
-- 1.0 (the flat per-hit prop value) and a `scenery` column frozen for the last
-- four minutes while their hit count kept climbing. Thousands of prop hits were
-- arriving as carry damage.
--
-- Instances of one prop type share an oCEntitySettings object (+0x28) — the
-- victim probe logs it for that reason — so a CONCLUSIVE scan of one jar can
-- answer for every other jar, including the ones whose own component map does
-- not read. And a row now carries how much of it rests on an unclassified
-- victim, so a board that looks wrong can be checked rather than argued about.
do
    package.loaded["rsmm"] = nil
    local Rs = require "rsmm"
    local logged = {}
    local saved_log = rsmm.log
    rsmm.log = function(...) logged[#logged + 1] = table.concat({ ... }, " ") end

    local ENEMY_ID, OTHER_ID = 0x1561073c, 0x11110000
    local ENEMY_VFT = I.module_base() + (0x140f30b78 - 0x140000000)
    local OTHER_VFT = I.module_base() + 0x1000
    local JAR_SETTINGS, GNOLL_SETTINGS = 0x66000000, 0x66100000

    local HERO, HERO_ENT = 0x67000000, 0x67100000
    I.write_u64(HERO + 0x08, HERO_ENT)
    I.write_u8(HERO + 0x1d88, 1)
    I.write_u64(HERO_ENT + 8, 0x13000000)

    local next_addr = 0x68000000
    -- `ids == nil` builds the TORN map (a non-null slot pointer that cannot be
    -- read) — the only shape that answers unknown.
    local function victim(ids, settings)
        local ent = next_addr; next_addr = next_addr + 0x100000
        I.write_u64(ent, OTHER_VFT)
        I.write_u64(ent + 0x28, settings or 0)
        if not ids then
            I.write_u64(ent + 0x5f0, 0x5)
            I.write_u64(ent + 0x600, 3)
            return ent
        end
        local slots = next_addr; next_addr = next_addr + 0x100000
        local cap = 1
        while cap < #ids do cap = cap * 2 end
        I.write_u64(ent + 0x5f0, slots)
        I.write_u64(ent + 0x600, cap - 1)
        for i = 1, cap do
            local slot = slots + (i - 1) * 0x10
            local id = ids[i]
            if id then
                local comp = next_addr; next_addr = next_addr + 0x1000
                I.write_u32(slot, id)
                I.write_u64(slot + 8, comp)
                I.write_u64(comp, id == ENEMY_ID and ENEMY_VFT or OTHER_VFT)
                I.write_u64(comp + 8, ent)
            else
                I.write_u32(slot, 0)
                I.write_u64(slot + 8, 0)
            end
        end
        return ent
    end

    -- A torn jar asked FIRST is unknown: nothing has been learned yet.
    local TORN_JAR = victim(nil, JAR_SETTINGS)
    check(Rs.damage.is_enemy(TORN_JAR) == nil,
          "an unreadable victim of an unlearned type is still unknown")

    -- One readable jar of the same type answers for the whole family.
    local GOOD_JAR = victim({ OTHER_ID, OTHER_ID }, JAR_SETTINGS)
    check(Rs.damage.is_enemy(GOOD_JAR) == false, "the readable jar is scenery")
    check(Rs.damage.is_enemy(victim(nil, JAR_SETTINGS)) == false,
          "another unreadable jar of the SAME type is scenery too — this is the "
          .. "leak that put thousands of flat-1.0 prop hits on the board")
    check(Rs.damage.is_enemy(TORN_JAR) == false,
          "and the one already cached as unknown is re-answered, not stuck")

    -- The type map must not overreach: a torn victim of an UNRELATED type is
    -- still unknown, and unknown still counts.
    local GOOD_GNOLL = victim({ ENEMY_ID }, GNOLL_SETTINGS)
    check(Rs.damage.is_enemy(GOOD_GNOLL) == true, "the readable gnoll is an enemy")
    check(Rs.damage.is_enemy(victim(nil, 0x66200000)) == nil,
          "an unreadable victim of an unrelated type stays unknown")
    check(Rs.damage.is_enemy(victim(nil, GNOLL_SETTINGS)) == true,
          "the type map answers for enemies as well, not only for props")

    -- A victim with NO settings pointer cannot be learned by type, and must not
    -- pick up some other family's answer.
    check(Rs.damage.is_enemy(victim(nil, 0)) == nil,
          "a torn victim with no settings pointer is unknown, never guessed")

    -- The per-row tally: unknown damage is COUNTED (fail-open) and also
    -- reported, so `hits` and `dps` can be sanity-checked against it.
    I.mem_find = function() return {} end
    Rs.damage.enable{ window = 10 }
    Rs.damage.ignore_scenery(true)
    Rs.damage.reset()
    local stats = hooks[I.resolve("HeroStats_OnDamageDealt")]
    local PD, PDVAL, PDSRC = 0x69000000, 0x69100000, 0x69200000
    I.write_u64(PD + 0x10, PDVAL)
    I.write_u64(PD + 0xa0, PDSRC)
    local function hit(target, amount)
        I.write_f32(PDVAL + 8, amount)
        I.write_u16(PDSRC + 0xc8, 0)
        stats.cb(HERO, target, PD, 0, function() end)
    end
    local MYSTERY = victim(nil, 0x66300000)
    hit(GOOD_GNOLL, 100.0)
    hit(MYSTERY, 1.0)
    hit(MYSTERY, 1.0)
    local row = Rs.damage.board()[1]
    check(row.dealt == 102.0, "unclassified damage is still counted")
    check(row.unknown == 2.0 and row.unknown_hits == 2,
          "and reported separately, so a row full of prop chip damage is visible")
    check(row.hits == 3, "those hits are in the hit count, as they are counted")

    -- `taken` must not claim 0 for a player nothing ever reported a hit on: on
    -- this build the damage-RECEIVED bookkeeping only fires for heroes this
    -- machine owns, so every ALLY read exactly 0 for a whole 55-minute run.
    check(row.taken == 0 and row.taken_known == false,
          "taken_known is false until some source has actually reported a hit")
    local taken = hooks[I.resolve("HeroStats_OnDamageTaken")]
    if taken then
        I.write_f32(PDVAL + 8, 25.0)
        taken.cb(HERO, PD, function() end)
        local hurt = Rs.damage.board()[1]
        check(hurt.taken == 25.0 and hurt.taken_known == true,
              "and true once one has")
    end

    check(Rs.damage.board()[1].dps_window == 10,
          "the board reports the window its dps covers, so a caller can label it")

    Rs.damage.ignore_scenery(false)
    Rs.damage.disable()
    rsmm.log = saved_log
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.damage: a chapter change must not fork the board -------------------
--
-- From a real run (2026-08-17 evening): a four-player lobby produced SEVEN
-- rows. "Juice" appeared twice, both flagged as the local player; labels ran to
-- "Player 7"; and the abandoned rows sat at 0.0 dps for the rest of the run
-- while their totals still counted toward every `share`. Cause: rows were keyed
-- by the hero CONTROLLER pointer, and crossing into the next chapter rebuilds
-- every controller, so each player forked a second row halfway through.
--
-- A player is re-adopted by hero id when the sweep has confirmed where that
-- lives, and by the engine's is-local byte otherwise — there is only ever one
-- local player, so a second local controller is the same person.
do
    package.loaded["rsmm"] = nil
    local Rc = require "rsmm"
    local logged = {}
    local saved_log = rsmm.log
    rsmm.log = function(...) logged[#logged + 1] = table.concat({ ... }, " ") end

    -- Chapter 1 controllers, then chapter 2's replacements for the same two
    -- players. The ally's hero id is planted at the offset the sweep finds.
    local HERO_OFF = 0x1ae0
    local ME1, ME2 = 0x70000000, 0x70100000
    local ALLY1, ALLY2 = 0x70200000, 0x70300000
    local function controller(addr, is_local, hero_id, entity)
        I.write_u64(addr + 0x08, entity)
        I.write_u8(addr + 0x1d88, is_local and 1 or 0)
        I.write_u32(addr + HERO_OFF, hero_id)
        I.write_u64(entity + 8, 0x13000000)
        I.write_u8(entity + 0x1d88, is_local and 1 or 0)
    end
    controller(ME1,   true,  4, 0x71000000)
    controller(ALLY1, false, 7, 0x71100000)
    controller(ME2,   true,  4, 0x71200000)   -- chapter 2: same players,
    controller(ALLY2, false, 7, 0x71300000)   -- brand new controllers

    I.mem_find = function() return {} end
    Rc.damage.enable{ window = 10 }
    local stats = hooks[I.resolve("HeroStats_OnDamageDealt")]
    local PD3, PDV3, PDS3 = 0x72000000, 0x72100000, 0x72200000
    I.write_u64(PD3 + 0x10, PDV3)
    I.write_u64(PD3 + 0xa0, PDS3)
    local ENEMY = 0x73000000
    I.write_u64(ENEMY + 0x5f0, 0x73100000)
    I.write_u64(ENEMY + 0x600, 0)
    I.write_u32(0x73100000, 0x1561073c)
    I.write_u64(0x73100000 + 8, 0x73200000)
    local function deal(who, amount)
        I.write_f32(PDV3 + 8, amount)
        I.write_u16(PDS3 + 0xc8, 0)
        stats.cb(who, ENEMY, PD3, 0, function() end)
    end

    -- The hero-id sweep checks candidate offsets against the LOBBY roster, so
    -- seed it the way the game does — through the attribute parser.
    Rc.lobby._note_blob('{"PlayerName":"Juice","RequestedHero":4}')
    Rc.lobby._note_blob('{"PlayerName":"Ada","RequestedHero":7}')

    -- The ALLY deals damage first, deliberately: the sweep cannot run until a
    -- second row exists, so whoever boards first has no hero id at creation and
    -- depends on the backfill. An ally boarding first is the ordinary case (the
    -- host's enemies are hit by whoever engages first), and it is the row that
    -- showed up as a "phantom player" after the chapter change.
    deal(ALLY1, 50.0)
    deal(ME1, 100.0)
    check(#Rc.damage.board() == 2, "chapter 1 boards one row per player")
    local swept
    for _, line in ipairs(logged) do
        if line:find("hero-id field probe", 1, true) then swept = line end
    end
    check(swept and swept:find("ADOPTED", 1, true),
          "the hero-id sweep adopts the one offset that reads a DIFFERENT known "
          .. "hero id for every row")
    check(Rc.damage.hero_id_offset() == HERO_OFF,
          "and the adopted offset is the field the ids were planted at")

    -- Chapter 2: the same two players, through new controllers.
    --
    -- The chapter EVENT is what makes the rebind legal. A new controller is
    -- only ever a rebuilt one after the engine has torn a chapter down; inside
    -- one chapter it is another player, and adopting it merges two people onto
    -- one row (2026-08-18: a four-player run showed two rows). So the epoch has
    -- to move before any of this is allowed to happen.
    fire("gameplay:GAME_END_NEXT_CHAPTER", { source = "gameplay" })
    deal(ALLY2, 25.0)
    deal(ME2, 25.0)

    local board = Rc.damage.board()
    check(#board == 2,
          "a chapter change re-adopts both players instead of forking the board")
    local locals = 0
    for _, row in ipairs(board) do if row.is_local then locals = locals + 1 end end
    check(locals == 1,
          "and the local player is never listed twice — there is only one of you")
    local me
    for _, row in ipairs(board) do if row.is_local then me = row end end
    check(me and me.dealt == 125.0,
          "the re-adopted row keeps its chapter-1 total and keeps counting")
    check(Rc.damage.total() == 200.0, "no damage is lost or double-counted")

    local rebound = false
    for _, line in ipairs(logged) do
        if line:find("rebound", 1, true) then rebound = true end
    end
    check(rebound, "the rebind is logged — a silent identity change is unreadable")

    -- The row boarded FIRST predates the sweep (which needs two rows before it
    -- can run), so it carries no hero id at the moment it is created. Unless it
    -- is backfilled it forks at the next chapter anyway — and since the sweep
    -- fires on the SECOND player's first hit, the un-backfilled row is usually
    -- an ally, which is precisely the "phantom player" left on the board.
    local ally
    for _, row in ipairs(Rc.damage.board()) do
        if not row.is_local then ally = row end
    end
    check(ally and ally.hero_id == 7,
          "a row boarded before the sweep is backfilled with its hero id")
    check(ally and ally.dealt == 75.0,
          "so the ally is re-adopted across the chapter change too, not forked")

    Rc.damage.disable()
    Rc.damage.reset()
    rsmm.log = saved_log
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.damage: an AMBIGUOUS hero-id sweep must not be adopted --------------
--
-- The sweep runs on a two-row sample, and two rows are enough for an unrelated
-- field to hold two distinct known hero ids by chance. Adopting the wrong
-- offset is worse than adopting none: two different players would then read the
-- same identity and be MERGED into one row — the mirror image of the bug the
-- identity exists to fix, and much harder to notice on a live board.
do
    package.loaded["rsmm"] = nil
    local Ra = require "rsmm"
    local logged = {}
    local saved_log = rsmm.log
    rsmm.log = function(...) logged[#logged + 1] = table.concat({ ... }, " ") end

    local ME, ALLY = 0x78000000, 0x78100000
    for addr, id in pairs({ [ME] = 4, [ALLY] = 7 }) do
        local ent = addr + 0x8000
        I.write_u64(addr + 0x08, ent)
        I.write_u8(addr + 0x1d88, addr == ME and 1 or 0)
        I.write_u64(ent + 8, 0x13000000)
        -- TWO fields that both read as a distinct known hero id.
        I.write_u32(addr + 0x1ae0, id)
        I.write_u32(addr + 0x0800, id)
    end

    I.mem_find = function() return {} end
    Ra.lobby._note_blob('{"PlayerName":"Juice","RequestedHero":4}')
    Ra.lobby._note_blob('{"PlayerName":"Ada","RequestedHero":7}')
    Ra.damage.enable{ window = 10 }
    local stats = hooks[I.resolve("HeroStats_OnDamageDealt")]
    local PD4, PDV4, PDS4 = 0x79000000, 0x79100000, 0x79200000
    I.write_u64(PD4 + 0x10, PDV4)
    I.write_u64(PD4 + 0xa0, PDS4)
    I.write_f32(PDV4 + 8, 10.0)
    stats.cb(ME, 0x7a000000, PD4, 0, function() end)
    stats.cb(ALLY, 0x7a000000, PD4, 0, function() end)

    local sweep
    for _, line in ipairs(logged) do
        if line:find("hero-id field probe", 1, true) then sweep = line end
    end
    check(sweep and sweep:find("ambiguous", 1, true),
          "two candidate offsets are reported as ambiguous, not adopted")
    check(Ra.damage.hero_id_offset() == nil,
          "and NO identity is adopted from an ambiguous sweep — merging two "
          .. "players onto one row is worse than forking one player onto two")

    Ra.damage.disable()
    Ra.damage.reset()
    rsmm.log = saved_log
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.damage: four live players must never be merged onto one row --------
--
-- From a real four-player run (2026-08-18, session 29a8): the board showed TWO
-- players. The chapter-fork fix had taught F._dmg_rebind to adopt an existing
-- row whenever it met a hero controller it had not seen before — but that is
-- also exactly what the THIRD and FOURTH players look like when they first deal
-- damage. Two joins can do it: a misread is-local byte (every ally folds onto
-- your row) or a wrongly adopted hero-id offset (an ally reads someone else's
-- id). Both are gated on the chapter EPOCH now: inside one chapter a new
-- controller is a new person, full stop.
do
    package.loaded["rsmm"] = nil
    local Rm = require "rsmm"
    local logged = {}
    local saved_log = rsmm.log
    rsmm.log = function(...) logged[#logged + 1] = table.concat({ ... }, " ") end

    -- Four controllers, and the WORST CASE for each join: every one of them
    -- reads back as the local player, and every one of them carries the SAME
    -- value at the field a hero-id sweep might pick. Nothing here may merge.
    local P = { 0x7b000000, 0x7b100000, 0x7b200000, 0x7b300000 }
    for i, addr in ipairs(P) do
        local ent = addr + 0x8000
        I.write_u64(addr + 0x08, ent)
        I.write_u8(addr + 0x1d88, 1)          -- misread: "this is my player"
        I.write_u64(ent + 8, 0x13000000)
        I.write_u8(ent + 0x1d88, 1)
        I.write_u32(addr + 0x1ae0, 4)         -- one id for all four rows
        local _ = i
    end

    I.mem_find = function() return {} end
    Rm.damage.enable{ window = 10 }
    local stats = hooks[I.resolve("HeroStats_OnDamageDealt")]
    local PD, PDV, PDS = 0x7c000000, 0x7c100000, 0x7c200000
    I.write_u64(PD + 0x10, PDV)
    I.write_u64(PD + 0xa0, PDS)
    I.write_f32(PDV + 8, 10.0)
    I.write_u16(PDS + 0xc8, 0)
    for _, addr in ipairs(P) do stats.cb(addr, 0x7d000000, PD, 0, function() end) end

    check(#Rm.damage.board() == 4,
          "four players in ONE chapter board four rows — an unseen controller "
          .. "inside a chapter is a different player, never a rebuilt one")
    local total = 0
    for _, row in ipairs(Rm.damage.board()) do total = total + row.dealt end
    check(total == 40.0, "and every player's damage is still on the board")
    local refused = false
    for _, line in ipairs(logged) do
        if line:find("refused to merge", 1, true) then refused = true end
    end
    check(refused,
          "the declined merge is logged — a refusal that leaves a duplicate row "
          .. "must be explainable from the log alone")

    -- And the rebind still WORKS once the chapter really does change: the same
    -- four players come back on new controllers and are re-adopted, not forked.
    fire("gameplay:GAME_END_NEXT_CHAPTER", { source = "gameplay" })
    local Q = { 0x7b400000, 0x7b500000, 0x7b600000, 0x7b700000 }
    for _, addr in ipairs(Q) do
        local ent = addr + 0x8000
        I.write_u64(addr + 0x08, ent)
        I.write_u8(addr + 0x1d88, 1)
        I.write_u64(ent + 8, 0x13000000)
        I.write_u32(addr + 0x1ae0, 4)
    end
    stats.cb(Q[1], 0x7d000000, PD, 0, function() end)
    check(#Rm.damage.board() == 4,
          "after a chapter change a rebuilt controller is adopted again, so the "
          .. "board does not grow a fifth row")

    Rm.damage.disable()
    Rm.damage.reset()
    rsmm.log = saved_log
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. co-op: an ally must not steal the local hero capture ----------------
--
-- From a real 4-player session (2026-08-15): allies fire the very same anchor
-- events (ABILITY_EXIT, COMBO_LINK, ...) from their own dispatchers. With no
-- local/remote test the capture flip-flopped to whichever ally acted last, and
-- every flip invalidated the published hero — ~500 identical "hero CAPTURED"
-- lines in ninety seconds, and R.give / R.combat / R.stat aimed at somebody
-- else's character for the whole run.
do
    package.loaded["rsmm"] = nil
    local Rc = require "rsmm"
    local saved_shared = {}
    for k, v in pairs(shared) do saved_shared[k] = v end
    local logged = {}
    local saved_log = rsmm.log
    rsmm.log = function(...)
        logged[#logged + 1] = table.concat({ ... }, " ")
    end

    local OFF = 0x520
    local MINE, ALLY = 0x1a000000, 0x1a800000
    local function hero_at(addr)
        I.write_f32(addr + 0x15c8, 50.0)
        I.write_f32(addr + 0x15cc, 100.0)
        I.write_u64(addr + 0x1d80, 0x12340000)
        I.write_u64(addr + 8, 0x13000000)
        I.write_u64(0x13000000, 0x13000100)
        local d = addr + OFF
        I.write_u64(d, 0x140f00000)          -- dispatcher vtable, inside the image
        return d
    end
    local d_mine, d_ally = hero_at(MINE), hero_at(ALLY)
    -- An ally is told apart by the engine's own is-local byte at +0x1d88.
    -- Not the net component (that engine call crashed the game) and not the
    -- HUD mirror (a live probe found an ALLY carrying one).
    I.write_u8(MINE + 0x1d88, 1)
    I.write_u8(ALLY + 0x1d88, 0)

    -- Teach the dispatcher offset. It needs two distinct CAPTURED heroes, and
    -- only a local one can ever be captured (the plausibility gate requires a
    -- HUD mirror) — in a real session that is a character switch or a new run,
    -- never an ally.
    local MINE2 = 0x1b000000
    local d_mine2 = hero_at(MINE2)
    I.write_u8(MINE2 + 0x1d88, 1)
    shared[0] = MINE
    check(Rc.entity.hero() == MINE, "spec fixture: local hero captured")
    fire("gameplay:ABILITY_EXIT", { source = "gameplay",
                                    dispatcher = string.format("0x%x", d_mine) })
    shared[0] = MINE2
    check(Rc.entity.hero() == MINE2, "spec fixture: a second local hero is seen")
    fire("gameplay:COMBO_LINK", { source = "gameplay",
                                  dispatcher = string.format("0x%x", d_mine2) })

    -- Now the offset is known, so the local/remote test can run. Publish OUR
    -- hero and make it the captured dispatcher first — the teaching fires above
    -- left the ALLY as the last one seen, and asserting against that would pass
    -- whether or not the guard exists.
    shared[0] = MINE
    Rc.entity.hero()
    fire("gameplay:ENERGY_COUNTER_INC", { source = "gameplay",
                                          dispatcher = string.format("0x%x", d_mine) })
    check(Rc.give.hero() == d_mine, "our own dispatcher is captured")

    -- Now let the ally act repeatedly. Nothing about our capture may move.
    for _ = 1, 5 do
        fire("gameplay:ABILITY_EXIT", { source = "gameplay",
                                        dispatcher = string.format("0x%x", d_ally) })
    end
    check(Rc.give.hero() == d_mine, "an ally's dispatcher never becomes ours")
    check(shared[0] == MINE, "and the published hero is left alone")

    -- One capture, one line — no matter how often the hero is polled.
    local captures = 0
    for _, line in ipairs(logged) do
        if line:find("hero CAPTURED", 1, true) then captures = captures + 1 end
    end
    for _ = 1, 20 do Rc.entity.hero() end
    local after = 0
    for _, line in ipairs(logged) do
        if line:find("hero CAPTURED", 1, true) then after = after + 1 end
    end
    check(after == captures, "re-polling a live capture logs nothing further")

    -- Second guard, for the window BEFORE the dispatcher offset is known (a
    -- fresh run: nothing can be told apart yet, so ally events are accepted).
    -- Dropping a LIVE capture there is what produced the re-capture storm, so
    -- the capture may only be invalidated once it has actually gone stale.
    package.loaded["rsmm"] = nil
    local Rf = require "rsmm"          -- fresh state: offset unlearned
    shared[0] = MINE
    check(Rf.entity.hero() == MINE, "spec fixture: live capture in a fresh state")
    fire("gameplay:ABILITY_EXIT", { source = "gameplay",
                                    dispatcher = string.format("0x%x", d_mine) })
    fire("gameplay:ABILITY_EXIT", { source = "gameplay",
                                    dispatcher = string.format("0x%x", d_ally) })
    check(shared[0] == MINE,
          "a live capture survives an unrecognised dispatcher change")

    rsmm.log = saved_log
    for k in pairs(shared) do shared[k] = nil end
    for k, v in pairs(saved_shared) do shared[k] = v end
    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. the name probe's string enumerator -----------------------------------
--
-- This parser is what turns the next co-op log into a struct layout: it must
-- report the OFFSET a name sits at, and it must see UTF-16 names, because
-- session 3e36 showed the local name narrow ("Brig", with a "Me" marker) and
-- another player's name wide ("E.a.t.c.h") inside the same 0x90-byte record.
-- Miss either and the log looks empty for reasons that have nothing to do
-- with the game. Cheaper to pin here than to spend a playtest on it.
do
    package.loaded["rsmm"] = nil
    local Rs = require "rsmm"
    local BASE = 0x1c000000
    local function put(off, s)
        for k = 1, #s do I.write_u8(BASE + off + k - 1, s:byte(k)) end
        I.write_u8(BASE + off + #s, 0)
    end
    local function put_wide(off, s)
        for k = 1, #s do
            I.write_u8(BASE + off + (k - 1) * 2, s:byte(k))
            I.write_u8(BASE + off + (k - 1) * 2 + 1, 0)
        end
        I.write_u8(BASE + off + #s * 2, 0)
        I.write_u8(BASE + off + #s * 2 + 1, 0)
    end
    put(-0x0c, "Me")            -- the slot marker seen before the local name
    put(0, "Brig")              -- the local name, narrow, at the hit itself
    put_wide(0x40, "Eatch")     -- another player's name, wide, same record

    local by = {}
    for _, s in ipairs(Rs.debug.strings_at(BASE, { before = 0x20, after = 0x80 })) do
        by[s.text] = s
    end
    check(by["Me"] == nil,
          "min_len defaults to 3, so the two-character slot marker is dropped")
    -- ...which is why the record dump lowers it: "Me" is how the local slot
    -- is told apart from an ally's, and losing it loses that.
    local by2 = {}
    for _, s in ipairs(Rs.debug.strings_at(BASE,
            { before = 0x20, after = 0x80, min_len = 2 })) do
        by2[s.text] = s
    end
    check(by2["Me"] and by2["Me"].off == -0x0c,
          "a narrow string is reported at its signed offset from the hit")
    check(by["Brig"] and by["Brig"].off == 0 and by["Brig"].wide == false,
          "the searched name is reported at offset 0, narrow")
    check(by["Eatch"] and by["Eatch"].off == 0x40 and by["Eatch"].wide == true,
          "a UTF-16 name in the same record is decoded, not missed — this is "
          .. "the ally name the whole probe exists to find")
    check(by["E"] == nil,
          "the narrow pass does not shred a wide string into single letters")
    -- min_len must not be satisfied by the stray printable bytes that fill
    -- any real struct, or every record dump drowns in two-character noise.
    put(0x60, "ab")
    local short = Rs.debug.strings_at(BASE, { before = 0, after = 0x70 })
    local saw_short = false
    for _, s in ipairs(short) do if s.text == "ab" then saw_short = true end end
    check(not saw_short, "runs below min_len are dropped")
end

-- N. MSVC std::string decoding ---------------------------------------------
--
-- A lobby attribute is a key/value pair of std::strings, so reading the value
-- beside a `PlayerName` key IS the ally name. Both storage forms have to work
-- (short strings live inline, long ones behind a pointer), and — the part that
-- makes it usable as a probe over arbitrary offsets — a slot that is NOT a
-- string must say so rather than return garbage.
do
    package.loaded["rsmm"] = nil
    local Rz = require "rsmm"
    local S = 0x1d000000
    local function put_sso(va, s)
        for k = 1, #s do I.write_u8(va + k - 1, s:byte(k)) end
        I.write_u8(va + #s, 0)
        I.write_u64(va + 0x10, #s)
        I.write_u64(va + 0x18, 15)
    end
    local function put_heap(va, buf, s)
        for k = 1, #s do I.write_u8(buf + k - 1, s:byte(k)) end
        I.write_u8(buf + #s, 0)
        I.write_u64(va, buf)
        I.write_u64(va + 0x10, #s)
        I.write_u64(va + 0x18, 31)
    end

    put_sso(S, "Brig")
    check(Rz.debug.stdstring_at(S) == "Brig", "a short std::string is read inline")

    put_heap(S + 0x20, S + 0x200, "AnAllyWithALongName")
    check(Rz.debug.stdstring_at(S + 0x20) == "AnAllyWithALongName",
          "a long std::string is followed through its heap pointer")

    -- Rejection: capacity below 15 is not a std::string, and size > capacity
    -- is a struct being misread. Both must return nil, or every probed offset
    -- reports a "name".
    I.write_u64(S + 0x40 + 0x10, 4)
    I.write_u64(S + 0x40 + 0x18, 3)
    check(Rz.debug.stdstring_at(S + 0x40) == nil, "an implausible capacity is rejected")
    I.write_u64(S + 0x60 + 0x10, 99)
    I.write_u64(S + 0x60 + 0x18, 15)
    check(Rz.debug.stdstring_at(S + 0x60) == nil, "size beyond capacity is rejected")
end

-- N. R.lobby: real player names from the lobby attribute table -------------
--
-- Reproduces the block found at 0x62fceb40 in session 364f exactly: 32-byte
-- entries, key at +0, value at +0x10. The anchor check ("RequestedHero" at
-- -0x60) is the load-bearing part — Lua interns the literal "PlayerName" for
-- this very search, and every session before the anchor existed drowned in
-- those self-hits.
do
    package.loaded["rsmm"] = nil
    local Rl = require "rsmm"
    local BLOCK = 0x1e000000
    local function put(va, s)
        for k = 1, #s do I.write_u8(va + k - 1, s:byte(k)) end
        I.write_u8(va + #s, 0)
    end
    -- A real member record.
    put(BLOCK - 0x60, "RequestedHero")
    put(BLOCK - 0x50, "Aladdin")
    put(BLOCK - 0x20, "InLobby")
    put(BLOCK, "PlayerName")
    put(BLOCK + 0x10, "Juice")
    -- A DECOY: the literal alone, exactly as Lua's string table holds it.
    local DECOY = 0x1e001000
    put(DECOY, "PlayerName")

    I.mem_find = function(needle)
        if needle == "PlayerName\0" then return { DECOY, BLOCK } end
        return {}
    end

    -- refresh() is the ONLY scanning entry point; members() is cache-only so
    -- it can be called from the main thread without a multi-second freeze.
    check(#Rl.lobby.members() == 0,
          "members() returns nothing before a refresh — it must never scan")
    local members = Rl.lobby.refresh(true)
    check(#members == 1, "the bare literal is rejected; only the anchored "
          .. "block counts as a lobby member")
    check(members[1] and members[1].name == "Juice",
          "the member's display name is read from key+0x10")
    check(members[1] and members[1].hero == "Aladdin",
          "the requested hero is read from the same value offset")

    -- allies() must drop the local player, or the board labels an ally with
    -- our own name.
    put(0x1e002000 - 0x60, "RequestedHero")
    put(0x1e002000, "PlayerName")
    put(0x1e002000 + 0x10, "Ovilli")          -- the mocked Steam persona
    I.mem_find = function(needle)
        if needle == "PlayerName\0" then return { BLOCK, 0x1e002000 } end
        return {}
    end
    -- SLICED SWEEP. A full pass costs ~4 s and hitches the game even off the
    -- main thread, so mem_find is resumable: it returns where it stopped and
    -- the next call continues from there. Findings must ACCUMULATE across
    -- slices, and a half-finished sweep must not publish a roster that is
    -- missing the members it has not reached yet.
    local A, B = 0x1e003000, 0x1e004000
    for _, va in ipairs({ A, B }) do
        put(va - 0x60, "RequestedHero")
        put(va, "PlayerName")
    end
    put(A + 0x10, "Ann")
    put(B + 0x10, "Bo")
    local slice = 0
    I.mem_find = function(needle, _max, _mb, from)
        if needle ~= "PlayerName\0" then return {}, 0 end
        slice = slice + 1
        if from == 0 then return { A }, 0x1e003800 end   -- paused mid-sweep
        return { B }, 0                                   -- finished
    end
    _G.__lobby_reset = true
    Rl.lobby.refresh(true)      -- force: drains every slice in one call
    local both = Rl.lobby.members()
    check(#both == 2, "a forced refresh drains every slice and finds both "
          .. "members, not just the first slice's")
    check(slice >= 2, "the sweep really did resume rather than stop at the "
          .. "first partial result")

    I.mem_find = function(needle)
        if needle == "PlayerName\0" then return { BLOCK }, 0 end
        return {}, 0
    end
    Rl.lobby.refresh(true)
    local allies = Rl.lobby.allies()
    check(#allies == 1 and allies[1] == "Juice",
          "allies() excludes the local player by Steam name")
end

-- N0. Hero diagnostics are gated on being IN A RUN ------------------------
--
-- There is no hero to find in the main menu. Session 6c4f sat there for eleven
-- minutes, spent all six process-wide field scans on a blank object, and then
-- reported the capture as 443.9s — measured from a candidate stashed while
-- nobody was playing. The run boundary is the gate; `is_in_main_menu` is not,
-- because it is derived from MainMenu asset READS and goes false a few seconds
-- after the menu finishes loading.
--
-- Session ba4f (2026-08-18) then proved the FALLBACK was the same bug: a whole
-- process spent in the menu and the matchmaking lobby, no run boundary ever
-- fired, so the old "fail open" branch answered `true` five seconds in and the
-- entire six-scan budget went on the character-select preview hero. Diagnostics
-- whose budget is gone before the measurement can be taken are worse than none,
-- so the gameplay bus is asked second and silence is the answer when neither
-- source knows.
do
    package.loaded["rsmm"] = nil
    local Rg = require "rsmm"
    local H = Rg.entity._scan          -- HERO_SCAN internals

    check(Rg.run.signalled() == false, "no run boundary has been seen yet")
    check(Rg.run.playing() == nil,
          "and the gameplay bus has said nothing either — which is not the same "
          .. "as saying 'no run'")
    check(H.in_play() == false,
          "with NOTHING claiming a run is running, diagnostics stay quiet "
          .. "instead of burning their budget in the menu")

    -- The gameplay bus alone is enough, for a build whose analytics run
    -- boundary never fires.
    fire("gameplay:MAP_GENERATION_DONE", { source = "gameplay" })
    check(Rg.run.playing() == true, "map generation means a run is running")
    check(H.in_play() == true, "so diagnostics arm on the bus alone")
    fire("gameplay:GAME_END_FAILED", { source = "gameplay" })
    check(Rg.run.playing() == false, "and the run ended")
    check(H.in_play() == false, "back to quiet")

    -- A chapter change is NOT a run boundary: the run continues.
    fire("gameplay:MAP_GENERATION_DONE", { source = "gameplay" })
    fire("gameplay:GAME_END_NEXT_CHAPTER", { source = "gameplay" })
    check(Rg.run.playing() == true,
          "GAME_END_NEXT_CHAPTER ends a chapter, not the run")

    -- The analytics boundary outranks the bus once it exists.
    Rg.emit("run_start", {})
    check(Rg.run.signalled() == true, "the run boundary was observed")
    check(Rg.run.active() == true, "and we are in a run")
    check(H.in_play() == true, "diagnostics run during a run")

    Rg.emit("run_end", {})
    check(Rg.run.active() == false, "the run ended")
    check(H.in_play() == false,
          "back in the menu with a known run signal, diagnostics are silenced")
    fire("gameplay:MAP_GENERATION_DONE", { source = "gameplay" })
    check(H.in_play() == false,
          "and the bus does not overrule the exact boundary once it exists")
end

-- N1b. R.lobby: names arrive from the attribute parser, not from a sweep ---
--
-- Every member's attributes pass through LobbyAttributes_Parse, so a detour
-- there sees each name as it lands — late joiners included — instead of
-- hunting the address space for a parse buffer that may already be recycled.
-- The blob's encoding is not pinned down, so the extractor accepts JSON,
-- key/value and prefixed-binary shapes; getting it wrong must yield nil and
-- leave the sweep as the fallback, never a garbage name.
do
    package.loaded["rsmm"] = nil
    local Rb = require "rsmm"

    -- The real thing, captured live 2026-08-16 (session 6c4f): plain JSON,
    -- RequestedHero a NUMBER, and that number is the join that ends positional
    -- name<->row matching.
    local real = '{"RequestedHero":4,"RequestedSkin":7,"InLobby":true,'
        .. '"PlayerName":"Brig","LobbyState":1,"UnlockedGameDifficulty":3}'
    local r = Rb.lobby._note_blob(real)
    check(r and r.name == "Brig", "the shipped blob format yields the name")
    check(r and r.hero_id == 4, "RequestedHero comes back as a number")

    local json = '{"InLobby":"1","RequestedHero":"Aladdin","PlayerName":"Akaza"}'
    local e = Rb.lobby._note_blob(json)
    check(e and e.name == "Akaza", "a JSON blob yields the player name")
    check(e and e.hero == "Aladdin", "and the requested hero alongside it")
    check(e and e.hero_id == nil, "a non-numeric hero leaves hero_id unset")

    check(Rb.lobby._note_blob("PlayerName=Brig;RequestedHero=Scarlet") ~= nil,
          "a plain key/value blob is accepted too")
    -- msgpack-ish: a type/length byte sits between key and value.
    local packed = "\170PlayerName\165Piper\173RequestedHero\166Geppet"
    local p = Rb.lobby._note_blob(packed)
    check(p and p.name == "Piper", "a length-prefixed binary blob is accepted")

    local names = {}
    for _, m in ipairs(Rb.lobby.members()) do names[m.name] = m end
    check(names.Akaza and names.Brig and names.Piper,
          "every hooked member shows up in members() with no scan at all")
    check(names.Akaza.src == "hook", "hook-fed rows are tagged as such")

    check(Rb.lobby._note_blob('{"LobbyState":"Connected"}') == nil,
          "a blob with no PlayerName records nothing")
    check(Rb.lobby._note_blob('{"PlayerName":"","InLobby":"1"}') == nil,
          "an empty name is rejected rather than labelling a row with nothing")
    check(Rb.lobby._note_blob("PlayerName") == nil,
          "a truncated blob that ends at the key records nothing")
    check(Rb.lobby._note_blob("PlayerNameRequestedHero") == nil,
          "the next KEY is never mistaken for this key's value")

    -- Re-seeing a member updates rather than duplicating.
    local before = #Rb.lobby.members()
    Rb.lobby._note_blob('{"PlayerName":"Akaza","RequestedHero":"Scarlet"}')
    local after = Rb.lobby.members()
    check(#after == before, "a repeated blob updates the existing row")
    for _, m in ipairs(after) do
        if m.name == "Akaza" then
            check(m.hero == "Scarlet", "and refreshes what it says")
        end
    end
end

-- N1c. R.lobby: the member RECORD, read exactly ----------------------------
--
-- param_1 of LobbyAttributes_Parse is the record it fills. Reading it back is
-- exact where reading the blob has to guess an encoding, and it is the only
-- source of RequestedHero — which is what lets a caller stop matching names
-- to heroes by POSITION. Layout comes from pairing each key literal in the
-- parser with the store it feeds.
do
    package.loaded["rsmm"] = nil
    local Rr = require "rsmm"
    local H = Rr.lobby._hook          -- internals under test
    local REC = 0x1f000000

    local function put(va, s)
        for k = 1, #s do I.write_u8(va + k - 1, s:byte(k)) end
        I.write_u8(va + #s, 0)
    end

    -- Compact string, INLINE form: chars at +0, remaining capacity at +0xd,
    -- flag 0x1000 in the word at +0xe.
    local function put_inline(va, s)
        put(va, s)
        I.write_u8(va + 0xd, 0xd - #s)
        I.write_u16(va + 0xe, 0x1000)
    end

    put_inline(REC, "Akaza")
    I.write_u32(REC + 0x10, 7)            -- RequestedHero
    I.write_u64(REC + 0xb8, 0x110000100000001)
    I.write_u8(REC + 0xc4, 1)             -- InLobby
    I.write_u8(REC + 0xc5, 1)             -- MemberDataInitialized

    local m = H.read(REC)
    check(m and m.name == "Akaza", "the inline compact string is decoded")
    check(m and m.hero_id == 7, "RequestedHero comes back as a number")
    check(m and m.steam_id == 0x110000100000001, "the Steam id is read")
    check(m and m.in_lobby == true, "InLobby is decoded")
    check(m and m.src == "record", "record rows are tagged as such")

    -- MemberDataInitialized == 0: the record is still being filled.
    I.write_u8(REC + 0xc5, 0)
    check(H.read(REC) == nil, "a record that is not initialised yet is refused")
    I.write_u8(REC + 0xc5, 1)

    -- HEAP form: length dword at +0, characters behind the pointer at +8.
    local REC2, TEXT = 0x1f001000, 0x1f002000
    put(TEXT, "AVeryLongPlayerName")
    I.write_u32(REC2, 19)
    I.write_u64(REC2 + 8, TEXT)
    I.write_u16(REC2 + 0xe, 0)            -- flag clear = not inline
    I.write_u8(REC2 + 0xc5, 1)
    local m2 = H.read(REC2)
    check(m2 and m2.name == "AVeryLongPlayerName",
          "the heap form of the compact string is decoded too")

    -- A length that disagrees with the bytes is refused rather than smeared.
    I.write_u32(REC2, 40)
    check(H.read(REC2) == nil, "a length that does not match the text is refused")
end

-- N2. R.lobby: a completed roster is not the final roster ------------------
--
-- Players join while the run is still loading. A sweep that finishes first
-- publishes a roster that is merely CURRENT, and the cheap path then found
-- every one of those blocks still alive and returned early — forever. Measured
-- in a 4-player session (2026-08-16): "lobby scan: 2 member(s)" and the other
-- two rows stayed "Player 3" / "Player 4" for the rest of the run, with the
-- demand gate asking for a scan every second and never getting one. Only
-- SHRINKAGE could trigger another sweep; growth could not.
do
    package.loaded["rsmm"] = nil
    local real_time = os.time
    local clock = 100000
    os.time = function() return clock end          -- luacheck: ignore
    local Rj = require "rsmm"
    local function put(va, s)
        for k = 1, #s do I.write_u8(va + k - 1, s:byte(k)) end
        I.write_u8(va + #s, 0)
    end
    local EARLY, LATE = 0x1e005000, 0x1e006000
    for va, who in pairs({ [EARLY] = "Early", [LATE] = "Late" }) do
        put(va - 0x60, "RequestedHero")
        put(va, "PlayerName")
        put(va + 0x10, who)
    end

    local visible = { EARLY }
    I.mem_find = function(needle)
        if needle ~= "PlayerName\0" then return {}, 0 end
        return visible, 0            -- one slice, sweep completes immediately
    end

    Rj.lobby.refresh()
    check(#Rj.lobby.members() == 1, "the first sweep publishes who is there")

    visible = { EARLY, LATE }        -- a second player joins the session
    clock = clock + 1
    Rj.lobby.refresh()
    check(#Rj.lobby.members() == 1,
          "a roster this fresh is trusted — no sweep on every tick")

    clock = clock + 20               -- past LOBBY_RESCAN_SECONDS
    Rj.lobby.refresh()
    check(#Rj.lobby.members() == 2,
          "a late joiner is picked up once the roster goes stale")

    -- A slice can pass an address before that member's block exists, so a
    -- completed sliced sweep MERGES with what it already knew. Replacing
    -- wholesale would drop a player who never left and re-label their row.
    visible = { LATE }
    clock = clock + 20
    Rj.lobby.refresh()
    check(#Rj.lobby.members() == 2,
          "a member missed by a later sweep survives if their block still reads")

    os.time = real_time              -- luacheck: ignore
end

-- N. R.player: the local player's real name ------------------------------
--
-- A scoreboard of "Player 1 / Player 2" is what this exists to avoid. Steam
-- can always name the LOCAL account; everything else degrades to nil rather
-- than to an empty label, which would look like a bug on screen.
do
    package.loaded["rsmm"] = nil
    local Rp = require "rsmm"
    check(Rp.player.name() == "Ovilli", "the local Steam persona is returned")
    check(Rp.player.name() == "Ovilli", "and cached on the second call")
    check(Rp.player.name_of(0x110000100000001) == nil,
          "an account Steam has never seen is nil, not an empty string")

    -- No Steam (game launched without it, or the DLL is absent): the caller
    -- must get nil and fall back, never a blank row.
    package.loaded["rsmm"] = nil
    local saved = I.steam_name
    I.steam_name = nil
    local Rn = require "rsmm"
    check(Rn.player.name() == nil, "no Steam binding degrades to nil")
    I.steam_name = saved

    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- N. R.overlay: a mod publishes HUD rows --------------------------------
--
-- The mod writes rows; the CLI and the desktop overlay read them back. The
-- payload therefore has to survive TWO escaping layers (JSON, then R.kv's
-- tab-delimited line format), and the "nothing changed" check has to be
-- reliable or every publish rewrites the state file on disk.
do
    package.loaded["rsmm"] = nil
    local Ro = require "rsmm"

    check(Ro.overlay.publish{ rows = { { label = "You", dealt = 4821.5, share = 0.5, top = true } },
                              meta = { total = 8410 } },
          "publish writes the first payload")
    local payload = Ro.overlay.last()
    check(payload:find('"label":"You"', 1, true) ~= nil, "string values are quoted")
    check(payload:find('"top":true', 1, true) ~= nil, "booleans survive as booleans")
    check(payload:find('"total":8410', 1, true) ~= nil, "meta rides along")
    -- Keys are emitted in sorted order so an unchanged board serialises
    -- byte-identically; without that the no-op check below never fires and
    -- the mod rewrites its state file every single tick.
    check(payload:find('"dealt".*"label".*"share".*"top"') ~= nil, "keys are sorted")

    check(Ro.overlay.publish{ rows = { { label = "You", dealt = 4821.5, share = 0.5, top = true } },
                              meta = { total = 8410 } } == false,
          "an unchanged payload is not written again")
    check(Ro.overlay.publish{ rows = { { label = "You", dealt = 4900, share = 0.5, top = true } },
                              meta = { total = 8410 } },
          "a changed payload is written")

    -- Values the reader has no column type for are dropped rather than
    -- guessed at; a nested table would break the flat-row contract.
    Ro.overlay.publish{ rows = { { label = "A", nested = { 1, 2 }, fn = print } } }
    check(Ro.overlay.last():find("nested", 1, true) == nil, "table values are dropped")
    check(Ro.overlay.last():find("fn", 1, true) == nil, "function values are dropped")

    -- NaN/inf are not JSON. One divide-by-zero must not poison the payload.
    Ro.overlay.publish{ rows = { { label = "B", dps = 0 / 0, best = math.huge } } }
    check(Ro.overlay.last():find("nan") == nil and Ro.overlay.last():find("inf") == nil,
          "non-finite numbers degrade to 0 instead of emitting invalid JSON")

    -- Control characters must be escaped, or the tab-delimited kv line the
    -- SDK writes would gain a field and the reader would drop the row.
    Ro.overlay.publish{ rows = { { label = "A\tB\nC" } } }
    check(Ro.overlay.last():find("\\t", 1, true) ~= nil, "tabs are escaped")
    check(Ro.overlay.last():find("\\n", 1, true) ~= nil, "newlines are escaped")

    Ro.overlay.clear()
    check(Ro.overlay.last() == "[]{}", "clear empties the overlay")

    package.loaded["rsmm"] = nil
    R = require "rsmm"
end

-- ---------------------------------------------------------------------------
io.write(string.format("rsmm_spec: %d passed, %d failed\n", passed, failed))
os.exit(failed == 0 and 0 or 1)
