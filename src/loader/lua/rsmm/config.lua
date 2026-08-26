-- R.config — typed per-mod config bound to the calling mod's id.
-- Backed by <mod_dir>/config.toml, read/written by the loader's native
-- rsmm._internal.config_* bindings (the sandbox nils `io`, so mods cannot
-- read the file directly). The host-side ConfigStore (rsmm.sdk.config)
-- owns the schema; `rsmm apply` / install-loader sync the file in.

local M = {}
local _watchers = {}     -- key -> { fn, ... }

-- `_G.rsmm and _G.rsmm._internal.config_get` reads as a guard and is not: when
-- `rsmm` exists but `_internal` does not, it indexes nil and RAISES. That is
-- exactly the case this module is supposed to survive — the Lua SDK ships
-- independently of the DLL, so it routinely runs against an older loader — and
-- the raise lands in the mod's init, not here.
local function _native()
    local g = _G.rsmm
    return g and g._internal or nil
end

-- Traceback-carrying message handler; `debug` is removed by the sandbox.
local function _msgh(e)
    local I = _native()
    if I and I.traceback then return I.traceback(e) end
    return tostring(e)
end

function M.get(key, fallback)
    local I = _native()
    if I and I.config_get then
        local v = I.config_get(key)
        if v ~= nil then return v end
    end
    return fallback
end

function M.set(key, value)
    local I = _native()
    if not I or not I.config_set then return end
    local old = M.get(key)
    I.config_set(key, value)
    local list = _watchers[key]
    if not list then return end
    for _, fn in ipairs(list) do
        local ok, err = xpcall(fn, _msgh, value, old)
        if not ok and _G.rsmm then
            _G.rsmm.log("config watcher error on '" .. tostring(key) .. "': "
                        .. tostring(err))
        end
    end
end

function M.on_change(key, fn)
    _watchers[key] = _watchers[key] or {}
    table.insert(_watchers[key], fn)
end

function M.all()
    local I = _native()
    if I and I.config_all then return I.config_all() end
    return {}
end

return M
