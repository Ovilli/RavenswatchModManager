-- R.config — typed per-mod config bound to the calling mod's id.
-- Backed by the host-side ConfigStore via the loader's IPC bridge.

local M = {}
local _watchers = {}     -- key -> { fn, ... }

function M.get(key, fallback)
    if _G.rsmm and _G.rsmm._internal.config_get then
        local v = _G.rsmm._internal.config_get(key)
        if v ~= nil then return v end
    end
    return fallback
end

function M.set(key, value)
    if _G.rsmm and _G.rsmm._internal.config_set then
        local old = M.get(key)
        _G.rsmm._internal.config_set(key, value)
        local list = _watchers[key]
        if list then
            for _, fn in ipairs(list) do
                local ok, err = pcall(fn, value, old)
                if not ok and _G.rsmm then _G.rsmm.log("config watcher error: " .. tostring(err)) end
            end
        end
    end
end

function M.on_change(key, fn)
    _watchers[key] = _watchers[key] or {}
    table.insert(_watchers[key], fn)
end

function M.all()
    if _G.rsmm and _G.rsmm._internal.config_all then
        return _G.rsmm._internal.config_all()
    end
    return {}
end

return M
