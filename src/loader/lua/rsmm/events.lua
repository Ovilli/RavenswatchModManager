-- R.events — minimal event bus. Built-in topics published by the loader.
-- Every handler receives ONE argument: a payload table (empty `{}` for
-- events that carry no data). Lifecycle order: setup -> ready -> tick*.
--   "setup"      — all mods' init.lua ran; fires before overrides apply
--   "ready"      — first frame, every mod loaded + overrides applied
--   "tick"       — periodic (~500ms; use sparingly)
--   "exit"       — DLL unload
--   "level_load" — payload { name = "...", id = ... }       (needs detour)
--   "hero_pick"  — payload { hero = ..., skin = ... }        (needs detour)
--   "damage"     — payload { src = ..., dst = ..., amount = ... } (post-hook)

local M = {}
local _subs = {}

function M.on(topic, fn)
    _subs[topic] = _subs[topic] or {}
    table.insert(_subs[topic], fn)
end

function M.off(topic, fn)
    local list = _subs[topic]
    if not list then return end
    for i, f in ipairs(list) do
        if f == fn then table.remove(list, i); return end
    end
end

function M.emit(topic, payload)
    local list = _subs[topic]
    if not list then return end
    for _, fn in ipairs(list) do
        local ok, err = pcall(fn, payload)
        if not ok and _G.rsmm then
            _G.rsmm.log("event handler error (" .. tostring(topic) .. "): " .. tostring(err))
        end
    end
end

return M
