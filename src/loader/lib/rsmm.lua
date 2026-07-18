-- rsmm — Ravenswatch Mod Manager SDK (Lua).
--
-- This is the documented surface for mod authors. Drop an init.lua in
-- your mod directory, start with:
--
--     local R = require "rsmm"
--
-- and use the R.* namespace. Everything below is a stable contract.
-- The raw engine bindings (memory read/write, native call, pattern
-- resolve) live under `R._internal` and are NOT covered by the contract;
-- they're an escape hatch for power users + the SDK itself.
--
-- TODO markers indicate features whose game-side wiring is still being
-- reverse-engineered. The API shape is fixed; the implementation lands
-- as the engine work catches up.

local native = rawget(_G, "rsmm")
assert(native, "rsmm.lua: native bindings missing (loader did not run)")
local I = native._internal or native

local R = {}

-- mod identity ----------------------------------------------------------

function R.mod_dir()  return native.mod_dir() end

-- logging ---------------------------------------------------------------

function R.log(...)
    local parts = {}
    for i = 1, select("#", ...) do
        parts[i] = tostring(select(i, ...))
    end
    native.log(table.concat(parts, " "))
end

-- events ----------------------------------------------------------------
--
-- Built-in events:
--   "ready" — loader has finished init; safe to query game state
--   "tick"  — fires every 500ms; cheap polling slot
--   "exit"  — DLL is being unloaded
--
-- Typed gameplay events (from data/symbols.json kind="event"; run
-- `rsmm symbols events` for the live list). Enable with
-- RSMM_ENABLE_GAME_EVENTS=1:
--   "level_up" -> { level },  "run_end"
--
-- Analytics firehose (same RSMM_ENABLE_GAME_EVENTS=1 gate). The game
-- funnels ~37 named analytics events through one telemetry sink
-- (Analytics_SubmitNamedEvent); the loader detours it once and
-- re-publishes EVERY event to this bus by its raw name — no per-event
-- wiring, and new names the game adds appear automatically. Confirmed:
--   "game_start" "run_start" "matchmaking_start" "matchmaking_end"
--   "chapter_end" "level_up_reach" "level_up_book" "enemy_killed"
--   "unlock_skill" "unlock_object" "unlock_hero" "unlock_level_nightmare"
--   "event_start" "event_end"
-- OBSERVATION-grade: they fire after the action and carry the analytics
-- payload, not a live entity handle. Great for "when X happens, do Y"
-- triggers; to mutate the actor use the oCGameNamedEvent gameplay bus
-- below.
--
-- Gameplay bus events (RSMM_ENABLE_GAMEPLAY_EVENTS=1) arrive as
-- "gameplay:<NAME>" — entity-context events the game itself dispatches
-- (NETWORK_DAMAGE, GIVE_MAGICAL_OBJECT, GAIN_REROLL, REMOVE_*_OBJECT,
-- CINE_START/STOP, ...; full map in docs/_re/kinds/events-bus.md). Their
-- payload carries live handles (dispatcher/entity as "0x..." strings) plus
-- decoded fields for verified layouts (NETWORK_DAMAGE: value, source_id,
-- target_entity, instigator_entity; GIVE_MAGICAL_OBJECT: mo_guid_lo/hi).
--
-- The callback receives a payload table:
--   ev.event  (string)  the event name
--   ev.seq    (number)  per-event fire counter (ordering signal)
--   ev.source (string)  "analytics" firehose / "gameplay" bus
--   ev.ctx/ev.arg       raw arg handles "0x..." (typed-event envelope only)
-- Lifecycle events (ready/tick/exit) pass an empty table.
--
-- Wildcard: R.on("*", function(ev, name) ... end) receives EVERY event;
-- the event name arrives as a second argument.

function R.on(event, cb)
    assert(type(event) == "string", "R.on: event must be string")
    assert(type(cb) == "function",  "R.on: cb must be function")
    native.on_event(event, cb)
end

-- named engine functions ------------------------------------------------
--
-- The symbol map (data/symbols.json) gives engine functions stable
-- semantic names + a `cabi` (return + arg types). R.engine lets a mod call
-- them by name with the right marshalling — no raw FUN_xxxxxxxx addresses,
-- no manual signature strings. Two equivalent forms:
--
--     local rsc = R.engine.call("Resource_LookupByPath", path, 0, 0, 0)
--     local rsc = R.engine.fn.Resource_LookupByPath(path, 0, 0, 0)
--
-- `R.engine.fn.<Name>` exposes every callable symbol as a method (built
-- lazily from the map, so new symbols appear automatically). Browse the
-- set with `R.engine.names()` or `rsmm symbols list`. The address is
-- resolved at runtime by byte pattern (survives game updates), and the
-- native call signature comes from the symbol's cabi (see engine_gen.lua).
--
-- For an address the map doesn't know yet, drop to the escape hatch:
--     R.engine.call_raw(va, "psppp", path, 0, 0, 0)  -- explicit sig
-- (sig codes: v=void i=int32 u=uint32 p/l=ptr/int64 f=float d=double s=string)

R.engine = {}

local _engine_map
local function engine_map()
    if _engine_map == nil then
        local ok, t = pcall(require, "engine_gen")
        _engine_map = (ok and type(t) == "table") and t or {}
        if not ok then R.log("[rsmm.engine] engine_gen table missing; names unavailable") end
    end
    return _engine_map
end

-- Resolve a semantic name to its runtime virtual address (or nil).
function R.engine.resolve(name)
    assert(type(name) == "string", "R.engine.resolve: name must be string")
    local e = engine_map()[name]
    if not e then R.log("[rsmm.engine] unknown symbol:", name); return nil end
    local base = I.resolve(e.pattern)
    if not base then return nil end
    return base + (e.offset or 0)
end

-- Call a named engine function. The native call signature is taken from the
-- symbol's `cabi` (generated into engine_gen.lua), so a mod just passes the
-- actual arguments — no manual signature string:
--
--     local res = R.engine.call("Resource_LookupByPath", path, 0, 0, 0)
--
-- Arg/return marshalling per the symbol's sig codes (v/i/u/p/l/f/d/s):
-- integers for i/u/p/l, numbers for f/d, Lua strings for s. Returns the
-- typed result (nil for void or if the symbol can't be resolved).
function R.engine.call(name, ...)
    local e = engine_map()[name]
    if not e then R.log("[rsmm.engine] unknown symbol:", name); return nil end
    local va = R.engine.resolve(name)
    if not va then return nil end
    if not e.sig then
        R.log("[rsmm.engine] no cabi/sig for", name, "-- use R.engine.call_raw(va, sig, ...)")
        return nil
    end
    return I.call(va, e.sig, ...)
end

-- Escape hatch: call any resolved address with an explicit signature string.
function R.engine.call_raw(va, sig, ...)
    return I.call(va, sig, ...)
end

-- The native call signature string for a named symbol (or nil).
function R.engine.sig(name)
    local e = engine_map()[name]
    return e and e.sig or nil
end

-- List the semantic names available to R.engine.call.
function R.engine.names()
    local out = {}
    for k in pairs(engine_map()) do out[#out + 1] = k end
    table.sort(out)
    return out
end

-- Named accessors: every callable symbol is exposed as
-- R.engine.fn.<Name>(...) so mods can call engine functions like methods
-- instead of stringly-typed names. Built lazily from the generated map, so
-- new symbols appear automatically with no edits here.
R.engine.fn = setmetatable({}, {
    __index = function(_, name)
        local fn = function(...) return R.engine.call(name, ...) end
        rawset(R.engine.fn, name, fn)  -- memoize
        return fn
    end,
})

-- give-item ----------------------------------------------------------------
--
-- Grant magical objects at runtime by dispatching GIVE_MAGICAL_OBJECT on the
-- gameplay bus. Requires the bus to be armed (RSMM_ENABLE_GAMEPLAY_EVENTS=1),
-- because the hero dispatcher is captured from live hero-anchored events.
--
-- The engine grants the item straight to the hero's inventory (no world orb)
-- and fires a SPAWN_MO cascade. Item identity is the GUID at def+0x88/+0x90 of
-- a g_MagicalObjectPool source entry — see docs/_re/kinds/events-bus.md.
--
--     R.give.random()            -- grant a random loaded item
--     R.give.by_index(0)         -- grant pool source slot 0
--     R.give.by_guid(lo, hi)     -- grant an explicit identity GUID
--     for i, lo, hi in R.give.each() do ... end   -- enumerate the pool

R.give = {}

-- One-time warning when absolute data addresses are disabled because the
-- game build no longer matches the symbol map (loader va-gate). Reads then
-- return nil instead of garbage; see loader.h va_globals_trusted().
local _va_warned = false
local function _va_ok(feature)
    if not I.va_trusted then return true end   -- older loader: no gate
    local ok, trusted = pcall(I.va_trusted)
    if not ok or trusted ~= false then return true end
    if not _va_warned then
        _va_warned = true
        R.log("[rsmm] game build != symbol-map build — " .. feature ..
              " (and other va-global features) disabled until data is updated")
    end
    return false
end

-- A heap pointer read out of a baked va slot is only build-trustworthy after
-- _va_ok. Even then, guard the dereference: a mis-derived va can hold a
-- consistent-but-wrong pointer that the build byte-check cannot catch (get
-- reads are fault-safe and degrade to nil, but a set WRITE to a wrong-but-mapped
-- address silently corrupts engine memory). _ptr_plausible rejects the obvious
-- garbage — null, non-canonical (outside the x64 user-space range), unaligned —
-- so a bad pointer degrades to a no-op instead of a fault or a stray write.
local function _ptr_plausible(p)
    if type(p) ~= "number" then return false end
    if p < 0x10000 then return false end               -- null / low reserved page
    if p > 0x00007fffffffffff then return false end     -- non-canonical user-space
    if (p % 8) ~= 0 then return false end               -- heap objects are 8-aligned
    return true
end

-- ── pointer-safety library ────────────────────────────────────────────────
-- Every loader crash this class (ctx-deref 2026-07-15, probe→engine walk
-- 2026-07-17) was the same mistake: handing a pointer the SDK never fully
-- validated to engine code, which then dereferences it without a guard.
-- `read_*` in the native layer is page-guarded (bad read → nil, no fault) so
-- probing is safe — but the moment a pointer becomes an ARGUMENT to
-- R.engine.call, the engine owns the deref and a bad value faults hard.
--
-- Rule (also in CLAUDE.md): never pass a probed or baked pointer to
-- R.engine.call without validating the full structure the callee will
-- traverse. Use the helpers below to build that validator, and prefer
-- R.engine.call_safe so the guard can't be forgotten.
local IMG_SPAN = 0x1600000                              -- .text+.rdata+.data span

-- Pointer lands inside the loaded game module (a vftable / static global).
local function _in_image(p)
    if not _ptr_plausible(p) then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    return p >= base and p < base + IMG_SPAN
end

-- `obj` looks like a live C++ object: plausible, and *(obj) (its vftable) is
-- a pointer into the game image. Cheap first gate before any vcall.
local function _obj_has_vtable(obj)
    if not _ptr_plausible(obj) then return false end
    return _in_image(I.read_u64(obj))
end

-- A {data, u32 count} pointer-vector at obj+data_off/obj+count_off is fully
-- traversable: plausible data ptr, sane count, and (when check_entry is given)
-- every element passes check_entry(elem, obj). Bound caps the count so a
-- garbage length can't spin. This is the generic form of the Xp component
-- array gate — use it before handing `obj` to any engine walker.
local function _vector_valid(obj, data_off, count_off, opts)
    opts = opts or {}
    if not _ptr_plausible(obj) then return false end
    local data = I.read_u64(obj + data_off)
    local n    = I.read_u32(obj + count_off)
    if not data or data == 0 or not _ptr_plausible(data) then return false end
    if not n or n < (opts.min or 0) or n > (opts.max or 0x400) then return false end
    local check = opts.check_entry
    if check then
        for i = 0, n - 1 do
            if not check(I.read_u64(data + i * 8), obj, i) then return false end
        end
    end
    return true
end

-- Guarded engine call: `ptr_args` is a list of 1-based argument indices that
-- MUST be plausible pointers (or a validator fn) before the call is allowed.
-- On any failure the call is REFUSED (returns nil) instead of faulting the
-- game — the fail-closed contract every mutating path already promises.
function R.engine.call_safe(name, ptr_args, ...)
    local args = { ... }
    for _, spec in ipairs(ptr_args or {}) do
        local idx, validate
        if type(spec) == "table" then idx, validate = spec[1], spec[2] else idx = spec end
        local v = args[idx]
        if validate then
            if not validate(v) then
                R.log("[rsmm.engine] call_safe refused " .. tostring(name)
                      .. ": arg " .. tostring(idx) .. " failed validator")
                return nil
            end
        elseif not _ptr_plausible(v) then
            R.log("[rsmm.engine] call_safe refused " .. tostring(name)
                  .. ": arg " .. tostring(idx) .. " not a plausible pointer")
            return nil
        end
    end
    return R.engine.call(name, ...)
end

-- Expose the primitives to advanced mods / the SDK's own paths.
R.ptr = {
    plausible    = _ptr_plausible,
    in_image     = _in_image,
    has_vtable   = _obj_has_vtable,
    vector_valid = _vector_valid,
}

-- g_MagicalObjectPool: pointer global; *ptr = { source array @+0,
-- u32 source count @+8, runtime array @+0x10, u32 runtime count @+0x18 }.
-- Re-derived 2026-07-10 after the 2026-07-09 game patch (readers of the new
-- slot dereference +0x10/+0x18 exactly like the old pool, e.g. FUN_1402b3030).
local GIVE_POOL_VA = 0x14143cc18
local GIVE_IMG_BASE = 0x140000000

-- Hero dispatcher, captured from any hero-anchored gameplay event. These all
-- fire at the local hero's own dispatcher (unlike GAIN_HEALTH, which fires at
-- the heal source). Verified in-game 2026-06-12.
local _give_hero = nil
local _GIVE_ANCHORS = {
    ["gameplay:GAIN_DREAM_SHARDS"] = true,
    ["gameplay:ABILITY_EXIT"] = true,
    ["gameplay:ENERGY_COUNTER_DEC"] = true,
    ["gameplay:ENERGY_COUNTER_INC"] = true,
    ["gameplay:COMBO_LINK"] = true,
    ["gameplay:INTERACTION_VALIDATE"] = true,
}

-- Forward-declared; assigned once the entity section (which owns _hero_char and
-- the shared slot) is defined below. Called when the live hero dispatcher
-- changes (hero switch / new run) to drop the now-stale HP-carrier capture.
local _invalidate_hero_capture

-- The NamedEventDispatcher sub-object lives at entity+0x4d8; subtract to reach
-- the owning entity so we can test whether it is a grantable hero.
local _DISPATCHER_ENTITY_OFF = 0x4d8

-- True iff `disp`'s owning entity is a grantable hero (not a summon/pet). Uses
-- the native, page-guarded magical-object-component lookup when available; if
-- the native side is older and lacks the binding, fall back to accepting the
-- dispatcher (prior behavior) rather than breaking give outright.
local function _dispatcher_is_hero(disp)
    if type(I.is_grant_target) ~= "function" then return true end
    local entity = disp - _DISPATCHER_ENTITY_OFF
    -- Fail OPEN, not closed. _DISPATCHER_ENTITY_OFF (0x4d8) is stale on the
    -- 2026-07-09+ build: disp-0x4d8 no longer lands on the real entity, so the
    -- component-store slot at entity+8 reads a -1 sentinel and the native
    -- discriminator rejects the actual hero (in-game diag confirmed store=-1,
    -- is_grant_target=false for the only, real, dispatcher). Only TRUST a
    -- positive native signal; when the check can't run (implausible entity or
    -- empty store), accept the dispatcher. The game's own grant handler
    -- (FUN_140397030) re-checks grantability and safely no-ops a non-hero
    -- target, so accepting a summon here cannot crash — worst case a grant is a
    -- silent no-op until the hero's own anchor event re-captures. Restores the
    -- pre-patch behavior that worked. Re-derive the offset to re-enable the
    -- strict summon filter -- see [[give-hero-agnostic-fix]].
    if not _ptr_plausible(entity) then return true end
    local store = I.read_u64(entity + 8)
    if not _ptr_plausible(store) then return true end
    return I.is_grant_target(entity) == true
end

R.on("*", function(ev, name)
    if _GIVE_ANCHORS[name] and type(ev.dispatcher) == "string" then
        local d = tonumber(ev.dispatcher)
        if d and d ~= 0 and d ~= _give_hero and _dispatcher_is_hero(d) then
            -- Only a dispatcher whose entity is a real hero reaches here. Summon
            -- and pet entities also fire anchor events (ABILITY_EXIT, ...) from
            -- their OWN dispatcher; accepting one would clobber _give_hero to a
            -- non-hero with no GIVE_MAGICAL_OBJECT subscriber, so every grant
            -- would silently no-op. That is the "give only works on Aladdin" bug
            -- (Aladdin has no persistent summon to clobber the capture).
            --
            -- A different (valid hero) dispatcher than last seen means the local
            -- hero changed — switched character, or a fresh run reallocated the
            -- entity. The captured HP-carrier and the shared slot point at the
            -- OLD hero's (possibly freed) memory, so invalidate + re-capture.
            if _give_hero ~= nil and _invalidate_hero_capture then
                _invalidate_hero_capture()
            end
            _give_hero = d
        end
    end
end)

-- True once a hero dispatcher has been seen (i.e. give will work). Until the
-- hero acts at least once in a run, grants are deferred.
function R.give.ready() return _give_hero ~= nil end

-- The hero dispatcher pointer (or nil). Advanced; most mods want the helpers.
function R.give.hero() return _give_hero end

local function _give_pool_vec()
    if not _va_ok("R.give") then return nil end
    local base = I.module_base()
    if not base or base == 0 then return nil end
    local vec = I.read_u64(base + (GIVE_POOL_VA - GIVE_IMG_BASE))
    if not _ptr_plausible(vec) then return nil end
    -- A mis-derived pool pointer reads an absurd source count; a real pool is a
    -- small non-negative number of loaded definitions. Refuse the outliers so a
    -- bad va can never drive an inject/enumerate off a garbage base.
    local n = I.read_u32(vec + 8)
    if type(n) ~= "number" or n > 100000 then return nil end
    return vec
end

-- Number of loaded magical-object definitions (pool source count), or 0.
function R.give.count()
    local vec = _give_pool_vec()
    if not vec then return 0 end
    local data = I.read_u64(vec)
    local n = I.read_u32(vec + 8)
    if not data or data == 0 or not n then return 0 end
    return n
end

-- The identity GUID (lo, hi) of pool source slot `i` (0-based), plus the def
-- pointer; nil if out of range or the pool can't be read.
function R.give.guid_at(i)
    local vec = _give_pool_vec()
    if not vec then return nil end
    local data = I.read_u64(vec)
    local n = I.read_u32(vec + 8)
    if not data or data == 0 or not n or i < 0 or i >= n then return nil end
    local def = I.read_u64(data + i * 8)
    if not def or def == 0 then return nil end
    return I.read_u64(def + 0x88), I.read_u64(def + 0x90), def
end

-- Iterator over (index, guid_lo, guid_hi) for every loaded item.
function R.give.each()
    local n = R.give.count()
    local i = -1
    return function()
        i = i + 1
        if i >= n then return nil end
        local lo, hi = R.give.guid_at(i)
        return i, lo, hi
    end
end

-- Grant the item with identity GUID (lo, hi). Returns true on dispatch.
-- Fails (false) if the bus hasn't armed a hero dispatcher yet.
function R.give.by_guid(lo, hi)
    if not _give_hero then
        R.log("[rsmm.give] no hero dispatcher yet — the hero must act once first")
        return false
    end
    local ev = R.engine.call("NamedEvent_GiveMagicalObject_Ctor", I.scratch(0x60))
    if not ev or ev == 0 then
        R.log("[rsmm.give] GiveMagicalObject ctor failed (symbol unresolved?)")
        return false
    end
    I.poke(ev + 0x50, lo or 0, 8)
    I.poke(ev + 0x58, hi or 0, 8)
    R.engine.call("NamedEvent_Dispatch", _give_hero, ev)
    return true
end

-- Grant pool source slot `i` (0-based). Returns true on dispatch.
function R.give.by_index(i)
    local lo, hi = R.give.guid_at(i)
    if not lo then
        R.log("[rsmm.give] no item at pool index", i)
        return false
    end
    return R.give.by_guid(lo, hi)
end

-- Grant a random loaded item. Returns the granted index, or nil.
function R.give.random()
    local n = R.give.count()
    if n == 0 then return nil end
    local i = math.random(0, n - 1)
    if R.give.by_index(i) then return i end
    return nil
end

-- Number of magical objects currently in the runtime (owned/active) pool array.
function R.give.owned_count()
    local vec = _give_pool_vec()
    if not vec then return 0 end
    local data = I.read_u64(vec + 0x10)
    local n = I.read_u32(vec + 0x18)
    if not data or data == 0 or not n then return 0 end
    return n
end

-- Iterator over the hero's currently-owned magical objects (runtime pool
-- array @vec+0x10/+0x18), yielding (index, guid_lo, guid_hi, def_ptr). The
-- runtime entries mirror the source-array def layout (GUID @def+0x88/+0x90).
-- EXPERIMENTAL: confirm the owned-set semantics in-game.
function R.give.owned()
    local vec = _give_pool_vec()
    local data = vec and I.read_u64(vec + 0x10) or 0
    local n = (vec and I.read_u32(vec + 0x18)) or 0
    local i = -1
    return function()
        i = i + 1
        if not data or data == 0 or i >= n then return nil end
        local def = I.read_u64(data + i * 8)
        if not def or def == 0 then return nil end
        return i, I.read_u64(def + 0x88), I.read_u64(def + 0x90), def
    end
end

-- True if the hero currently owns the magical object with identity GUID (lo,hi).
function R.give.owns(lo, hi)
    for _, glo, ghi in R.give.owned() do
        if glo == lo and ghi == hi then return true end
    end
    return false
end

-- entity / combat -------------------------------------------------------
--
-- Read and modify the local hero's health. The hero CHARACTER object (the one
-- carrying HP) is NOT the bus dispatcher and can't be derived from it — the
-- engine bakes the hero into each event subscription as the handler's first
-- arg. So we capture it by hooking two hero-bound handlers read-only (the
-- GAIN_HEALTH handler and the give-item handler) and grabbing param_1 the
-- first time either fires (i.e. the hero heals/regens or picks something up).
-- Health is then applied through the engine's own modify-health routine
-- (Entity_ModifyHealth), so clamping, the UI bar, on-heal/on-damage triggers
-- and analytics all fire exactly as if the game did it.
--
--   R.entity.hp()        -- current HP (float) or nil (hero not captured yet)
--   R.entity.max_hp()    -- max HP or nil
--   R.entity.hp_frac()   -- hp/max in 0..1 or nil
--   R.entity.ready()     -- true once the hero is captured
--   R.combat.heal(20)    -- heal 20
--   R.combat.damage(15)  -- self-damage 15
--   R.combat.set_hp(50)  -- set HP to an absolute value

R.entity = {}
R.combat = {}

local ENTITY_HP_OFF      = 0x15c8        -- f32 current HP on the hero character
local ENTITY_MAXHP_OFF   = 0x15cc        -- f32 max HP
local ENTITY_HUDMIRROR_OFF = 0x1d80      -- ptr to the HUD HP mirror (hero-only)
-- Function addresses are resolved at runtime through the pattern DB
-- (I.resolve on the semantic symbol name) so a game patch that shifts code
-- can never leave us hooking/calling a stale VA: an unresolved symbol fails
-- closed instead. Only data addresses (vftable) stay link-time constants.
local FLAGLIST_VFT_VA    = 0x140f01650   -- oCCustomFlagList::vftable (re-derived 2026-07-10)
local ENTITY_IMG_BASE    = 0x140000000

local _hero_char = nil          -- captured hero character object (HP@+0x15c8)
local _hero_capture_armed = false
-- Process-global shared slots (see hook_events.cpp install_hero_capture):
--   0 = hero character pointer (published by native capture)
--   1 = native "authoritative seen" flag (give handler fired)
--   2 = native capture active sentinel (loader owns the capture hooks)
local SHARED_HERO_SLOT = 0
local HERO_AUTH_SLOT = 1
local NATIVE_CAPTURE_SLOT = 2
local HERO_PENDING_SLOT = 3   -- spawn-init candidate whose fields weren't live yet

-- True when the loader's native hero-capture is installed. When it is, the Lua
-- side must not arm its own per-state capture hooks (they'd collide with the
-- native ones, MH_ERROR_ALREADY_CREATED) — it just reads the shared slot.
local function _native_capture_active()
    if not I.shared_get then return false end
    local ok, v = pcall(I.shared_get, NATIVE_CAPTURE_SLOT)
    return ok and v == 1
end

-- A captured pointer is "hero-like" if its max-HP field reads as a sane float
-- AND it carries a valid HUD HP-mirror pointer at +0x1d80. The mirror is the
-- hero discriminator: Entity_ModifyHealth dereferences **(hero+0x1d80) on every
-- heal/damage, so a pointer that lacks a live mirror would crash R.combat.
-- Non-player entities (GAIN_HEALTH fires for enemies too) have no HUD mirror,
-- so requiring it rejects false captures and keeps every captured pointer
-- ModifyHealth-safe. Verified in Ghidra (FUN_140391d30 / FUN_140399a10). All
-- reads are fault-safe (return nil on a bad address).
local function _hero_plausible(e)
    if not e or e == 0 then return false end
    local mx = I.read_f32(e + ENTITY_MAXHP_OFF)
    local cur = I.read_f32(e + ENTITY_HP_OFF)
    -- cur may legitimately EXCEED mx (overheal / shields / HP-boost items), so
    -- only bound it as finite+non-negative, not cur <= mx. mx must be a sane
    -- positive bar size — that's the real garbage-pointer discriminator.
    if not (type(mx) == "number" and mx > 0 and mx < 1e6
        and type(cur) == "number" and cur >= 0 and cur < 1e6) then
        return false
    end
    local mirror = I.read_u64(e + ENTITY_HUDMIRROR_OFF)
    if type(mirror) ~= "number" or mirror == 0 then return false end
    -- mirror is dereferenced as *(mirror) (a float) by the engine; confirm it's
    -- readable so a later R.combat call can't fault.
    return type(I.read_f32(mirror)) == "number"
end

-- NOTE: ev.entity (= dispatcher - 0x4d8 from the gameplay bus) is NOT the hero
-- HP-carrier. Empirically _hero_plausible(ev.entity) fails: the dispatch entity
-- (dispatcher owner) and the HP-carrier are separate sub-objects — the hero is
-- bound into each subscription as functor context, not reachable from the event
-- by a fixed offset. So capture stays hook-based (param_1 of the hero handlers),
-- which needs one hero action (heal/lifesteal/pickup) but reads the right object.

-- Install the read-only capture hooks once. Both handlers take pointer args
-- only (no float), so hooking them is safe; the callback returns nil to replay
-- the original unchanged. Called lazily so R.hook is defined by first use.
local function _arm_hero_capture()
    if _hero_capture_armed then return end
    local base = I.module_base()
    if not base or base == 0 or not R.hook then return end
    _hero_capture_armed = true
    -- The GAIN_HEALTH handler fires for ANY entity that heals (incl. enemies),
    -- so its capture is only tentative (taken if nothing better seen yet). The
    -- give-item handler is hero-only (only the local player picks up MOs), so it
    -- is authoritative and overwrites any tentative capture.
    local function capture(p1, authoritative)
        if not _hero_plausible(p1) then return end
        if _hero_char == p1 then return end
        if _hero_char ~= nil and not authoritative then return end
        _hero_char = p1
        -- Publish to the process-global slot so other mods' Lua states (which
        -- lose the MinHook install with ALREADY_CREATED) still see this hero.
        if I.shared_set then pcall(I.shared_set, SHARED_HERO_SLOT, p1) end
        R.log(string.format("[rsmm.entity] hero captured @0x%x (hp %.0f/%.0f)%s",
            p1, I.read_f32(p1 + ENTITY_HP_OFF), I.read_f32(p1 + ENTITY_MAXHP_OFF),
            authoritative and " [authoritative]" or " [tentative]"))
    end
    -- Best-effort: a failed capture hook must NEVER abort the mod that
    -- required rsmm. Handler addresses come from the pattern DB (nil when the
    -- symbol is unverified for this game build — fail closed, never hook a
    -- stale VA), and R.hook can still raise on install failure, so guard each
    -- with pcall — capture just stays unavailable; everything else still runs.
    local gain_va = I.resolve and I.resolve("Entity_GainHealthHandler")
    local give_va = I.resolve and I.resolve("Entity_GiveHandler")
    -- Both handlers take pointer-only args (ptr,ptr,ptr). Either one captures
    -- the hero (the mirror plausibility check inside capture() rejects any
    -- non-hero entity that also fires them), so capture survives as long as ONE
    -- resolves; only warn when BOTH are unresolved for this build.
    -- ARG SEMANTICS differ: the gain-health handler's param_1 is the hero
    -- entity, but the give handler's param_1 is the hero's VALUE CONTEXT
    -- (*(hero+0x2f8)) and its param_2 is the hero entity (decompile-verified
    -- 2026-07-15; the ctx never passes _hero_plausible, which is why the
    -- authoritative capture silently never fired).
    local ok1 = gain_va and pcall(R.hook, gain_va, "vppp",
        function(p1) capture(p1, false); return nil end)
    local ok2 = give_va and pcall(R.hook, give_va, "vppp",
        function(_, p2) capture(p2, true); return nil end)
    if not (ok1 or ok2) then
        R.log("[rsmm.entity] hero-capture hooks unavailable (both handlers "
            .. "unresolved for this game build); R.combat/R.entity/R.stat/R.xp "
            .. "disabled this run, other mods unaffected")
    end
end

-- The captured local hero character pointer, or nil if not seen yet. The
-- loader's native capture publishes it to the shared slot at hero spawn (it
-- hooks the hero's spawn/post-load init, NamedEvent_HeroSubscribeAll, whose
-- param_1 is the HP-carrier) — so it's available almost immediately, no longer
-- gated on the hero's first heal/pickup. Read fresh every call so a hero-switch
-- (which clears the slot) is picked up automatically.
local _hero_diag_n = 0
function R.entity.hero()
    if I.shared_get then
        local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
        if ok and type(h) == "number" and h ~= 0 then
            if _hero_plausible(h) then return h end
            -- DIAG (first few only): the native capture published a pointer the
            -- Lua plausibility gate now rejects — log the raw reads so a
            -- playtest log shows WHY (stale/freed entity? moved offsets?).
            if _hero_diag_n < 6 then
                _hero_diag_n = _hero_diag_n + 1
                R.log(string.format(
                    "[rsmm.entity] slot hero 0x%x REJECTED: hp=%s max=%s mirror=%s",
                    h, tostring(I.read_f32(h + ENTITY_HP_OFF)),
                    tostring(I.read_f32(h + ENTITY_MAXHP_OFF)),
                    tostring(I.read_u64(h + ENTITY_HUDMIRROR_OFF))))
            end
        end
        -- Pending spawn candidate: the native spawn-init hook stashes the hero
        -- identity BEFORE its HP/mirror fields are populated (they fill during
        -- the load sequence). Promote it to the real slot the first time it
        -- reads plausible — instant capture with no combat prerequisite.
        local okp, p = pcall(I.shared_get, HERO_PENDING_SLOT)
        if okp and type(p) == "number" and p ~= 0 and _hero_plausible(p) then
            if I.shared_set then
                pcall(I.shared_set, SHARED_HERO_SLOT, p)
                pcall(I.shared_set, HERO_AUTH_SLOT, 1)
                pcall(I.shared_set, HERO_PENDING_SLOT, 0)
            end
            R.log(string.format("[rsmm.entity] pending spawn hero 0x%x promoted (instant capture)", p))
            return p
        end
    end
    -- Legacy fallback: an older loader without native capture. Arm the per-state
    -- Lua hooks (safe only when native capture is NOT present — otherwise it
    -- would collide with the native hooks on the same addresses).
    if not _native_capture_active() then
        if not _hero_char then _arm_hero_capture() end
        return _hero_char
    end
    return nil
end

-- True once the hero has been captured (hp/max/heal/damage will work).
function R.entity.ready() return R.entity.hero() ~= nil end

function R.entity.hp()
    local e = R.entity.hero(); if not e then return nil end
    return I.read_f32(e + ENTITY_HP_OFF)
end

function R.entity.max_hp()
    local e = R.entity.hero(); if not e then return nil end
    return I.read_f32(e + ENTITY_MAXHP_OFF)
end

function R.entity.hp_frac()
    local cur, mx = R.entity.hp(), R.entity.max_hp()
    if not cur or not mx or mx <= 0 then return nil end
    return cur / mx
end

-- Apply a raw health delta (delta>0 heals, delta<0 damages). Returns true on
-- dispatch, false if the hero isn't captured yet, the module base is
-- unavailable, or health reads implausible (guards against a bad pointer).
local function _modify_health(delta)
    local e = R.entity.hero()
    if not e then
        R.log("[rsmm.combat] no hero yet — wait until the hero heals/regens or "
            .. "picks something up once (R.entity.ready())")
        return false
    end
    if not _hero_plausible(e) then
        R.log("[rsmm.combat] hero health reads implausible — refusing modify")
        return false
    end
    if not _va_ok("R.combat") then return false end
    local base = I.module_base()
    if not base or base == 0 then return false end
    -- empty oCCustomFlagList ctx { vftable, list=0, count=0 } in scratch
    local ctx = I.scratch(0x20)
    I.poke(ctx + 0x00, base + (FLAGLIST_VFT_VA - ENTITY_IMG_BASE), 8)
    I.poke(ctx + 0x08, 0, 8)
    I.poke(ctx + 0x10, 0, 8)
    local fn = I.resolve and I.resolve("Entity_ModifyHealth")
    if not fn then
        R.log("[rsmm.combat] Entity_ModifyHealth unresolved for this game build "
            .. "— refusing modify (regenerate function_patterns.json)")
        return false
    end
    R.engine.call_raw(fn, "vpfp", e, delta + 0.0, ctx)
    return true
end

function R.combat.heal(amount)   return _modify_health(math.abs(amount or 0)) end
function R.combat.damage(amount) return _modify_health(-math.abs(amount or 0)) end

-- Set HP to an absolute value by applying the difference from current.
function R.combat.set_hp(value)
    local cur = R.entity.hp()
    if not cur then return false end
    return _modify_health((value or 0) - cur)
end

-- Wire the forward-declared invalidator now that _hero_char + the shared slot
-- exist. On hero switch / new run the captured HP-carrier is stale; drop it and
-- clear the process-global slot so the next heal/pickup re-captures cleanly.
_invalidate_hero_capture = function()
    _hero_char = nil
    if I.shared_set then
        pcall(I.shared_set, SHARED_HERO_SLOT, 0)  -- drop stale hero pointer
        pcall(I.shared_set, HERO_AUTH_SLOT, 0)    -- let native re-capture new hero
    end
end

-- entity values (generic CRC-keyed run/stat store) ----------------------
--
-- Each hero carries a generic keyed value store on its value context. The
-- context is a POINTER field: ctx = *(hero+0x2f8), and the store hangs off it
-- at *(ctx+0x4c8). The engine's own reader (FUN_140399d00, the damage-taken
-- handler) loads the pointer first — `ctx = *(hero+0x2f8)` — then calls
-- EntityValue_Get(ctx, out, crcKey). Passing hero+0x2f8 (the field's ADDRESS)
-- instead makes EntityValue_Get read *(hero+0x7c0) as the store — a float
-- field, not a pointer — and EntityValue_Lookup then faults dereferencing it
-- (the 2026-07-15 in-run crash: store=0xbf800000, i.e. -1.0f, read at +0xc8).
-- EntityValue_Get reads one key into a ~0x20-byte oCEntityValueUnion: type tag
-- @+0x8 (4 = inline f32), value @+0x10. A missing key yields value 0 (safe —
-- never faults). We only read INLINE numeric values (every modifier/difficulty
-- key is numeric); a non-inline (string/vector) key returns nil rather than
-- deref an unknown-typed pointer, so no union destructor is needed.
-- See docs/_re/kinds/entity-values.md and docs/_re/kinds/stats.md.
local ENTITY_VALCTX_OFF = 0x2f8   -- hero -> POINTER to entity value context
local EV_STORE_OFF      = 0x4c8   -- ctx -> POINTER to value store
local EV_TAG_OFF        = 0x08    -- oCEntityValueUnion type tag
local EV_VAL_OFF        = 0x10    -- inline f32 when tag == EV_TAG_INLINE
local EV_TAG_INLINE     = 4

-- Resolve the hero's value CONTEXT pointer, fail-closed. Validates the whole
-- chain the engine will dereference unguarded inside EntityValue_Get /
-- EntityValue_Lookup before we hand it a pointer:
--   ctx   = *(hero+0x2f8)  must be a plausible, readable pointer
--   store = *(ctx+0x4c8)   may be 0 (engine handles it) — but if non-zero it
--                          must be plausible AND its hot fields readable:
--                          count u32 @store+0xc8 (read unconditionally), the
--                          override array ptr @store+0xc0 (read when count>0)
--                          and the base hashmap ptr @store+0x80 (deref'd
--                          unconditionally on a cache miss).
-- Every probe is page-guarded (nil on unmapped), so validation cannot fault.
-- Returns ctx, or nil if any link is implausible.
local function _ev_ctx(hero)
    local ctx = I.read_u64(hero + ENTITY_VALCTX_OFF)
    if not ctx or not _ptr_plausible(ctx) then return nil end
    local store = I.read_u64(ctx + EV_STORE_OFF)
    if store == nil then return nil end                     -- ctx page unreadable
    if store ~= 0 then
        if not _ptr_plausible(store) then return nil end
        local count = I.read_u32(store + 0xc8)
        if count == nil or count > 0x10000 then return nil end
        if count > 0 then
            local data = I.read_u64(store + 0xc0)
            if not data or not _ptr_plausible(data) then return nil end
        end
        local hmap = I.read_u64(store + 0x80)
        if not hmap or not _ptr_plausible(hmap) then return nil end
    end
    return ctx
end

-- Read one entity-value by raw CRC key from the current hero's store.
-- Returns a Lua number (inline f32) or nil (no hero / missing / non-inline).
function R.entity.value(key)
    assert(type(key) == "number", "R.entity.value: key must be a number (CRC id)")
    local e = R.entity.hero(); if not e then return nil end
    local ctx = _ev_ctx(e); if not ctx then return nil end
    local out = I.scratch(0x20)               -- zeroed; tag starts at 0
    local ok = pcall(R.engine.call, "EntityValue_Get", ctx, out, key)
    if not ok then return nil end
    if I.read_u32(out + EV_TAG_OFF) ~= EV_TAG_INLINE then return nil end
    return I.read_f32(out + EV_VAL_OFF)
end

-- game modifiers ("negative modes" / run mutators) ----------------------
--
-- The toggleable run mutators (No boss timer, No minimap, More experience,
-- Day only, ...) plus the difficulty / XP scalars each have a CRC-keyed value in
-- the entity-value store. R.modifier reads them by name. The keys are the literal
-- ids the engine registers them under (Ghidra: EntityValueRegistry_RegisterAll,
-- FUN_1401d9b70); full map + provenance in docs/_re/kinds/game-modifiers.md.
--
--   R.modifier.value("Game Difficulty")  -- numeric value (or nil)
--   R.modifier.active("No minimap")      -- true if the toggle is on this run
--   R.modifier.names()                   -- known modifier/scalar names (sorted)
--
-- NOTE: read-only and pending in-game verification that the modifier state lives
-- on the hero's value store (vs a global game entity); a wrong store just makes
-- every read return 0/nil, never faults.
R.modifier = {}

local _MODIFIER_KEYS = {
    -- toggles (bool: value ~= 0 => active)
    ["No boss timer"]                            = 0x1a7945fc,
    ["Less day/night half cycle"]                = 0x1a77d42d,
    ["More experience"]                          = 0x1a77e2e4,
    ["No revive token"]                          = 0x1a793d1a,
    ["No minimap"]                               = 0x99f27eac,
    ["One chapter"]                              = 0x1a8a3688,
    ["Day only"]                                 = 0x1a8b53b4,
    ["Night only"]                               = 0x1a8b53bc,
    ["Random hero at map start"]                 = 0x1ab183ab,
    ["All same heroes"]                          = 0x1ab58780,
    -- difficulty / xp scalars
    ["Game Difficulty"]                          = 0x18700873,
    ["Difficulty Xp Modifier"]                   = 0x19bddb2e,
    ["Global Xp Modifier"]                       = 0x187afd1d,
    ["Rare Skill Chance Modifier"]               = 0x1871c2fa,
    ["Dream Shard Costs Modifier"]               = 0x187310ec,
    ["Half Cycle Count Before Boss Awakens"]     = 0x187443de,
    ["Camp Difficulty Modifier"]                 = 0x187aaecf,
    ["Camp Difficulty Modifier Chance To Apply"] = 0x187ab36e,
}

-- Numeric value of a named modifier/scalar, or nil (unknown name / no hero).
function R.modifier.value(name)
    local key = _MODIFIER_KEYS[name]
    if not key then
        R.log("[rsmm.modifier] unknown modifier name: " .. tostring(name))
        return nil
    end
    return R.entity.value(key)
end

-- True if a toggle modifier is active this run (value present and non-zero).
function R.modifier.active(name)
    local v = R.modifier.value(name)
    return type(v) == "number" and v ~= 0
end

-- The known modifier / scalar names, sorted (for listing / iteration).
function R.modifier.names()
    local t = {}
    for k in pairs(_MODIFIER_KEYS) do t[#t + 1] = k end
    table.sort(t)
    return t
end

-- Read a raw entity-value key the name table doesn't cover (forward-compat).
function R.modifier.value_by_key(key) return R.entity.value(key) end

-- stats (generic keyed value store — read/grant any per-hero stat) -------
--
-- Beyond HP (R.combat) and XP (R.xp), most hero stats — max health, attack
-- power, crit chance/damage, move speed, cooldown reduction, life steal,
-- dream shards, xp multipliers — live in the engine's generic CRC-keyed
-- entity-value store (the same store R.entity.value / R.modifier read). The
-- keys are decompile-verified from EntityValueRegistry_RegisterAll; full
-- catalog + provenance in docs/_re/kinds/stats.md.
--
--   R.stat.get("attack_power")     -- current value (number) or nil
--   R.stat.names()                 -- known stat names (sorted)
--   R.stat.enable_writes()         -- opt in to the EXPERIMENTAL write path
--   R.stat.set("move_speed", 1.5)  -- set a stat (see caveats)
--   R.stat.add("attack_power", 10) -- current + delta
--
-- READS are always safe. WRITES are EXPERIMENTAL + engine-mutating: run them
-- on the MAIN thread (from a gameplay-event handler or R.schedule.next_main —
-- see [[loader-thread-model]]) and opt in with R.stat.enable_writes() first.
-- DURABILITY: a write lands in the store's override cache, which the engine
-- rebuilds from base+modifiers on the next stat recompute (item pickup, level
-- up, ...), so a set() is not necessarily permanent. HP has its own committed
-- path (R.combat); prefer it for health. Pending in-game verification.
R.stat = {}

-- name -> { key = <crc id>, kind = "f32"|"int" }. Decompile-verified 2026-07-13
-- (agent RE batch; see docs/_re/kinds/stats.md for the full ~40-key table).
R.stat.keys = {
    max_health         = { key = 0x188671a6, kind = "f32" },  -- base "Vitality"
    max_health_pct     = { key = 0x15c9296d, kind = "f32" },  -- default 1.0
    attack_power       = { key = 0x15a486c4, kind = "f32" },
    crit_chance        = { key = 0x15c7d482, kind = "f32" },
    crit_damage        = { key = 0x15c82d13, kind = "f32" },
    move_speed         = { key = 0x044dadde, kind = "f32" },  -- "Move Speed Ratio"
    cooldown_reduction = { key = 0x15b45d80, kind = "f32" },
    life_steal         = { key = 0x15c028c2, kind = "f32" },
    life_on_hit        = { key = 0x1894f1a2, kind = "f32" },
    dream_shards       = { key = 0x171c27b5, kind = "int" },  -- currency count
    xp_multiplier      = { key = 0x187afd1d, kind = "f32" },  -- "Global Xp Modifier"
    difficulty_xp_mult = { key = 0x19bddb2e, kind = "f32" },
}

-- oCEntityValueUnion is a 0x20-byte tagged value. In the caller-provided read
-- buffer it starts at +0; inside a 0x38-byte override entry it starts at +0x08.
local EV_INLINE_OFF = 0x08   -- union: inline sentinel (== 4 => value is inline)
local EV_VALUE_OFF  = 0x10   -- union: inline value (f32 or int32)
local EV_TAG_OFF    = 0x18   -- union: type-tag byte (0 = int/float)
local EV_INLINE     = 4
local ENTRY_UNION_OFF = 0x08 -- override entry: embedded union offset
local ENTRY_KEY_OFF   = 0x00 -- override entry: u32 key
local OVR_DATA_OFF  = 0xc0   -- store -> override vector data ptr (vec base)
local OVR_COUNT_OFF = 0xc8   -- store -> override count (vec+8)
local OVR_STRIDE    = 0x38   -- override entry stride

-- Resolve the value-store pointer for a captured hero: *(ctx+0x4c8) where
-- ctx = *(hero+0x2f8). _ev_ctx (entity-values section above) has already
-- validated the whole chain — plausible ctx, plausible store, readable hot
-- fields — so a non-nil ctx with a non-zero store slot is usable as-is.
-- Returns the store ptr or nil.
local function _stat_store(hero)
    local ctx = _ev_ctx(hero)
    if not ctx then return nil end
    local s = I.read_u64(ctx + EV_STORE_OFF)
    if not s or s == 0 then return nil end
    return s
end

-- Read one stat by its spec ({key,kind}) from the current hero. Always safe:
-- the engine call is made only with an _ev_ctx-validated context pointer.
local function _stat_read(spec)
    local e = R.entity.hero(); if not e then return nil end
    local ctx = _ev_ctx(e); if not ctx then return nil end
    local out = I.scratch(0x20)                               -- zeroed union buffer
    local ok = pcall(R.engine.call, "EntityValue_Get", ctx, out, spec.key)
    if not ok then return nil end
    if I.read_u32(out + EV_INLINE_OFF) ~= EV_INLINE then return nil end
    if spec.kind == "int" then return I.read_u32(out + EV_VALUE_OFF) end
    return I.read_f32(out + EV_VALUE_OFF)
end

-- Current value of a named stat, or nil (unknown name / no hero / non-inline).
function R.stat.get(name)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return nil end
    return _stat_read(spec)
end

-- The known stat names, sorted.
function R.stat.names()
    local t = {}
    for k in pairs(R.stat.keys) do t[#t + 1] = k end
    table.sort(t)
    return t
end

-- EXPERIMENTAL write opt-in (default off — writes mutate live engine state).
local _stat_writes_enabled = false
function R.stat.enable_writes() _stat_writes_enabled = true end

-- Find the override entry for `key` in the store (entry addr, or nil).
local function _stat_find_entry(store, key)
    local data  = I.read_u64(store + OVR_DATA_OFF)
    local count = I.read_u32(store + OVR_COUNT_OFF)
    if not data or data == 0 or not count then return nil end
    for i = 0, count - 1 do
        local entry = data + i * OVR_STRIDE
        if I.read_u32(entry + ENTRY_KEY_OFF) == key then return entry end
    end
    return nil
end

-- Write an inline numeric value into an override entry's embedded union. Uses
-- only page-guarded pokes (a bad address no-ops rather than faults).
local function _stat_write_union(entry, spec, value)
    local u = entry + ENTRY_UNION_OFF
    I.write_u64(u + EV_INLINE_OFF, EV_INLINE)                 -- mark inline
    if spec.kind == "int" then
        I.write_u32(u + EV_VALUE_OFF, math.floor((value or 0) + 0.5))
    else
        I.write_f32(u + EV_VALUE_OFF, (value or 0) + 0.0)
    end
    I.write_u8(u + EV_TAG_OFF, 0)                             -- type tag: int/float
end

-- Set a named stat. EXPERIMENTAL, engine-mutating, MAIN-THREAD ONLY. Finds the
-- hero's override entry for the key (creating one via the engine allocator on a
-- miss) and writes the value into its union. Returns true on write. Fails
-- closed (logs, no-op) if writes aren't enabled, the hero/store is implausible,
-- or a symbol is unresolved.
function R.stat.set(name, value)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    if not _stat_writes_enabled then
        R.log("[rsmm.stat] writes are experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.stat") then return false end
    local e = R.entity.hero()
    if not e then R.log("[rsmm.stat] no hero captured yet"); return false end
    if not _hero_plausible(e) then R.log("[rsmm.stat] hero reads implausible — refusing"); return false end
    local store = _stat_store(e)
    if not store then R.log("[rsmm.stat] value store not found for this build — refusing"); return false end
    local entry = _stat_find_entry(store, spec.key)
    if not entry then
        -- Miss: grow the override vector via the engine allocator, init the slot.
        local count = I.read_u32(store + OVR_COUNT_OFF) or 0
        local ok, slot = pcall(R.engine.call, "EntityValueOverride_Alloc", store + OVR_DATA_OFF, count, 1)
        if not ok or not slot or slot == 0 then R.log("[rsmm.stat] override alloc failed"); return false end
        I.write_u32(slot + ENTRY_KEY_OFF, spec.key)
        pcall(R.engine.call, "EntityValueUnion_DefaultCtor", slot + ENTRY_UNION_OFF)
        I.write_u32(slot + 0x28, 0); I.write_u16(slot + 0x2c, 0); I.write_u64(slot + 0x30, 0)
        entry = slot
    end
    _stat_write_union(entry, spec, value)
    R.log(string.format("[rsmm.stat] set %s = %s (override cache — TRANSIENT; use R.stat.stick to keep it)",
        name, tostring(value)))
    return true
end

-- current + delta (reads then sets). EXPERIMENTAL (see R.stat.set).
function R.stat.add(name, delta)
    local cur = R.stat.get(name); if not cur then return false end
    return R.stat.set(name, cur + (delta or 0))
end

-- native engine modifier (composes with the game's own math) -------------
--
-- R.stat.modify(name, amount [, duration]) inserts a REAL engine modifier for
-- the stat's key: it builds an oCGameEventNetworkModifier (layout decompile-
-- verified from FUN_1403c7560's inline construction + ModifierEvent_Ctor
-- FUN_140389fb0) and calls EntityValueStore_ApplyModifierEvent(store, ev, 0, 0)
-- directly. Unlike R.stat.set (cache poke, wiped by recompute) and R.stat.stick
-- (re-assertion, pins the FINAL value), a modifier lives in the store's
-- modifier registry (store+0x88) and is folded together with the game's own
-- item/talent modifiers on every recompute — it COMPOSES and SURVIVES.
--
-- Event layout (0x98 bytes):
--   +0x00 vftable (oCGameEventNetworkModifier)  +0x08 state u32 (0 = ready)
--   +0x20 name oCString {ptr,cap|0x80000000,len} +0x30 name hash (bus only —
--   unused on the direct call)                   +0x38 modifier id (-1 = fresh)
--   +0x50 serial u32   +0x54 stat CRC key u32    +0x58 counter u32
--   +0x60 oCEntityValueUnion (0x20B) carrying the AMOUNT (engine-ctor'd)
--   +0x80 duration f32 (<0 = permanent; give-handler uses 5.0 for its 5s buff)
--   +0x84/+0x88 multipliers f32 (1.0)            +0x8c flag u8 (1)
--   +0x90 source entity (0 = no lifetime binding)
--
-- How the amount folds (add/mul/replace) is DATA-DRIVEN per key: the value
-- def in the store's base map picks the typed modifier (def+0x74) and the
-- merge op (def+0x70: 1=add-stack 2=set 3=match-replace 4=min-remaining) and
-- caps the count (def+0x68). We can't choose the op — the engine applies its
-- native semantics for that stat, which is exactly what "compose correctly"
-- means. In co-op non-authority the engine relays the event to the host
-- instead of applying locally (its own code path, not ours).
--
-- EXPERIMENTAL + engine-mutating: MAIN THREAD only, R.stat.enable_writes()
-- required, fail-closed on any unresolved symbol / implausible pointer.
-- Pending in-game verification. Don't combine with R.stat.stick on the same
-- stat (stick pins the final value and would fight the modifier).
local MODIFIER_EVENT_VFT_VA = 0x140f322d0  -- oCGameEventNetworkModifier_vftable (symbol map)
local _mod_serial = 0

function R.stat.modify(name, amount, duration)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    if type(amount) ~= "number" then
        R.log("[rsmm.stat] modify: amount must be a number"); return false
    end
    if not _stat_writes_enabled then
        R.log("[rsmm.stat] writes are experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.stat.modify") then return false end
    local e = R.entity.hero()
    if not e then R.log("[rsmm.stat] no hero captured yet"); return false end
    if not _hero_plausible(e) then R.log("[rsmm.stat] hero reads implausible — refusing"); return false end
    local store = _stat_store(e)
    if not store then R.log("[rsmm.stat] value store not found — refusing"); return false end

    -- Rebase the vftable va and sanity-probe it: slot 0 must hold a pointer
    -- into the game module (a wrong build / stale va reads as garbage and we
    -- refuse rather than hand the engine a fake object with a bad vtable).
    local base = I.module_base()
    if not base or base == 0 then return false end
    local vft = base + (MODIFIER_EVENT_VFT_VA - GIVE_IMG_BASE)
    local slot0 = I.read_u64(vft)
    if not slot0 or slot0 < base or slot0 >= base + 0x1600000 then
        R.log("[rsmm.stat] modifier-event vftable implausible on this build — refusing")
        return false
    end

    -- ONE scratch alloc for event + trailing ""-buffer. NEVER take a second
    -- scratch while the first is live: the native arena may hand back an
    -- overlapping block and zero its front — a second call here wiped the
    -- event's vftable and crashed the engine's virtual fill with a null
    -- vtable (2026-07-16, minidumps 25815b01/0425b5d9: READ @0x20 at
    -- ModifierEvent_Ctor+0xb9).
    local ev = I.scratch(0xb0)                     -- 0x98 event + 0x10 name tail
    local empty = ev + 0xa0                        -- zeroed tail doubles as ""
    I.write_u64(ev + 0x00, vft)
    I.write_u32(ev + 0x08, 0)                      -- state: ready
    I.write_u64(ev + 0x20, empty)                  -- name: empty, UNOWNED
    I.write_u32(ev + 0x28, 0x80000000)             -- (cap flag = engine won't free)
    I.write_u32(ev + 0x2c, 0)
    I.write_u32(ev + 0x30, 0)                      -- name hash: direct call, unused
    I.write_u64(ev + 0x38, 0xffffffffffffffff)     -- modifier id: fresh
    I.write_u32(ev + 0x40, 0)
    I.write_u64(ev + 0x48, 0xffffffffffffffff)
    _mod_serial = _mod_serial + 1
    I.write_u32(ev + 0x50, _mod_serial)
    I.write_u32(ev + 0x54, spec.key)
    I.write_u32(ev + 0x58, 0)
    -- The amount rides in the embedded union at +0x60. Construct it through
    -- the engine's own ctors (exactly the sequence the give-handler and
    -- ApplyModifierEvent use for their locals: default-ctor, destruct,
    -- re-init as numeric type 0) — then write the inline value.
    local u = ev + 0x60
    local okc, uret = pcall(R.engine.call, "EntityValueUnion_DefaultCtor", u)
    if not okc or not uret then
        R.log("[rsmm.stat] union ctor unresolved — refusing"); return false
    end
    pcall(R.engine.call, "EntityValueUnion_Destruct", u)
    pcall(R.engine.call, "EntityValueUnion_InitAsType", u, 0)
    if spec.kind == "int" then
        I.write_u32(u + 0x10, math.floor(amount + 0.5))
    else
        I.write_f32(u + 0x10, amount + 0.0)
    end
    I.write_f32(ev + 0x80, duration or -1.0)       -- default: permanent
    I.write_f32(ev + 0x84, 1.0)
    I.write_f32(ev + 0x88, 1.0)
    I.write_u8(ev + 0x8c, 1)
    I.write_u64(ev + 0x90, 0)                      -- no entity-lifetime binding
    -- Resolve BEFORE calling: ApplyModifierEvent returns void, so a nil from
    -- R.engine.call can't distinguish success from an unresolved symbol.
    if not R.engine.resolve("EntityValueStore_ApplyModifierEvent") then
        R.log("[rsmm.stat] ApplyModifierEvent unresolved on this build — refusing"); return false
    end
    local ok = pcall(R.engine.call, "EntityValueStore_ApplyModifierEvent", store, ev, 0, 0)
    if not ok then
        R.log("[rsmm.stat] ApplyModifierEvent raised — modifier NOT applied"); return false
    end
    R.log(string.format("[rsmm.stat] modify %s %+g (native modifier, %s)", name, amount,
        (duration and duration >= 0) and (tostring(duration) .. "s") or "permanent"))
    return true
end

-- durable stats (sticky re-assertion) -----------------------------------
--
-- R.stat.set writes the override CACHE, which EntityValueStore_Recompute
-- (FUN_140749a90) rebuilds from base + engine modifiers whenever the key goes
-- dirty (item pickup, level-up, ...). So a bare set is TRANSIENT. R.stat.stick
-- makes a value DURABLE by re-asserting it on the main-thread gameplay pump:
-- once a recompute clobbers the key, the next gameplay event re-applies it. The
-- re-assert is DRIFT-GATED — it only re-pokes when the live value has actually
-- moved off the target — so steady-state cost is one page-guarded read per
-- pinned stat per gameplay event and zero writes.
--
-- This is re-assertion over the existing (gated) poke, NOT a native engine
-- modifier: it pins the FINAL value and does not compose with the game's own
-- modifier math. For "set attack to X and keep it" that is exactly right. A true
-- additive modifier that composes with item/talent modifiers needs the
-- oCGameEventNetworkModifier dispatch path (symbols EntityValueStore_ApplyModifierEvent
-- / ModifierEvent_Ctor) whose event payload is not yet decoded — see
-- docs/_re/kinds/stats.md.
--
--   R.stat.stick("attack_power", 500)   -- set + keep it there
--   R.stat.unstick("attack_power")      -- stop pinning (engine restores base)
--   R.stat.sticky()                     -- table of currently-pinned {name=value}
local _stat_sticky = {}
local _stat_reassert_installed = false
local _STAT_DRIFT = 1e-4

-- Re-apply every pinned stat whose live value has drifted. Runs on the main
-- thread (called only from the gameplay-bus handler installed below).
local function _stat_reassert()
    if not _stat_writes_enabled then return end
    if not R.entity.hero() then return end
    for name, value in pairs(_stat_sticky) do
        local cur = R.stat.get(name)
        if cur == nil or math.abs(cur - value) > _STAT_DRIFT then
            R.stat.set(name, value)
        end
    end
end

-- Subscribe the re-assert to the gameplay bus once. The gameplay-bus wildcard
-- runs on the game's MAIN thread (same pump as the schedule main tick below);
-- gating on ev.source == "gameplay" keeps engine-mutating writes off the loader
-- background thread ("tick"/"ready"), per [[loader-thread-model]].
local function _stat_install_reassert()
    if _stat_reassert_installed then return end
    _stat_reassert_installed = true
    R.on("*", function(ev)
        if ev and ev.source == "gameplay" then _stat_reassert() end
    end)
end

-- Pin a stat to `value` durably. Applies immediately through R.stat.set (so all
-- its gates apply: enable_writes, main-thread, hero/store plausibility) and
-- re-asserts after every recompute. Returns the immediate-apply result.
function R.stat.stick(name, value)
    local spec = R.stat.keys[name]
    if not spec then R.log("[rsmm.stat] unknown stat: " .. tostring(name)); return false end
    _stat_sticky[name] = value
    _stat_install_reassert()
    return R.stat.set(name, value)
end

-- Stop pinning a stat. The engine's next recompute restores its computed value.
-- Returns true if it was pinned.
function R.stat.unstick(name)
    local had = _stat_sticky[name] ~= nil
    _stat_sticky[name] = nil
    return had
end

-- Shallow copy of the currently-pinned {name = value} table.
function R.stat.sticky()
    local t = {}
    for k, v in pairs(_stat_sticky) do t[k] = v end
    return t
end

-- experience (level / xp grant) -----------------------------------------
--
-- XP lives on its own hero component (the XpComponent), not the value store.
-- R.xp reads level/xp and (EXPERIMENTAL) grants XP through the engine's own
-- gain-experience routine, which runs the level-up loop and fires _XP_LEVEL_UP.
-- Grant is engine-mutating: MAIN THREAD + R.stat.enable_writes() opt-in.
--
--   R.xp.level() / R.xp.xp()   -- current level / xp-within-level, or nil
--   R.xp.grant(100)            -- add XP (levels up as needed)
R.xp = {}

local XP_VFTABLE_VA      = 0x140f23200  -- XpComponent::vftable
local XP_TESTER_VA       = 0x141476e00  -- XpComponent_TypeTester (data global)
local XP_ARR_OFF         = 0x190        -- entity -> component ptr array
local XP_ARR_COUNT_OFF   = 0x198        -- entity -> component count
local XP_OWNER_OFF       = 0x08         -- component -> owner entity (back-ptr)
local XP_PROGRESS_OFF    = 0x108        -- xpComp -> {level u32 @+0, xp u32 @+4}
local XP_GAIN_AMOUNT_OFF = 0x50         -- xpGain struct -> amount (int)

local _xp_cache_hero, _xp_cache_comp = nil, nil
local _xp_diag_done = false

-- Candidate component-array owners. The two direct candidates —
-- *(hero+0x2f8) and the captured object itself — both had EMPTY component
-- arrays in the 2026-07-17 playtest (diag: arr=0 count=0), so the
-- component-owning oCEntity hangs off some OTHER field of the captured
-- controller. Probe every pointer-sized field of the hero and of the value
-- ctx for an object with a plausible component array @+0x190/+0x198
-- (Entity_GetComponentByTester's walk, decompile-reconfirmed 2026-07-17).
-- Pure page-guarded reads, cached per hero — tick-thread safe.
-- An owner is accepted ONLY if its ENTIRE component array validates: every
-- entry is a plausible pointer whose vftable lies inside the game image and
-- whose owner back-ptr points back at the entity. This is the gate that
-- makes it safe to hand the entity to engine code later — the 2026-07-17
-- crash (null deref at Entity_GetComponentByTester+0x36) was the engine
-- walking a false-positive "array" the loose probe had accepted.
local function _xp_owner_valid(entity, _mbase)
    return _vector_valid(entity, XP_ARR_OFF, XP_ARR_COUNT_OFF, {
        min = 1, max = 0x100,
        check_entry = function(comp, owner)
            -- component: vtable in image AND owner back-ptr matches the entity.
            return _obj_has_vtable(comp) and I.read_u64(comp + XP_OWNER_OFF) == owner
        end,
    })
end

local _xp_owners_hero, _xp_owners = nil, nil
local function _xp_entities(hero)
    if hero == _xp_owners_hero and _xp_owners then return _xp_owners end
    local mbase = I.module_base(); if not mbase or mbase == 0 then return {} end
    local owners, seen = {}, {}
    local function consider(P)
        if not P or P == 0 or seen[P] or not _ptr_plausible(P) then return end
        seen[P] = true
        if _xp_owner_valid(P, mbase) then owners[#owners + 1] = P end
    end
    local ctx = I.read_u64(hero + ENTITY_VALCTX_OFF)
    consider(ctx); consider(hero)
    for _, base in ipairs({ hero, ctx }) do
        if base and base ~= 0 and _ptr_plausible(base) then
            for off = 0, 0x7f8, 8 do
                consider(I.read_u64(base + off))
            end
        end
    end
    _xp_owners_hero, _xp_owners = hero, owners
    return owners
end

-- Engine-call-free XP detection: the XpComponent is recognizable by shape —
-- +0x108 points at a {level u32, xp u32} block with sane values and +0x10
-- holds the curve object pointer. Accepted only when exactly ONE component
-- across all validated owners matches (ambiguity falls through to the
-- engine-tester path rather than risking a grant on the wrong component).
local function _xp_heuristic(hero, mbase)
    local hit, hits = nil, 0
    for _, entity in ipairs(_xp_entities(hero)) do
        local arr = I.read_u64(entity + XP_ARR_OFF)
        local n   = I.read_u32(entity + XP_ARR_COUNT_OFF)
        for i = 0, n - 1 do
            local comp = I.read_u64(arr + i * 8)
            local prog = I.read_u64(comp + XP_PROGRESS_OFF)
            if prog and prog ~= 0 and _ptr_plausible(prog)
               and _ptr_plausible(I.read_u64(comp + 0x10)) then
                local lvl = I.read_u32(prog)
                local xpv = I.read_u32(prog + 4)
                if lvl and xpv and lvl >= 1 and lvl <= 200 and xpv < 10000000 then
                    hits = hits + 1
                    hit = comp
                end
            end
        end
    end
    if hits == 1 then
        local vft = I.read_u64(hit)
        R.log(string.format(
            "[rsmm.xp] heuristic found XpComponent 0x%x (vft 0x%x; map expects 0x%x)",
            hit, vft and (vft - mbase + ENTITY_IMG_BASE) or 0, XP_VFTABLE_VA))
        return hit
    end
    if hits > 1 then
        R.log(string.format("[rsmm.xp] heuristic ambiguous (%d progress-shaped components) — deferring to engine tester", hits))
    end
    return nil
end

-- Pure-memory fallback: scan the component array for the exact XpComponent
-- vftable. Misses if the live component is a SUBCLASS (different vftable) —
-- the suspected cause of the 2026-07-16 "XP component not found". Kept as the
-- thread-safe read path; each hit validated by the owner back-ptr.
local function _xp_scan(hero)
    local base = I.module_base(); if not base or base == 0 then return nil end
    local want = base + (XP_VFTABLE_VA - ENTITY_IMG_BASE)
    for _, entity in ipairs(_xp_entities(hero)) do
        if entity and entity ~= 0 then
            local arr   = I.read_u64(entity + XP_ARR_OFF)
            local count = I.read_u32(entity + XP_ARR_COUNT_OFF)
            if arr and arr ~= 0 and count and count <= 0x400 then
                for i = 0, count - 1 do
                    local comp = I.read_u64(arr + i * 8)
                    if comp and comp ~= 0 and I.read_u64(comp) == want
                       and I.read_u64(comp + XP_OWNER_OFF) == entity then
                        return comp
                    end
                end
            end
        end
    end
    return nil
end

-- One-shot diagnostic when everything misses: log each candidate's component
-- count and the rebased vftables of its first few components, so the real
-- XpComponent vftable can be identified from the log without a debugger.
local function _xp_diag(hero)
    if _xp_diag_done then return end
    _xp_diag_done = true
    local base = I.module_base(); if not base or base == 0 then return end
    local owners = _xp_entities(hero)
    R.log(string.format("[rsmm.xp] diag: %d component-array owner(s) probed from hero 0x%x",
        #owners, hero))
    for ci = 1, math.min(#owners, 8) do
        local entity = owners[ci]
        local arr   = I.read_u64(entity + XP_ARR_OFF)
        local count = I.read_u32(entity + XP_ARR_COUNT_OFF)
        R.log(string.format("[rsmm.xp] diag cand%d entity=0x%x arr=0x%x count=%s",
            ci, entity, arr or 0, tostring(count)))
        if arr and arr ~= 0 and count and count <= 0x400 then
            for i = 0, math.min(count, 12) - 1 do
                local comp = I.read_u64(arr + i * 8)
                local vft  = comp and comp ~= 0 and I.read_u64(comp) or nil
                if vft and vft > base then
                    R.log(string.format("[rsmm.xp] diag cand%d comp[%d]=0x%x vft=0x%x",
                        ci, i, comp, vft - base + ENTITY_IMG_BASE))
                end
            end
        end
    end
end

-- Locate the hero's XpComponent. `allow_engine` (MAIN THREAD ONLY — the
-- engine walk calls each component's virtual IsKindOf) uses the engine's own
-- Entity_GetComponentByTester with the XpComponent type-tester, which
-- resolves subclasses the exact-vftable scan can't. The result is cached per
-- hero so the tick-thread readers (level/xp) never touch engine code.
local function _xp_component(hero, allow_engine)
    if not hero then return nil end
    if hero == _xp_cache_hero and _xp_cache_comp then return _xp_cache_comp end
    local comp = _xp_scan(hero)
    if not comp then
        local mb = I.module_base()
        if mb and mb ~= 0 then comp = _xp_heuristic(hero, mb) end
    end
    if not comp and allow_engine then
        local base = I.module_base()
        local tester = base and base ~= 0 and (base + (XP_TESTER_VA - ENTITY_IMG_BASE)) or nil
        if tester and _ptr_plausible(I.read_u64(tester)) then
            for _, entity in ipairs(_xp_entities(hero)) do
                -- entity already passed _xp_owner_valid (full component-array
                -- validation) inside _xp_entities — safe to hand to the engine
                -- walk. call_safe re-guards both pointer args as belt-and-braces.
                if entity and entity ~= 0 and _ptr_plausible(entity) then
                    local ok, got = pcall(R.engine.call_safe, "Entity_GetComponentByTester",
                                          { 1, { 2, _in_image } }, entity, tester)
                    local prog = ok and type(got) == "number" and got ~= 0
                                 and I.read_u64(got + XP_PROGRESS_OFF) or 0
                    if prog and prog ~= 0 then
                        local vft = I.read_u64(got)
                        R.log(string.format(
                            "[rsmm.xp] engine lookup found XpComponent 0x%x (vft 0x%x; map scan expects 0x%x)",
                            got, vft and (vft - base + ENTITY_IMG_BASE) or 0, XP_VFTABLE_VA))
                        comp = got
                        break
                    end
                end
            end
        end
        if not comp then _xp_diag(hero) end
    end
    if comp then _xp_cache_hero, _xp_cache_comp = hero, comp end
    return comp
end

local function _xp_progress(field)
    local comp = _xp_component(R.entity.hero()); if not comp then return nil end
    local prog = I.read_u64(comp + XP_PROGRESS_OFF)
    if not prog or prog == 0 then return nil end
    return I.read_u32(prog + field)
end

function R.xp.level() return _xp_progress(0) end
function R.xp.xp()    return _xp_progress(4) end

-- Grant XP through the engine's gain-experience routine. EXPERIMENTAL,
-- MAIN-THREAD ONLY, gated by R.stat.enable_writes(). Fails closed on any guard.
function R.xp.grant(amount)
    if not _stat_writes_enabled then
        R.log("[rsmm.xp] grant is experimental and off — call R.stat.enable_writes() first")
        return false
    end
    if not _va_ok("R.xp") then return false end
    amount = math.floor(amount or 0)
    if amount <= 0 then return false end
    local hero = R.entity.hero()
    if not hero then R.log("[rsmm.xp] no hero captured yet"); return false end
    -- grant runs on the MAIN thread (schedule.next_main contract) — the only
    -- place the engine-walk lookup is safe.
    local comp = _xp_component(hero, true)
    if not comp then R.log("[rsmm.xp] XP component not found for this build — refusing"); return false end
    -- The routine reads only *(int*)(xpGain+0x50); a zeroed scratch is enough.
    local gain = I.scratch(0x60)
    I.write_u32(gain + XP_GAIN_AMOUNT_OFF, amount)
    local ok = pcall(R.engine.call, "Hero_GainExperience", comp, gain)
    if not ok then R.log("[rsmm.xp] Hero_GainExperience unresolved/failed"); return false end
    R.log("[rsmm.xp] granted " .. amount .. " xp")
    return true
end

-- hero (identity / per-hero scope) --------------------------------------
--
-- Every hero has its own ability/event vocabulary (Piper's rats, Juliet's
-- mechanics, Scarlet's crows, ...). REACTING to those events already works —
-- they arrive on the gameplay bus by name, e.g.:
--
--     R.on("gameplay:ENCHANTED_BLADES_HEAVY_IMPACT", function(ev) ... end)
--
-- and only ever fire when the hero that owns the ability acts, so subscribing
-- is implicitly per-hero. R.hero adds the missing piece: a stable handle to the
-- CURRENT hero plus identity, so a mod can scope its logic ("only for Juliet")
-- and so we can build a per-hero event catalog.
--
--   R.hero.handle()   -- live hero dispatcher pointer (instant; nil pre-act)
--   R.hero.ready()    -- true once the hero has acted once this run
--   R.hero.name()     -- "Piper"/"Scarlet"/... from event signature, or nil
--   R.hero.is("Piper")-- true if the current hero matches (case-insensitive)
--   R.hero.catalog()  -- dump this hero's distinctive events (seeds signatures)
--   R.hero.on(name, cb) -- R.on("gameplay:"..name) gated to fire only when a
--                          hero is active this run (convenience for ability hooks)
R.hero = {}

-- IDENTITY MODEL: event-signature. Ghidra confirmed the hero entity has no
-- type/def field — it's a generic oe::Entity component aggregate (carrier
-- vtable 0x140f2b930, ctor FUN_14038e320: dozens of component arrays, no
-- herodef). So "which hero" is inferred from the EXCLUSIVE ability events the
-- hero fires on the gameplay bus (Piper -> rat/flute events, Scarlet -> crows,
-- ...). Robust (no fragile offsets) and engine-aligned. The name<->event map
-- is seeded from observed play (R.hero.catalog dumps a hero's distinctive
-- events; fold them into _HERO_SIGNATURES below).

-- Live hero dispatcher (instant — captured from the first hero-anchored event,
-- shared with R.give). This is the right "current hero" handle for emitting
-- events at the hero; it does NOT require the heal/pickup capture R.combat does.
function R.hero.handle() return _give_hero end
function R.hero.ready()  return _give_hero ~= nil end

-- Substrings marking events that EVERY hero fires (movement, items, UI, charge
-- counters, ...). These carry no identity, so they're excluded from a hero's
-- signature set, leaving only ability-distinctive events.
local _GENERIC_EVENT_PATTERNS = {
    "ABILITY_MAX", "ABILITY_EXIT", "COUNTER", "OPTIMIZE", "MODIFIER", "LIFE_BAR",
    "SHOW", "HIDE", "TILE", "INTERACT", "NETWORK", "REFUGEE", "MASTER", "TAB",
    "BORDER", "DREAM", "REROLL", "ENERGY", "COMBO", "COLLECT", "IMPACT",
    "STAGGER", "KILL", "DEAD", "DEATH", "PROJECTILE", "SPAWN", "BARK", "RESET",
    "CLEAR", "LEGENDARY", "GIVE_MAG", "POSITION", "PRIMARY_", "SECONDARY_",
    "DEFENSIVE_", "ULTIMATE_", "DASH_", "HEALTH", "TELEPORT", "MAP", "GAME_",
    "CHEST", "FOUNTAIN", "INGREDIENT", "TRAIT_CHARGE", "AMMO", "TRIGGER",
    "DUPLICATE", "OBJECT", "REWARD", "WISH", "XP_LEVEL", "ACTIVITY", "BHV",
    "BUTTON", "MENU", "CHRONO", "GENERATE", "FEEDBACK", "GLOBE",
}
local function _is_generic(gp)
    for _, pat in ipairs(_GENERIC_EVENT_PATTERNS) do
        if gp:find(pat, 1, true) then return true end
    end
    return false
end

-- name -> { signature event names }. A hero matches when ALL its signature
-- events have been seen this session. Seed from R.hero.catalog() output (play
-- each hero, read the distinctive list, paste the hero-exclusive ones here).
-- Empty entries are placeholders to be filled; an unmatched hero yields nil.
local _HERO_SIGNATURES = {
    -- Seeded from in-game catalogs. Each entry = events the hero fires that no
    -- other hero does; a hero matches when ALL its signature events are seen.
    -- SHATTER = Snow Queen's freeze->shatter payoff (her core ice mechanic).
    -- Excluded as non-exclusive: START_DAYMARE/START_NIGHTMARE (global day/night
    -- cycle), SUMMON_DEAD_ENTITIES/TEARING_SLASHES (talent/object effects).
    SnowQueen = { "SHATTER" },
    -- Piper   = { ... },  -- play Piper, read R.hero.catalog(), seed here
    -- Scarlet = { ... },
}

-- Gameplay events seen (with fire counts) for the CURRENT hero session. Reset
-- when the live hero dispatcher changes (switch character / new run). We record
-- ALL events here; _is_generic only labels them in the catalog so the
-- hero-distinctive ones are easy to spot for seeding signatures.
local _hero_events = {}
local _sig_last_hero = nil
R.on("*", function(ev, name)
    if type(name) ~= "string" then return end
    local gp = name:match("^gameplay:(.+)$")
    if not gp then return end
    if _give_hero ~= _sig_last_hero then
        _hero_events = {}
        _sig_last_hero = _give_hero
    end
    _hero_events[gp] = (_hero_events[gp] or 0) + 1
end)

-- Short hero name (e.g. "Piper") inferred from the events seen this session, or
-- nil if no signature has matched yet (early in a run, or hero not yet mapped).
function R.hero.name()
    for who, sig in pairs(_HERO_SIGNATURES) do
        local all = true
        for _, evname in ipairs(sig) do
            if not _hero_events[evname] then all = false; break end
        end
        if all and #sig > 0 then return who end
    end
    return nil
end

-- True if event `gp` is fired by all heroes (no identity value). Used only to
-- LABEL catalog output; collection records everything.
local function _generic(gp) return _is_generic(gp) end

-- True if the current hero is `who` (case-insensitive short name).
function R.hero.is(who)
    local n = R.hero.name()
    return n ~= nil and who ~= nil and n:lower() == tostring(who):lower()
end

-- Dump the distinctive (non-generic) events seen for the current hero this
-- session — the raw material for seeding _HERO_SIGNATURES. Play one hero, fire
-- its abilities, then call this; the hero-exclusive lines become its signature.
function R.hero.catalog()
    local names = {}
    for k in pairs(_hero_events) do names[#names + 1] = k end
    table.sort(names)
    R.log(string.format("[rsmm.hero] catalog: %d event(s) this session (hero=%s) "
        .. "— '*' = hero-distinctive candidate, '.' = generic",
        #names, tostring(R.hero.name())))
    for _, k in ipairs(names) do
        R.log(string.format("[rsmm.hero]   %s %s (x%d)",
            _generic(k) and "." or "*", k, _hero_events[k]))
    end
end

-- Subscribe to a hero ability event by bare NAME, only firing while a hero is
-- active this run. cb(ev) gets the gameplay payload. Thin sugar over R.on that
-- documents intent ("this is a hero ability hook") and skips menu-time noise.
function R.hero.on(name, cb)
    assert(type(name) == "string", "R.hero.on: name must be string")
    assert(type(cb) == "function", "R.hero.on: cb must be function")
    return R.on("gameplay:" .. name, function(ev)
        if _give_hero ~= nil then cb(ev) end
    end)
end

-- netcode (advanced / experimental) -------------------------------------
--
-- Replication-authority observation, for host-migration research. The
-- per-entity replication setup (Netcode_EntityReplSetup) decides master vs
-- client; the role lives behind the net manager. Offsets are SDK-internal — a
-- mod only sees (netmgr, role) and may return a number to overwrite role
-- (DANGEROUS: a live netcode write, can crash). See docs/_re/MULTIPLAYER.md.
--
--   R.net.on_repl_setup(function(netmgr, role, ctx)
--       R.log("role", role)        -- 1 = client/non-master
--       -- return 0 to force the master path (Phase 2; can crash)
--   end)

R.net = {}

local NET_CTX_TO_NETMGR_OFF = 0x10         -- netmgr = *(ctx + 0x10)
local NET_ROLE_OFF          = 0xf8         -- role   = *(netmgr + 0xf8); 1=client

-- Hook the per-entity replication setup. cb(netmgr, role, ctx) fires for each
-- entity; return a number from cb to OVERWRITE role (dangerous), or nil to
-- leave it. Returns the hook handle, or nil if Netcode_EntityReplSetup is
-- unresolved for this game build (pattern DB fail-closed — never hook stale).
function R.net.on_repl_setup(cb)
    assert(type(cb) == "function", "R.net.on_repl_setup: cb must be function")
    local va = I.resolve and I.resolve("Netcode_EntityReplSetup")
    if not va then
        R.log("[rsmm.net] Netcode_EntityReplSetup unresolved for this game "
            .. "build — on_repl_setup unavailable")
        return nil
    end
    return R.hook(va, "vp", function(ctx)
        if not ctx or ctx == 0 then return nil end
        local netmgr = I.read_u64(ctx + NET_CTX_TO_NETMGR_OFF)
        if not netmgr or netmgr == 0 then return nil end
        local role = I.read_u32(netmgr + NET_ROLE_OFF)
        local newrole = cb(netmgr, role, ctx)
        if type(newrole) == "number" then
            I.write_u32(netmgr + NET_ROLE_OFF, newrole)
        end
        return nil
    end)
end

-- game options ----------------------------------------------------------
--
-- The engine keeps every persisted setting in one inline registry object
-- (g_GameOptions). Each option stores its current value at +0x28 of its
-- 0x30-byte slot; consumers read that field directly, so writing it from Lua
-- takes effect without any save/reload. This exposes the debug/cheat toggles
-- the retail build ships but never surfaces in the UI, plus normal settings.
--
--   R.options.set("Forced seed", 12345)      -- reproducible run gen
--   R.options.set("Show enemy debug info", true)
--   R.options.get("Force epilogue")          -- -> false
--   for name in R.options.list() do ... end
--
-- NOTE: a few pure-debug toggles may be additionally gated by g_bEnableDebug
-- (a runtime cvar we can't resolve), so writing them can be a no-op in retail.
-- The non-debug options (Forced seed, screen shake, damage numbers, ...) are
-- unconditional. Test per option.

R.options = {}

-- Re-derived 2026-07-10 after the 2026-07-09 game patch (ctor is now
-- FUN_1401ca130, found via the "Forced seed" string xref; it stores the
-- singleton to this slot as its first write).
local OPT_GAMEOPTIONS_VA = 0x14143cb58
local OPT_IMG_BASE = 0x140000000
local OPT_VALUE_OFF = 0x28

-- name -> { off = byte offset of the option's slot from the object base,
--           type = "bool" | "uint" | "int" | "float" }
-- Offsets transcribed from the options ctor (FUN_1401ca130, 2026-07-09 build);
-- value at off+0x28. The patch added "Delay before can unpause" / "Max pause
-- per player", which moved "Pause during choices" (0x10f8 -> 0x10f0); every
-- other slot is unchanged.
local _OPT = {
    ["Forced seed"]                                 = { off = 0x0000, type = "uint"  },
    -- "Dev" is the build-type flag the ctor seeds from a baked constant; the
    -- engine honours "Forced seed" only while it is true (this is what the
    -- old seeded-runs raw poke at +0x58 was flipping).
    ["Dev"]                                         = { off = 0x0030, type = "bool"  },
    ["Test"]                                        = { off = 0x0060, type = "bool"  },
    ["Dash at cursor"]                              = { off = 0x0e80, type = "bool"  },
    ["Screen shake"]                                = { off = 0x1090, type = "bool"  },
    ["Pause during choices"]                        = { off = 0x10f0, type = "bool"  },
    ["Show damage and healing numbers"]             = { off = 0x11b0, type = "bool"  },
    ["Select random skin when using random heroes"] = { off = 0x11e0, type = "bool"  },
    ["Show enemy debug info"]                       = { off = 0x1210, type = "bool"  },
    ["Sectorize enemy camps"]                       = { off = 0x1240, type = "bool"  },
    ["Display fake unlock in recap"]                = { off = 0x1270, type = "bool"  },
    ["Show social options debug"]                   = { off = 0x12a0, type = "bool"  },
    ["Show hourglass debug info"]                   = { off = 0x12d0, type = "bool"  },
    ["Force epilogue"]                              = { off = 0x1300, type = "bool"  },
    ["Force end credits"]                           = { off = 0x1330, type = "bool"  },
}

-- Accept the GameOptions singleton pointer only if a couple of known bool slots
-- read as real booleans (0/1). A wrong-but-mapped pointer will almost always
-- fail this, turning a mis-derived va into a safe no-op instead of a stray write
-- into unrelated engine memory. Reads are fault-safe (nil on a bad address),
-- and `nil ~= 0 and nil ~= 1` is true, so an unmapped obj also fails closed.
local function _options_obj_valid(obj)
    local dev  = I.read_u8(obj + 0x0030 + OPT_VALUE_OFF)   -- "Dev"
    if dev ~= 0 and dev ~= 1 then return false end
    local test = I.read_u8(obj + 0x0060 + OPT_VALUE_OFF)   -- "Test"
    if test ~= 0 and test ~= 1 then return false end
    return true
end

local _opt_bad_warned = false
local function _opt_value_addr(name)
    local o = _OPT[name]
    if not o then return nil, nil end
    if not _va_ok("R.options") then return nil, nil end
    local base = I.module_base()
    if not base or base == 0 then return nil, nil end
    local obj = I.read_u64(base + (OPT_GAMEOPTIONS_VA - OPT_IMG_BASE))
    if not _ptr_plausible(obj) or not _options_obj_valid(obj) then
        if not _opt_bad_warned then
            _opt_bad_warned = true
            R.log("[rsmm.options] g_GameOptions pointer failed validation — "
                .. "refusing reads/writes this run (regenerate the symbol map)")
        end
        return nil, nil
    end
    return obj + o.off + OPT_VALUE_OFF, o.type
end

-- Read an option's current value. Returns bool/number, or nil if the name is
-- unknown or the registry isn't initialised yet.
function R.options.get(name)
    local addr, ty = _opt_value_addr(name)
    if not addr then return nil end
    if ty == "bool"  then return I.read_u8(addr) ~= 0 end
    if ty == "float" then return I.read_f32(addr) end
    return I.read_u32(addr)
end

-- Write an option's current value. Bools accept true/false; numeric options
-- accept a number. Returns true on success, false if unknown/unavailable.
function R.options.set(name, value)
    local addr, ty = _opt_value_addr(name)
    if not addr then
        R.log("[rsmm.options] unknown option or registry not ready:", name)
        return false
    end
    if ty == "bool" then
        I.write_u8(addr, value and 1 or 0)
    elseif ty == "float" then
        I.write_f32(addr, value + 0.0)
    else
        I.write_u32(addr, math.floor(value or 0))
    end
    return true
end

-- Iterator over every known option name.
function R.options.list()
    local names = {}
    for k in pairs(_OPT) do names[#names + 1] = k end
    table.sort(names)
    local i = 0
    return function()
        i = i + 1
        return names[i]
    end
end

-- hooks (low-level escape valve; users should prefer R.* abstractions) -

R.hook   = native.hook
R.unhook = native.unhook

-- Hero-capture is armed lazily on first R.entity / R.combat use (see
-- R.entity.hero) — NOT eagerly here. Arming touches R.hook, which can fail on
-- handler-address drift; doing it at module load would abort require"rsmm" for
-- EVERY mod, not just ones using combat. Lazy + pcall-guarded keeps it contained.

-- key-value store -------------------------------------------------------
--
-- Per-mod persistent state. Scalar values (string/number/boolean) are saved
-- to <mod_dir>/.rsmm_state and reloaded next launch, so counters and flags
-- survive game restarts. Loaded lazily on first access; flushed automatically
-- on the "exit" event, and on demand via R.kv.save(). Non-scalar values
-- (tables/functions) are kept in memory but skipped when saving.

R.kv = {}

local _kv
local _kv_dirty = false

-- line format, one entry per line: "<s|n|b>\t<key>\t<value>"; key and string
-- values are escaped so embedded TAB/newline/backslash round-trip safely.
local function _esc(s)
    return (s:gsub("[\\\n\t]", { ["\\"] = "\\\\", ["\n"] = "\\n", ["\t"] = "\\t" }))
end

local function _unesc(s)
    return (s:gsub("\\(.)", { ["\\"] = "\\", n = "\n", t = "\t" }))
end

local function _serialize(tbl)
    local out = {}
    for k, v in pairs(tbl) do
        local t = type(v)
        if t == "string" then
            out[#out + 1] = "s\t" .. _esc(k) .. "\t" .. _esc(v)
        elseif t == "number" then
            out[#out + 1] = "n\t" .. _esc(k) .. "\t" .. tostring(v)
        elseif t == "boolean" then
            out[#out + 1] = "b\t" .. _esc(k) .. "\t" .. (v and "1" or "0")
        end  -- tables/functions: in-memory only, not persisted
    end
    return table.concat(out, "\n")
end

local function _deserialize(str)
    local tbl = {}
    for line in (str .. "\n"):gmatch("(.-)\n") do
        local t, k, v = line:match("^(%a)\t(.-)\t(.*)$")
        if t then
            k = _unesc(k)
            if t == "s" then
                tbl[k] = _unesc(v)
            elseif t == "n" then
                tbl[k] = tonumber(v)
            elseif t == "b" then
                tbl[k] = (v == "1")
            end
        end
    end
    return tbl
end

local _exit_hooked = false
local function _kv_load()
    if _kv ~= nil then return end
    local ok, raw = pcall(function() return I.state_read() end)
    _kv = (ok and type(raw) == "string") and _deserialize(raw) or {}
    if not _exit_hooked then
        _exit_hooked = true
        native.on_event("exit", function() R.kv.save() end)
    end
end

-- Flush the store to disk now. Returns true on success (or if nothing
-- changed since the last save). Pass force=true to write regardless.
function R.kv.save(force)
    if _kv == nil then return true end
    if not _kv_dirty and not force then return true end
    local ok, wrote = pcall(function() return I.state_write(_serialize(_kv)) end)
    if ok and wrote then _kv_dirty = false end
    return ok and wrote or false
end

function R.kv.get(k, default)
    _kv_load()
    local v = _kv[k]
    if v == nil then return default end
    return v
end

function R.kv.set(k, v)
    _kv_load()
    _kv[k] = v
    _kv_dirty = true
end

function R.kv.inc(k, by)
    _kv_load()
    _kv[k] = (_kv[k] or 0) + (by or 1)
    _kv_dirty = true
    return _kv[k]
end

function R.kv.all()
    _kv_load()
    local out = {}
    for k, v in pairs(_kv) do out[k] = v end
    return out
end

-- item registry ---------------------------------------------------------
--
-- R.item.register{ id=, name=, description=, rarity=, base= }
--   * `base` clones the bytes of an existing MO entity (e.g.
--     "Common/Armor_Per_Object") as a starting template.
--   * `name` and `description` populate the corresponding text-bank
--     keys via Text/Magical_Objects~GAM.xls.LocalText.gen overrides.
--
-- Custom LOGIC for an item is attached separately with R.item.behavior (below),
-- so a mod's item does whatever the mod's Lua says — not just a cloned game
-- effect. The two compose: register the carrier, then bind behavior to its GUID.

R.item = {}

local _registered_items = {}

function R.item.register(spec)
    assert(type(spec) == "table",       "R.item.register: spec must be table")
    assert(type(spec.id) == "string",   "R.item.register: spec.id required")
    if _registered_items[spec.id] then
        R.log("[rsmm.item] duplicate id, ignoring:", spec.id)
        return false
    end
    _registered_items[spec.id] = spec

    local entity_path = spec.entity_path
        or ("EntitySettings/Objects/Magical_Objects/"
            .. (spec.rarity or "Common") .. "/"
            .. spec.id .. ".entity.ot.EntitySettingsResource")

    local ok = I.register_item(
        spec.id,
        spec.name or "",
        spec.description or "",
        spec.base or "",
        entity_path,
        -- arg 6 is the NUMERIC rarity index; spec.rarity doubles as the path
        -- tier name (a string like "Common"), so only forward it when numeric.
        type(spec.rarity) == "number" and spec.rarity or 0
    )
    if ok then
        R.log("[rsmm.item] registered and wired:", spec.id)
        return true
    else
        R.log("[rsmm.item] native rejected duplicate:", spec.id)
        return false
    end
end

function R.item.list()
    local out = {}
    for _, s in pairs(_registered_items) do out[#out+1] = s end
    return out
end

-- R.item.guid(id) -> lo, hi  (or nil until the item's def loads into the pool).
-- Resolves a registered custom item's runtime identity GUID so the SAME mod can
-- bind R.item.behavior to its OWN item without precomputing the cook-derived
-- GUID. nil until the magical-object pool has the definition, so callers poll
-- (e.g. R.item.on_guid below, or retry on a tick).
function R.item.guid(id)
    assert(type(id) == "string", "R.item.guid: id must be a string")
    if not (I and I.item_guid) then return nil end
    return I.item_guid(id)
end

-- R.item.on_guid(id, cb) — poll until R.item.guid(id) resolves, then cb(lo, hi)
-- once. The clean way to wire behaviour to a freshly-registered custom item:
--   R.item.register{ id = "MyTalent", ... }
--   R.item.on_guid("MyTalent", function(lo, hi)
--       R.item.behavior{ guid = { lo, hi }, on_tick = ... }
--   end)
function R.item.on_guid(id, cb, opts)
    assert(type(cb) == "function", "R.item.on_guid: cb must be a function")
    opts = opts or {}
    local every = opts.every or 1.0
    local tries, limit = 0, opts.tries or 120
    local function poll()
        local lo, hi = R.item.guid(id)
        if lo then cb(lo, hi); return end
        tries = tries + 1
        if tries >= limit then
            R.log("[rsmm.item] on_guid timed out for", id); return
        end
        if R.schedule and R.schedule.after then R.schedule.after(every, poll) end
    end
    if R.schedule and R.schedule.after then R.schedule.after(every, poll)
    else R.log("[rsmm.item] on_guid needs the tick pump (R.schedule)") end
end

-- Bind custom logic to ownership of a magical object — the core of a
-- mod-defined item that runs the mod's OWN behaviour, not a cloned game effect.
-- The item is identified by its definition identity GUID (lo, hi); pair this
-- with a carrier created by R.item.register / the item SDK kind.
--
--   R.item.behavior{
--       guid = { lo, hi },          -- or guid_lo=, guid_hi=
--       every = 1.0,                -- on_tick cadence in seconds (default 1)
--       on_acquire = function(c) R.log("got it") end,
--       on_tick    = function(c) R.combat.heal(4) end,   -- while owned
--       on_lose    = function(c) end,
--   }
--
-- The callbacks receive ctx = { lo, hi } and may use R.combat / R.entity /
-- R.give freely — that is where the mod's logic lives. Ownership is polled from
-- R.give.owned() on the tick pump (R.schedule), so it needs the hero to have
-- acted once (R.give.ready()). EXPERIMENTAL: owned-set semantics confirmed in
-- game per the runtime pool array.
function R.item.behavior(spec)
    assert(type(spec) == "table", "R.item.behavior: spec must be table")
    local lo, hi = spec.guid_lo, spec.guid_hi
    if type(spec.guid) == "table" then lo, hi = spec.guid[1], spec.guid[2] end
    assert(type(lo) == "number" and type(hi) == "number",
        "R.item.behavior: needs guid {lo,hi} (or guid_lo/guid_hi)")
    local every = spec.every or 1.0
    local owned = false
    local function ctx() return { lo = lo, hi = hi } end

    local function poll()
        local now = R.give.owns(lo, hi)
        if now and not owned then
            owned = true
            if spec.on_acquire then spec.on_acquire(ctx()) end
        elseif (not now) and owned then
            owned = false
            if spec.on_lose then spec.on_lose(ctx()) end
        end
        if now and spec.on_tick then spec.on_tick(ctx()) end
        if R.schedule and R.schedule.after then R.schedule.after(every, poll) end
    end

    if R.schedule and R.schedule.after then
        R.schedule.after(every, poll)
        return true
    end
    R.log("[rsmm.item] behavior needs the tick pump (R.schedule) — unavailable")
    return false
end

-- NOT-YET-IMPLEMENTED stubs ---------------------------------------------
--
-- R.scaling and R.talent have a fixed API shape but NO game-side effect yet
-- (gated on RE of the value-modifier-computer and the skill-grant path). They
-- record the request and warn once so a mod author isn't misled into thinking
-- an override took. `R.scaling.pending()` / `R.talent.pending()` expose what
-- was requested, for when the wiring lands.

local _warned = {}
local function _warn_unimpl(api)
    if _warned[api] then return end
    _warned[api] = true
    R.log("[rsmm." .. api .. "] NOT IMPLEMENTED yet — calls are recorded but "
        .. "have no in-game effect. Track: docs/_re/HOOKPOINTS.md")
end

-- scaling: R.scaling.set("enemy_damage", function(act) return ({1,1.5,2})[act] end)
R.scaling = {}
local _scaling = {}

function R.scaling.set(field, fn)
    assert(type(field) == "string",   "R.scaling.set: field must be string")
    assert(type(fn)    == "function", "R.scaling.set: fn must be function")
    _scaling[field] = fn
    _warn_unimpl("scaling")
end

function R.scaling.get(field) return _scaling[field] end
function R.scaling.pending() return _scaling end

-- talent: R.talent.allow_stack(true) / R.talent.extra_at_level(11)
R.talent = {}
local _talent_cfg = { allow_stack = false, extra_at = {} }

function R.talent.allow_stack(b)
    _talent_cfg.allow_stack = b and true or false
    _warn_unimpl("talent")
end

function R.talent.extra_at_level(lvl)
    table.insert(_talent_cfg.extra_at, lvl)
    _warn_unimpl("talent")
end

function R.talent.pending() return _talent_cfg end

-- PICKABLE talents: react to the player choosing a level-up / reward card.
-- The gameplay bus fires "gameplay:POWER_UP_COLLECT_REQUEST" when a card is
-- picked; the loader attaches ev.card (the picked card's identity GUID, the
-- "0xlo:0xhi" payload slot the GIVE-event template fixes at +0x50/+0x58) plus a
-- confirm window ev.p38..ev.p58. `card` selects WHICH pick fires the callback:
--   nil / "*"        -> any card pick
--   function(ev)     -> custom predicate (inspect ev.card / ev.p38..ev.p58)
--   string id        -> match ev.card (a "0xlo:0xhi" GUID read from the probe;
--                       see docs/_re/kinds/talents-pick.md)
local function _pick_matches(card, ev)
    if card == nil or card == "*" then return true end
    if type(card) == "function" then
        local ok, keep = pcall(card, ev)
        return ok and keep and true or false
    end
    return ev ~= nil and tostring(ev.card) == tostring(card)
end

-- R.talent.on_pick(card, cb) — run cb(ev) when a matching card is picked.
-- POWER_UP_COLLECT_REQUEST fires on the game's main thread, so cb may call
-- R.combat / R.give / R.entity directly. cb is pcall-guarded.
-- IMPORTANT: this event fires for EVERY power-up collect — level-up CARDS and
-- world orbs/globes alike. Pass a specific `card` GUID to target one talent
-- card; nil/"*" fires on ANY power-up (use a `function(ev)` predicate if you
-- need finer discrimination than the identity).
function R.talent.on_pick(card, cb)
    if type(card) == "function" and cb == nil then card, cb = nil, card end
    assert(type(cb) == "function", "R.talent.on_pick: cb must be a function")
    R.on("gameplay:POWER_UP_COLLECT_REQUEST", function(ev)
        if not _pick_matches(card, ev) then return end
        local ok, err = pcall(cb, ev)
        if not ok then
            R.log("[rsmm.talent] on_pick callback error: " .. tostring(err))
        end
    end)
    return true
end

-- Define a CUSTOM TALENT: bind your own effect to a gameplay trigger. This is
-- the tier-2 "build your own talent" entry point — the `effect` callback is the
-- mod's own logic (heal, grant, buff, count, ...), not a cloned game talent.
--
--   R.talent.define{
--       id     = "lifesteal_on_ability",
--       hero   = "Juliet",                     -- optional: scope to ONE hero
--       on     = "gameplay:ABILITY_EXIT",      -- a gameplay event, or a list
--       when   = function(ev) return true end, -- optional predicate
--       effect = function(ev) R.combat.heal(5) end,
--   }
--
-- HERO-SPECIFIC: most talents belong to one hero. Set `hero="<ShortName>"` and
-- the effect fires only when that hero is active (gated through R.hero.is). This
-- depends on the hero's signature being seeded in R.hero; the signature-free way
-- to be hero-specific is a `pickable` talent bound to a hero-exclusive skill-card
-- GUID (only that hero's herodef has it). See R.talent.for_hero below.
--
-- Threading is handled for you: gameplay-event handlers run on the game's MAIN
-- thread, so an effect there may call R.combat / R.give / R.entity directly;
-- if you trigger off a non-gameplay event (e.g. "tick", background thread) the
-- effect is deferred onto the main-thread pump so engine calls stay safe (see
-- [[loader-thread-model]]). Each effect is pcall-guarded — a buggy talent logs
-- and is skipped, it never breaks the event bus for other mods.
--
-- PICKABLE talent (the effect arms only after the player chooses its card in
-- the level-up book, instead of being an always-on passive):
--
--   R.talent.define{
--       id       = "vampiric_casting",
--       pickable = true,                  -- dormant until picked
--       card     = "0x1a92...:0x0",       -- card GUID from TalentPickProbe; omit
--                                         -- (or "*") to arm on ANY card pick
--       on       = "gameplay:ABILITY_EXIT",
--       effect   = function() R.combat.heal(5) end,
--   }
--
-- `pickable = "<card>"` is shorthand for `pickable = true, card = "<card>"`.
-- Arming resets per run (run_start). Omit `pickable` for the always-on form.
local _talents = {}
function R.talent.define(spec)
    assert(type(spec) == "table",            "R.talent.define: spec must be table")
    assert(type(spec.id) == "string",        "R.talent.define: spec.id required")
    assert(type(spec.effect) == "function",  "R.talent.define: spec.effect must be function")
    if _talents[spec.id] then
        R.log("[rsmm.talent] duplicate id, ignoring:", spec.id)
        return false
    end
    local events = spec.on or "gameplay:ABILITY_EXIT"
    if type(events) == "string" then events = { events } end
    assert(type(events) == "table", "R.talent.define: spec.on must be a string or list of strings")
    _talents[spec.id] = spec

    -- `pickable = "<card>"` is shorthand for `pickable = true, card = "<card>"`.
    if type(spec.pickable) == "string" then
        if spec.card == nil then spec.card = spec.pickable end
        spec.pickable = true
    end

    -- Pickable talents stay DORMANT until the player picks their card; `card`
    -- selects which pick arms it (see R.talent.on_pick). A picked talent is
    -- permanent for the whole RUN (all chapters/islands), so arming resets only
    -- on "run_start" — NOT on GAME_START / GAME_CHRONO_START, which re-fire per
    -- chapter and would silently disarm the talent mid-run.
    if spec.pickable then
        spec._armed = false
        R.talent.on_pick(spec.card, function()
            -- Hero-scoped pickable: only arm when the matching hero is active.
            -- (Mostly redundant when `card` is a hero-exclusive skill GUID — that
            -- GUID exists in one herodef — but matters for card=nil/"*".)
            if spec.hero and not R.hero.is(spec.hero) then return end
            if not spec._armed then
                spec._armed = true
                R.log("[rsmm.talent] '" .. spec.id .. "' armed (card picked)")
            end
        end)
        R.on("run_start", function() spec._armed = false end)
    end

    for _, ev_name in ipairs(events) do
        R.on(ev_name, function(ev)
            -- HERO-SPECIFIC gate: most talents belong to one hero. `hero=` fires
            -- the effect only when that hero is active (via R.hero.is, which
            -- infers the hero from its exclusive ability events). NOTE: needs the
            -- hero's signature seeded in R.hero (_HERO_SIGNATURES) — if it isn't,
            -- prefer a pickable talent bound to a hero-exclusive card GUID, which
            -- is hero-specific without any signature. See skills-system.md.
            if spec.hero and not R.hero.is(spec.hero) then return end
            if spec.pickable and not spec._armed then return end
            if spec.when then
                local okc, keep = pcall(spec.when, ev)
                if not okc or not keep then return end
            end
            local function run()
                local ok, err = pcall(spec.effect, ev)
                if not ok then
                    R.log("[rsmm.talent] '" .. spec.id .. "' effect error: " .. tostring(err))
                end
            end
            -- gameplay events already fire on the main thread; anything else is
            -- deferred there so engine-mutating effects don't race the engine.
            if ev_name:sub(1, 9) == "gameplay:" then
                run()
            elseif R.schedule and R.schedule.next_main then
                R.schedule.next_main(run)
            else
                run()
            end
        end)
    end
    R.log("[rsmm.talent] defined:", spec.id)
    return true
end

function R.talent.list()
    local out = {}
    for _, s in pairs(_talents) do out[#out + 1] = s end
    return out
end

-- True once a pickable talent's card has been picked this run (nil if no such
-- talent, false if defined-but-not-yet-picked). Non-pickable talents read true.
function R.talent.armed(id)
    local s = _talents[id]
    if not s then return nil end
    if not s.pickable then return true end
    return s._armed and true or false
end

-- Scoped builder for a hero's talent file: stamps hero="<name>" onto every
-- talent so hero-specific talent code reads cleanly and can't leak to other
-- heroes. Per-talent `hero` still wins if set explicitly.
--   local J = R.talent.for_hero("Juliet")
--   J{ id = "bleed_on_dash", on = "gameplay:ABILITY_EXIT", effect = ... }
function R.talent.for_hero(hero)
    assert(type(hero) == "string", "R.talent.for_hero: hero must be a string")
    return function(spec)
        if type(spec) == "table" and spec.hero == nil then spec.hero = hero end
        return R.talent.define(spec)
    end
end

-- counters --------------------------------------------------------------
--
-- The simplest demo of the SDK: bump a counter every time an event
-- fires. Backed by R.kv, so counts persist across game restarts.
--
-- R.counter.on("run_end")  -- registers a "<event>_count" KV bump

R.counter = {}

function R.counter.on(event)
    R.on(event, function()
        local key = event .. "_count"
        R.kv.inc(key)
        R.log("[rsmm.counter]", key, "=", R.kv.get(key))
    end)
end

-- modular submodules ----------------------------------------------------
--
-- The remaining namespaces live in their own files under rsmm/ (installed
-- alongside this entrypoint) and are merged onto R here, so a mod gets them
-- via the single `require "rsmm"`:
--   R.health   — crash history + per-mod boot canary checkpoints
--   R.config   — typed per-mod config (get/set/on_change/all)
--   R.i18n     — translation lookup with {var} interpolation
--   R.api      — inter-mod API registry (expose/require with semver)
--   R.schedule — next_frame / after(seconds) timers (driven on "tick")
-- Each degrades gracefully if its backing native binding is absent.

local function _submodule(name)
    local ok, m = pcall(require, "rsmm." .. name)
    if ok and type(m) == "table" then return m end
    R.log("[rsmm] submodule rsmm." .. name .. " unavailable: " .. tostring(m))
    return nil
end

R.health   = _submodule("health")
R.config   = _submodule("config")
R.i18n     = _submodule("i18n")
R.api      = _submodule("api")
R.schedule = _submodule("schedule")

-- Drive the schedule module's frame pump off the one true event bus.
if R.schedule and R.schedule._tick then
    R.on("tick", function() R.schedule._tick() end)
end

-- Drive the MAIN-thread schedule pump off the gameplay bus. Those handlers run
-- inside the NamedEvent_Dispatch detour = the game's main thread, unlike "tick"
-- (loader background thread). Gating on ev.source == "gameplay" is essential:
-- the wildcard also fires for "tick"/"ready" on the background thread, and
-- running engine-mutating callbacks there is exactly the race we're avoiding.
if R.schedule and R.schedule._main_tick then
    R.on("*", function(ev)
        if ev and ev.source == "gameplay" then R.schedule._main_tick() end
    end)
end

-- R.mods — mod list + host-side lifecycle intents (in-game mod menu) -----
--
-- The game runs under Proton while the rsmm CLI lives on the host, so the
-- loader cannot enable/disable/uninstall a mod itself. Instead an intent is
-- queued to <cooking>/.rsmm_intents.jsonl (next to .rsmm_state.json) and the
-- HOST consumes it: `rsmm intents apply` (or the desktop app) performs the
-- operation and re-runs apply. Ops take effect on the next apply+restart.

R.mods = {}

-- Installed mods as {id, name, version, author, enabled} rows.
function R.mods.list()
    if not I.list_mods then return {} end
    return I.list_mods()
end

local _INTENT_OPS = { enable = true, disable = true, uninstall = true }

-- Queue a lifecycle intent for the host CLI. Returns true when queued.
function R.mods.request(op, mod_id)
    if not I.intent_write then
        R.log("[mods] intent_write unavailable (loader too old)")
        return false
    end
    if not _INTENT_OPS[op] then
        R.log("[mods] bad intent op: " .. tostring(op))
        return false
    end
    if type(mod_id) ~= "string" or mod_id == "" then
        R.log("[mods] bad mod id: " .. tostring(mod_id))
        return false
    end
    return I.intent_write(op, mod_id) and true or false
end

-- struct introspection (RE aid) -----------------------------------------
--
-- Turns "probe a struct across many game launches" into one launch: dump a
-- pointer's fields to the log with each qword CLASSIFIED (image vftable /
-- global, plausible heap pointer, small int, float, ASCII), and scan a struct
-- for pointer fields that look like component-array holders. All reads are
-- page-guarded (bad address → nil, never a fault), so this is safe to point
-- at a half-captured or wrong pointer. Reads only — never mutates.
R.debug = {}

local function _classify(v)
    if not v or v == 0 then return "0" end
    if _in_image(v) then
        local base = I.module_base()
        return string.format("IMG +0x%x", v - base + ENTITY_IMG_BASE)
    end
    if _ptr_plausible(v) then
        -- does *(v) look like a vtable? then v is likely a live object.
        local vt = I.read_u64(v)
        if _in_image(vt) then
            return string.format("ptr->obj (vt IMG +0x%x)",
                vt - I.module_base() + ENTITY_IMG_BASE)
        end
        return "ptr"
    end
    if v < 0x10000000 then return "int " .. tostring(v) end
    return nil
end

-- Dump `len` bytes (default 0x200, capped 0x1000) of *ptr as classified
-- qwords. `label` tags the log lines.
function R.debug.dump(ptr, len, label)
    label = label or "dump"
    if not _ptr_plausible(ptr) then
        R.log(string.format("[rsmm.debug] %s: 0x%s not a plausible pointer",
            label, tostring(ptr))); return
    end
    len = math.min(len or 0x200, 0x1000)
    R.log(string.format("[rsmm.debug] %s @ 0x%x (%d bytes):", label, ptr, len))
    for off = 0, len - 8, 8 do
        local v = I.read_u64(ptr + off)
        if v ~= nil then
            local cls = _classify(v)
            local f = I.read_f32(ptr + off)
            local extra = ""
            if f and f == f and f ~= 0 and math.abs(f) > 1e-6 and math.abs(f) < 1e9 then
                extra = string.format("  f32=%.4g", f)
            end
            R.log(string.format("[rsmm.debug]   +0x%03x  0x%016x  %s%s",
                off, v, cls or "-", extra))
        end
    end
end

-- Scan every pointer field of `obj` (0..max_off) for objects that hold a
-- {data,count} pointer-vector at data_off/count_off (default the component
-- array 0x190/0x198). Returns a list of {off, holder, count}; logs each.
-- This is the generalized form of the XP-owner hunt — reuse it whenever a
-- captured pointer's real payload lives on some sub-object.
function R.debug.find_arrays(obj, opts)
    opts = opts or {}
    local data_off  = opts.data_off  or 0x190
    local count_off = opts.count_off or 0x198
    local max_off   = opts.max_off   or 0x800
    local found = {}
    if not _ptr_plausible(obj) then return found end
    for off = 0, max_off - 8, 8 do
        local P = I.read_u64(obj + off)
        if _vector_valid(P, data_off, count_off, {
            min = 1, max = opts.max_count or 0x100,
            check_entry = opts.check_entry,
        }) then
            local n = I.read_u32(P + count_off)
            found[#found + 1] = { off = off, holder = P, count = n }
            R.log(string.format(
                "[rsmm.debug] find_arrays: obj+0x%x -> 0x%x has %d-entry vector @+0x%x",
                off, P, n, data_off))
        end
    end
    if #found == 0 then
        R.log("[rsmm.debug] find_arrays: no matching vectors found")
    end
    return found
end

-- escape hatch ----------------------------------------------------------
--
-- Last-resort access to the raw engine bindings. Not part of the
-- contract: function names, signatures, and presence may change.

R._internal = I

return R
