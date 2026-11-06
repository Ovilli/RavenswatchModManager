-- R.audio — mute game sound, all of it or only what you pick.
--
-- Backed by the loader's FMOD hooks (src/loader/src/hook_audio.cpp), resolved
-- by FMOD export name, so no game address is involved and a game patch cannot
-- move them. Paths are FMOD's own, as `rsmm` lists them from the game's
-- strings bank (the `fmod-sounds` config option source):
--
--   R.audio.select{ "bus:/Music", "event:/Heroes/Red", "event:/GUI" }
--       mute exactly these: a BUS mutes everything mixed through it, an EVENT
--       entry mutes that event or every event in that folder. "all" in the
--       list mutes everything (FMOD's master). Replaces the previous selection;
--       select{} releases it all. Reaches sounds already playing.
--   R.audio.mute(true|false)  -- the master switch on its own
--   R.audio.muted()           -- the master request
--   R.audio.available()       -- false on a loader without the hooks
--   R.audio.status()          -- counters: hooked, studio_hooked, buses_muted,
--                                instances_muted, last_error, ...
--
-- Mutes are re-asserted while selected (the game may toggle the same flags);
-- a release is applied once, then the flag is the game's again. Any thread.

local M = {}

-- Same guard shape as rsmm/health.lua: the SDK ships independently of the
-- DLL, so `_internal` may exist without these bindings.
local function _native()
    local g = _G.rsmm
    return g and g._internal or nil
end

local _wanted = false

function M.available()
    local I = _native()
    if not I or not I.audio_status then return false end
    local st = I.audio_status()
    return st ~= nil and (st.hooked == true or st.studio_hooked == true)
end

-- Returns true when the request reached the loader. A false return means the
-- running loader has no audio support (update it with `rsmm update-loader`).
function M.mute(on)
    on = on and true or false
    local I = _native()
    if not I or not I.audio_mute then return false end
    I.audio_mute(on)
    _wanted = on
    return true
end

-- Returns true when the selection reached the loader.
function M.select(paths)
    local I = _native()
    if type(paths) ~= "table" then paths = {} end
    local list, all = {}, false
    for _, p in ipairs(paths) do
        if type(p) == "string" then
            if p:lower() == "all" then all = true else list[#list + 1] = p end
        end
    end
    if not I or not I.audio_targets then
        -- An older loader: the master switch may still exist.
        return M.mute(all) and #list == 0
    end
    I.audio_targets(list)
    M.mute(all)
    return true
end

function M.unmute() return M.mute(false) end

function M.toggle() return M.mute(not M.muted()) end

function M.muted()
    local I = _native()
    if I and I.audio_status then
        local st = I.audio_status()
        if st then return st.muted == true end
    end
    return _wanted
end

function M.status()
    local I = _native()
    if not I or not I.audio_status then
        return { hooked = false, studio_hooked = false, muted = _wanted, systems = 0,
                 updates = 0, buses = 0, buses_muted = 0, events = 0, instances = 0,
                 instances_muted = 0, last_error = 0 }
    end
    return I.audio_status()
end

return M
