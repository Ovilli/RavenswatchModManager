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

-- g_MagicalObjectPool: pointer global; *ptr = { source array @+0,
-- u32 source count @+8, runtime array @+0x10, u32 runtime count @+0x18 }.
local GIVE_POOL_VA = 0x1414365d0
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

R.on("*", function(ev, name)
    if _GIVE_ANCHORS[name] and type(ev.dispatcher) == "string" then
        local d = tonumber(ev.dispatcher)
        if d and d ~= 0 then
            -- A different dispatcher than last seen means the local hero changed
            -- (switched character, or a fresh run reallocated the entity). The
            -- captured HP-carrier and the shared slot point at the OLD hero's
            -- (possibly freed) memory, so invalidate them and re-capture clean.
            if _give_hero ~= nil and d ~= _give_hero and _invalidate_hero_capture then
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
    local base = I.module_base()
    if not base or base == 0 then return nil end
    local vec = I.read_u64(base + (GIVE_POOL_VA - GIVE_IMG_BASE))
    if not vec or vec == 0 then return nil end
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
local MODIFY_HEALTH_VA   = 0x140399a10   -- Entity_ModifyHealth(hero, delta, tags)
local GAINHEALTH_HDLR_VA = 0x1403993f0   -- GAIN_HEALTH handler; param_1 = hero
local GIVE_HDLR_VA       = 0x1403a7ba0   -- give-item handler; param_1 = hero
local FLAGLIST_VFT_VA    = 0x140efc320   -- oCCustomFlagList::vftable
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
    -- required rsmm. R.hook raises on install failure (e.g. the handler RVA
    -- drifted across a game patch -> MH_ERROR_NOT_EXECUTABLE), so guard each
    -- with pcall — capture just stays unavailable; everything else still runs.
    local ok1 = pcall(R.hook, base + (GAINHEALTH_HDLR_VA - ENTITY_IMG_BASE), "vppp",
        function(p1) capture(p1, false); return nil end)
    local ok2 = pcall(R.hook, base + (GIVE_HDLR_VA - ENTITY_IMG_BASE), "vpp",
        function(p1) capture(p1, true); return nil end)
    if not (ok1 and ok2) then
        R.log("[rsmm.entity] hero-capture hooks unavailable (handler addr drift); "
            .. "R.combat/R.entity disabled this run, other mods unaffected")
    end
end

-- The captured local hero character pointer, or nil if not seen yet. The
-- loader's native capture publishes it to the shared slot at hero spawn (it
-- hooks the hero's spawn/post-load init, NamedEvent_HeroSubscribeAll, whose
-- param_1 is the HP-carrier) — so it's available almost immediately, no longer
-- gated on the hero's first heal/pickup. Read fresh every call so a hero-switch
-- (which clears the slot) is picked up automatically.
function R.entity.hero()
    if I.shared_get then
        local ok, h = pcall(I.shared_get, SHARED_HERO_SLOT)
        if ok and type(h) == "number" and h ~= 0 and _hero_plausible(h) then
            return h
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
    local base = I.module_base()
    if not base or base == 0 then return false end
    -- empty oCCustomFlagList ctx { vftable, list=0, count=0 } in scratch
    local ctx = I.scratch(0x20)
    I.poke(ctx + 0x00, base + (FLAGLIST_VFT_VA - ENTITY_IMG_BASE), 8)
    I.poke(ctx + 0x08, 0, 8)
    I.poke(ctx + 0x10, 0, 8)
    local fn = base + (MODIFY_HEALTH_VA - ENTITY_IMG_BASE)
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

local NET_REPL_SETUP_VA     = 0x140720c10  -- Netcode_EntityReplSetup
local NET_CTX_TO_NETMGR_OFF = 0x10         -- netmgr = *(ctx + 0x10)
local NET_ROLE_OFF          = 0xf8         -- role   = *(netmgr + 0xf8); 1=client
local NET_IMG_BASE          = 0x140000000

-- Hook the per-entity replication setup. cb(netmgr, role, ctx) fires for each
-- entity; return a number from cb to OVERWRITE role (dangerous), or nil to
-- leave it. Returns the hook handle, or nil if the module base is unavailable.
function R.net.on_repl_setup(cb)
    assert(type(cb) == "function", "R.net.on_repl_setup: cb must be function")
    local base = I.module_base()
    if not base or base == 0 then return nil end
    local va = base + (NET_REPL_SETUP_VA - NET_IMG_BASE)
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

local OPT_GAMEOPTIONS_VA = 0x141436510
local OPT_IMG_BASE = 0x140000000
local OPT_VALUE_OFF = 0x28

-- name -> { off = byte offset of the option's slot from the object base,
--           type = "bool" | "uint" | "int" | "float" }
-- Offsets transcribed from the options ctor (FUN_1401c99f0); value at off+0x28.
local _OPT = {
    ["Forced seed"]                                 = { off = 0x0000, type = "uint"  },
    ["Dash at cursor"]                              = { off = 0x0e80, type = "bool"  },
    ["Screen shake"]                                = { off = 0x1090, type = "bool"  },
    ["Pause during choices"]                        = { off = 0x10f8, type = "bool"  },
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

local function _opt_value_addr(name)
    local o = _OPT[name]
    if not o then return nil, nil end
    local base = I.module_base()
    if not base or base == 0 then return nil, nil end
    local obj = I.read_u64(base + (OPT_GAMEOPTIONS_VA - OPT_IMG_BASE))
    if not obj or obj == 0 then return nil, nil end
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

-- Define a CUSTOM TALENT: bind your own effect to a gameplay trigger. This is
-- the tier-2 "build your own talent" entry point — the `effect` callback is the
-- mod's own logic (heal, grant, buff, count, ...), not a cloned game talent.
--
--   R.talent.define{
--       id     = "lifesteal_on_ability",
--       on     = "gameplay:ABILITY_EXIT",      -- a gameplay event, or a list
--       when   = function(ev) return true end, -- optional predicate
--       effect = function(ev) R.combat.heal(5) end,
--   }
--
-- Threading is handled for you: gameplay-event handlers run on the game's MAIN
-- thread, so an effect there may call R.combat / R.give / R.entity directly;
-- if you trigger off a non-gameplay event (e.g. "tick", background thread) the
-- effect is deferred onto the main-thread pump so engine calls stay safe (see
-- [[loader-thread-model]]). Each effect is pcall-guarded — a buggy talent logs
-- and is skipped, it never breaks the event bus for other mods.
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

    for _, ev_name in ipairs(events) do
        R.on(ev_name, function(ev)
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

-- escape hatch ----------------------------------------------------------
--
-- Last-resort access to the raw engine bindings. Not part of the
-- contract: function names, signatures, and presence may change.

R._internal = I

return R
