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
-- triggers; to mutate the actor you need the oCGameNamedEvent gameplay
-- bus (next surface to map).
--
-- The callback receives a payload table:
--   ev.event  (string)  the event name
--   ev.seq    (number)  per-event fire counter (ordering signal)
--   ev.source (string)  "analytics" for firehose events
--   ev.ctx/ev.arg       raw arg handles "0x..." (typed-event envelope only)
-- Lifecycle events (ready/tick/exit) pass an empty table.

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

-- hooks (low-level escape valve; users should prefer R.* abstractions) -

R.hook   = native.hook
R.unhook = native.unhook

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
-- R.item.register{ id=, name=, description=, rarity=, base=, effect= }
--
-- TODO: not yet wired to the game. The contract:
--   * `base` clones the bytes of an existing MO entity (e.g.
--     "Common/Armor_Per_Object") as a starting template.
--   * `name` and `description` populate the corresponding text-bank
--     keys via Text/Magical_Objects~GAM.xls.LocalText.gen overrides.
--   * `effect` runs every tick the hero owns the MO. Implementation
--     gated on the MO-stat-getter / hero-update hook (see
--     docs/_re/HOOKPOINTS.md).

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
        spec.rarity or 0
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

-- escape hatch ----------------------------------------------------------
--
-- Last-resort access to the raw engine bindings. Not part of the
-- contract: function names, signatures, and presence may change.

R._internal = I

return R
