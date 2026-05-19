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
-- Future events emitted by the SDK as RE catches up:
--   "run_start", "run_end", "level_up", "boss_kill", ...

function R.on(event, cb)
    assert(type(event) == "string", "R.on: event must be string")
    assert(type(cb) == "function",  "R.on: cb must be function")
    native.on_event(event, cb)
end

-- hooks (low-level escape valve; users should prefer R.* abstractions) -

R.hook   = native.hook
R.unhook = native.unhook

-- key-value store -------------------------------------------------------
--
-- Per-mod state. Currently in-memory; persists across hot-reload via
-- the registry, lost on game exit. Persistence to disk is on the
-- roadmap (mods/<id>/state.json).

local _kv = {}
R.kv = {}

function R.kv.get(k, default)
    local v = _kv[k]
    if v == nil then return default end
    return v
end

function R.kv.set(k, v)
    _kv[k] = v
end

function R.kv.inc(k, by)
    _kv[k] = (_kv[k] or 0) + (by or 1)
    return _kv[k]
end

function R.kv.all()
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
    R.log("[rsmm.item] registered:", spec.id, "(TODO: not yet wired to game)")
    return false   -- intentionally false until wiring lands
end

function R.item.list()
    local out = {}
    for _, s in pairs(_registered_items) do out[#out+1] = s end
    return out
end

-- scaling ---------------------------------------------------------------
--
-- R.scaling.set("enemy_damage", function(act) return ({1, 1.5, 2})[act] end)
--
-- TODO: not yet wired. Will hook the value-modifier-computer once
-- located. Until then this just records the override for later
-- application.

R.scaling = {}

local _scaling = {}

function R.scaling.set(field, fn)
    assert(type(field) == "string",  "R.scaling.set: field must be string")
    assert(type(fn)    == "function","R.scaling.set: fn must be function")
    _scaling[field] = fn
    R.log("[rsmm.scaling] set:", field, "(TODO: not yet wired to game)")
end

function R.scaling.get(field) return _scaling[field] end

-- talent controls -------------------------------------------------------
--
-- R.talent.allow_stack(true)   -- let the same talent be picked twice
-- R.talent.extra_at_level(11)  -- grant another talent pick at lvl 11
--
-- TODO: gated on Skill-emitter + skill-grant function RE.

R.talent = {}

local _talent_cfg = { allow_stack = false, extra_at = {} }

function R.talent.allow_stack(b)
    _talent_cfg.allow_stack = b and true or false
    R.log("[rsmm.talent] allow_stack =", tostring(b), "(TODO)")
end

function R.talent.extra_at_level(lvl)
    table.insert(_talent_cfg.extra_at, lvl)
    R.log("[rsmm.talent] extra pick at lvl", lvl, "(TODO)")
end

-- counters --------------------------------------------------------------
--
-- The simplest demo of the SDK: bump a counter every time an event
-- fires. Backed by R.kv for now.
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

-- escape hatch ----------------------------------------------------------
--
-- Last-resort access to the raw engine bindings. Not part of the
-- contract: function names, signatures, and presence may change.

R._internal = I

return R
