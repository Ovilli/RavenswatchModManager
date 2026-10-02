-- R.config — typed per-mod config bound to the calling mod's id.
-- Backed by <mod_dir>/config.toml, read/written by the loader's native
-- rsmm._internal.config_* bindings (the sandbox nils `io`, so mods cannot
-- read the file directly). The host-side ConfigStore (rsmm.sdk.config)
-- owns the schema; `rsmm apply` / install-loader sync the file in.

local M = {}
local _watchers = {}     -- key -> { fn, ... }
local _last = nil        -- the values _poll last saw (see live reload below)

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
    -- Our own change, not an outside edit: keep the poll's snapshot in step so
    -- the next reload does not fire this key a second time.
    if _last then _last[key] = value end
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

-- Live reload. A value changed OUTSIDE the game — the desktop overlay's
-- controls write the installed config.toml — reaches the running mod here:
-- rsmm.lua calls _poll on every loader tick, the native re-reads the file only
-- when its mtime moved, and each key whose value differs fires its on_change
-- watchers with (new, old), exactly as M.set does. A loader without
-- config_reload (older DLL) makes this a no-op, never an error.
--
-- THREAD: the tick runs on the loader's background thread, so a watcher must
-- not call engine functions directly — use R.schedule.next_main for those. A
-- plain memory write (R.camera.set) is fine.

local function _fire(key, value, old)
    for _, fn in ipairs(_watchers[key] or {}) do
        local ok, err = xpcall(fn, _msgh, value, old)
        if not ok and _G.rsmm then
            _G.rsmm.log("config watcher error on '" .. tostring(key) .. "': " .. tostring(err))
        end
    end
end

function M._poll()
    local I = _native()
    if not (I and I.config_reload) then return end
    if _last == nil then _last = M.all() end
    if not I.config_reload() then return end
    local now = M.all()
    local old = _last
    _last = now
    local changed = {}
    for k, v in pairs(now) do
        if old[k] ~= v then changed[#changed + 1] = k .. "=" .. tostring(v) end
    end
    if #changed > 0 and _G.rsmm and _G.rsmm.log then
        table.sort(changed)
        _G.rsmm.log("[rsmm.config] config.toml changed outside the game: "
                    .. table.concat(changed, ", "))
    end
    for k, v in pairs(now) do
        if old[k] ~= v then _fire(k, v, old[k]) end
    end
    for k, v in pairs(old) do
        if now[k] == nil then _fire(k, nil, v) end
    end
end

return M
