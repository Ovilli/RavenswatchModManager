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
function I.read_u32(a) return rint(a, 4) end
function I.read_u64(a) return rint(a, 8) end
function I.read_f32(a) return (string.unpack("<f", rbytes(a, 4))) end
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
function I.shared_get(slot) return shared[slot] end
function I.shared_set(slot, v) shared[slot] = v end
function I.list_mods() return {} end
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
local R = chunk()
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
io.write(string.format("rsmm_spec: %d passed, %d failed\n", passed, failed))
os.exit(failed == 0 and 0 or 1)
