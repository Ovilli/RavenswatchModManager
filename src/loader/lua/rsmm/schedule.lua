-- R.schedule — frame-based coroutine helpers. Built on R.on("tick", ...).

local M = {}
local _next_frame = {}
local _timers = {}        -- { fire_at, fn }
local _main_q = {}        -- main-thread immediate callbacks
local _main_timers = {}   -- main-thread { fire_at, fn }

local _now = function()
    if _G.rsmm and _G.rsmm._internal.now then return _G.rsmm._internal.now() end
    return os.time()
end

function M.next_frame(fn)
    table.insert(_next_frame, fn)
end

function M.after(seconds, fn)
    table.insert(_timers, { fire_at = _now() + seconds, fn = fn })
end

-- MAIN-THREAD variants. The regular tick pump (M._tick) runs on the loader's
-- BACKGROUND thread. Engine calls that mutate game state — anything routing
-- through NamedEvent_Dispatch (R.give.*, R.combat.*) — MUST run on the game's
-- main thread or they race the engine and crash (proven: a give that crashes
-- from M.after survives identically from a gameplay-event handler). These queue
-- onto lists drained by M._main_tick, which rsmm.lua drives off the gameplay
-- bus (those handlers run on the main thread). Requires the gameplay bus
-- (RSMM_ENABLE_GAMEPLAY_EVENTS=1) — the only main-thread heartbeat available.
function M.next_main(fn)
    table.insert(_main_q, fn)
end

function M.after_main(seconds, fn)
    table.insert(_main_timers, { fire_at = _now() + seconds, fn = fn })
end

-- Main-thread pump. Driven by rsmm.lua from gameplay-bus events only.
function M._main_tick()
    if #_main_q > 0 then
        local cur = _main_q
        _main_q = {}
        for _, fn in ipairs(cur) do
            local ok, err = pcall(fn)
            if not ok and _G.rsmm then _G.rsmm.log("schedule.next_main error: " .. tostring(err)) end
        end
    end
    if #_main_timers > 0 then
        local now = _now()
        local keep = {}
        for _, t in ipairs(_main_timers) do
            if t.fire_at <= now then
                local ok, err = pcall(t.fn)
                if not ok and _G.rsmm then _G.rsmm.log("schedule.after_main error: " .. tostring(err)) end
            else
                table.insert(keep, t)
            end
        end
        _main_timers = keep
    end
end

-- Frame pump. rsmm.lua subscribes this to the "tick" event so timers fire
-- without the module needing to subscribe at load time.
function M._tick()
    if #_next_frame > 0 then
        local cur = _next_frame
        _next_frame = {}
        for _, fn in ipairs(cur) do
            local ok, err = pcall(fn)
            if not ok and _G.rsmm then _G.rsmm.log("schedule.next_frame error: " .. tostring(err)) end
        end
    end
    if #_timers > 0 then
        local now = _now()
        local keep = {}
        for _, t in ipairs(_timers) do
            if t.fire_at <= now then
                local ok, err = pcall(t.fn)
                if not ok and _G.rsmm then _G.rsmm.log("schedule.after error: " .. tostring(err)) end
            else
                table.insert(keep, t)
            end
        end
        _timers = keep
    end
end

return M
