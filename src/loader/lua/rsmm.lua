-- RSMM Lua API root. Loaded as `R = require "rsmm"` from mod init.lua.
-- Host-side mirrors live in src/rsmm/sdk/*.py. The Lua surface is
-- intentionally a thin facade — call out to the loader DLL for the
-- privileged operations (resolve, hook, mem r/w) and keep the
-- safety/config/i18n/api layer here so mods can be tested without the
-- DLL by stubbing _internal.

local R = {}

R._internal = R._internal or {}    -- populated by the loader DLL on boot
R._API_VERSION = "1.0.0"

-- Submodules. Each one returns a table that we copy/merge into R so
-- mods can write `R.health.crash_count()` without an extra require.
local function _merge(name, tbl)
    R[name] = tbl
end

_merge("health",   require("rsmm.health"))
_merge("config",   require("rsmm.config"))
_merge("i18n",     require("rsmm.i18n"))
_merge("api",      require("rsmm.api"))
_merge("events",   require("rsmm.events"))
_merge("schedule", require("rsmm.schedule"))

-- Convenience top-level aliases.
R.log = function(msg)
    if R._internal.log then R._internal.log(tostring(msg)) end
end
R.on  = R.events.on
R.emit = R.events.emit

R.resolve = function(name)
    if not R._internal.resolve then return 0 end
    return R._internal.resolve(name)
end

R.call = function(target, sig, ...)
    if not R._internal.call then
        error("rsmm.call requires the loader DLL", 2)
    end
    return R._internal.call(target, sig, ...)
end

R.hook = function(va, sig, cb)
    if not R._internal.hook then
        error("rsmm.hook not supported on this build (TLS injection disabled)", 2)
    end
    return R._internal.hook(va, sig, cb)
end

R.read_u32 = function(va)
    return R._internal.read_u32 and R._internal.read_u32(va) or 0
end
R.write_u32 = function(va, v)
    if R._internal.write_u32 then R._internal.write_u32(va, v) end
end

-- Per-mod scratch KV store, persisted to <cooking>/.rsmm_kv_<modid>.json
-- by the loader. Useful for hit-counters / state across runs.
R.kv = R.kv or {}
function R.kv.inc(key, by)
    by = by or 1
    local cur = (R._internal.kv_get and R._internal.kv_get(key)) or 0
    cur = cur + by
    if R._internal.kv_set then R._internal.kv_set(key, cur) end
    return cur
end
function R.kv.get(key) return R._internal.kv_get and R._internal.kv_get(key) or nil end
function R.kv.set(key, v) if R._internal.kv_set then R._internal.kv_set(key, v) end end

return R
