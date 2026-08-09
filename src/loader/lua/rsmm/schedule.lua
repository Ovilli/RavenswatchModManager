-- R.schedule — frame-based coroutine helpers. Built on R.on("tick", ...).

local M = {}
local _next_frame = {}
local _timers = {}        -- { fire_at, fn }
local _main_q = {}        -- main-thread immediate callbacks
local _main_timers = {}   -- main-thread { fire_at, fn }

-- Monotonic, sub-second clock. os.time() is the fallback ONLY for a loader
-- too old to provide _internal.now(): it has one-second resolution, so with it
-- `after(0.25, ...)` really means "some time in the next second or two" and a
-- burst of sub-second polls all fire in the same tick.
local _now = function()
    local I = _G.rsmm and _G.rsmm._internal
    if I and I.now then return I.now() end
    return os.time()
end

function M.next_frame(fn)
    assert(type(fn) == "function", "R.schedule.next_frame: fn must be a function")
    table.insert(_next_frame, fn)
end

-- Timers carry a handle so they can be cancelled, and `every` repeats until
-- you do. Before this the only way to stop a repeating poll was a flag the
-- callback checked itself, and every `on_guid`/`item.behavior` poller
-- re-armed itself by hand.
local _next_timer = 0
local function _add(list, seconds, fn, repeating)
    _next_timer = _next_timer + 1
    table.insert(list, { id = _next_timer, fire_at = _now() + seconds,
                         every = repeating and seconds or nil, fn = fn })
    return _next_timer
end

function M.after(seconds, fn)
    assert(type(seconds) == "number", "R.schedule.after: seconds must be a number")
    assert(type(fn) == "function", "R.schedule.after: fn must be a function")
    return _add(_timers, seconds, fn, false)
end

-- Repeat every `seconds` until cancelled. Returns a handle for M.cancel.
function M.every(seconds, fn)
    assert(type(seconds) == "number" and seconds > 0,
           "R.schedule.every: seconds must be a positive number")
    assert(type(fn) == "function", "R.schedule.every: fn must be a function")
    return _add(_timers, seconds, fn, true)
end

-- Main-thread variant of `every` (see next_main for the threading rules).
function M.every_main(seconds, fn)
    assert(type(seconds) == "number" and seconds > 0,
           "R.schedule.every_main: seconds must be a positive number")
    assert(type(fn) == "function", "R.schedule.every_main: fn must be a function")
    return _add(_main_timers, seconds, fn, true)
end

-- Fire everything due in `list`, re-arming repeaters and dropping one-shots.
-- `store` writes the surviving list back (the pumps own the upvalues).
local function _drain(list, label, store)
    if #list == 0 then return end
    local now = _now()
    local keep = {}
    for _, t in ipairs(list) do
        if t.fire_at <= now then
            local ok, err = pcall(t.fn)
            if not ok and _G.rsmm then
                _G.rsmm.log("schedule." .. label .. " error: " .. tostring(err))
            end
            -- A repeater survives a raising callback: a transient failure
            -- (hero not spawned yet, say) shouldn't silently kill the timer.
            -- Schedule off `now`, not fire_at, so a stalled pump doesn't queue
            -- a burst of catch-up fires.
            if t.every then t.fire_at = now + t.every; keep[#keep + 1] = t end
        else
            keep[#keep + 1] = t
        end
    end
    store(keep)
end

-- Cancel a timer from either queue. Returns true if it was still pending.
function M.cancel(handle)
    for _, list in ipairs({ _timers, _main_timers }) do
        for i, t in ipairs(list) do
            if t.id == handle then table.remove(list, i); return true end
        end
    end
    return false
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
    assert(type(fn) == "function", "R.schedule.next_main: fn must be a function")
    table.insert(_main_q, fn)
end

function M.after_main(seconds, fn)
    assert(type(seconds) == "number", "R.schedule.after_main: seconds must be a number")
    assert(type(fn) == "function", "R.schedule.after_main: fn must be a function")
    return _add(_main_timers, seconds, fn, false)
end

-- Pending work, for diagnostics: {next_frame, timers, next_main, main_timers}.
function M.pending()
    return { next_frame = #_next_frame, timers = #_timers,
             next_main = #_main_q, main_timers = #_main_timers }
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
    _drain(_main_timers, "after_main", function(t) _main_timers = t end)
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
    _drain(_timers, "after", function(t) _timers = t end)
end

return M
